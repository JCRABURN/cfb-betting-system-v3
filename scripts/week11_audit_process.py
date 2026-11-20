"""Postgame mechanisms and market evidence, never prediction inputs or causal claims."""
from __future__ import annotations
import gzip
import json
from collections import defaultdict
from scripts.week11_audit_inputs import source_json, source_files, BOARD, sha
from scripts.week10_audit_sources import unique, instant
from scripts.week8_scoring_sequence_review import validate_sequence
from scripts.week10_audit_game_process import NON_OFFENSE_TD, PASS, RUSH, defensive_sack_score


def process(finals, grades, data, cohorts):
    boxes = unique(data['cfbd-team-stats'], 'id')
    players = unique(data['cfbd-player-stats'], 'id')
    by_game = {}
    for key in ('advanced','drives','plays'):
        index = defaultdict(list)
        for r in data['cfbd-'+key]:
            index[str(r['gameId'])].append(r)
        by_game[key] = index
    top_games = {r['game_id'] for name, rows in cohorts.items() if not name.endswith('TOP10') for r in rows}
    team_rows, passer_rows, game_rows, scoring, failures = [], [], [], [], []
    for final in finals:
        gid = final['game_id']
        match_grades = [r for r in grades if r['game_id']==gid]
        advanced = unique(by_game['advanced'][gid], 'team')
        box = unique(boxes[gid]['teams'], 'homeAway')
        qbs = unique(players[gid]['teams'], 'homeAway')
        plays, drives = by_game['plays'][gid], by_game['drives'][gid]
        unique(plays,'id'); unique(drives,'id')
        if len(advanced)!=2 or not plays or not drives or set(box)!= {'home','away'}:
            raise ValueError('Incomplete process coverage: '+gid)
        for side in ('away','home'):
            t = box[side]; a=advanced[t['team']]
            if t['teamId'] != final[side+'_id'] or t['points'] != final[side+'_score'] or a['week'] != 11 or a['season'] != 2026:
                raise ValueError('Process team/score identity mismatch')
            stats = {s['category']:s['stat'] for s in t['stats']}
            team_rows.append(dict(game_id=gid,team=t['team'],side=side,points=t['points'],
                                  total_yards=stats.get('totalYards'),turnovers=stats.get('turnovers'),sacks=stats.get('sacks'),
                                  possession_time=stats.get('possessionTime'),third_down=stats.get('thirdDownEff'),fourth_down=stats.get('fourthDownEff'),
                                  red_zone_box=stats.get('redZoneEff'),offensive_plays=a['offense']['plays'],provider_drives=a['offense']['drives'],
                                  offensive_ppa=a['offense']['ppa'],success_rate=a['offense']['successRate'],explosiveness=a['offense']['explosiveness']))
            passing = next((c for c in qbs[side]['categories'] if c['name']=='passing'),None)
            athletes = {}
            for category in passing['types'] if passing else []:
                for athlete in category['athletes']:
                    entry = athletes.setdefault(athlete['id'],dict(game_id=gid,team=t['team'],athlete_id=athlete['id'],name=athlete['name'],
                                                                  status='OBSERVED_PASSER;STARTER_AND_MEDICAL_CLEARANCE_NOT_INFERRED'))
                    entry[category['name']] = athlete['stat']
            passer_rows += list(athletes.values())
        seq = data['espn-'+gid].get('scoringPlays',[])
        try:
            validate_sequence(seq,final['away_score'],final['home_score']); valid=True
        except (ValueError,KeyError,TypeError):
            valid=False
        nonoffense_points = 0 if valid else None
        if valid:
            previous=(0,0)
            for p in seq:
                delta=p['awayScore']+p['homeScore']-sum(previous)
                kind=p['type']['text']
                if kind in NON_OFFENSE_TD or kind in {'Safety','Defensive 2pt Conversion'} or kind=='Sack' and delta==2:
                    nonoffense_points+=delta
                    scoring.append(dict(game_id=gid,play_id=p['id'],type=kind,points_with_bundled_conversion=delta,text=p['text'],period=p['period']['number'],clock=p['clock']['displayValue']))
                elif kind=='Sack' and delta in (6,7,8):
                    other=next((q for q in plays if str(q['id'])==str(p['id'])),None)
                    try:
                        adjudicated=defensive_sack_score(p,other,final,previous)
                        nonoffense_points+=delta; scoring.append(adjudicated)
                    except (ValueError,KeyError,TypeError):
                        scoring.append(dict(game_id=gid,play_id=p['id'],type='UNRESOLVED_SCORING_SACK',points_with_bundled_conversion=None,text=p['text']))
                        nonoffense_points=None
                previous=(p['awayScore'],p['homeScore'])
        redzone_drives={p['driveId'] for p in plays if p['period']<=4 and 0<=p['yardsToGoal']<=20 and p['playType'] in PASS|RUSH|{'Pass Incompletion','Sack'}}
        record=dict(game_id=gid,away=final['away'],home=final['home'],
                    provider_plays=sum(a['offense']['plays'] for a in advanced.values()),
                    provider_drives=sum(a['offense']['drives'] for a in advanced.values()),
                    raw_drive_records=len(drives),regulation_positive_play_drives=sum(d['startPeriod']<=4 and d['plays']>0 for d in drives),
                    red_zone_drives_observed=len(redzone_drives),
                    red_zone_drive_tds=sum(d['id'] in redzone_drives and d['driveResult']=='TD' for d in drives),
                    short_field_drives_start_inside40=sum(d['startYardsToGoal']<=40 and d['plays']>0 for d in drives),
                    explosive_pass20=sum(p['playType'] in PASS and p['yardsGained']>=20 for p in plays),
                    explosive_rush10=sum(p['playType'] in RUSH and p['yardsGained']>=10 for p in plays),
                    nonoffensive_points_with_bundled_conversions=nonoffense_points,
                    overtime=any(p['period']>4 for p in plays),scoring_sequence_valid=valid,
                    combined_points_per_provider_drive=(final['away_score']+final['home_score'])/sum(a['offense']['drives'] for a in advanced.values()),
                    espn_raw_sha256=final['espn_raw_sha256'],
                    weather='PREGAME_FORECAST_ARCHIVED;ACTUAL_STADIUM_OBSERVATIONS_UNVERIFIED',
                    availability='BOX_USAGE_OBSERVED;OL_DEFENSIVE_SNAP_SHARES_AND_CAUSAL_EFFECTS_UNVERIFIED')
        game_rows.append(record)
        for r in match_grades:
            error=abs(float(r['forecast_error_actual_minus_predicted']))
            priority=gid in top_games or error>=20 or float(r['selected_forecast_edge'])>=10 and r['result']=='LOSS' or r['market']=='TOTAL' and int(r['confidence'])>=4 and r['result']=='LOSS'
            if not priority:
                continue
            # G/F are descriptive forecast-selection classifications. A-E need causal corroboration.
            code='G' if r['result']=='WIN' and error>=20 else 'F' if r['result']=='LOSS' and error<=7 else 'H'
            failures.append(dict(game_id=gid,market=r['market'],selection=r['selection'],line=r['locked_line'],result=r['result'],
                                 absolute_error=error,theoretical_edge=r['selected_forecast_edge'],priority_top5=gid in top_games,
                                 taxonomy=code,classification_basis='G: winning pick despite >=20-point miss; F: losing pick despite <=7-point forecast error; otherwise H pending causal evidence. Thresholds are descriptive postgame categories, not selection policy.',
                                 process=record,observed_passers=[p for p in passer_rows if p['game_id']==gid],
                                 observed_teams=[t for t in team_rows if t['game_id']==gid],
                                 pregame_available='Original frozen EPA and timestamped contextual files preserved separately.',
                                 attribution='No automatic variance explanation. Box scores do not establish pregame knowledge or causal personnel, weather, matchup or pace effects.'))
    return dict(games=game_rows,teams=team_rows,passers=passer_rows,scoring=scoring,failures=failures,
                definitions='All process data are postgame only, unfiltered unless explicitly regulation. Provider advanced excludeGarbageTime=false. Raw drives and provider advanced counts are distinct. Red-zone trips are unique regulation drive IDs with observed rush/pass/sack at <=20 yards; this is not an official red-zone statistic. Points/drive includes nonoffensive points and is not offensive efficiency. No incompatible garbage-time series are pooled.')


def clv(finals, data, records):
    eligible=unique(finals); observations=[]
    captures=[]
    for path in sorted(p for p in source_files() if p.startswith('outputs/2026-week11-context/') and p.endswith('/manifest.json')):
        manifest=source_json(path)
        for r in manifest.get('records',[]):
            if r.get('name') != 'separate-current-market' or r.get('status')!='CAPTURED':
                continue
            raw=gzip.decompress(source_files()[path.rsplit('/',1)[0]+'/'+r['path']])
            if sha(raw)!=r['raw_sha256']:
                raise ValueError('Pregame market evidence changed')
            captures.append((json.loads(raw),r['received_at_utc'],r['resolved_url'],r['raw_sha256']))
    captures.append((data['cfbd-lines'],records['cfbd-lines']['received_at_utc'],records['cfbd-lines']['resolved_url'],records['cfbd-lines']['raw_sha256']))
    for games,received,url,digest in captures:
        for g in games:
            gid=str(g['id'])
            if gid not in eligible:
                continue
            for line in g['lines']:
                timestamp={k:v for k,v in line.items() if any(s in k.lower() for s in ('timestamp','updated','date'))}
                observations.append(dict(game_id=gid,book=line['provider'],home_spread=line.get('spread'),total=line.get('overUnder'),
                                         retrieved_at_utc=received,provider_timestamp_fields=timestamp,
                                         qualification='PREGAME_OBSERVATION_ONLY' if instant(received)<instant(eligible[gid]['kickoff_utc']) else 'POSTGAME_SNAPSHOT',
                                         actual_quote_timestamp=None,qualified_closing_line=None,clv=None,source=url,raw_sha256=digest))
    return dict(status='INCOMPLETE',qualified_closes=0,predictions=128,coverage=0,
                observations=observations,positive_negative_neutral_results='UNAVAILABLE_NO_TIMESTAMP_QUALIFIED_CLOSES',
                reason='None of the inspected CFBD quotes establishes an actual closing timestamp. Retrieval time is not quote time. No timestamp or CLV manufactured.')
