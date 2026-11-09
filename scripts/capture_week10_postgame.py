"""Capture fresh ESPN and CFBD postgame evidence, without any forecast writes."""
from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

from scripts.capture_week6_core import _key

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / 'outputs/2026-week10-postgame-evidence'
BOARD = ROOT / 'outputs/2026-week10-prospective'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/'
CFBD = 'https://api.collegefootballdata.com'
VERSION = 'week10-postgame-capture-v1'


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def capture(output: Path) -> dict:
    output = output.resolve()
    if not output.is_relative_to(PARENT) or output == PARENT or output.exists():
        raise ValueError('capture requires a new version inside the evidence directory')
    with (BOARD / 'week10_ats_full_card.csv').open(encoding='utf-8-sig', newline='') as stream:
        ids = [row['game_id'] for row in csv.DictReader(stream)]
    if len(ids) != 57 or len(set(ids)) != 57:
        raise ValueError('exactly 57 distinct eligible games required')
    from scripts.verify_week10_acceptance import verify
    verify()
    latest = max(datetime.fromisoformat(r['source_kickoff_utc'].replace('Z','+00:00')) for r in json.loads((BOARD/'week10_locked_line_snapshot.json').read_bytes())['lines'])
    if datetime.now(timezone.utc) <= latest:
        raise ValueError('postgame capture requires elapsed slate')
    key = _key()
    output.mkdir(parents=True, exist_ok=False)

    def fetch(spec: tuple) -> dict:
        name, provider, url, params = spec
        row = {'name': name, 'provider': provider, 'endpoint': url, 'parameters': params,
               'requested_at_utc': utc_now(), 'parser_version': VERSION}
        headers = {'User-Agent': 'CFB-Formal-Audit/1.0'}
        if provider == 'CFBD':
            headers['Authorization'] = 'Bearer ' + key
        try:
            response = requests.get(url, params=params, headers=headers, timeout=90)
            raw = response.content
            compressed = gzip.compress(raw, mtime=0)
            name_on_disk = name + '.json.gz'
            with (output / name_on_disk).open('xb') as stream:
                stream.write(compressed)
            row.update(received_at_utc=utc_now(), http_status=response.status_code,
                       resolved_url=response.url, path=name_on_disk,
                       raw_sha256=hashlib.sha256(raw).hexdigest(), raw_bytes=len(raw),
                       stored_sha256=hashlib.sha256(compressed).hexdigest())
            try:
                data = json.loads(raw)
                row['top_level_type'] = type(data).__name__
                row['records'] = len(data) if isinstance(data, list) else None
                row['status'] = 'CAPTURED' if response.status_code == 200 else 'HTTP_ERROR'
            except ValueError:
                row['status'] = 'INVALID_JSON'
        except requests.RequestException as exc:
            row.update(status='REQUEST_FAILED', received_at_utc=utc_now(), error_type=type(exc).__name__)
        return row

    requests_to_make = [('espn-scoreboard', 'ESPN', ESPN + 'scoreboard',
                         {'year': 2026, 'week': 10, 'seasontype': 2, 'groups': 80, 'limit': 300})]
    requests_to_make += [('espn-' + gid, 'ESPN', ESPN + 'summary', {'event': gid}) for gid in sorted(ids)]
    week = {'year': 2026, 'week': 10, 'seasonType': 'regular'}
    requests_to_make += [('cfbd-' + name, 'CFBD', CFBD + endpoint, dict(week, **({'excludeGarbageTime':'false'} if name == 'advanced' else {}))) for name, endpoint in
                         [('games', '/games'), ('team-stats', '/games/teams'),
                          ('player-stats', '/games/players'), ('advanced', '/stats/game/advanced'),
                          ('drives', '/drives'), ('plays', '/plays')]]
    with ThreadPoolExecutor(max_workers=6) as executor:
        records = list(executor.map(fetch, requests_to_make))
    required = {'espn-scoreboard', 'cfbd-games'} | {'espn-' + gid for gid in ids}
    failures = [r['name'] for r in records if r['name'] in required and r['status'] != 'CAPTURED']
    result = {'version': VERSION, 'season': 2026, 'week': 10, 'captured_at_utc': utc_now(),
              'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
              'capture_code_sha256_lf': hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
              'status': 'INCOMPLETE' if failures else 'CAPTURED_REQUIRES_RECONCILIATION',
              'required_game_ids': sorted(ids), 'required_request_failures': failures,
              'records': records, 'postgame_only': True, 'model_or_policy_changes': False}
    with (output / 'capture-manifest.json').open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    folder = args.output or PARENT / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    result = capture(folder)
    print(json.dumps({'folder': str(folder), 'status': result['status'],
                      'requests': [(r['name'], r['status'], r.get('records')) for r in result['records']]}))
