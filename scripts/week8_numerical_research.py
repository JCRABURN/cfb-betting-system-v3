"""Exploratory prior-week bias and score shrinkage; never changes model policy."""
import argparse
import math
from scripts.research_week7_acceptance import load_modern
from scripts.build_week8_postgame_audit import ROOT, read_csv, serialized

def calculate():
    prior=[p for w in (5,6,7) for p in load_modern(w) if p.market=='TOTAL']
    latest=read_csv(ROOT/'outputs/2026-week8-postgame-audit/week8_totals_audit.csv')
    rows=[dict(week=p.week,error=p.error,score=p.score,win=p.result=='WIN') for p in prior]
    rows += [dict(week=8,error=float(r['forecast_error_actual_minus_predicted']),score=float(r['research_score_not_calibrated']),win=r['result']=='WIN') for r in latest]
    folds=[]
    for week in (6,7,8):
        train=[r for r in rows if r['week']<week];test=[r for r in rows if r['week']==week]
        bias=sum(r['error'] for r in train)/len(train)
        folds.append(dict(test_week=week,prior_training_n=len(train),test_n=len(test),prior_bias=bias,
            baseline_mae=sum(abs(r['error']) for r in test)/len(test),candidate_mae=sum(abs(r['error']-bias) for r in test)/len(test),
            baseline_rmse=math.sqrt(sum(r['error']**2 for r in test)/len(test)),candidate_rmse=math.sqrt(sum((r['error']-bias)**2 for r in test)/len(test))))
    shrink=[]
    for strength in (0,.25,.5,1):
        test=[r for r in rows if r['week']>=6];scores=[.5+strength*(r['score']-.5) for r in test]
        shrink.append(dict(strength=strength,test_weeks=[6,7,8],n=len(test),
            brier=sum((q-r['win'])**2 for q,r in zip(scores,test))/len(test),
            log_loss=-sum(math.log(q if r['win'] else 1-q) for q,r in zip(scores,test))/len(test)))
    return dict(status='RESEARCH_ONLY_NOT_DEPLOYED',prior_week_bias_correction=folds,score_shrinkage_exploratory_grid=shrink,
        limitation='Bias uses only earlier weeks in each fold, but the candidate was proposed after viewing these results. Shrinkage grid is retrospective exploration, not independent validation.')

def main(verify=False):
    path=ROOT/'outputs/2026-week8-audit-research/numerical_research_candidates.json';raw=serialized(calculate())
    if verify:
        if path.read_bytes()!=raw:raise ValueError('numerical research replay mismatch')
    else:
        with path.open('xb') as f:f.write(raw)
    return calculate()

if __name__=='__main__':
    import json
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');print(json.dumps(main(p.parse_args().verify),indent=2))
