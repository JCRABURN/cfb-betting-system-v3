"""Verify recovered original screenshots and derive a separate prospective subset."""
from __future__ import annotations

import argparse
import csv
import io
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from ingestion import CanonicalTeamResolver
from scripts import prepare_week11_readiness as readiness
from scripts import verify_week11_transcription as original
from scripts import week11_eligibility

ROOT = readiness.ROOT
OUT = ROOT / 'outputs/2026-week11-prospective'
EVIDENCE = OUT / 'source-evidence'
SOURCE = OUT / 'eligible-lines.csv'
METADATA = OUT / 'eligible-line-metadata.json'
CONTEST_KEY = 'splashsports-cfb-2026-w11'


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(path.read_text(encoding='utf-8'))))


def verify_images(evidence: Path = EVIDENCE) -> dict:
    custody = json.loads((evidence / 'screenshot-custody.json').read_bytes())
    source, metadata, transcription, reconciliation = original.load()
    if (custody['source_csv_sha256'] != metadata['production_csv_sha256']
            or custody['source_metadata_sha256'] != original.HASHES['production-weeks/2026-week11-splashsports-lock-metadata.json']
            or custody['owner_selection_approval'] != 'PENDING'
            or custody['source_quote_timestamp'] is not None):
        raise ValueError('screenshot custody status or source contradiction')
    images = custody['images']
    if [r['screenshot_number'] for r in images] != list(range(1, 9)):
        raise ValueError('exact eight screenshot identities required')
    expected_files = {'screenshot-custody.json', 'independent-visual-transcription.csv'}
    for number, image in enumerate(images, 1):
        if image['path'] != f'splashsports-{number:02}.png':
            raise ValueError('screenshot path identity')
        p = evidence / image['path']
        if readiness.digest(p.read_bytes()) != image['sha256'] or p.stat().st_size != image['bytes']:
            raise ValueError('original screenshot bytes changed')
        expected_files.add(image['path'])
    if {p.name for p in evidence.iterdir()} != expected_files:
        raise ValueError('exact screenshot custody coverage required')
    if images[0]['sha256'] != metadata['screenshot_last_asset_available_sha256']:
        raise ValueError('previous available asset hash does not match recovered chronological image01')
    if custody['independent_review_path'] != 'independent-visual-transcription.csv':
        raise ValueError('review path identity')
    review = evidence / custody['independent_review_path']
    if readiness.digest(review.read_bytes()) != custody['independent_review_sha256']:
        raise ValueError('independent visual transcription changed')
    rows = read_csv(review)
    schedule = json.loads((readiness.OUT / 'schedule.json').read_bytes())
    original.reconcile(source, metadata, transcription, reconciliation, schedule)
    if len(rows) != len(source):
        raise ValueError('67 independently inspected rows required')
    aliases = json.loads((readiness.OUT / 'resolver-aliases.json').read_bytes())
    aliases['SplashSports'].update(metadata['normalized_aliases'])
    resolver = CanonicalTeamResolver(sorted({r[s] for r in schedule for s in ('away', 'home')}), aliases)
    for image_row, row, transcribed, reconciled in zip(rows, source, transcription, reconciliation):
        if (image_row['image'], image_row['row']) != (transcribed['screenshot_number'], transcribed['row_in_screenshot']):
            raise ValueError('screenshot row identity conflict')
        for side in ('away', 'home'):
            resolved = resolver.resolve('SplashSports', image_row[side])
            if resolved.status != 'resolved' or resolved.canonical_name != reconciled['canonical_' + side]:
                raise ValueError('visual team identity conflict')
        if Decimal(image_row['away_spread']) != -Decimal(row['Spread']) or Decimal(image_row['total']) != Decimal(row['Total']):
            raise ValueError('visual locked-line discrepancy')
        displayed = datetime.strptime(row['Game Date'] + ' ' + row['Game Time'], '%Y-%m-%d %I:%M %p')
        if displayed.strftime('%a') != image_row['day'] or displayed.strftime('%I:%M%p').lstrip('0').lower() != image_row['clock']:
            raise ValueError('visual date/clock discrepancy')
    received = readiness.timestamp(custody['chat_received_at_utc'])
    if received != datetime.fromtimestamp(custody['chat_received_unix_seconds'], timezone.utc):
        raise ValueError('actual chat receipt mismatch')
    if received > readiness.timestamp(custody['recovered_at_utc']):
        raise ValueError('recovery before source receipt')
    return dict(custody=custody, images=8, independently_verified_line_pairs=len(rows),
                discrepancy_count=0, original_source_sha256=metadata['production_csv_sha256'])


def prepare(eligibility_folder: Path, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if any(p.exists() for p in (SOURCE, METADATA, OUT / 'source-reconciliation.json')):
        raise FileExistsError('prospective subset already exists; never overwrite')
    verified = verify_images()
    if readiness.timestamp(verified['custody']['recovered_at_utc']) > now:
        raise ValueError('image recovery after preparation time')
    ledger = week11_eligibility.verify(eligibility_folder)
    age = now - readiness.timestamp(ledger['as_of_utc'])
    if not timedelta(0) <= age <= timedelta(minutes=5):
        raise ValueError('refresh both providers within five minutes before prospective preparation')
    if ledger['blocked_provider_conflict'] or any(r['issues'] for r in ledger['games']):
        raise ValueError('provider conflicts require reconciliation')
    source, _, transcription, mapping = original.load()
    by_game = readiness.unique(ledger['games'], 'game_id')
    eligible, excluded, records = [], [], []
    for index, (row, mapped) in enumerate(zip(source, mapping), 1):
        game = by_game[mapped['game_id']]
        kickoff = readiness.timestamp(game['original_kickoff_utc'])
        if game['eligibility'].startswith('EXCLUDED') or kickoff <= now:
            excluded.append(dict(game_id=int(mapped['game_id']), source_row=index,
                                 kickoff_utc=kickoff.isoformat(), reason='ELAPSED_OR_STARTED_BEFORE_MODEL_EXECUTION'))
        elif game['eligibility'] == 'UPCOMING_SCHEDULE_ONLY':
            eligible.append(row.copy())
        else:
            raise ValueError('unhandled eligibility state')
        records.append(dict(game_id=int(mapped['game_id']), original_source_row=index,
                            canonical_home=mapped['canonical_home'], canonical_away=mapped['canonical_away'],
                            screenshot=int(transcription[index-1]['screenshot_number']),
                            eligibility=game['eligibility'], line_values_match=True))
    if len(eligible) + len(excluded) != 67 or not eligible:
        raise ValueError('incomplete or empty prospective coverage')
    earliest = min(readiness.timestamp(g['original_kickoff_utc']) for g in ledger['games']
                   if g['eligibility'] == 'UPCOMING_SCHEDULE_ONLY')
    if readiness.timestamp(verified['custody']['recovered_at_utc']) >= earliest:
        raise ValueError('screenshot recovery not pregame for prospective subset')
    text = io.StringIO(newline='')
    writer = csv.DictWriter(text, fieldnames=list(eligible[0]), lineterminator='\n')
    writer.writeheader(); writer.writerows(eligible)
    raw = text.getvalue().encode()
    metadata = dict(season=2026, week=11, contest_key=CONTEST_KEY, source='SplashSports',
                    authoritative_locked_lines=True, source_received_at_utc=verified['custody']['chat_received_at_utc'],
                    source_timestamp_kind='chat_received', game_time_zone='America/Chicago',
                    spread_convention='home_team_spread', total_convention='contest_over_under',
                    canonical_csv_sha256=readiness.digest(raw), raw_file_sha256=readiness.digest(raw),
                    game_count=len(eligible), original_game_count=67, original_source_sha256=verified['original_source_sha256'],
                    excluded_completed_games=excluded, unlined_fbs_games=[],
                    screenshot_custody_sha256=readiness.digest((EVIDENCE / 'screenshot-custody.json').read_bytes()),
                    eligibility_capture=eligibility_folder.relative_to(ROOT).as_posix(),
                    eligibility_manifest_sha256=readiness.digest((eligibility_folder / 'capture-manifest.json').read_bytes()),
                    prepared_at_utc=now.isoformat(), owner_approval='PENDING', model_policy='Master Prompt v2.8 UNCHANGED')
    for path, content in ((SOURCE, raw), (METADATA, readiness.serialized(metadata)),
                          (OUT / 'source-reconciliation.json', readiness.serialized(dict(verification=verified, rows=records)))):
        with path.open('xb') as stream:
            stream.write(content)
    return metadata


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--eligibility', type=Path)
    args = parser.parse_args()
    result = prepare(args.eligibility) if args.eligibility else verify_images()
    print(json.dumps(result, indent=2))
