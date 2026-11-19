"""Capture missing official summaries for prior-drive adjudication, never model training."""
import gzip
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import requests
from scripts.week11_drive_adjudication import adjudicate
from scripts.week11_audit_inputs import EVIDENCE, sha


def main():
    ids=sorted({str(r['game_id']) for r in adjudicate()['rows'] if r['reason']=='Missing independently archived ESPN summary'})
    out=EVIDENCE/'drive-summaries-v1'
    if out.exists():raise FileExistsError('Never overwrite evidence')
    out.mkdir()
    def fetch(gid):
        now=lambda:datetime.now(timezone.utc).isoformat()
        requested=now();url='https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary'
        response=requests.get(url,params={'event':gid},timeout=45)
        raw=response.content;z=gzip.compress(raw,mtime=0);name='espn-'+gid+'.json.gz'
        (out/name).write_bytes(z)
        return dict(game_id=gid,path=name,requested_at_utc=requested,received_at_utc=now(),endpoint=url,parameters={'event':gid},
                    http_status=response.status_code,status='CAPTURED' if response.status_code==200 else 'HTTP_ERROR',
                    raw_sha256=sha(raw),stored_sha256=sha(z),raw_bytes=len(raw),resolved_url=response.url)
    with ThreadPoolExecutor(max_workers=6) as pool:records=list(pool.map(fetch,ids))
    (out/'capture-manifest.json').write_text(json.dumps(dict(records=records,purpose='POSTGAME_ONLY_DRIVE_QUARANTINE_ADJUDICATION'),indent=2,sort_keys=True)+'\n',encoding='utf8',newline='\n')
    print(json.dumps(dict(games=len(ids),failures=[r['game_id'] for r in records if r['status']!='CAPTURED'])))


if __name__=='__main__':main()
