"""Postgame-only Week8 play evidence for drive quarantine adjudication."""
import gzip
import json
from datetime import datetime, timezone
import requests
from scripts.capture_week6_core import _key
from scripts.week11_audit_inputs import EVIDENCE, sha


def main():
    output=EVIDENCE/'drive-supplement-v1'
    if output.exists():
        raise FileExistsError('Immutable evidence already exists')
    now=lambda:datetime.now(timezone.utc).isoformat()
    requested=now(); url='https://api.collegefootballdata.com/plays'
    params=dict(year=2026,week=8,seasonType='regular')
    response=requests.get(url,params=params,headers={'Authorization':'Bearer '+_key()},timeout=60)
    raw=response.content; compressed=gzip.compress(raw,mtime=0)
    output.mkdir(parents=True,exist_ok=False)
    (output/'cfbd-week8-plays.json.gz').write_bytes(compressed)
    row=dict(name='cfbd-week8-plays',provider='CFBD',endpoint=url,parameters=params,requested_at_utc=requested,
             received_at_utc=now(),http_status=response.status_code,resolved_url=response.url,path='cfbd-week8-plays.json.gz',
             raw_sha256=sha(raw),stored_sha256=sha(compressed),raw_bytes=len(raw),
             status='CAPTURED' if response.status_code==200 else 'HTTP_ERROR',purpose='POSTGAME_ADJUDICATION_ONLY_NOT_HISTORICAL_PREGAME_FEATURES')
    (output/'capture-manifest.json').write_text(json.dumps(row,indent=2,sort_keys=True)+'\n',encoding='utf8',newline='\n')
    print(json.dumps(row))


if __name__=='__main__':main()
