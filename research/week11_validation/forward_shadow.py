"""Separate, preregistered remaining-game shadow; never changes the v2.8 card."""
import argparse
import gzip
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from research.week11_validation.anchor_diagnostics_v2 import METHODS, observations, predict, rounded
from scripts.seal_week11_board import ROOT, OUT as BOARD, csv_rows, instant, read, sha

OUT = ROOT/'research/week11_validation/forward-v1.json'
CAPTURE = ROOT/'outputs/2026-week11-readiness/20261110T193209Z'

def encoded(value): return (json.dumps(rounded(value),indent=2,sort_keys=True,allow_nan=False)+'\n').encode()

def drive_summary():
    rows=[]; hashes={}; excluded=0; quarantine=[]
    games={g['id']:g for g in json.loads(gzip.decompress((CAPTURE/'cfbd-games-all.json.gz').read_bytes()))}
    manifest=read(CAPTURE/'capture-manifest.json')
    for week in (8,9,10):
        path=CAPTURE/f'cfbd-prior-week{week}-drives.json.gz'
        record=next(r for r in manifest['records'] if r['path']==path.name)
        if sha(path)!=record['stored_sha256']:raise ValueError('drive input bytes changed')
        hashes[path.relative_to(ROOT).as_posix()]=sha(path)
        for r in json.loads(gzip.decompress(path.read_bytes())):
            game=games[r['gameId']]
            if game['season']!=2026 or game['week']!=week or not game['completed']:raise ValueError('drive season/week identity')
            if r['startPeriod']>4 or r['driveResult'] in {'END OF HALF','END OF GAME'}:
                excluded+=1;continue
            delta=r['endOffenseScore']-r['startOffenseScore']
            allowed={6,7,8} if r['driveResult']=='TD' else {3} if r['driveResult']=='FG' else {0}
            if delta not in allowed:
                quarantine.append(dict(week=week,drive_id=r['id'],game_id=r['gameId'],offense=r['offense'],defense=r['defense'],drive_result=r['driveResult'],observed_offensive_score_delta=delta,permitted_delta=sorted(allowed),status='QUARANTINE_BOTH_TEAMS_NO_REPAIR'))
            rows.append(r)
    summary={}
    for team in sorted({r[s] for r in rows for s in ('offense','defense')}):
        if any(team in (q['offense'],q['defense']) for q in quarantine):continue
        off=[r for r in rows if r['offense']==team];defense=[r for r in rows if r['defense']==team]
        ids={r['gameId'] for r in off}
        if len(ids)<2 or not defense:continue
        points=lambda r:r['endOffenseScore']-r['startOffenseScore']
        if any(points(r)<0 or points(r)>8 for r in off+defense):raise ValueError('unexplained scoring delta')
        summary[team]=dict(games=len(ids),offensive_drives=len(off),defensive_drives=len(defense),
            drives_per_game=len(off)/len(ids),points_per_drive=math.fsum(points(r) for r in off)/len(off),
            allowed_points_per_drive=math.fsum(points(r) for r in defense)/len(defense),
            plays_per_game=math.fsum(r['plays'] for r in off)/len(ids),
            yards_per_play=math.fsum(r['yards'] for r in off)/math.fsum(r['plays'] for r in off))
    return summary,hashes,excluded,quarantine

def build(as_of):
    cutoff=instant(as_of); training=observations()
    if max(r['week'] for r in training)!=10:raise ValueError('training cutoff must be Week10')
    raw=read(BOARD/'week11_raw_model_components.json');games={str(g['game_id']):g for g in raw['games']}
    if cutoff<instant(raw['generated_at_utc']):raise ValueError('shadow before original board')
    eligible={gid for gid,g in games.items() if instant(g['kickoff_utc'])>cutoff}
    targets=[]
    for market,name in [('ATS','ats'),('TOTAL','totals')]:
        for r in csv_rows(f'week11_{name}_full_card.csv'):
            if r['game_id'] not in eligible:continue
            line=float(r['locked_total']) if market=='TOTAL' else -float(r['locked_home_spread'])
            sign=(1 if r['pick']=='over' else -1) if market=='TOTAL' else (1 if r['selected_side']=='home' else -1)
            targets.append(dict(game_id=r['game_id'],game=r['away']+' @ '+r['home'],week=11,market=market,selection=r['pick'],
                contest_line=float(r['locked_total']) if market=='TOTAL' else float(r['pick_spread']),
                line_forecast=line,forecast=float(r['projected_total'] if market=='TOTAL' else r['projected_home_margin']),sign=sign))
    output=[];fits=[];top=[]
    for method in METHODS:
        both=[]
        for market in ('ATS','TOTAL'):
            rows,fit=predict([r for r in training if r['market']==market],[r for r in targets if r['market']==market],method)
            both+=rows;fits.append(dict(method=method,market=market,**fit))
        output+=both
        if method=='LOCKED_LINE':continue
        selected=[];seen=set()
        for r in sorted(both,key=lambda r:(-r['probability'],r['market'],r['game_id'])):
            if r['game_id'] in seen:continue
            selected.append(r);seen.add(r['game_id'])
            if len(selected)==5:break
        top.append(dict(method=method,scope='COMBINED_FUTURE_ONLY_EXPERIMENT',selections=selected))
    drives,hashes,excluded,quarantine=drive_summary(); drive_predictions=[]
    for gid in sorted(eligible):
        g=games[gid]; h=drives.get(g['home']);a=drives.get(g['away'])
        if not h or not a:
            drive_predictions.append(dict(game_id=gid,status='BLOCKED_QUARANTINED_OR_INSUFFICIENT_PRIOR_DRIVES_NO_IMPUTATION'));continue
        possessions=(h['drives_per_game']+a['drives_per_game'])/2
        home=possessions*(h['points_per_drive']+a['allowed_points_per_drive'])/2
        away=possessions*(a['points_per_drive']+h['allowed_points_per_drive'])/2
        drive_predictions.append(dict(game_id=gid,status='UNVALIDATED_FORWARD_PROTOTYPE',projected_home_points=home,projected_away_points=away,projected_total=home+away,projected_home_margin=home-away,expected_possessions_per_team=possessions,home_sample=h,away_sample=a,confidence=None,probability=None))
    inputs=[BOARD/'week11_initial_seal_manifest.json',BOARD/'week11_ats_full_card.csv',BOARD/'week11_totals_full_card.csv',BOARD/'week11_raw_model_components.json',CAPTURE/'capture-manifest.json',CAPTURE/'cfbd-games-all.json.gz',ROOT/'research/week11_validation/results-v2.json']
    hashes.update({p.relative_to(ROOT).as_posix():sha(p) for p in inputs})
    return dict(status='RESEARCH_ONLY_FUTURE_61_GAMES_NOT_POLICY',registered_at_utc=as_of,training_max_week=10,
        training_rows_sha256=hashlib.sha256(encoded(training)).hexdigest(),input_sha256=hashes,
        included_game_ids=sorted(eligible),excluded_already_started_ids=sorted(set(games)-eligible),
        original_ats_research_top5=csv_rows('week11_ats_research_top5.csv'),original_combined_research_top5=csv_rows('week11_legacy_mixed_research_top5.csv'),
        methods=METHODS,parameters=fits,predictions=output,top5=top,drive_predictions=drive_predictions,
        drive_rule='Weeks8-10 regulation drives; omit END OF HALF/END OF GAME and overtime. Average both teams offensive drives/game, multiply by mean of own offensive and opponent allowed points/drive. Minimum2 prior games each; no imputation. Not opponent-adjusted; non-offensive scores and game-script effects are unresolved. No drive probability or confidence is assigned.',
        excluded_drive_rows=excluded,drive_quarantine=quarantine,forward_metrics='PENDING_UNTOUCHED_WEEK11_OUTCOMES',
        protocol='All five anchor/calibration methods and the drive prototype remain reported regardless of outcomes. Train only Weeks5-10 (drives8-10). Grade every remaining game and each frozen research Top5 after independent final reconciliation; report MAE/RMSE, Brier/AUC/ECE, hit rate, -110 units, overlap, paired selection differences and game/week-cluster uncertainty. Preserve original ATS Top5 including its already-started member; compare the four still-future original ATS members separately rather than retrospectively replacing that member. This is a new November12 forward experiment, not a pre-Wednesday registration.',
        drive_backtest_status='BLOCKED_NO_GENUINE_HISTORICAL_PREGAME_DRIVE_SNAPSHOTS; no fabricated chronological validation',
        policy_gate='No promotion, new Confidence3-5, or validated probability claim. Prior retrospective folds do not validate this forward experiment. Independent review and formal governance required.',owner_approval='PENDING')

def main(verify=False):
    if verify:
        saved=read(OUT); result=build(saved['registered_at_utc'])
        if OUT.read_bytes()!=encoded(result):raise ValueError('forward research exact replay mismatch')
    else:
        if OUT.exists():raise FileExistsError('never overwrite frozen research')
        result=build(datetime.now(timezone.utc).isoformat())
        if len(result['included_game_ids'])!=61:raise ValueError('expected remaining61; require separately versioned protocol for changed timing')
        with OUT.open('xb') as stream:stream.write(encoded(result))
    return dict(status='VERIFIED' if verify else 'FROZEN_RESEARCH_ONLY',games=len(result['included_game_ids']),predictions=len(result['predictions']),drive_predictions=len(result['drive_predictions']))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');print(json.dumps(main(p.parse_args().verify)))
