"""Offline per-game context ledger with explicit personnel and calibration gaps."""
from __future__ import annotations
import argparse
import gzip
import json
import math
from datetime import timedelta, timezone
from pathlib import Path
from scripts.prepare_week12_source import ROOT, load_capture, digest, serialized, csv_bytes, timestamp, unique

CAP=ROOT/'outputs/2026-week12-context/20261118-initial'
CONF=ROOT/'outputs/2026-week12-context/20261118-conference'
OUT=ROOT/'outputs/2026-week12-context/review-v2'


def read_raw(folder, record):
    path=(folder/record['path']).resolve()
    if not path.is_relative_to(folder.resolve()):raise ValueError('unsafe source path')
    stored=path.read_bytes();raw=gzip.decompress(stored)
    if digest(stored)!=record['stored_sha256'] or digest(raw)!=record['raw_sha256']:raise ValueError('raw context changed')
    return json.loads(raw)


def distance(a,b):
    if not a or not b or any(x.get(k) is None for x in (a,b) for k in ('latitude','longitude')):return None
    la,lo,lb,lp=[math.radians(v) for v in (a['latitude'],a['longitude'],b['latitude'],b['longitude'])]
    return round(3958.7613*2*math.asin(min(1,math.sqrt(math.sin((lb-la)/2)**2+math.cos(la)*math.cos(lb)*math.sin((lp-lo)/2)**2))),1)


def conference_rows(manifest):
    result=[]
    for record in manifest['records']:
        data=read_raw(CONF,record)
        for provider_id,g in data.items():
            offset={'ET':-5,'CT':-6}.get(g['conferenceTimeZone'])
            if offset is None:raise ValueError('unknown conference timezone')
            published=timestamp(g['publishDate']+'T'+g['postedTime']+f'{offset:03d}:00')
            retrieved=timestamp(record['received_at_utc'])
            for team in g['games']:
                usable=g['ReportType'] not in ('Report Pending',) and published<=retrieved and bool(team['rows'])
                result.append(dict(team=team['teamDisplayName'],conference=record['conference'],provider_game_id=provider_id,
                                   report_type=g['ReportType'],publication_utc=published.isoformat(),retrieved_at_utc=retrieved.isoformat(),
                                   status='INITIAL_REPORT_NOT_FINAL_CLEARANCE' if usable else 'REPORT_PENDING_OR_NOT_TIME_QUALIFIED',
                                   rows=team['rows'] if usable else [],source_file=record['path'],source_url=record['official_wrapper']))
    return result


def build():
    m=json.loads((CAP/'manifest.json').read_bytes())
    actual={p.name:digest(p.read_bytes()) for p in CAP.iterdir() if p.is_file() and p.name!='manifest.json'}
    if actual!=m['files_sha256']:raise ValueError('context file custody')
    conf=conference_rows(json.loads((CONF/'manifest.json').read_bytes()))
    conf_by={r['team']:r for r in conf}
    _,_,data=load_capture()
    all_games=unique(data['cfbd-games-all'],'id');teams=unique(data['cfbd-fbs-teams'],'id'); venues=unique(data['cfbd-venues'],'id')
    features=unique(data['cfbd-prior-season-advanced'],'team')
    weather=unique(m['weather'],'game_id')
    records={r['name']:r for r in m['records'] if 'name' in r}
    coaches=read_raw(CAP,records['cfbd-coaches']) if records['cfbd-coaches']['status']=='CAPTURED' else []
    markets=read_raw(CAP,records['market-separate']) if records['market-separate']['status']=='CAPTURED' else []
    market_by=unique(markets,'id')
    rows=[]; people=[]
    for gid in m['game_ids']:
        g=all_games[str(gid)];kickoff=timestamp(g['startDate'])
        espn=records[f'espn-{gid}']
        if timestamp(espn['received_at_utc'])>=kickoff:raise ValueError('postkickoff ESPN context')
        summary=read_raw(CAP,espn)
        if summary['header']['competitions'][0]['status']['type']['state']!='pre':raise ValueError('nonpregame ESPN context')
        w=weather[str(gid)]
        for request in w['requests']:
            if timestamp(request['received_at_utc'])>=kickoff:raise ValueError('postkickoff weather')
        hours=w.get('game_hours',[])
        if hours and timestamp(w['generated_at'])>timestamp(m['completed_at_utc']):raise ValueError('future weather issue time')
        row=dict(game_id=gid,away=g['awayTeam'],home=g['homeTeam'],kickoff_utc=g['startDate'],
                 weather_status=w['status'],temperature_f=';'.join(str(h['temperature']) for h in hours),
                 wind=';'.join(str(h['windSpeed'])+' '+str(h['windDirection']) for h in hours),
                 precipitation_probability=';'.join(str(h['probabilityOfPrecipitation']['value']) for h in hours),
                 weather_description=';'.join(h['shortForecast'] for h in hours),
                 forecast_issued_utc=w.get('generated_at',''),weather_gust_status='UNAVAILABLE',field_condition='UNCONFIRMED',
                 espn_injuries_status='MISSING_NOT_HEALTHY' if 'injuries' not in summary else 'PRESENT_REQUIRES_REVIEW',
                 market_providers=';'.join(x['provider'] for x in market_by.get(str(gid),{}).get('lines',[])),
                 numeric_adjustment_points='',adjustment_status='NO_APPROVED_NUMERIC_CONTEXT_MODEL',
                 common_calibrated_probability='',research_status='WEAK_UNVALIDATED')
        for side in ('away','home'):
            team=g[side+'Team'];tid=g[side+'Id']
            articles=[r for r in m['records'] if r.get('team')==team and r.get('name','').startswith('article-') and r['status']=='CAPTURED']
            row[side+'_official_recent_articles']=len(articles)
            row[side+'_article_sources']=';'.join(r['url'] for r in articles)
            availability=conf_by.get(team)
            row[side+'_availability']=availability['status'] if availability else 'NO_CONFERENCE_REPORT_CAPTURED'
            row[side+'_starting_qb']='UNCONFIRMED_FROM_CAPTURED_STRUCTURED_SOURCES'
            for category,prefixes in [('qb',('QB ',)),('ol',('OL ','OT ','OG ','C ')),('defense',('DL ','DT ','DE ','LB ','ILB ','OLB ','CB ','DB ','S '))]:
                personnel=[r for r in availability['rows'] if r['name'].startswith(prefixes)] if availability else []
                row[side+'_'+category+'_report']=';'.join(r['name']+': '+r['status'] for r in personnel) if personnel else 'MISSING_NOT_ZERO_ABSENCES'
                for person in personnel:people.append(dict(game_id=gid,team=team,category=category,**person,publication_utc=availability['publication_utc'],source_url=availability['source_url'],final_clearance=False))
            leader=[l for t in summary.get('leaders',[]) if str(t['team']['id'])==str(tid) for l in t.get('leaders',[]) if l.get('name')=='passingYards']
            row[side+'_passing_leader_not_confirmed_starter']=';'.join(x.get('athlete',{}).get('displayName','') for l in leader for x in l.get('leaders',[]))
            prior=[old for old in all_games.values() if old['season']==2026 and old['week']<=11 and old['completed'] and tid in (old['homeId'],old['awayId'])]
            last=max(prior,key=lambda x:x['startDate']) if prior else None
            row[side+'_rest_days_kickoff_to_kickoff']=round((kickoff-timestamp(last['startDate'])).total_seconds()/86400,3) if last else ''
            row[side+'_previous_game_id']=last['id'] if last else ''
            row[side+'_straight_line_stadium_miles_not_itinerary']=distance(teams[str(tid)].get('location'),venues.get(str(g['venueId'])))
            named=[c['firstName']+' '+c['lastName'] for c in coaches if any(s['school']==team and s['year']==2026 for s in c.get('seasons',[]))]
            row[side+'_season_coach_record']=';'.join(named) if named else 'UNAVAILABLE'
            row[side+'_coaching_change_confirmation']='UNCONFIRMED_REQUIRES_CURRENT_NEWS_REVIEW'
            feature=features.get(team)
            row[side+'_prior_week_offense_ppa']=feature['offense']['ppa'] if feature else ''
            row[side+'_prior_week_defense_ppa']=feature['defense']['ppa'] if feature else ''
        rows.append(row)
    outputs={'all-game-context.csv':csv_bytes(rows),'conference-personnel.csv':csv_bytes(people),'conference-report-status.json':serialized(conf)}
    outputs['manifest.json']=serialized(dict(version='week12-context-review-v2',as_of_utc=m['completed_at_utc'],games=len(rows),
        weather_available=sum(r['weather_status']=='CAPTURED' for r in rows),indoor=sum(r['weather_status'].startswith('INDOOR') for r in rows),
        initial_personnel_report_teams=sum(bool(r['rows']) for r in conf),pending_report_teams=sum(not bool(r['rows']) for r in conf),
        personnel_records=len(people),numerical_adjustments=0,original_lines_changed=False,
        input_manifests={str(p.relative_to(ROOT)).replace('\\','/'):digest(p.read_bytes()) for p in [CAP/'manifest.json',CONF/'manifest.json']},
        files={name:digest(raw) for name,raw in outputs.items()}))
    return outputs


def main(verify=False):
    outputs=build()
    if verify:
        for name,raw in outputs.items():
            if (OUT/name).read_bytes()!=raw:raise ValueError('context replay mismatch: '+name)
    else:
        OUT.mkdir(exist_ok=False)
        for name,raw in outputs.items():(OUT/name).write_bytes(raw)
    print(outputs['manifest.json'].decode())


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');main(p.parse_args().verify)
