"""Append-only Week 11 readiness capture; never creates contest locks or picks."""
from __future__ import annotations

import argparse
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
PARENT = ROOT / 'outputs/2026-week11-readiness'
CFBD = 'https://api.collegefootballdata.com'
ESPN = 'https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard'
SPECS = [
    ('cfbd-games-all', CFBD+'/games', {'year':2026, 'seasonType':'regular'}),
    ('cfbd-fbs-teams', CFBD+'/teams/fbs', {'year':2026}),
    ('cfbd-all-teams', CFBD+'/teams', {}),
    ('cfbd-venues', CFBD+'/venues', {}),
    ('cfbd-prior-season-advanced', CFBD+'/stats/season/advanced', {'year':2026,'endWeek':10,'excludeGarbageTime':'true'}),
    ('cfbd-market-observations', CFBD+'/lines', {'year':2026,'week':11,'seasonType':'regular'}),
    ('espn-schedule', ESPN, {'year':2026,'week':11,'seasontype':2,'groups':80,'limit':1000}),
] + [(f'cfbd-prior-week{week}-{kind}', CFBD+endpoint,
      dict(year=2026,week=week,seasonType='regular',**({'excludeGarbageTime':'false'} if kind=='advanced' else {})))
     for week in (8,9,10) for kind,endpoint in [('advanced','/stats/game/advanced'),('drives','/drives')]]


def instant():
    return datetime.now(timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def capture(output: Path):
    output=output.resolve()
    if output==PARENT or not output.is_relative_to(PARENT) or output.exists():
        raise ValueError('new timestamped Week11 readiness directory required')
    key=_key()
    output.mkdir(parents=True,exist_ok=False)

    def fetch(spec):
        name,url,params=spec
        record=dict(name=name,endpoint=url,parameters=params,requested_at_utc=instant())
        headers={'User-Agent':'CFB-Week11-Readiness/1.0'}
        if url.startswith(CFBD+'/'):headers['Authorization']='Bearer '+key
        try:
            response=requests.get(url,params=params,headers=headers,timeout=90)
            raw=response.content;stored=gzip.compress(raw,mtime=0);filename=name+'.json.gz'
            with (output/filename).open('xb') as stream:stream.write(stored)
            record.update(received_at_utc=instant(),http_status=response.status_code,path=filename,
                          raw_sha256=digest(raw),stored_sha256=digest(stored),raw_bytes=len(raw),resolved_url=response.url)
            try:
                parsed=json.loads(raw)
                record.update(status='CAPTURED' if response.status_code==200 else 'HTTP_ERROR',
                              records=len(parsed) if isinstance(parsed,list) else None)
            except ValueError:record['status']='INVALID_JSON'
        except requests.RequestException as error:
            record.update(received_at_utc=instant(),status='REQUEST_FAILED',error_type=type(error).__name__)
        return record

    with ThreadPoolExecutor(max_workers=4) as pool:records=list(pool.map(fetch,SPECS))
    manifest=dict(version='week11-readiness-capture-v1',season=2026,week=11,captured_at_utc=instant(),
                  source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                  capture_code_sha256_lf=digest(Path(__file__).read_bytes().replace(b'\r\n',b'\n')),
                  status='CAPTURED_REQUIRES_RECONCILIATION' if all(r['status']=='CAPTURED' for r in records) else 'INCOMPLETE',
                  records=records,owner_screenshots_received=False,contest_lines_locked=False,predictions_generated=False,
                  governing_policy='Master Prompt v2.8',policy_changed=False,
                  feature_cutoff=dict(season=2026,end_week=10),market_prices_are_contest_lines=False,
                  note='Schedule coverage includes every game involving an FBS team, including FCS opponents. Retrieval time is not a market quote timestamp. No target-game results may enter prediction features.')
    with (output/'capture-manifest.json').open('x',encoding='utf-8',newline='\n') as stream:
        stream.write(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args()
    out=a.output or PARENT/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    result=capture(out)
    print(json.dumps(dict(output=str(out),status=result['status'],records=[(r['name'],r['status'],r.get('records')) for r in result['records']])))
