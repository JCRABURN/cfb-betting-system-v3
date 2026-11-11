"""Run unchanged v2.8 modules on verified Week11 lines in a disposable database."""
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from business_entities.full_card import locked_line_snapshot_sha256
from business_entities.totals_weekly_model import run_component_totals_shadow_model
from business_entities.weekly_controller import run_epa_only_model
from contest_lines import create_contest, list_effective_locked_lines, lock_contest_line
from migrations.runner import apply_migrations, table_row_counts
from operations.providers import CfbdGamesParser, CfbdTeamStatsParser, _write_games, _write_team_stats
from scripts import prepare_week11_readiness as readiness
from scripts import prepare_week11_source as source
from scripts import verify_week11_transcription as original
from scripts import week11_eligibility
from scripts.run_week6_execution import ingest, read_capture, iso, sha

ROOT, OUT = source.ROOT, source.OUT
SOURCE_DB = ROOT / 'data/cfb.db'


def write_json(path: Path, value: object) -> None:
    with path.open('xb') as stream:
        stream.write(readiness.serialized(value))


def prior_stats(week: int) -> tuple[list[dict], dict]:
    folders = {
        4: 'outputs/2026-week5-execution-20260930-v4/provider-evidence',
        5: 'outputs/2026-week6-execution-20261006T2133Z/provider-evidence/core',
        6: 'outputs/2026-week7-prospective/provider-evidence/core-initial',
        7: 'outputs/2026-week8-prospective-v2/core-initial',
        8: 'outputs/2026-week9-prospective/core-initial',
        9: 'outputs/2026-week10-prospective/core-initial',
    }
    folder = ROOT / folders[week]
    manifest = json.loads((folder / 'capture-manifest.json').read_bytes())
    manifest['requests'] = [{**r, 'requested_at': r.get('requested_at_utc', r.get('requested_at'))}
                            for r in manifest['requests']]
    values, item = read_capture(folder, manifest, f'cfbd-week{week}-advanced')
    if item['parameters'] != {'year': 2026, 'endWeek': week, 'excludeGarbageTime': 'true'}:
        raise ValueError('historical cumulative feature cutoff mismatch')
    return values, item


def locked_rows(now: datetime) -> tuple[list[dict], dict]:
    images = source.verify_images()
    if iso(images['custody']['recovered_at_utc']) > now:
        raise ValueError('image recovery after model generation')
    metadata = json.loads(source.METADATA.read_bytes())
    if (metadata['contest_key'] != source.CONTEST_KEY or metadata['week'] != 11
            or metadata['season'] != 2026 or metadata['owner_approval'] != 'PENDING'
            or metadata['raw_file_sha256'] != sha(source.SOURCE.read_bytes())
            or metadata['canonical_csv_sha256'] != sha(source.SOURCE.read_bytes())
            or metadata['screenshot_custody_sha256'] != sha((source.EVIDENCE / 'screenshot-custody.json').read_bytes())):
        raise ValueError('prospective source metadata/hash contradiction')
    folder = (ROOT / metadata['eligibility_capture']).resolve()
    if not folder.is_relative_to(readiness.PARENT) or sha((folder / 'capture-manifest.json').read_bytes()) != metadata['eligibility_manifest_sha256']:
        raise ValueError('eligibility custody mismatch')
    live = week11_eligibility.verify(folder)
    if not timedelta(0) <= now - iso(live['as_of_utc']) <= timedelta(minutes=5):
        raise ValueError('live eligibility must be captured within five minutes before execution')
    if live['blocked_provider_conflict'] or any(r['issues'] for r in live['games']):
        raise ValueError('live provider conflict')
    full, _, _, mapping = original.load()
    by_game = readiness.unique(live['games'], 'game_id')
    expected, excluded, rows = [], [], []
    for ordinal, (row, mapped) in enumerate(zip(full, mapping), 1):
        game = by_game[mapped['game_id']]
        if game['eligibility'].startswith('EXCLUDED'):
            excluded.append(int(mapped['game_id']))
            continue
        if game['eligibility'] != 'UPCOMING_SCHEDULE_ONLY' or iso(game['original_kickoff_utc']) <= now:
            raise ValueError('target kickoff elapsed or target no longer eligible')
        expected.append(row)
        rows.append(dict(csv_row=ordinal, game_id=int(mapped['game_id']), raw_away=row['Away Team'],
                         raw_home=row['Home Team'], away=mapped['canonical_away'], home=mapped['canonical_home'],
                         home_spread=float(row['Spread']), locked_total=float(row['Total']),
                         source_kickoff_utc=game['original_kickoff_utc'], provider_kickoff_utc=game['cfbd_kickoff_utc'],
                         total_status='LOCKED', source_note=row['Notes']))
    if (source.read_csv(source.SOURCE) != expected or len(rows) != metadata['game_count']
            or set(excluded) != {r['game_id'] for r in metadata['excluded_completed_games']}
            or len(rows) + len(excluded) != 67 or metadata['unlined_fbs_games']):
        raise ValueError('prospective subset must exactly preserve all eligible original rows')
    return rows, metadata


def run(database: Path) -> dict:
    database = database.resolve()
    if not database.is_relative_to(ROOT) or database == SOURCE_DB or database.exists():
        raise ValueError('new disposable database inside this isolated worktree required')
    if any((OUT / p).exists() for p in ('provider-evidence', 'week11_ingestion_manifest.json',
                                      'week11_locked_line_snapshot.json', 'week11_initial_seal_manifest.json')):
        raise FileExistsError('execution output exists; never overwrite')
    now = datetime.now(timezone.utc)
    locked, metadata = locked_rows(now)
    readiness.main(True)
    capture, records, data, _ = readiness.load()
    # Only the November10 pregame capture supplies model data. Live Week11 results
    # are used exclusively for exclusion and never passed to ingestion or training.
    games = data['cfbd-games-all']
    teams = data['cfbd-fbs-teams']
    if records['cfbd-prior-season-advanced']['parameters'] != {'year': 2026, 'endWeek': 10, 'excludeGarbageTime': 'true'}:
        raise ValueError('Week11 features must end at Week10')
    def adapter(record):
        return {**record, 'requested_at': record['requested_at_utc'], 'sha256': record['raw_sha256']}
    games_item = adapter(records['cfbd-games-all'])
    stats = [(week, *prior_stats(week)) for week in range(4, 10)]
    stats.append((10, data['cfbd-prior-season-advanced'], adapter(records['cfbd-prior-season-advanced'])))
    for _, _, item in stats:
        if not iso(item['requested_at']) <= now:
            raise ValueError('feature receipt after generation')
    target_ids = {r['game_id'] for r in locked}
    targets = [g for g in games if g['id'] in target_ids]
    if (len(targets) != len(target_ids) or any(g['week'] != 11 or g['completed']
            or g['homePoints'] is not None or g['awayPoints'] is not None for g in targets)):
        raise ValueError('pregame target coverage or outcome contamination')
    source_hash = sha(SOURCE_DB.read_bytes())
    database.parent.mkdir(parents=True, exist_ok=True)
    with database.open('xb') as stream:
        stream.write(SOURCE_DB.read_bytes())
    if sha(database.read_bytes()) != source_hash:
        raise ValueError('disposable database copy checksum')
    conn = sqlite3.connect(database)
    conn.execute('PRAGMA foreign_keys=ON')
    before = table_row_counts(conn)
    if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('source copy integrity')
    migrations = apply_migrations(conn)
    for team in teams:
        if team['classification'] != 'fbs':
            raise ValueError('FBS identity registry conflict')
        if not conn.execute('SELECT 1 FROM teams WHERE school=?', (team['school'],)).fetchone():
            conn.execute('INSERT INTO teams(team_id,school,conference,division) VALUES(?,?,?,?)',
                         (team['id'], team['school'], team.get('conference'), team.get('division')))
    conn.commit()
    (OUT / 'provider-evidence').mkdir(exist_ok=False)
    ingestions = []
    for week in range(2, 12):
        batch = [g for g in games if g['week'] == week and g['homeClassification'] == g['awayClassification'] == 'fbs']
        if week < 11 and any(not g['completed'] for g in batch):
            raise ValueError('prior-week outcomes incomplete')
        if week == 11:
            batch = targets
        ingestions.append(ingest(conn, OUT, batch, name=f'cfbd-week{week}-games', item=games_item,
                                 parameters={'year': 2026, 'week': week, 'classification': 'fbs'},
                                 parser=CfbdGamesParser(), writer=_write_games))
    for week, values, item in stats:
        ingestions.append(ingest(conn, OUT, values, name=f'cfbd-week{week}-advanced', item=item,
                                 parameters={'year': 2026, 'endWeek': week, 'excludeGarbageTime': 'true'},
                                 parser=CfbdTeamStatsParser(), writer=_write_team_stats))
    contest = create_contest(conn, contest_key=source.CONTEST_KEY, name='SplashSports 2026 Week11',
                             season=2026, week=11, source='SplashSports', source_contest_id=source.CONTEST_KEY,
                             created_at=now, provenance='owner Week11 original screenshots; disposable copy')
    for row in locked:
        record = lock_contest_line(conn, contest_id=contest.id, game_id=row['game_id'],
            raw_home_team=row['raw_home'], raw_away_team=row['raw_away'], normalized_home_team=row['home'],
            normalized_away_team=row['away'], home_spread=row['home_spread'], total=row['locked_total'],
            source='SplashSports', source_line_id=f"original-csv-row:{row['csv_row']}",
            payload_sha256=metadata['original_source_sha256'], locked_at=now,
            provenance='unchanged original owner source;images independently verified;prospective subset')
        row['locked_line_id'] = record.line.id
    conn.commit()
    lines = list_effective_locked_lines(conn, contest.id, as_of=now)
    if len(lines) != len(locked):
        raise ValueError('locked-line coverage mismatch')
    lock_hash = locked_line_snapshot_sha256(lines)
    write_json(OUT / 'week11_locked_line_snapshot.json', dict(contest_key=source.CONTEST_KEY,
        source_csv_sha256=metadata['raw_file_sha256'], original_source_sha256=metadata['original_source_sha256'],
        metadata_sha256=sha(source.METADATA.read_bytes()), locked_at_utc=now.isoformat(),
        locked_line_snapshot_sha256=lock_hash, lines=locked))
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    ats = run_epa_only_model(conn, contest_id=contest.id, model_run_key='week11-20261111:epa',
                            code_commit_sha=commit, generated_at=now, provenance='owner-request://2026-week11-prospective')
    totals = run_component_totals_shadow_model(conn, contest_id=contest.id, model_run_key='week11-20261111:component-totals',
                            code_commit_sha=commit, generated_at=now, provenance='owner-request://2026-week11-prospective')
    conn.commit()
    ats_count = conn.execute('SELECT COUNT(*) FROM model_predictions WHERE model_run_id=?', (ats.id,)).fetchone()[0]
    total_count = conn.execute('SELECT COUNT(*) FROM total_model_predictions WHERE total_model_run_id=?', (totals.id,)).fetchone()[0]
    if ats_count != len(lines) or total_count != len(lines):
        raise ValueError('complete ATS and totals model coverage required')
    if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('post-execution database integrity')
    if sha(SOURCE_DB.read_bytes()) != source_hash:
        raise ValueError('protected source database changed')
    if datetime.now(timezone.utc) >= min(iso(r['source_kickoff_utc']) for r in locked):
        raise ValueError('execution reached first eligible kickoff')
    result = dict(generated_at_utc=now.isoformat(), code_commit_sha=commit,
        source_database_sha256=source_hash, source_csv_sha256=metadata['raw_file_sha256'],
        original_source_sha256=metadata['original_source_sha256'], metadata_sha256=sha(source.METADATA.read_bytes()),
        locked_line_snapshot_sha256=lock_hash, provider_capture=capture, provider_ingestion=ingestions,
        migration_versions=[m.version for m in migrations], before_counts=before, after_counts=table_row_counts(conn),
        locked_games=len(lines), ats_predictions=ats_count, totals_predictions=total_count,
        scheduled_fbs_games=67, excluded_completed_games=metadata['excluded_completed_games'],
        documented_unlined_fbs_games=[], explicit_missing_locked_totals=0,
        ats_run=asdict(ats), totals_run=asdict(totals), integrity='ok', foreign_key_violations=0)
    write_json(OUT / 'week11_ingestion_manifest.json', result)
    conn.close()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.database)
    print(json.dumps({k: result[k] for k in ('locked_games', 'ats_predictions', 'totals_predictions')}))
