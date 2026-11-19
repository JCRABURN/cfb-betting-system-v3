"""Append-only pregame research capture; no forecasts, lines or DB mutations."""
from __future__ import annotations
import argparse
import gzip
import json
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests
from scripts.capture_week6_core import _key
from scripts.capture_week9_context import Page, official_article_links, SITES as OLD_SITES
from scripts.week11_context import SITES as RECENT_SITES
from scripts.prepare_week12_source import ROOT, load_capture, digest, timestamp, serialized, unique

SITES = {**OLD_SITES, **RECENT_SITES, 'San José State':'sjsuspartans.com',
    'Akron':'gozips.com','Massachusetts':'umassathletics.com','Central Michigan':'cmuchippewas.com',
    'Buffalo':'ubbulls.com','Rice':'riceowls.com','Temple':'owlsports.com','Iowa State':'cyclones.com',
    'UCF':'ucfknights.com','Bowling Green':'bgsufalcons.com','Toledo':'utrockets.com','Clemson':'clemsontigers.com',
    'Air Force':'goairforcefalcons.com','Michigan State':'msuspartans.com','BYU':'byucougars.com',
    'Memphis':'gotigersgo.com','Florida':'floridagators.com','Cincinnati':'gobearcats.com',
    'Purdue':'purduesports.com','Tulane':'tulanegreenwave.com','Nebraska':'huskers.com','Minnesota':'gophersports.com',
    'Wake Forest':'godeacs.com','Georgia Tech':'ramblinwreck.com','East Carolina':'ecupirates.com','Army':'goarmywestpoint.com',
    'North Carolina':'goheels.com','Virginia':'virginiasports.com','Western Kentucky':'wkusports.com',
    'Liberty':'libertyflames.com','Missouri State':'missouristatebears.com','Jacksonville State':'jaxstatesports.com',
    'Charlotte':'charlotte49ers.com','Middle Tennessee':'goblueraiders.com','Illinois':'fightingillini.com',
    'App State':'appstatesports.com','South Florida':'gousfbulls.com','Delaware':'bluehens.com',
    'New Mexico State':'nmstatesports.com','Coastal Carolina':'goccusports.com','Louisiana':'ragincajuns.com',
    'Florida International':'fiusports.com','UCLA':'uclabruins.com','NC State':'gopack.com',
    'Florida State':'seminoles.com','Old Dominion':'odusports.com','UConn':'uconnhuskies.com',
    'Indiana':'iuhoosiers.com','Washington':'gohuskies.com','LSU':'lsusports.net','Tennessee':'utsports.com',
    'Baylor':'baylorbears.com','Arkansas':'arkansasrazorbacks.com','Rutgers':'scarletknights.com',
    'Penn State':'gopsusports.com','Texas A&M':'12thman.com','Oklahoma':'soonersports.com',
    'Marshall':'herdzone.com','South Alabama':'usajaguars.com','Northern Illinois':'niuhuskies.com',
    'Maryland':'umterps.com','USC':'usctrojans.com','Virginia Tech':'hokiesports.com','UNLV':'unlvrebels.com',
    'Arizona':'arizonawildcats.com','Kansas State':'kstatesports.com','Arkansas State':'astateredwolves.com',
    'Pittsburgh':'pittsburghpanthers.com','Louisville':'gocards.com','Georgia':'georgiadogs.com',
    'South Carolina':'gamecocksonline.com','Kentucky':'ukathletics.com','Missouri':'mutigers.com',
    'Stanford':'gostanford.com','California':'calbears.com','UAB':'uabsports.com','Utah':'utahutes.com',
    'TCU':'gofrogs.com','San Diego State':'goaztecs.com','Arizona State':'thesundevils.com','Nevada':'nevadawolfpack.com'}


def now(): return datetime.now(timezone.utc)


def capture(output: Path) -> dict:
    output=output.resolve()
    if not output.is_relative_to(ROOT/'outputs/2026-week12-context') or output.exists():
        raise ValueError('new append-only Week12 context directory required')
    _,_,data=load_capture()
    frozen=json.loads((ROOT/'outputs/2026-week12-prospective/week12_locked_line_snapshot.json').read_bytes())
    source_hash=digest((ROOT/'data/ingest/2026-week12-splashsports/original.pdf').read_bytes())
    all_games=unique(data['cfbd-games-all'],'id'); venues=unique(data['cfbd-venues'],'id')
    games=[all_games[str(r['game_id'])] for r in frozen['lines'] if timestamp(r['source_kickoff_utc'])>now()]
    output.mkdir(parents=True); start=now()
    def get(name,url,headers=None):
        record=dict(name=name,url=url,requested_at_utc=now().isoformat(),status='UNAVAILABLE')
        try:
            r=requests.get(url,headers=headers or {'User-Agent':'CFB-Week12-Research/1.0'},timeout=25)
            raw=r.content; stored=gzip.compress(raw,mtime=0); filename=name+'.gz'
            with (output/filename).open('xb') as stream:stream.write(stored)
            record.update(received_at_utc=now().isoformat(),http_status=r.status_code,resolved_url=r.url,path=filename,
                          raw_sha256=digest(raw),stored_sha256=digest(stored),status='CAPTURED' if r.ok else 'HTTP_ERROR')
            if r.ok and 'html' in r.headers.get('Content-Type',''):
                page=Page();page.feed(r.text)
                (output/(name+'.txt')).write_text('\n'.join(page.words)+'\n',encoding='utf-8',newline='\n')
            return record,raw if r.ok else None
        except requests.RequestException as error:
            record.update(received_at_utc=now().isoformat(),error_type=type(error).__name__)
            return record,None
    def espn(g):
        if timestamp(g['startDate'])<=now():return dict(name=f"espn-{g['id']}",status='SKIPPED_STARTED')
        return get(f"espn-{g['id']}",f"https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event={g['id']}")[0]
    with ThreadPoolExecutor(max_workers=6) as pool: records=list(pool.map(espn,games))
    def weather(g):
        v=venues.get(str(g['venueId'])); gid=g['id']
        row=dict(game_id=gid,status='UNAVAILABLE',requests=[],kickoff_utc=g['startDate'])
        if timestamp(g['startDate'])<=now():return dict(row,status='SKIPPED_STARTED')
        if not v:return row
        row['venue']=v
        if v.get('dome'):return dict(row,status='INDOOR_NO_OUTDOOR_WIND_ADJUSTMENT')
        entry,raw=get(f'weather-point-{gid}',f"https://api.weather.gov/points/{v['latitude']:.4f},{v['longitude']:.4f}")
        row['requests'].append(entry)
        if raw:
            url=json.loads(raw).get('properties',{}).get('forecastHourly')
            if url:
                entry,raw=get(f'weather-hourly-{gid}',url);row['requests'].append(entry)
                if raw:
                    props=json.loads(raw)['properties']; kickoff=timestamp(g['startDate'])
                    row['game_hours']=[h for h in props['periods'] if timestamp(h['startTime'])<kickoff+timedelta(hours=3) and timestamp(h['endTime'])>kickoff]
                    row.update(status='CAPTURED' if row['game_hours'] else 'NO_KICKOFF_COVERAGE',generated_at=props.get('generatedAt'),gusts='NOT_IN_HOURLY_PRODUCT',field_condition='UNCONFIRMED')
        return row
    with ThreadPoolExecutor(max_workers=6) as pool: weather_rows=list(pool.map(weather,games))
    def site(team):
        host=SITES.get(team)
        if not host:return [dict(team=team,status='OFFICIAL_HOST_UNRESOLVED')]
        name=re.sub('[^a-z0-9]+','-',team.lower()); url=f'https://{host}/sports/football'
        entry,raw=get('official-'+name,url);entry['team']=team; result=[entry]
        if raw:
            page=Page();page.feed(raw.decode('utf-8',errors='replace'))
            for i,link in enumerate(official_article_links(url,page.links,start)):
                if '/football' not in link and '/cowboy-football' not in link:continue
                item,_=get(f'article-{name}-{i}',link); item['team']=team;result.append(item)
        return result
    teams=sorted({g[s+'Team'] for g in games for s in ('home','away')})
    with ThreadPoolExecutor(max_workers=8) as pool:
        for result in pool.map(site,teams):records.extend(result)
    for name,url in [('cfbd-coaches','https://api.collegefootballdata.com/coaches?year=2026'),
                     ('market-separate','https://api.collegefootballdata.com/lines?year=2026&week=12&seasonType=regular')]:
        item,_=get(name,url,{'Authorization':'Bearer '+_key()});records.append(item)
    if digest((ROOT/'data/ingest/2026-week12-splashsports/original.pdf').read_bytes())!=source_hash:
        raise ValueError('source changed')
    manifest=dict(started_at_utc=start.isoformat(),completed_at_utc=now().isoformat(),pdf_sha256=source_hash,
                  game_ids=[g['id'] for g in games],teams=teams,records=records,weather=weather_rows,numeric_adjustments=[],
                  policy_changes=[],clearance='Capture is not confirmed availability or a starting assignment; explicit review and missing-data labels required.',
                  external_week11_submissions_used=False,market_usage='Separate current observation; never replaces original contest lines.',
                  files_sha256={p.name:digest(p.read_bytes()) for p in output.iterdir()})
    (output/'manifest.json').write_bytes(serialized(manifest))
    return dict(games=len(games),teams=len(teams),records=len(records),weather_available=sum(w['status']=='CAPTURED' for w in weather_rows))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True)
    print(json.dumps(capture(p.parse_args().output)))
