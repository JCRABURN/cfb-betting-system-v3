"""Owner-authorized postgame season capture; raw responses only, no DB writes."""
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
from scripts.week11_audit_inputs import ROOT, sha

EVIDENCE = ROOT / 'outputs/2026-season-contest-evidence'


def capture(output: Path):
    output = output.resolve()
    if not output.is_relative_to(EVIDENCE) or output == EVIDENCE or output.exists():
        raise ValueError('Use a new season evidence directory')
    key = _key()
    output.mkdir(parents=True)
    specs = []
    for week in range(1, 12):
        specs.extend([
            (f'cfbd-week{week}', 'CFBD', 'https://api.collegefootballdata.com/games',
             dict(year=2026, week=week, seasonType='regular')),
            (f'espn-week{week}', 'ESPN', 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard',
             dict(year=2026, week=week, seasontype=2, groups=80, limit=300)),
        ])
    now = lambda: datetime.now(timezone.utc).isoformat()
    def fetch(spec):
        name, provider, url, params = spec
        row = dict(name=name, provider=provider, endpoint=url, parameters=params,
                   requested_at_utc=now(), parser_version='season-contest-v1')
        headers = {'User-Agent': 'CFB-Season-Audit/1.0'}
        if provider == 'CFBD':
            headers['Authorization'] = 'Bearer ' + key
        try:
            response = requests.get(url, params=params, headers=headers, timeout=45)
            raw = response.content
            stored = gzip.compress(raw, mtime=0)
            path = name + '.json.gz'
            (output / path).write_bytes(stored)
            payload = json.loads(raw)
            row.update(received_at_utc=now(), http_status=response.status_code,
                       resolved_url=response.url, path=path, raw_sha256=sha(raw),
                       stored_sha256=sha(stored), raw_bytes=len(raw),
                       records=len(payload) if isinstance(payload, list) else len(payload.get('events', [])),
                       status='CAPTURED' if response.status_code == 200 else 'HTTP_ERROR')
        except (requests.RequestException, ValueError) as exc:
            row.update(received_at_utc=now(), status='FAILED', error_type=type(exc).__name__)
        return row
    with ThreadPoolExecutor(max_workers=4) as pool:
        records = list(pool.map(fetch, specs))
    failures = [r['name'] for r in records if r['status'] != 'CAPTURED']
    manifest = dict(version='season-contest-v1', season=2026, weeks=list(range(1, 12)),
                    captured_at_utc=now(), source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                    code_sha256_lf=sha(Path(__file__).read_bytes().replace(b'\r\n',b'\n')),
                    records=records, failures=failures, postgame_only=True,
                    status='INCOMPLETE' if failures else 'CAPTURED_REQUIRES_RECONCILIATION')
    (output/'capture-manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf8')
    return dict(requests=len(records), failures=failures)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--output',type=Path,required=True)
    print(json.dumps(capture(parser.parse_args().output)))
