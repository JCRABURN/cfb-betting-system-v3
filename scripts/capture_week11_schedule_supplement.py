"""Preserve a date-bounded ESPN schedule after the week query returned only 25 games."""
import gzip
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone
import requests
from scripts.capture_week11_readiness import ROOT, PARENT, ESPN, digest, instant


def capture():
    output=PARENT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-schedule')
    output.mkdir(parents=True,exist_ok=False)
    params={'dates':'20261110-20261116','groups':80,'limit':1000}
    requested=instant();response=requests.get(ESPN,params=params,timeout=60)
    raw=response.content;stored=gzip.compress(raw,mtime=0)
    with (output/'espn-date-schedule.json.gz').open('xb') as f:f.write(stored)
    m=dict(version='week11-date-schedule-v1',requested_at_utc=requested,received_at_utc=instant(),
           endpoint=ESPN,parameters=params,resolved_url=response.url,http_status=response.status_code,
           path='espn-date-schedule.json.gz',raw_sha256=digest(raw),stored_sha256=digest(stored),
           source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
           code_sha256_lf=digest(Path(__file__).read_bytes().replace(b'\r\n',b'\n')),
           reason='Original ESPN week query returned 25 games versus 67 CFBD games; preserve both responses and reconcile date-bounded supplement.',
           contest_lines_locked=False,predictions_generated=False)
    with (output/'capture-manifest.json').open('x',encoding='utf-8',newline='\n') as f:f.write(json.dumps(m,indent=2)+'\n')
    response.raise_for_status()
    print(json.dumps(dict(output=str(output),events=len(json.loads(raw)['events']))))


if __name__=='__main__':capture()
