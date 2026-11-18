"""Reconcile the original Week 12 PDF transcription without changing its lines."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ingestion import CanonicalTeamResolver
from ingestion.custody import DEFAULT_TEAM_ALIASES
from scripts.capture_week12_readiness import ROOT, digest
from scripts.prepare_week11_readiness import read_payload, serialized, timestamp, unique

SOURCE = ROOT / 'data/ingest/2026-week12-splashsports'
PDF_SHA = '60d6ced55737fe6749a34f092735b3a613d75824ebfd9138de1aa429d393edd2'
CAPTURE = ROOT / 'outputs/2026-week12-readiness/20261118T190925Z'
OUT = SOURCE / 'frozen-v1'
DAY = {'Tue': 17, 'Wed': 18, 'Thu': 19, 'Fri': 20, 'Sat': 21}


def parse_pages(pages: list[str]) -> list[dict]:
    if len(pages) != 8 or 'Week 12' not in pages[0]:
        raise ValueError('eight original Week 12 pages required')
    rows = []
    for page, text in enumerate(pages, 1):
        if '11/17/26, 2:22' not in text or f'Page {page} of 8' not in text:
            raise ValueError('page date or pagination changed')
        lines = text.splitlines()
        for i, line in enumerate(lines):
            match = re.fullmatch(r'([A-Z0-9-]+) @ ([A-Z0-9-]+)', line)
            if not match:
                continue
            away_code, home_code = match.groups()
            pattern = (re.escape(away_code) + r'(.+?) \d+-\d+ · ([+-]\d+\.5) '
                       + re.escape(home_code) + r'(.+?) \d+-\d+ · ([+-]\d+\.5) '
                       + r'(Tue|Wed|Thu|Fri|Sat) (\d{1,2}:\d{2}[ap]m)')
            detail = re.fullmatch(pattern, lines[i+1])
            total = re.fullmatch(r'Over (\d+\s*\.5) Under (\d+\s*\.5)', lines[i+2])
            if not detail or not total:
                raise ValueError(f'unparsed source row {page}: {line}')
            away, aspread, home, hspread, day, clock = detail.groups()
            a, h = float(aspread), float(hspread)
            over, under = (float(v.replace(' ', '')) for v in total.groups())
            if a != -h or over != under or not 0 < over < 150:
                raise ValueError('spread sign or paired total mismatch')
            # This dated November source explicitly displays CST (UTC-6).
            local = datetime.strptime(f'2026-11-{DAY[day]} {clock}', '%Y-%m-%d %I:%M%p').replace(tzinfo=timezone(timedelta(hours=-6)))
            rows.append(dict(source_row=len(rows)+1, pdf_page=page, raw_away=away,
                             raw_home=home, away_abbreviation=away_code, home_abbreviation=home_code,
                             away_spread=a, home_spread=h, locked_total=over,
                             displayed_kickoff=f'{day} {clock}', source_kickoff_utc=local.astimezone(timezone.utc).isoformat()))
    if len(rows) != 66 or len({(r['raw_away'], r['raw_home']) for r in rows}) != 66:
        raise ValueError('exactly 66 unique matchups required')
    if len({t for r in rows for t in (r['raw_away'], r['raw_home'])}) != 132:
        raise ValueError('duplicate team on weekly board')
    return rows


def load_capture(folder: Path = CAPTURE) -> tuple[dict, dict, dict]:
    manifest = json.loads((folder/'capture-manifest.json').read_bytes())
    if manifest['week'] != 12 or manifest['feature_cutoff'] != {'season': 2026, 'end_week': 11}:
        raise ValueError('Week 12 prior-week cutoff required')
    records = unique(manifest['records'], 'name')
    data = {key: read_payload(folder, value) for key, value in records.items()}
    if records['cfbd-prior-season-advanced']['parameters'] != {'year':2026,'endWeek':11,'excludeGarbageTime':'true'}:
        raise ValueError('feature request contamination')
    return manifest, records, data


def reconcile(rows: list[dict], data: dict, as_of: datetime) -> tuple[list[dict], list[dict]]:
    teams = unique(data['cfbd-all-teams'], 'id')
    resolver = CanonicalTeamResolver(sorted({t['school'] for t in teams.values()}), DEFAULT_TEAM_ALIASES)
    games = {gid: g for gid, g in unique(data['cfbd-games-all'], 'id').items()
             if g['season'] == 2026 and g['week'] == 12 and
             'fbs' in (g['homeClassification'], g['awayClassification'])}
    espn = data['espn-schedule']
    if espn['season'] != {'type': 2, 'year': 2026} or espn['week']['number'] != 12:
        raise ValueError('ESPN season/week conflict')
    events = unique(espn['events'], 'id')
    matched = []
    for raw in rows:
        names = {}
        for side in ('away', 'home'):
            resolved = resolver.resolve('SplashSports', raw['raw_'+side])
            if resolved.status != 'resolved':
                raise ValueError('unrecognized team: '+raw['raw_'+side])
            names[side] = resolved.canonical_name
        choices = [g for g in games.values() if all(g[s+'Team'] == names[s] for s in names)]
        if len(choices) != 1:
            raise ValueError('missing/ambiguous/reversed provider matchup: '+str(names))
        g = choices[0]
        event = events[str(g['id'])]
        if len(event['competitions']) != 1:
            raise ValueError('ambiguous ESPN competition')
        c = event['competitions'][0]
        sides = unique(c['competitors'], 'homeAway')
        if set(sides) != {'home', 'away'} or any(str(g[s+'Id']) != str(sides[s]['team']['id']) for s in sides):
            raise ValueError('provider orientation/identity conflict')
        if any(teams[str(g[s+'Id'])]['school'] != g[s+'Team'] for s in sides):
            raise ValueError('canonical provider registry conflict')
        times = {timestamp(x) for x in (g['startDate'], c['date'], raw['source_kickoff_utc'])}
        issues = [] if len(times) == 1 else ['KICKOFF_DIFFERENCE_PRESERVE_SOURCE']
        elapsed = min(times) <= as_of or g['completed'] or c['status']['type']['state'] != 'pre'
        if not elapsed and (g['homePoints'] is not None or g['awayPoints'] is not None):
            raise ValueError('upcoming score contamination')
        if g['startTimeTBD']:
            issues.append('KICKOFF_TBD')
        matched.append(dict(**raw, game_id=g['id'], **names, away_id=g['awayId'], home_id=g['homeId'],
                            provider_kickoff_utc=g['startDate'], espn_kickoff_utc=c['date'],
                            status='ELAPSED_NO_PROSPECTIVE_FORECAST' if elapsed else ('BLOCKED_PROVIDER_CONFLICT' if issues else 'UPCOMING'),
                            issues=';'.join(issues)))
    if len({r['game_id'] for r in matched}) != 66:
        raise ValueError('duplicate provider game')
    included = {r['game_id'] for r in matched}
    extras = [dict(game_id=g['id'], away=g['awayTeam'], home=g['homeTeam'], kickoff_utc=g['startDate'],
                   classification=f"{g['awayClassification']}_vs_{g['homeClassification']}",
                   status='NOT_DISPLAYED_ON_ORIGINAL_66_GAME_PDF_NO_CONTEST_LINE')
              for g in games.values() if g['id'] not in included]
    return matched, extras


def csv_bytes(rows: list[dict]) -> bytes:
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
    writer.writeheader(); writer.writerows(rows)
    return stream.getvalue().encode()


def build() -> dict[str, bytes]:
    if digest((SOURCE/'original.pdf').read_bytes()) != PDF_SHA:
        raise ValueError('original PDF checksum changed')
    receipt = json.loads((SOURCE/'receipt.json').read_bytes())
    if receipt['sha256'] != PDF_SHA or receipt['displayed_print_time'] != '2026-11-17T14:22:00-06:00':
        raise ValueError('source receipt contradiction')
    pages = json.loads((SOURCE/'extracted-pages.json').read_bytes())
    rows = parse_pages(pages)
    manifest, records, data = load_capture()
    as_of = max(timestamp(r['received_at_utc']) for r in records.values())
    reconciled, extras = reconcile(rows, data, as_of)
    outputs = {'contest-lines.csv': csv_bytes(rows), 'provider-reconciliation.csv': csv_bytes(reconciled),
               'scheduled-games-not-on-pdf.json': serialized(extras)}
    report = dict(version='week12-source-v1', source='SplashSports', season=2026, week=12,
                  source_timestamp=receipt['displayed_print_time'], source_timestamp_kind='PDF_PRINT_TIME_NOT_MODEL_FORECAST',
                  actual_recovery_timestamp=receipt['recovered_at_utc'], pdf_sha256=PDF_SHA,
                  extracted_text_sha256=digest((SOURCE/'extracted-pages.json').read_bytes()),
                  receipt_sha256=digest((SOURCE/'receipt.json').read_bytes()),
                  provider_manifest_sha256=digest((CAPTURE/'capture-manifest.json').read_bytes()),
                  eligibility_as_of_utc=as_of.isoformat(), game_count=66, ats_count=66, totals_count=66,
                  canonical_matches=66, duplicate_games=0, unresolved_teams=0,
                  kickoff_differences=sum(bool(r['issues']) for r in reconciled),
                  elapsed_games=sum(r['status'].startswith('ELAPSED') for r in reconciled),
                  upcoming_games=sum(r['status']=='UPCOMING' for r in reconciled),
                  additional_provider_games=len(extras),
                  visual_validation='All eight original PDF pages inspected; all 66 names, signed spreads, paired totals and displayed kickoffs checked.',
                  calibrated_cross_market_probabilities_available=False, policy='v2.8 unchanged',
                  files={name:digest(raw) for name,raw in outputs.items()})
    outputs['manifest.json'] = serialized(report)
    return outputs


def main(verify: bool = False) -> None:
    outputs = build()
    if verify:
        if {p.name for p in OUT.iterdir()} != set(outputs):
            raise ValueError('frozen source file coverage')
        for name, raw in outputs.items():
            if (OUT/name).read_bytes() != raw:
                raise ValueError('frozen source changed: '+name)
    else:
        OUT.mkdir(exist_ok=False)
        for name,raw in outputs.items():
            with (OUT/name).open('xb') as stream:
                stream.write(raw)
    print(outputs['manifest.json'].decode())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--verify', action='store_true')
    main(parser.parse_args().verify)
