"""Offline Week 11 schedule/custody reconciliation. No contest source, no card."""
from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import math
import sqlite3
import subprocess
from datetime import datetime
from pathlib import Path

from ingestion import CanonicalTeamResolver
from ingestion.custody import DEFAULT_TEAM_ALIASES
from scripts.capture_week11_readiness import ROOT, PARENT, SPECS, digest
from scripts.build_week10_formal_audit import custody as historical_custody

BASE='95a21305c6676383bcfbd0405954975fbfe38ddf'
PR49='a2a98cf460be6564d7df3dafe81ba7f467b807c9'
PR51='24c3eb44b6f0951bb32203dcb16c561e6568a9e6'
CAPTURE=PARENT/'20261110T193209Z'
SUPPLEMENT=PARENT/'20261110T193425Z-schedule-v2'
OUT=PARENT/'prepared-v1'


def timestamp(value):
    result=datetime.fromisoformat(value.replace('Z','+00:00'))
    if result.tzinfo is None:raise ValueError('timezone required')
    return result


def unique(rows,field):
    result={str(r[field]):r for r in rows}
    if len(result)!=len(rows):raise ValueError('duplicate identity: '+field)
    return result


def read_payload(folder,record):
    p=(folder/record['path']).resolve()
    if not p.is_relative_to(folder.resolve()):raise ValueError('capture path escape')
    stored=p.read_bytes();raw=gzip.decompress(stored)
    if digest(stored)!=record['stored_sha256'] or digest(raw)!=record['raw_sha256']:raise ValueError('capture checksum')
    if record['http_status']!=200 or record.get('status','CAPTURED')!='CAPTURED':raise ValueError('unsuccessful required source')
    if timestamp(record['requested_at_utc'])>timestamp(record['received_at_utc']):raise ValueError('capture time contradiction')
    return json.loads(raw)


def load():
    manifest=json.loads((CAPTURE/'capture-manifest.json').read_bytes())
    records=unique(manifest['records'],'name')
    expected={name:(url,params) for name,url,params in SPECS}
    if set(records)!=set(expected):raise ValueError('exact request coverage required')
    if manifest['feature_cutoff']!={'season':2026,'end_week':10}:raise ValueError('point-in-time cutoff')
    if (manifest['status']!='CAPTURED_REQUIRES_RECONCILIATION' or manifest['season']!=2026 or manifest['week']!=11
        or any(manifest[k] is not False for k in ('owner_screenshots_received','contest_lines_locked','predictions_generated','policy_changed','market_prices_are_contest_lines'))):
        raise ValueError('readiness status contradiction')
    if digest((ROOT/'scripts/capture_week11_readiness.py').read_bytes().replace(b'\r\n',b'\n'))!=manifest['capture_code_sha256_lf']:raise ValueError('capture code changed')
    if {p.name for p in CAPTURE.iterdir()}!={'capture-manifest.json'}|{r['path'] for r in records.values()}:raise ValueError('capture file coverage')
    for name,(url,params) in expected.items():
        if records[name]['endpoint']!=url or records[name]['parameters']!=params:raise ValueError('request specification changed')
    data={name:read_payload(CAPTURE,r) for name,r in records.items()}
    extra=json.loads((SUPPLEMENT/'capture-manifest.json').read_bytes())
    if extra['parameters']!={'year':2026,'week':11,'seasontype':2,'groups':80,'limit':300}:raise ValueError('supplement identity')
    if digest((ROOT/'scripts/capture_week11_schedule_v2.py').read_bytes().replace(b'\r\n',b'\n'))!=extra['code_sha256_lf']:raise ValueError('supplement code changed')
    data['espn-complete']=read_payload(SUPPLEMENT,extra)
    return manifest,records,data,extra


def reconcile(data,as_of):
    games=unique(data['cfbd-games-all'],'id');fbs=unique(data['cfbd-fbs-teams'],'id')
    teams=unique(data['cfbd-all-teams'],'id');venues=unique(data['cfbd-venues'],'id')
    aliases={provider:dict(values) for provider,values in DEFAULT_TEAM_ALIASES.items()}
    aliases['SplashSports']['Miami OH']='Miami (OH)'
    resolver=CanonicalTeamResolver(sorted({t['school'] for t in teams.values()}),aliases)
    schedule={gid:g for gid,g in games.items() if g['season']==2026 and g['week']==11 and
              (str(g['homeId']) in fbs or str(g['awayId']) in fbs or g['homeClassification']=='fbs' or g['awayClassification']=='fbs')}
    if not schedule:raise ValueError('empty FBS schedule')
    espn=data['espn-complete']
    if espn['season']!={'type':2,'year':2026} or espn['week']['number']!=11:raise ValueError('ESPN season/week mismatch')
    events=unique(espn['events'],'id')
    if set(events)!=set(schedule):raise ValueError('unreconciled ESPN/CFBD schedule coverage')
    features=unique(data['cfbd-prior-season-advanced'],'team')
    for f in features.values():
        if f['season']!=2026:raise ValueError('feature season')
        for side in ('offense','defense'):
            if not isinstance(f[side]['ppa'],(float,int)) or not math.isfinite(f[side]['ppa']):raise ValueError('invalid EPA feature')
    for week in (8,9,10):
        for r in data[f'cfbd-prior-week{week}-advanced']:
            g=games[str(r['gameId'])]
            if r['week']!=week or r['season']!=2026 or g['week']!=week or not g['completed'] or timestamp(g['startDate'])>=as_of:
                raise ValueError('prior game feature lookahead')
        for r in data[f'cfbd-prior-week{week}-drives']:
            g=games[str(r['gameId'])]
            if g['week']!=week or g['season']!=2026 or not g['completed'] or timestamp(g['startDate'])>=as_of:
                raise ValueError('prior drive lookahead')
    market=unique(data['cfbd-market-observations'],'id');rows=[];prices=[]
    if not set(market).issubset(schedule):raise ValueError('market outside schedule')
    for gid,m in market.items():
        g=schedule[gid]
        if m['season']!=2026 or m['week']!=11 or any(m[side+'TeamId']!=g[side+'Id'] for side in ('home','away')):
            raise ValueError('market orientation/season mismatch')
    for gid,g in sorted(schedule.items(),key=lambda p:(p[1]['startDate'],p[0])):
        event=events[gid]
        if len(event['competitions'])!=1:raise ValueError('ambiguous competition')
        competition=event['competitions'][0];sides=unique(competition['competitors'],'homeAway')
        if set(sides)!={'home','away'} or timestamp(competition['date'])!=timestamp(g['startDate']):raise ValueError('kickoff/orientation conflict')
        for side in ('home','away'):
            tid=str(g[side+'Id']);name=g[side+'Team'];resolved=resolver.resolve('collegefootballdata',name)
            if tid!=str(sides[side]['team']['id']) or teams[tid]['school']!=name or resolved.status!='resolved' or resolved.canonical_name!=name:
                raise ValueError('provider team identity conflict')
            if (tid in fbs)!=(g[side+'Classification']=='fbs'):raise ValueError('FBS registry classification conflict')
        elapsed=timestamp(g['startDate'])<=as_of or g['completed'] or competition['status']['type']['state']!='pre'
        if not elapsed and (g['homePoints'] is not None or g['awayPoints'] is not None):raise ValueError('pregame score contamination')
        missing=[g[s+'Team'] for s in ('home','away') if g[s+'Team'] not in features]
        observed=market.get(gid,{}).get('lines',[])
        for price in observed:
            prices.append(dict(game_id=gid,away=g['awayTeam'],home=g['homeTeam'],**price,
                               contest_line=False,qualified_close=False,provider_quote_timestamp=price.get('lastUpdated')))
        venue=venues.get(str(g['venueId']),{})
        row=dict(game_id=gid,away=g['awayTeam'],home=g['homeTeam'],away_id=g['awayId'],home_id=g['homeId'],
                 away_classification=g['awayClassification'],home_classification=g['homeClassification'],
                 matchup_class='FBS_VS_FBS' if str(g['homeId']) in fbs and str(g['awayId']) in fbs else 'FBS_VS_FCS_OR_OTHER',
                 kickoff_utc=g['startDate'],kickoff_tbd=g['startTimeTBD'],neutral_site=g['neutralSite'],venue_id=g['venueId'],
                 venue=g['venue'],latitude=venue.get('latitude'),longitude=venue.get('longitude'),
                 status_at_capture='ELAPSED_NO_PROSPECTIVE_PICK' if elapsed else 'UPCOMING_AT_CAPTURE',
                 contest_coverage='UNKNOWN_OWNER_SCREENSHOTS_NOT_RECEIVED',locked_spread=None,locked_total=None,
                 model_feature_status='PRIOR_WEEK_EPA_AVAILABLE' if not missing else 'UNSUPPORTED_MISSING_EPA_NO_APPROVED_FALLBACK',
                 missing_feature_teams=missing,market_providers=[p['provider'] for p in observed],
                 market_status='OBSERVED_SEPARATELY_NOT_CONTEST_LINES' if observed else 'NO_CAPTURED_MARKET_LINES_NOT_PROOF_CONTEST_UNLINED')
        for side in ('home','away'):
            prior=[old for old in games.values() if old['completed'] and old['week']<=10 and
                   g[side+'Id'] in (old['homeId'],old['awayId']) and timestamp(old['startDate'])<as_of]
            last=max(prior,key=lambda x:x['startDate']) if prior else None
            row[side+'_previous_game_id']=last['id'] if last else None
            row[side+'_kickoff_to_kickoff_rest_days']=round((timestamp(g['startDate'])-timestamp(last['startDate'])).total_seconds()/86400,6) if last else None
        rows.append(row)
    mappings=[dict(provider_id=tid,canonical_school=t['school'],classification=t['classification'],abbreviation=t['abbreviation'],provider_alternate_names=t['alternateNames']) for tid,t in sorted(teams.items()) if tid in {str(r[s+'_id']) for r in rows for s in ('home','away')}]
    return rows,prices,mappings,aliases


def require_contest_source(source):
    if not source or not source.get('original_screenshots') or source.get('source')!='SplashSports' or not source.get('independent_transcription_reconciled'):
        raise ValueError('OWNER_SCREENSHOTS_AND_INDEPENDENT_RECONCILIATION_REQUIRED')
    raise ValueError('READINESS_ONLY_USE_SEPARATE_VERIFIED_WEEK11_LOCK_EXECUTOR')


def serialized(value):return (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()


def build():
    manifest,records,data,extra=load();as_of=max(timestamp(r['received_at_utc']) for r in list(records.values())+[extra])
    rows,prices,mappings,aliases=reconcile(data,as_of)
    historical=historical_custody()
    baseline=json.loads((PARENT/'repository-baseline.json').read_bytes())
    if baseline['base_main_commit']!=BASE or baseline['pr49_ancestor'] is not True or baseline['pr51_ancestor'] is not True or baseline['tree_equals_pr51'] is not True:
        raise ValueError('repository baseline contradiction')
    with sqlite3.connect(f'file:{(ROOT/"data/cfb.db").as_posix()}?mode=ro&immutable=1',uri=True) as conn:
        integrity=conn.execute('pragma integrity_check').fetchall();foreign=conn.execute('pragma foreign_key_check').fetchall()
    if integrity!=[('ok',)] or foreign:raise ValueError('source database integrity')
    policy_paths=['config/production_policies.example.json','config/epa-only-oos-uncertainty-v1.json','business_entities/weekly_controller.py','business_entities/totals_weekly_model.py','scripts/finalize_week10_card.py']
    policy={p:digest((ROOT/p).read_bytes().replace(b'\r\n',b'\n')) for p in policy_paths}
    summary=dict(version='week11-readiness-v1',status='READINESS_PREPARED_CONTEST_SOURCE_PENDING',as_of_utc=as_of.isoformat(),
                 base_main_commit=BASE,week10_delivery_commit=PR49,week10_audit_commit=PR51,
                 governing_policy='Master Prompt v2.8 per owner instruction and preserved Week10 governance; no v2.9 authorization',
                 policy_artifact_limit='No standalone Master Prompt text is tracked. Existing production_policies.example.json contains implementation versions and proposed-registration provenance; it does not independently authorize a policy promotion.',
                 policy_and_model_sha256_lf=policy,policy_changed=False,source_database_sha256=digest((ROOT/'data/cfb.db').read_bytes()),
                 database_integrity='ok',foreign_key_violations=0,historical_custody=historical,
                 scheduled_fbs_games=len(rows),fbs_vs_fbs=sum(r['matchup_class']=='FBS_VS_FBS' for r in rows),
                 fbs_vs_fcs_or_other=sum(r['matchup_class']!='FBS_VS_FBS' for r in rows),
                 upcoming_at_capture=sum(r['status_at_capture']=='UPCOMING_AT_CAPTURE' for r in rows),
                 elapsed_at_capture=[r['game_id'] for r in rows if r['status_at_capture']!='UPCOMING_AT_CAPTURE'],
                 missing_model_features=[r['game_id'] for r in rows if r['missing_feature_teams']],
                 unresolved_provider_mappings=[],market_observations=len(prices),
                 games_without_market_observations=[r['game_id'] for r in rows if not r['market_providers']],
                 owner_screenshots_received=False,locked_games=0,ats_picks=0,totals_picks=0,top5_generated=False,owner_approval='PENDING',
                 blockers=['Original Week11 SplashSports screenshots and actual receipt timestamp are missing',
                           'Contest inclusion, original locked spreads/totals and source hashes cannot yet be established',
                           'No official forecasts, Top10s, combined five, candidate-specific context review or forward research shadow has been generated',
                           'Execution must refresh schedule eligibility and exclude every game elapsed at actual generation; readiness is a timestamped snapshot'],
                 known_provider_issue='Original ESPN limit=1000 query returned 25 events; date-range query returned HTTP400. Preserved separately. Limit=300 week query reconciles complete CFBD schedule.',
                 calibration_warnings=['Governed ATS confidence was uniformly1 with no calibrated discrimination','Week10 ATS/totals both26-31; model MAE worse than locked-line baseline','Week10 human five0-5 and controlled combined1-4; no demonstrated strongest-five improvement','Uncalibrated ATS and totals scores are not equivalent probabilities; no cross-market probability ranking or new policy'],
                 clv='INCOMPLETE_NO_QUALIFIED_CLOSES',feature_cutoff=dict(season=2026,end_week=10))
    table=io.StringIO(newline='');writer=csv.DictWriter(table,fieldnames=list(rows[0]),lineterminator='\n');writer.writeheader();writer.writerows(rows)
    files={'readiness.json':serialized(summary),'coverage.csv':table.getvalue().encode(),'schedule.json':serialized(rows),
           'market-observations-NOT-CONTEST-LINES.json':serialized(dict(received_at_utc=records['cfbd-market-observations']['received_at_utc'],raw_sha256=records['cfbd-market-observations']['raw_sha256'],observations=prices)),
           'provider-mappings.json':serialized(mappings),'resolver-aliases.json':serialized(aliases)}
    files['manifest.json']=serialized(dict(version='week11-readiness-output-v1',output_sha256={k:digest(v) for k,v in files.items()},
         capture_manifest_sha256=digest((CAPTURE/'capture-manifest.json').read_bytes()),supplement_manifest_sha256=digest((SUPPLEMENT/'capture-manifest.json').read_bytes()),
         code_sha256_lf=digest(Path(__file__).read_bytes().replace(b'\r\n',b'\n')),contest_lines_locked=False,predictions_generated=False))
    return files


def main(verify=False):
    if not verify and OUT.exists():raise ValueError('readiness version exists; overwrite forbidden')
    files=build()
    if verify:
        if {p.name for p in OUT.iterdir()}!=set(files) or any((OUT/name).read_bytes()!=raw for name,raw in files.items()):raise ValueError('readiness exact replay mismatch')
    else:
        OUT.mkdir(parents=True,exist_ok=False)
        for name,raw in files.items():
            with (OUT/name).open('xb') as stream:stream.write(raw)
    return {'status':'VERIFIED_READ_ONLY' if verify else 'READINESS_WRITTEN','files':len(files),'locked_games':0,'predictions':0}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');a=p.parse_args();print(json.dumps(main(a.verify)))
