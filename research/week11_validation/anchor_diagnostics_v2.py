"""Research replay v2: integer-count unit differences; original v1 stays intact."""
import argparse
import json
import math
from pathlib import Path
from scripts.week10_audit_diagnostics import historical_rows, mean
from scripts.week10_audit_sources import ROOT, read_csv, sha
from scripts.week10_research_metrics import auc, wilson

OUT=ROOT/'research/week11_validation/results-v2.json'
METHODS={'LOCKED_LINE':0.0,'MODEL_25':0.25,'MODEL_50':0.5,'ORIGINAL_POINT_GAUSSIAN':1.0,'PRIOR_FREQUENCY':1.0}
ORIGINAL_ZERO_COHORTS=(12,13,14,15,16,17,18,19,20,22,27,29,30,32,33,47)


def verify_original(current):
    """Exact byte custody plus a finite, signed-zero-only v1/v2 representation bridge."""
    original_path=OUT.with_name('results-v1.json')
    code=OUT.with_name('anchor_diagnostics.py')
    if sha(original_path.read_bytes())!='a2c1b7c1f6ba5aaa5953daab039160e41b4fc01fc8680403850aa8c196c82fb1':
        raise ValueError('original research bytes changed')
    if sha(code.read_bytes().replace(b'\r\n',b'\n'))!='6f4a1c49f79b7cbd3a250910cfc9da4e11e21f718dc871febd08dc11dccbad6d':
        raise ValueError('original research implementation changed')
    original=json.loads(original_path.read_bytes())
    for index in ORIGINAL_ZERO_COHORTS:
        value=original['top5'][index]['unit_difference_vs_ats_research']
        if type(value) is not float or value!=0 or math.copysign(1,value)!=-1:
            raise ValueError('unexpected original zero representation')
        original['top5'][index]['unit_difference_vs_ats_research']=0.0
    if json.dumps(original,sort_keys=True,allow_nan=False)!=json.dumps(current,sort_keys=True,allow_nan=False):
        raise ValueError('substantive or unauthorized representation difference')
    return dict(original_bytes_preserved=True,permitted_signed_zero_paths=len(ORIGINAL_ZERO_COHORTS),substantive_changes=0)


def observations():
    rows=historical_rows()
    for market,name in [('ATS','ats'),('TOTAL','totals')]:
        rows.extend(dict(r,week=10,research_rank=int(r['research_rank']),game=r['away']+' @ '+r['home'])
                    for r in read_csv(ROOT/f'outputs/2026-week10-postgame-audit/v2/week10_{name}_audit.csv'))
    if any(r['week'] not in range(5,11) for r in rows):raise ValueError('only audited prior weeks5-10 permitted')
    for r in rows:
        r['line_forecast']=float(r['locked_line']) if r['market']=='TOTAL' else -float(r['locked_home_spread'])
        r['forecast']=float(r['raw_projection']);r['actual']=float(r['actual_model_target'])
        if r['market']=='TOTAL':r['sign']=1 if r['selection'].lower()=='over' else -1
        else:
            away,home=r['game'].split(' @ ')
            if r['selection'] not in (away,home):raise ValueError('original side identity')
            r['sign']=1 if r['selection']==home else -1
        cover=r['sign']*(r['actual']-r['line_forecast'])
        if ('WIN' if cover>0 else 'LOSS' if cover<0 else 'PUSH')!=r['result']:raise ValueError('independent original grade mismatch')
    return rows


def bucket(edge,sigma):return 0 if edge/sigma<.25 else 1 if edge/sigma<.5 else 2


def predict(train,test,method):
    if not train or not test or max(r['week'] for r in train)>=min(r['week'] for r in test):raise ValueError('chronological split violated')
    alpha=METHODS[method]
    estimate=lambda r:r['line_forecast']+alpha*(r['forecast']-r['line_forecast'])
    errors=[r['actual']-estimate(r) for r in train];bias=mean(errors)
    sigma=math.sqrt(math.fsum((e-bias)**2 for e in errors)/(len(errors)-1))
    if sigma<=0:raise ValueError('missing usable prior residual scale')
    decided=[r for r in train if r['result']!='PUSH'];output=[]
    for r in test:
        prediction=estimate(r);edge=abs(r['forecast']-r['line_forecast']);fallback=False
        if method=='LOCKED_LINE':probability=.5
        elif method=='PRIOR_FREQUENCY':
            group=[q for q in decided if bucket(abs(q['forecast']-q['line_forecast']),sigma)==bucket(edge,sigma)]
            if len(group)<20:group=decided;fallback=True
            probability=(sum(q['result']=='WIN' for q in group)+1)/(len(group)+2)
        else:probability=.5*(1+math.erf(r['sign']*(prediction-r['line_forecast']+bias)/(sigma*math.sqrt(2))))
        output.append(dict(r,candidate=method,candidate_forecast=prediction,probability=max(1e-6,min(1-1e-6,probability)),
                           pooled_calibration_fallback=fallback,train_n=len(train),train_max_week=max(q['week'] for q in train)))
    return output,dict(n=len(train),weeks=sorted({r['week'] for r in train}),residual_bias=bias,residual_sd=sigma)


def metrics(rows,no_bets=False):
    w=sum(r['result']=='WIN' for r in rows);l=sum(r['result']=='LOSS' for r in rows);p=sum(r['result']=='PUSH' for r in rows)
    decided=[r for r in rows if r['result']!='PUSH'];probs=[r['probability'] for r in decided];labels=[int(r['result']=='WIN') for r in decided]
    errors=[r['actual']-r['candidate_forecast'] for r in rows];bins=[]
    for low in range(10):
        group=[(prob,y) for prob,y in zip(probs,labels) if low/10<=prob<(low+1)/10 or low==9 and prob==1]
        if group:bins.append(dict(lower=low/10,n=len(group),probability=mean([q[0] for q in group]),hit_rate=mean([q[1] for q in group])))
    return dict(n=len(rows),bets=0 if no_bets else len(rows),wins=None if no_bets else w,losses=None if no_bets else l,pushes=None if no_bets else p,
                units=0 if no_bets else w*10/11-l,hit_rate=None if no_bets else w/(w+l) if w+l else None,wilson95=None if no_bets else wilson(w,w+l),
                mae=mean([abs(e) for e in errors]),rmse=math.sqrt(mean([e*e for e in errors])) if errors else None,
                brier=mean([(prob-y)**2 for prob,y in zip(probs,labels)]),auc=auc(probs,labels),
                ece=math.fsum(b['n']*abs(b['probability']-b['hit_rate']) for b in bins)/len(labels) if labels else None,
                reliability=bins,probability_caveat='Unvalidated research probabilities; line baseline .5 is scored on original sides and makes no bets.')


def rounded(value):
    if isinstance(value,float):return round(value,8)
    if isinstance(value,list):return [rounded(v) for v in value]
    if isinstance(value,dict):return {k:rounded(v) for k,v in value.items()}
    return value


def build():
    rows=observations();folds=[];ranked=[];parameters=[]
    for week in range(6,11):
        for method in METHODS:
            both=[]
            for market in ('ATS','TOTAL'):
                train=[r for r in rows if r['market']==market and r['week']<week]
                test=[r for r in rows if r['market']==market and r['week']==week]
                result,fit=predict(train,test,method);both.extend(result)
                folds.append(dict(week=week,market=market,method=method,training=fit,**metrics(result,method=='LOCKED_LINE')))
            if method=='LOCKED_LINE':continue
            for scope in ('ATS','TOTAL','COMBINED'):
                group=both if scope=='COMBINED' else [r for r in both if r['market']==scope]
                selected=[];seen=set()
                for r in sorted(group,key=lambda r:(-r['probability'],r['market'],r['game_id'])):
                    if r['game_id'] in seen:continue
                    selected.append(r);seen.add(r['game_id'])
                    if len(selected)==5:break
                stats=metrics(selected)
                if scope=='COMBINED':stats['mae']=stats['rmse']=None
                benchmark=sorted([r for r in both if r['market']=='ATS'],key=lambda r:r['research_rank'])[:5]
                benchmark_wins=sum(r['result']=='WIN' for r in benchmark)
                benchmark_losses=sum(r['result']=='LOSS' for r in benchmark)
                benchmark_units=(10*benchmark_wins-11*benchmark_losses)/11
                # Integer counts avoid Python-version-dependent floating sum and signed zero.
                unit_difference=(10*(stats['wins']-benchmark_wins)-11*(stats['losses']-benchmark_losses))/11
                ranked.append(dict(week=week,method=method,scope=scope,**stats,ats_research_benchmark_units=benchmark_units,
                                   unit_difference_vs_ats_research=unit_difference,
                                   picks=[{k:r[k] for k in ('game_id','game','market','selection','locked_line','probability','result')} for r in selected]))
    # No Week11 estimates are computed; only historical diagnostic folds exist.
    return rounded(dict(status='RESEARCH_ONLY_RETROSPECTIVE_CHRONOLOGICAL_EXPLORATION',methods=METHODS,
                        folds=folds,top5=ranked,week11_predictions=0,official_card_changed=False,
                        cutoff='All fits use weeks strictly earlier than their evaluation week. Methods specified after Week10, so these folds are not prospective validation.',
                        selection_rule='Original sides remain fixed for all positive blends. Top5 probability ranking is experimental; no official cross-market probability comparison.',
                        frequency_rule='Prior-only standardized-edge bins <.25, .25-.5, >=.5; Beta(1,1) smoothing; fewer than20 decided picks falls back to pooled same-market prior outcomes.',
                        probability_rule='Gaussian candidates use prior-week residual bias and sample SD; point forecast remains the stated fixed blend. Probability floor1e-6 is numerical only.',
                        drive_model_status='FORWARD_RESEARCH_PENDING: Week11 prior drives8-10 captured. Do not fabricate historical pregame drive snapshots or claim comparable season/recent filters. Seal complete candidate implementation before Week11 outcomes.',
                        limitations=['Methods and thresholds chosen after Weeks5-10: retrospective research only','Repeated teams, six weeks and overlapping selections limit inference','Week11 shadow awaits genuine contest lines and unchanged official forecasts','No model promotion or Confidence3-5 authorization']))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');a=p.parse_args()
    if not a.verify and OUT.exists():raise ValueError('research version exists; overwrite forbidden')
    result=build();verify_original(result)
    raw=(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    if a.verify:
        if OUT.read_bytes()!=raw:raise ValueError('research exact replay mismatch')
    else:
        with OUT.open('xb') as f:f.write(raw)
    print(json.dumps({'status':'VERIFIED_READ_ONLY' if a.verify else 'RESEARCH_WRITTEN','week11_predictions':0}))
