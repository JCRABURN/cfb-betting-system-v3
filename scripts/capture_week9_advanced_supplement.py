"""One-request additive correction of the optional advanced-stat endpoint."""
import gzip
import hashlib
import json
from datetime import datetime, timezone

import requests

from scripts.capture_week9_postgame import PARENT, _key, utc_now


def main():
    folder = PARENT / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-advanced')
    folder.mkdir(parents=True, exist_ok=False)
    record = dict(provider='CFBD', endpoint='https://api.collegefootballdata.com/stats/game/advanced',
                  parameters=dict(year=2026, week=9, seasonType='regular', excludeGarbageTime='false'),
                  requested_at_utc=utc_now(), parser_version='week9-advanced-supplement-v1',
                  documentation='https://github.com/CFBD/cfbd-python/blob/main/README.md',
                  supersedes_failed_request='20261104T150801Z/cfbd-advanced.json.gz',
                  preserves_failed_response=True, postgame_only=True)
    response = requests.get(record['endpoint'], params=record['parameters'],
                            headers={'Authorization': 'Bearer ' + _key()}, timeout=90)
    raw = response.content
    stored = gzip.compress(raw, mtime=0)
    (folder / 'cfbd-advanced.json.gz').write_bytes(stored)
    record.update(received_at_utc=utc_now(), http_status=response.status_code,
                  raw_sha256=hashlib.sha256(raw).hexdigest(), raw_bytes=len(raw),
                  stored_sha256=hashlib.sha256(stored).hexdigest(), path='cfbd-advanced.json.gz',
                  capture_code_sha256_lf=hashlib.sha256(__import__('pathlib').Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest())
    try:
        data = json.loads(raw)
        record.update(status='CAPTURED' if response.status_code == 200 and isinstance(data, list) else 'FAILED',
                      records=len(data) if isinstance(data, list) else None)
    except ValueError:
        record['status'] = 'INVALID_JSON'
    (folder / 'capture-manifest.json').write_text(json.dumps(record, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'folder': str(folder), 'status': record['status'], 'records': record.get('records')}))
    if record['status'] != 'CAPTURED':
        raise ValueError('advanced supplement failed; raw response preserved')


if __name__ == '__main__':
    main()
