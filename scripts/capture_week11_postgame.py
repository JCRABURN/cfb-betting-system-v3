"""Explicitly authorized, append-only postgame ESPN/CFBD capture; no database writes."""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from scripts.capture_week6_core import _key
from scripts.week11_audit_inputs import ROOT, EVIDENCE, SOURCE_COMMIT, source_csv, sha


def now():
    return datetime.now(timezone.utc).isoformat()


def capture(output: Path):
    output = output.resolve()
    if not output.is_relative_to(EVIDENCE) or output == EVIDENCE or output.exists():
        raise ValueError('Capture requires a new evidence directory')
    board = source_csv('data/ingest/2026-week11-splashsports-schedule-reconciliation.csv')
    ids = sorted(r['game_id'] for r in board)
    if len(ids) != 67 or len(set(ids)) != 67:
        raise ValueError('67 distinct original games required')
    if any(datetime.fromisoformat(r['provider_utc_kickoff'].replace('Z', '+00:00')) >= datetime.now(timezone.utc) for r in board):
        raise ValueError('Slate has not elapsed')
    key = _key()
    output.mkdir(parents=True, exist_ok=False)
    espn = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/'
    specs = [('espn-scoreboard', 'ESPN', espn + 'scoreboard', dict(year=2026, week=11, seasontype=2, groups=80, limit=300))]
    specs += [('espn-' + gid, 'ESPN', espn + 'summary', dict(event=gid)) for gid in ids]
    specs += [('cfbd-' + name, 'CFBD', 'https://api.collegefootballdata.com' + endpoint,
               dict(year=2026, week=11, seasonType='regular', **({'excludeGarbageTime': 'false'} if name == 'advanced' else {})))
              for name, endpoint in [('games', '/games'), ('team-stats', '/games/teams'), ('player-stats', '/games/players'),
                                     ('advanced', '/stats/game/advanced'), ('drives', '/drives'), ('plays', '/plays'), ('lines', '/lines')]]

    def fetch(spec):
        name, provider, url, params = spec
        row = dict(name=name, provider=provider, endpoint=url, parameters=params, requested_at_utc=now(), parser_version='week11-postgame-v1')
        headers = {'User-Agent': 'CFB-Forensic-Audit/1.0'}
        if provider == 'CFBD':
            headers['Authorization'] = 'Bearer ' + key
        try:
            response = requests.get(url, params=params, headers=headers, timeout=45)
            raw = response.content
            compressed = gzip.compress(raw, mtime=0)
            name_on_disk = name + '.json.gz'
            with (output / name_on_disk).open('xb') as stream:
                stream.write(compressed)
            row.update(received_at_utc=now(), http_status=response.status_code, resolved_url=response.url,
                       path=name_on_disk, raw_sha256=sha(raw), raw_bytes=len(raw), stored_sha256=sha(compressed))
            try:
                data = json.loads(raw)
                row.update(status='CAPTURED' if response.status_code == 200 else 'HTTP_ERROR',
                           records=len(data) if isinstance(data, list) else None)
            except ValueError:
                row['status'] = 'INVALID_JSON'
        except requests.RequestException as exc:
            row.update(status='REQUEST_FAILED', received_at_utc=now(), error_type=type(exc).__name__)
        return row

    with ThreadPoolExecutor(max_workers=6) as executor:
        records = list(executor.map(fetch, specs))
    failures = [r['name'] for r in records if r['status'] != 'CAPTURED']
    manifest = dict(version='week11-postgame-v1', season=2026, week=11, captured_at_utc=now(),
                    source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    prediction_source_commit=SOURCE_COMMIT, capture_code_sha256_lf=sha(Path(__file__).read_bytes().replace(b'\r\n', b'\n')),
                    required_game_ids=ids, records=records, request_failures=failures,
                    status='INCOMPLETE' if failures else 'CAPTURED_REQUIRES_RECONCILIATION',
                    postgame_only=True, prediction_or_database_writes=False,
                    lines_qualification='POSTGAME_OBSERVATIONS_UNLESS_PROVIDER_SUPPLIES_ACTUAL_QUOTE_TIMESTAMPS')
    with (output / 'capture-manifest.json').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    return dict(output=str(output), requests=len(records), failures=failures)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    print(json.dumps(capture(parser.parse_args().output)))
