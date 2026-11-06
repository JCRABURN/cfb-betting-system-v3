"""Copy exact Git blobs into a small offline research pack; no database writes."""
import csv
import gzip
import hashlib
import io
import json
import subprocess
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent
PRE={5:'2026-week5-execution-20260930-v4',6:'2026-week6-execution-20261006T2133Z',7:'2026-week7-prospective-corrected-v2',8:'2026-week8-prospective-v2',9:'2026-week9-prospective',10:'2026-week10-prospective'}


def sha(data):return hashlib.sha256(data).hexdigest()
def stamp(s):return datetime.fromisoformat(s.replace('Z','+00:00'))
def write(path,data):
    with path.open('x',encoding='utf-8',newline='\n') as stream:stream.write(json.dumps(data,indent=2,sort_keys=True,allow_nan=False)+'\n')


def export():
    destination=HERE/'sources'
    if destination.exists():raise ValueError('source archive exists; no overwrite')
    destination.mkdir()
    protocol=json.loads((HERE/'protocol.json').read_text())
    manifest={}; frames=[]; capture_time=datetime.now(timezone.utc).isoformat()
    def read(commit,path,alias):
        raw=subprocess.check_output(['git','show',commit+':'+path],cwd=ROOT)
        packed=gzip.compress(raw,mtime=0);(destination/(alias+'.gz')).write_bytes(packed)
        manifest[alias]=dict(commit=commit,path=path,git_blob=subprocess.check_output(['git','rev-parse',commit+':'+path],cwd=ROOT,text=True).strip(),sha256=sha(raw),stored_sha256=sha(packed),storage=alias+'.gz')
        return list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))) if path.endswith('.csv') else json.loads(raw)
    for week,folder in PRE.items():
        commit=protocol['week10_source_commit'] if week==10 else protocol['audit_source_commit'];pre='outputs/'+folder
        model=read(commit,f'{pre}/week{week}_model_manifest.json',f'w{week}_model')
        generated=model['generated_at_utc']
        games=read(commit,f'{pre}/provider-evidence/cfbd-week{week}-games.derived.json',f'w{week}_schedule')
        games={str(g['id']):g for g in games}
        statpath=f'{pre}/provider-evidence/cfbd-week{week-1}-advanced.derived.json'
        if week==10:statpath=f'{pre}/core-initial/week9-advanced.raw.json'
        advanced={r['team']:r for r in read(commit,statpath,f'w{week}_pregame_stats')}
        for market,name in [('ATS','ats'),('TOTAL','totals')]:
            card=read(commit,f'{pre}/week{week}_{name}_full_card.csv',f'w{week}_{name}_card')
            audit={}
            if week<10:
                folder=f'outputs/2026-week{week}-postgame-audit'+('/v1' if week==9 else '')
                audit={r['game_id']:r for r in read(commit,f'{folder}/week{week}_{name}_audit.csv',f'w{week}_{name}_audit')}
            if week<10 and set(audit)!={r['game_id'] for r in card}:raise ValueError('audit coverage')
            order=sorted(card,key=lambda r:(-abs(float(r['home_ats_edge'])),int(r['locked_line_id']))) if market=='ATS' else sorted(card,key=lambda r:(-float(r['raw_selected_probability']),int(r['game_id'])))
            ranks={r['game_id']:i for i,r in enumerate(order,1)}
            for r in card:
                gid=r['game_id'];g=games[gid];a=audit.get(gid); ats=market=='ATS'
                if stamp(generated)>=stamp(g['startDate']) or g['completed'] or g['homePoints'] is not None or g['awayPoints'] is not None:raise ValueError('pregame boundary')
                home=r['home'];away=r['away'];line=float(r['pick_spread'] if ats else r['locked_total']);market_forecast=-float(r['locked_home_spread']) if ats else line
                forecast=float(r['projected_home_margin'] if ats else r['projected_total']);sign=(1 if r['selected_side']=='home' else -1) if ats else (1 if r['pick'].lower()=='over' else -1)
                outcome=actual=cover=None
                if a:
                    if 'actual_model_target' in a:actual=float(a['actual_model_target'])
                    else:
                        hs=float(a.get('home_score',a.get('final_home_score')));aws=float(a.get('away_score',a.get('final_away_score')));actual=hs-aws if ats else hs+aws
                    cover=(actual-market_forecast)*sign;outcome='WIN' if cover>0 else 'LOSS' if cover<0 else 'PUSH'
                    if outcome!=a.get('result',a.get('ats_result' if ats else 'total_result')):raise ValueError('independent grading mismatch')
                    al=a.get('locked_line',a.get('selected_spread' if ats else 'locked_splash_total',a.get('locked_total')))
                    if float(al)!=line:raise ValueError('audit line mismatch')
                stats=[advanced[team] for team in (home,away)]
                def avg(section,field):return sum(s[section][field] for s in stats)/2
                context=dict(plays_per_drive=sum(s['offense']['plays']/s['offense']['drives'] for s in stats)/2,
                             rush_rate=sum(s['offense']['rushingPlays']['rate'] for s in stats)/2,
                             off_success=avg('offense','successRate'),def_success=avg('defense','successRate'),
                             off_explosiveness=avg('offense','explosiveness'),def_explosiveness=avg('defense','explosiveness'),
                             off_ppa=avg('offense','ppa'),def_ppa=avg('defense','ppa'))
                score=float(r['ats_shadow_score_not_calibrated']) if ats and r.get('ats_shadow_score_not_calibrated') else min(.6,.5+.005*abs(forecast-market_forecast)) if ats else float(r['raw_selected_probability'])
                frames.append(dict(week=week,game_id=gid,market=market,home=home,away=away,kickoff=g['startDate'],generated_at=generated,
                                   source_stats_through_week=week-1,original_selection=r['pick'],line=line,market_forecast=market_forecast,
                                   forecast=forecast,sign=sign,actual=actual,result=outcome,cover=cover,edge=abs(forecast-market_forecast),
                                   score=score,sigma=float(r['shadow_uncertainty_points'] if ats else r['uncertainty_points']),
                                   governed_uncertainty=r.get('uncertainty_points') if ats else r['uncertainty_points'],
                                   confidence=int(r['confidence']),rank=int(r.get('ats_research_rank' if ats else 'totals_research_rank') or ranks[gid]),
                                   rank_provenance='ARCHIVED_RANK' if week>=7 else 'RETROSPECTIVE_ORDER_OF_PREGAME_FIELDS',
                                   governed_top5=r.get('top_five')=='True',locked_line_id=int(r.get('locked_line_id') or list(games).index(gid)),
                                   features=context,personnel_features='UNAVAILABLE_NOT_IMPUTED'))
    # Preserve source code evidence for the diagnosed confidence mechanisms.
    for path,alias in [('business_entities/ranking.py','confidence_code'),('business_entities/weekly_controller.py','controller_code')]:
        raw=subprocess.check_output(['git','show',protocol['audit_source_commit']+':'+path],cwd=ROOT)
        (destination/(alias+'.gz')).write_bytes(gzip.compress(raw,mtime=0))
        manifest[alias]=dict(commit=protocol['audit_source_commit'],path=path,sha256=sha(raw),stored_sha256=sha((destination/(alias+'.gz')).read_bytes()),storage=alias+'.gz')
    ids={(r['week'],r['game_id']):r['locked_line_id'] for r in frames if r['market']=='ATS'}
    for row in frames:row['locked_line_id']=ids[row['week'],row['game_id']]
    write(HERE/'source_manifest.json',dict(created_at_utc=capture_time,sources=manifest,note='Exact Git blob bytes, not rewritten checkout receipts. Original custody and historical files untouched.'))
    write(HERE/'observations.json',dict(status='RESEARCH_INPUT_COPY_NOT_NEW_HISTORICAL_PREDICTIONS',rows=frames))
    print(json.dumps({'rows':len(frames),'sources':len(manifest),'historical_games':sum(r['week']<10 for r in frames)//2,'week10_games':sum(r['week']==10 for r in frames)//2}))


if __name__=='__main__':export()
