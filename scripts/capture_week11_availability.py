"""Capture public conference reports through the official embedded read API."""
import argparse
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
import requests
from scripts.seal_week11_board import ROOT, sha

ENDPOINT = 'https://app.hdintelligence.com/api/get-publish-public'
OFFICIAL = {'B10':'https://bigten.org/sports/2026/9/10/FB_Availability_Reports.aspx',
            'B12':'https://big12sports.com/FBReporting',
            'ACC':'https://app.hdintelligence.com/?conf=ACC&source=ACC&sport=Football&type=report'}

def capture(folder):
    folder=folder.resolve()
    if not folder.is_relative_to(ROOT/'outputs/2026-week11-context') or folder.exists():raise ValueError('new append-only directory required')
    folder.mkdir(parents=True); records=[]
    for conference in OFFICIAL:
        params={'sport':'Football','organization':conference,'conference':conference}
        item=dict(provider='Official conference public report embed',conference=conference,official_wrapper=OFFICIAL[conference],endpoint=ENDPOINT,method='POST_READ_ONLY_PUBLIC_REPORT',parameters=params,requested_at_utc=datetime.now(timezone.utc).isoformat())
        response=requests.post(ENDPOINT,json=params,timeout=30)
        item.update(received_at_utc=datetime.now(timezone.utc).isoformat(),http_status=response.status_code)
        raw=response.content;name=conference+'.json.gz';stored=gzip.compress(raw,mtime=0)
        with (folder/name).open('xb') as stream:stream.write(stored)
        item.update(path=name,raw_sha256=hashlib.sha256(raw).hexdigest(),stored_sha256=hashlib.sha256(stored).hexdigest(),status='CAPTURED' if response.ok else 'FAILED')
        records.append(item)
    payload=dict(records=records,created_at_utc=datetime.now(timezone.utc).isoformat(),code_sha256_lf=hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n',b'\n')).hexdigest(),usage='Pregame context only for future candidate games; initial availability is not final clearance or a starting assignment.',owner_approval='PENDING')
    with (folder/'manifest.json').open('x',encoding='utf-8',newline='\n') as stream:stream.write(json.dumps(payload,indent=2,sort_keys=True)+'\n')
    return verify(folder)

def verify(folder):
    m=json.loads((folder/'manifest.json').read_bytes())
    if {p.name for p in folder.iterdir()}!={'manifest.json',*[r['path'] for r in m['records']]}:raise ValueError('exact report coverage')
    if len(m['records'])!=3 or {r['conference'] for r in m['records']}!=set(OFFICIAL):raise ValueError('conference coverage')
    for r in m['records']:
        path=folder/r['path']
        if sha(path)!=r['stored_sha256'] or hashlib.sha256(gzip.decompress(path.read_bytes())).hexdigest()!=r['raw_sha256']:raise ValueError('report bytes changed')
        if r['endpoint']!=ENDPOINT or r['parameters']!={'sport':'Football','organization':r['conference'],'conference':r['conference']}:raise ValueError('request identity')
    if m['owner_approval']!='PENDING':raise ValueError('approval contradiction')
    return {'status':'RAW_REPORTS_VERIFIED_NOT_FINAL_CLEARANCE','reports':3}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--verify',action='store_true');a=p.parse_args()
    print(json.dumps(verify(a.output) if a.verify else capture(a.output)))
