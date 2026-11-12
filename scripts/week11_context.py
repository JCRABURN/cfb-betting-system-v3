"""Append-only official context for future Week 11 research candidates."""
from __future__ import annotations
import argparse
import gzip
import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from scripts.capture_week9_context import Page, official_article_links
from scripts.seal_week11_board import ROOT, OUT as BOARD, csv_rows, instant, read, sha

SITES = dict(zip(
    ['Boston College','Notre Dame','Michigan','Oregon','Duke','Miami','Northwestern','Ohio State','Georgia State','Georgia Southern','Colorado','Houston','Colorado State','Washington State','Vanderbilt','Alabama','Sam Houston','Kennesaw State','Texas Tech','Oklahoma State','Florida Atlantic','Tulsa','North Texas','UTSA','Kansas','West Virginia','Wyoming','UTEP','Oregon State','Boise State','Fresno State','Texas State','Southern Miss','Louisiana Tech','North Dakota State',"Hawai'i"],
    ['bceagles.com','fightingirish.com','mgoblue.com','goducks.com','goduke.com','miamihurricanes.com','nusports.com','ohiostatebuckeyes.com','georgiastatesports.com','gseagles.com','cubuffs.com','uhcougars.com','csurams.com','wsucougars.com','vucommodores.com','rolltide.com','gobearkats.com','ksuowls.com','texastech.com','okstate.com','fausports.com','tulsahurricane.com','meangreensports.com','goutsa.com','kuathletics.com','wvusports.com','gowyo.com','utepminers.com','osubeavers.com','broncosports.com','gobulldogs.com','txst.com','southernmiss.com','latechsports.com','gobison.com','hawaiiathletics.com']))
EXTRA = [
 'https://okstate.com/news/2026/11/10/cowboy-football-oklahoma-state-hosts-no-10-texas-tech-in-blackout-game-at-boone-pickens-stadium',
 'https://fausports.com/news/2026/11/10/football-game-notes-10',
 'https://meangreensports.com/news/2026/11/10/football-mean-green-ready-for-pivotal-road-game-at-utsa',
 'https://goducks.com/news/2026/11/10/football-surging-ducks-welcome-michigan-to-autzen-stadium',
 'https://fausports.com/documents/download/2026/11/11/2026_Game_Notes__10_remediated.pdf',
 'https://mgoblue.com/documents/download/2026/11/9/20261109-fbl-notes-oregon.pdf',
]

def now(): return datetime.now(timezone.utc).isoformat()
def digest(data): return hashlib.sha256(data).hexdigest()

def candidates(as_of):
    schedule = {g['game_id']:g for g in read(ROOT/'outputs/2026-week11-readiness/prepared-v1/schedule.json')}
    ids = {r['game_id'] for name in ('ats','totals') for r in csv_rows(f'week11_{name}_research_top10.csv')}
    return [dict(schedule[gid], context_status='FUTURE_REVIEW' if instant(schedule[gid]['kickoff_utc'])>as_of else 'FROZEN_STARTED_NO_NEW_CONTEXT') for gid in sorted(ids)]

def capture(output):
    output = output.resolve()
    if not output.is_relative_to(ROOT/'outputs/2026-week11-context') or output.exists():
        raise ValueError('new append-only context directory required')
    board_seal = BOARD/'week11_initial_seal_manifest.json'
    initial = sha(board_seal)
    start = now(); games = candidates(instant(start)); output.mkdir(parents=True)
    def get(name,url,headers=None):
        entry=dict(name=name,url=url,requested_at_utc=now(),status='UNAVAILABLE')
        try:
            r=requests.get(url,headers=headers or {'User-Agent':'CFB-Research-Audit/1.0'},timeout=25)
            raw=r.content; path=name+'.gz'; stored=gzip.compress(raw,mtime=0)
            with (output/path).open('xb') as stream: stream.write(stored)
            entry.update(received_at_utc=now(),http_status=r.status_code,resolved_url=r.url,path=path,raw_sha256=digest(raw),stored_sha256=digest(stored),status='CAPTURED' if r.ok else 'HTTP_ERROR')
            if r.ok and 'html' in r.headers.get('Content-Type',''):
                page=Page();page.feed(r.text)
                with (output/(name+'.txt')).open('x',encoding='utf-8',newline='\n') as stream: stream.write('\n'.join(page.words)+'\n')
            return entry,raw if r.ok else None
        except requests.RequestException as exc:
            entry.update(received_at_utc=now(),error_type=type(exc).__name__)
            return entry,None
    future=[g for g in games if g['context_status']=='FUTURE_REVIEW']
    teams={g[s] for g in future for s in ('home','away')}
    def site(team):
        host=SITES.get(team)
        if not host:return [dict(team=team,status='OFFICIAL_HOST_UNRESOLVED')]
        slug=re.sub('[^a-z0-9]+','-',team.lower()); url=f'https://{host}/sports/football'
        entry,raw=get('official-'+slug,url);entry['team']=team; result=[entry]
        if raw:
            page=Page();page.feed(raw.decode('utf-8',errors='replace'))
            links=official_article_links(url,page.links,instant(start))
            for i,link in enumerate(links):
                if '/football' not in link and '/cowboy-football' not in link:continue
                item,_=get(f'article-{slug}-{i}',link);item['team']=team;result.append(item)
        return result
    records=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for batch in pool.map(site,sorted(teams)):records.extend(batch)
    for i,url in enumerate(EXTRA):
        item,_=get(f'primary-supplement-{i}',url); records.append(item)
    def weather(game):
        row=dict(game_id=game['game_id'],kickoff_utc=game['kickoff_utc'],venue=game['venue'],status='UNAVAILABLE',requests=[])
        if instant(now())>=instant(game['kickoff_utc']):return dict(row,status='SKIPPED_KICKOFF_PASSED')
        if game['venue']=='Alamodome':return dict(row,status='INDOOR_NO_OUTDOOR_WIND_ADJUSTMENT')
        entry,raw=get('weather-point-'+game['game_id'],f"https://api.weather.gov/points/{game['latitude']:.4f},{game['longitude']:.4f}"); row['requests'].append(entry)
        if raw:
            url=json.loads(raw).get('properties',{}).get('forecastHourly')
            if url:
                entry,raw=get('weather-hourly-'+game['game_id'],url);row['requests'].append(entry)
                if raw:
                    props=json.loads(raw)['properties']; kickoff=instant(game['kickoff_utc'])
                    row['game_hours']=[h for h in props['periods'] if instant(h['startTime'])<kickoff+timedelta(hours=3) and instant(h['endTime'])>kickoff]
                    row.update(status='CAPTURED' if row['game_hours'] else 'NO_KICKOFF_COVERAGE',generated_at=props.get('generatedAt'),gusts='NOT_IN_HOURLY_PRODUCT')
        return row
    with ThreadPoolExecutor(max_workers=6) as pool: weather_rows=list(pool.map(weather,future))
    from scripts.capture_week6_core import _key
    item,_=get('separate-current-market','https://api.collegefootballdata.com/lines?year=2026&week=11&seasonType=regular',{'Authorization':'Bearer '+_key()});records.append(item)
    if sha(board_seal)!=initial:raise ValueError('board changed during context capture')
    payload=dict(started_at_utc=start,completed_at_utc=now(),board_seal_sha256=initial,candidates=games,records=records,weather=weather_rows,owner_approval='PENDING',numeric_adjustments=[],market_usage='Separate retrieval-time observation only; never locked line replacement or qualified historical close; elapsed-game entries prohibited as prospective context.',clearance='Capture is not medical clearance; evidence must be reviewed independently.')
    payload['files_sha256']={p.name:sha(p) for p in sorted(output.iterdir()) if p.is_file()}
    with (output/'manifest.json').open('x',encoding='utf-8',newline='\n') as stream: stream.write(json.dumps(payload,indent=2,sort_keys=True)+'\n')
    return dict(records=len(records),future_games=len(future),started_games=len(games)-len(future),weather_available=sum(r['status']=='CAPTURED' for r in weather_rows))

def verify(output):
    m=read(output/'manifest.json')
    actual={p.name:sha(p) for p in output.iterdir() if p.is_file() and p.name!='manifest.json'}
    if actual!=m['files_sha256']:raise ValueError('exact context checksum coverage')
    if sha(BOARD/'week11_initial_seal_manifest.json')!=m['board_seal_sha256']:raise ValueError('board seal changed')
    if m['numeric_adjustments'] or m['owner_approval']!='PENDING':raise ValueError('unauthorized adjustment or approval')
    if candidates(instant(m['started_at_utc']))!=m['candidates']:raise ValueError('candidate timing contradiction')
    for r in m['records']+[r for w in m['weather'] for r in w['requests']]:
        if 'path' in r:
            raw=(output/r['path']).read_bytes()
            if digest(raw)!=r['stored_sha256'] or digest(gzip.decompress(raw))!=r['raw_sha256']:raise ValueError('raw context checksum')
    return {'status':'CONTEXT_BYTES_VERIFIED_NOT_PERSONNEL_CLEARANCE','files':len(actual)}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--verify',action='store_true');args=parser.parse_args()
    print(json.dumps(verify(args.output) if args.verify else capture(args.output),indent=2))
