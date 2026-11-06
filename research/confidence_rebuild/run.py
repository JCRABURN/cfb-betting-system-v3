"""Chronological research replay and separately timestamped prospective holdout."""
import argparse
import hashlib
import itertools
import json
import random
import subprocess
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
from .data import HERE,load,instant
from .engine import Fit,select,mean
from .metrics import summarize,top5,paired_week_gain,week_block_ci


def canonical(value):
    if isinstance(value,float):return round(value,10)
    if isinstance(value,list):return [canonical(x) for x in value]
    if isinstance(value,dict):return {str(k):canonical(v) for k,v in value.items()}
    return value


def dump(path,value):
    with path.open('x',encoding='utf-8',newline='\n') as stream:stream.write(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')


def source_code():
    return {p.name:hashlib.sha256(p.read_bytes().replace(b'\r\n',b'\n')).hexdigest() for p in HERE.glob('*.py')}


def prospective(output):
    rows,protocol=load();started=datetime.now(timezone.utc);all_test=[r for r in rows if r['week']==10]
    eligible=[r for r in all_test if instant(r['kickoff'])>started];predictions=[]
    if output.exists():raise ValueError('prospective version exists')
    for market in protocol['markets']:
        fit=Fit([r for r in rows if r['week']<10 and r['market']==market],10,protocol)
        for name in protocol['candidates']:
            predictions.extend(fit.predict(r,name) for r in eligible if r['market']==market)
    finished=datetime.now(timezone.utc)
    # Do not backdate a slow computation. Drop any game that started during it.
    predictions=[r for r in predictions if instant(r['kickoff'])>finished]
    retained={r['game_id'] for r in predictions}
    result=dict(status='PROSPECTIVE_RESEARCH_ONLY_NOT_CONTEST_REVISION',generated_at_utc=finished.isoformat(),
                source_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=HERE,text=True).strip(),
                source_code_sha256_lf=source_code(),protocol_sha256=hashlib.sha256((HERE/'protocol.json').read_bytes()).hexdigest(),
                original_sealed_games=57,eligible_shadow_games=len(retained),excluded_started_games=sorted({r['game_id'] for r in all_test}-retained),
                owner_approval='PENDING',policy_changed=False,selections=predictions,
                top5={name:[{'game_id':r['game_id'],'market':r['market'],'candidate_sign':r['candidate_sign'],'score':r['ranking_score']} for r in select([r for r in predictions if r['candidate']==name])] for name in protocol['candidates']})
    output.mkdir(parents=True);dump(output/'prospective.json',result)
    dump(output/'seal.json',{'sha256':hashlib.sha256((output/'prospective.json').read_bytes()).hexdigest(),'generated_at_utc':finished.isoformat()})
    print(json.dumps({k:result[k] for k in ('generated_at_utc','eligible_shadow_games','excluded_started_games')}))


def replay(rows,protocol):
    predictions=[];fits={};folds=[]
    for week in protocol['evaluation_weeks']:
        for market in protocol['markets']:
            train=sorted([r for r in rows if r['week']<week and r['market']==market],key=lambda r:(r['week'],r['game_id']))
            test=[r for r in rows if r['week']==week and r['market']==market]
            if max(instant(r['kickoff']) for r in train)>=min(instant(r['generated_at']) for r in test):raise ValueError('training game not before forecast time')
            fit=Fit(train,week,protocol);fits[week,market]=fit
            for name in protocol['candidates']:
                predicted=[fit.predict(r,name) for r in test];predictions+=predicted
                folds.append(dict(week=week,market=market,candidate=name,training_weeks=sorted({r['week'] for r in train}),training_n=len(train),**summarize(predicted,protocol['probability_bins'])))
    return predictions,folds,fits


def stability(rows,protocol,ordinary):
    results=[];rng=random.Random(protocol['random_seed'])
    for week in protocol['evaluation_weeks']:
        train=[r for r in rows if r['week']<week];test=[r for r in rows if r['week']==week];weeks=sorted({r['week'] for r in train});overlaps={};frequencies={}
        base={name:{scope:{(r['game_id'],r['market']) for r in top5([p for p in ordinary if p['week']==week and p['candidate']==name],scope)} for scope in ('ATS','TOTAL','COMBINED')} for name in protocol['candidates'] if name!='LOCKED_LINE'}
        for _ in range(protocol['stability_training_week_bootstraps']):
            sampled=[w for w in rng.choices(weeks,k=len(weeks))];boot=[]
            for market in protocol['markets']:
                training=[r for w in sampled for r in train if r['week']==w and r['market']==market];fit=Fit(training,week,protocol)
                for name in base:
                    boot.extend(fit.predict(r,name) for r in test if r['market']==market)
            for name in base:
                for scope in ('ATS','TOTAL','COMBINED'):
                    chosen=top5([r for r in boot if r['candidate']==name],scope);keys={(r['game_id'],r['market']) for r in chosen};union=keys|base[name][scope]
                    overlaps.setdefault((name,scope),[]).append(len(keys&base[name][scope])/len(union))
                    frequencies.setdefault((name,scope),Counter()).update(keys)
        for (name,scope),values in overlaps.items():
            results.append(dict(week=week,candidate=name,scope=scope,mean_jaccard=mean(values),minimum_jaccard=min(values),
                                resamples=len(values),training_week_clusters=len(weeks),
                                warning='Single training-week resampling has no between-week variability' if len(weeks)==1 else 'Training-week bootstrap, correlated teams remain',
                                selection_frequencies=[dict(game_id=g,market=m,count=n) for (g,m),n in sorted(frequencies[name,scope].items())]))
    return results


def analyze(output,verify=False):
    rows,protocol=load();predictions,folds,fits=replay(rows,protocol);bins=protocol['probability_bins'];summaries=[];top=[];gains=[];controls=[]
    for market in protocol['markets']:
        for name in protocol['candidates']:
            selected=[r for r in predictions if r['market']==market and r['candidate']==name]
            summaries.append(dict(market=market,candidate=name,**summarize(selected,bins),auc_week_block95=week_block_ci(selected,'auc')))
    unit_tables={}
    for name in protocol['candidates']:
        if name=='LOCKED_LINE':continue
        for scope in ('ATS','TOTAL','COMBINED'):
            selected=[];unit_tables[name,scope]={}
            for week in protocol['evaluation_weeks']:
                picks=top5([r for r in predictions if r['week']==week and r['candidate']==name],scope);selected+=picks
                unit_tables[name,scope][week]=summarize(picks,bins)['units_minus110']
            top.append(dict(candidate=name,scope=scope,**summarize(selected,bins),selections=[dict(week=r['week'],game_id=r['game_id'],market=r['market'],sign=r['candidate_sign'],result=r['candidate_result']) for r in selected]))
            gains.append(dict(candidate=name,scope=scope,**paired_week_gain(unit_tables[name,scope],unit_tables.get(('FROZEN_V28',scope),unit_tables[name,scope]))))
    for (week,market),fit in fits.items():
        for name,logit in fit.logits.items():
            controls.append(dict(week=week,market=market,candidate=name,standardized_coefficients=logit.coef,
                                 feature_names=['intercept','edge_over_sigma']+(['log_sigma','absolute_line','selected_direction'] if name!='EDGE_LOGIT' else []),
                                 training_feature_scales=logit.design.scales,constant_features=logit.design.constant,
                                 interpretation='Penalized descriptive coefficient; no causal interpretation or p-value. Evaluate incremental OOS discrimination.'))
    confidence=[];baseline=[]
    for market in protocol['markets']:
        for weekset,label in [(set(range(5,10)),'5-9'),(set(range(6,10)),'6-9')]:
            original=[]
            for r in rows:
                if r['week'] in weekset and r['market']==market:
                    original.append(dict(r,candidate='FROZEN_V28',candidate_forecast=r['forecast'],candidate_sign=r['sign'],candidate_result=r['result'],probability=r['score'],ranking_score=r['score'],interval_radii={'0.8':1.2815515655*r['sigma'],'0.9':1.644853627*r['sigma']}))
            baseline.append(dict(market=market,weeks=label,**summarize(original,bins)))
            for c in range(1,6):confidence.append(dict(market=market,weeks=label,confidence=c,**summarize([r for r in original if r['confidence']==c],bins)))
    result=canonical(dict(status='RETROSPECTIVE_TEMPORAL_RESEARCH_REPLAY_NOT_NEW_OFFICIAL_PREDICTIONS',protocol=protocol,
                          historical_rows=558,evaluation_rows=len([r for r in rows if 6<=r['week']<=9]),baseline=baseline,
                          summaries=summaries,folds=folds,top5=top,paired_top5_gains=gains,edge_controls=controls,
                          original_confidence=confidence,selection_stability=stability(rows,protocol,predictions),
                          promotion='NOT_QUALIFIED: no untouched prospective outcomes, four evaluation weeks, one season, only 20 combined Top5 selections per candidate',
                          original_predictions_or_policy_changed=False))
    raw=(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    if verify:
        if (output/'results.json').read_bytes()!=raw:raise ValueError('research replay mismatch')
    else:
        if output.exists():raise ValueError('results directory exists')
        output.mkdir(parents=True);(output/'results.json').write_bytes(raw)
    print(json.dumps(dict(status='REPLAY_VERIFIED' if verify else 'RESEARCH_COMPLETE',output=str(output),sha256=hashlib.sha256(raw).hexdigest())))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);parser.add_argument('--prospective',action='store_true');parser.add_argument('--verify',action='store_true');args=parser.parse_args()
    if args.prospective:prospective(args.output)
    else:analyze(args.output,args.verify)
