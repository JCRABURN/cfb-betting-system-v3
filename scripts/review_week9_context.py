"""Read-only derivations of new context; no changes to any sealed prediction."""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from scripts.seal_week9_board import main as verify_board

ROOT=Path(__file__).resolve().parents[1]
BOARD=ROOT/'outputs/2026-week9-prospective'

def read(path):return json.loads(path.read_text(encoding='utf-8'))
def instant(value):return datetime.fromisoformat(value.replace('Z','+00:00'))
def timezone_shift(kickoff,origin,destination):
    if not origin or not destination:return None
    try:
        return (kickoff.astimezone(ZoneInfo(destination)).utcoffset()-kickoff.astimezone(ZoneInfo(origin)).utcoffset()).total_seconds()/3600
    except ZoneInfoNotFoundError:
        return None  # Preserve source zone names; never guess an offset without tzdata.
def distance(a,b):
    lat1,lat2=map(math.radians,(a['latitude'],b['latitude']))
    dl=math.radians(b['longitude']-a['longitude']);dp=lat2-lat1
    return 3958.7613*2*math.asin(min(1,math.sqrt(math.sin(dp/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dl/2)**2)))

def verify_capture(folder):
    manifest=read(folder/'capture-manifest.json')
    entries=manifest['records']+[r for w in manifest['weather'] for r in w['requests']]
    for item in entries:
        if item['status']!='CAPTURED':continue
        raw=gzip.decompress((folder/item['path']).read_bytes())
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('context payload changed')
        if instant(item['requested_at_utc'])>instant(item['received_at_utc']):raise ValueError('context timestamp ordering')
    return manifest

def build(folder):
    verify_board(verify=True);manifest=verify_capture(folder)
    games=read(BOARD/'core-initial/cfbd-2026-games.json');teams={t['id']:t for t in read(BOARD/'core-initial/cfbd-2026-fbs-teams.json')}
    locked={g['game_id']:g for g in read(BOARD/'week9_locked_line_snapshot.json')['lines']}
    components={g['game_id']:g for g in read(BOARD/'week9_raw_model_components.json')['games']}
    weather={g['game_id']:g for g in manifest['weather']}
    market={g['id']:g for g in json.loads(gzip.decompress((folder/'cfbd-current-week9-lines.gz').read_bytes()))}
    eligible_ids=set(locked);uncovered=[g['id'] for g in market.values() if g['homeClassification']=='fbs' and g['awayClassification']=='fbs' and g['id'] not in eligible_ids]
    excluded={g['game_id'] for g in read(ROOT/'production-weeks/2026-week9-splashsports-lock-metadata.json')['excluded_completed_games']}
    if set(uncovered)-excluded:raise ValueError('additional market-lined FBS games require explicit coverage resolution')
    records=[]
    for game in games:
        gid=game['id']
        if gid not in locked:continue
        w=weather[gid];venue=w.get('venue');row={'game_id':gid,'away':game['awayTeam'],'home':game['homeTeam'],'kickoff_utc':game['startDate'],
            'neutral_site':game['neutralSite'],'venue':venue,'context_received_at_utc':manifest['captured_at_utc'],
            'pregame_context':instant(manifest['captured_at_utc'])<instant(game['startDate']),
            'locked_home_spread':locked[gid]['home_spread'],'locked_total':locked[gid]['locked_total'],
            'current_quotes_context_only':market.get(gid,{}).get('lines',[]),'quote_time_status':'RETRIEVAL_TIME_KNOWN;PROVIDER_QUOTE_TIME_NOT_SUPPLIED;NOT_CLOSING_LINE',
            'weather':w,'weather_applicability':'INDOOR_EXTERNAL_WEATHER_NOT_APPLIED' if venue and venue.get('dome') else 'OUTDOOR_FORECAST_NOT_OBSERVATION',
            'numerical_adjustments':[],'availability_status':'UNVERIFIED_UNLESS_EXPLICITLY_CONFIRMED_IN_OWNER_REVIEW;SEASON_LEADER_NOT_STARTER_CONFIRMATION'}
        for side in ('away','home'):
            team_id=game[side+'Id'];origin=teams[team_id]['location'];past=[g for g in games if g['completed'] and g['week']<=8 and team_id in (g['homeId'],g['awayId']) and g['homeClassification']==g['awayClassification']=='fbs']
            last=max(past,key=lambda x:instant(x['startDate'])) if past else None
            splits={}
            for label in ('HOME','AWAY','NEUTRAL'):
                group=[g for g in past if ('NEUTRAL' if g['neutralSite'] else 'HOME' if g['homeId']==team_id else 'AWAY')==label]
                scored=[g['homePoints'] if g['homeId']==team_id else g['awayPoints'] for g in group]
                allowed=[g['awayPoints'] if g['homeId']==team_id else g['homePoints'] for g in group]
                splits[label]={'n':len(group),'mean_points_for':sum(scored)/len(group) if group else None,'mean_points_against':sum(allowed)/len(group) if group else None}
            kickoff=instant(game['startDate']);tz=origin.get('timezone');destination=venue.get('timezone') if venue else None
            row[side+'_context']={'last_fbs_game_id':last['id'] if last else None,'last_fbs_kickoff':last['startDate'] if last else None,
                'days_between_fbs_kickoffs':(kickoff-instant(last['startDate'])).total_seconds()/86400 if last else None,
                'home_stadium_to_venue_great_circle_miles':round(distance(origin,venue),1) if venue else None,
                'travel_limit':'Geodesic stadium proxy, not verified team itinerary; rest is kickoff-to-kickoff, not full rest days',
                'origin_timezone':tz,'venue_timezone':destination,
                'time_zone_shift_hours':timezone_shift(kickoff,tz,destination),
                'time_zone_offset_status':'VERIFIED_TZDATA' if timezone_shift(kickoff,tz,destination) is not None else 'UNAVAILABLE_LOCAL_TZDATA;SOURCE_ZONE_NAMES_RETAINED',
                'fbs_only_splits_through_week8':splits,'frozen_epa_package':components[gid]['raw_point_in_time_package'][side+'_stats']}
        records.append(row)
    if len(records)!=54 or len({r['game_id'] for r in records})!=54:raise ValueError('context board coverage mismatch')
    return {'status':'SEPARATE_CONTEXT_NOT_MODEL_INPUT','games':records,'market_games':len(market),'additional_market_games_beyond_screenshots':[],
        'elapsed_excluded_games':sorted(excluded),'source_card_unchanged':True,'owner_approval':'PENDING'}

def main(folder,verify=False):
    folder=folder.resolve()
    if not folder.is_relative_to(ROOT/'outputs/2026-week9-context'):raise ValueError('context path outside worktree')
    raw=(json.dumps(build(folder),indent=2,sort_keys=True,allow_nan=False)+'\n').encode();target=folder/'derived_context_board.json'
    if verify:
        if target.read_bytes()!=raw:raise ValueError('context replay mismatch')
    else:
        with target.open('xb') as stream:stream.write(raw)
    return {'context_games':54,'owner_approval':'PENDING','model_adjustments':0}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--capture',type=Path,required=True);p.add_argument('--verify',action='store_true');a=p.parse_args();print(json.dumps(main(a.capture,a.verify)))
