"""Append explicit official sources missed by automated football-page discovery."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import json
import requests
from scripts.capture_week9_context import Page
from scripts.prepare_week12_source import ROOT, digest, serialized

URLS = {
    'massachusetts-preview': 'https://umassathletics.com/news/2026/11/15/massachusetts-football-hosts-akron-on-wednesday-for-senior-night',
    'arizona-state-preview': 'https://thesundevils.com/news/2026/11/17/football-ready-for-final-home-game-against-oklahoma-state',
    'memphis-navy-preview': 'https://gotigersgo.com/news/2026/11/15/football-memphis-navy-to-air-on-espn2',
    'south-alabama-schedule': 'https://usajaguars.com/news/2026/11/9/football-final-road-trip-slated-for-3-pm-kick-at-southern-miss.aspx',
    'san-jose-state-official': 'https://sjsuspartans.com/sports/football',
    'arkansas-official-retry': 'https://arkansasrazorbacks.com/sport/m-footbl/',
    'georgia-tech-official-retry': 'https://ramblinwreck.com/sports/m-footbl/',
}

def capture():
    folder=ROOT/'outputs/2026-week12-context/20261118-supplement'
    folder.mkdir(exist_ok=False)
    def one(item):
        name,url=item
        row=dict(name=name,url=url,requested_at_utc=datetime.now(timezone.utc).isoformat())
        try:
            response=requests.get(url,timeout=25,headers={'User-Agent':'CFB-Week12-Research/1.0'})
            raw=response.content; stored=gzip.compress(raw,mtime=0)
            (folder/(name+'.gz')).write_bytes(stored)
            row.update(received_at_utc=datetime.now(timezone.utc).isoformat(),http_status=response.status_code,
                       status='CAPTURED' if response.ok else 'HTTP_ERROR',path=name+'.gz',
                       raw_sha256=digest(raw),stored_sha256=digest(stored))
            if response.ok:
                page=Page(); page.feed(response.text)
                (folder/(name+'.txt')).write_text('\n'.join(page.words)+'\n',encoding='utf-8',newline='\n')
        except requests.RequestException as error:
            row.update(status='UNAVAILABLE',error_type=type(error).__name__)
        return row
    with ThreadPoolExecutor(max_workers=7) as pool: rows=list(pool.map(one,URLS.items()))
    payload=dict(records=rows,files_sha256={p.name:digest(p.read_bytes()) for p in folder.iterdir()},
                 purpose='Separate supplemental research; no historical forecast or initial capture rewritten.')
    (folder/'manifest.json').write_bytes(serialized(payload))
    print(json.dumps([{'name':r['name'],'status':r['status']} for r in rows]))

if __name__=='__main__':capture()
