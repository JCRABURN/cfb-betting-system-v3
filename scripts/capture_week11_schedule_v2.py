"""Preserve a bounded-size ESPN week query; retain earlier partial/error captures."""
import gzip
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone
import requests
from scripts.capture_week11_readiness import ROOT, PARENT, ESPN, digest, instant


def capture():
    output=PARENT/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-schedule-v2')
    output.mkdir(parents=True,exist_ok=False)
    params={'year':2026,'week':11,'seasontype':2,'groups':80,'limit':300}
    requested=instant();response=requests.get(ESPN,params=params,timeout=60)
    raw=response.content;stored=gzip.compress(raw,mtime=0)
    with (output/'espn-week-schedule.json.gz').open('xb') as f:f.write(stored)
    m=dict(version='week11-week-schedule-v2',requested_at_utc=requested,received_at_utc=instant(),
           endpoint=ESPN,parameters=params,resolved_url=response.url,http_status=response.status_code,
           path='espn-week-schedule.json.gz',raw_sha256=digest(raw),stored_sha256=digest(stored),
           source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
           code_sha256_lf=digest(Path(__file__).read_bytes().replace(b'\r\n',b'\n')),
           reason='Original limit=1000 week query returned 25 events; date-range query returned HTTP400. Retry the prior verified 300-event week-query form and preserve every response.',
           contest_lines_locked=False,predictions_generated=False)
    with (output/'capture-manifest.json').open('x',encoding='utf-8',newline='\n') as f:f.write(json.dumps(m,indent=2)+'\n')
    response.raise_for_status()
    print(json.dumps(dict(output=str(output),events=len(json.loads(raw)['events']))))


if __name__=='__main__':capture()
