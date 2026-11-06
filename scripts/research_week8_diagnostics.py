"""Retrospective comparisons of frozen Week 5-8 predictions; no policy writes."""
from __future__ import annotations
import math
from scripts import research_week7_acceptance as prior

def analyze(tables):
    rows=[r for week in (5,6,7) for r in prior.load_modern(week)]
    for market,name in (("ATS","ats"),("TOTAL","totals")):
        for r in tables[f"week8_{name}_audit.csv"]:
            rows.append(prior.Pick(8,r["game_id"],market,f"{r['away']} @ {r['home']}",r['selection'],
                r['locked_line'],r['raw_projection'],r['actual_model_target'],r['margin_vs_locked'],r['result'],
                abs(r['raw_projection']+r['locked_home_spread']) if market=='ATS' else abs(r['raw_projection']-r['locked_line']),
                r['research_score_not_calibrated'],None,r['confidence'],r['research_rank'],
                r.get('governed_top5')=='True',r.get('location','NOT_APPLICABLE'),r.get('favorite_dog','NOT_APPLICABLE'),
                'SEALED_PREGAME_RANK'))
    weekly=[]; bands=[]; segments=[]
    for week in (5,6,7,8,'5-8','7-8'):
        for market in ('ATS','TOTAL'):
            group=[r for r in rows if r.market==market and (week=='5-8' or week=='7-8' and r.week>=7 or r.week==week)]
            weekly.append(dict(week=week,market=market,**prior.metrics(group)))
            for name,predicate in [('1-5',lambda r:r.rank<=5),('6-10',lambda r:5<r.rank<=10),('11+',lambda r:r.rank>10)]:
                bands.append(dict(week=week,market=market,rank_segment=name,**prior.metrics([r for r in group if predicate(r)])))
            dimensions={'confidence':lambda r:str(r.confidence),'research_score':lambda r:'0.50-0.549' if r.score<.55 else '0.55-0.599' if r.score<.6 else '0.60-0.699' if r.score<.7 else '0.70+',
                'edge_points':lambda r:'<3' if r.edge<3 else '3-6.999' if r.edge<7 else '7-9.999' if r.edge<10 else '10+'}
            if market=='ATS':dimensions.update(favorite=lambda r:r.favorite,location=lambda r:r.location,spread_size=lambda r:prior.spread_bucket(r.line),road_favorite=lambda r:str(r.favorite=='FAVORITE' and r.location=='AWAY'))
            else:dimensions.update(direction=lambda r:r.selection,total_size=lambda r:'<50' if r.line<50 else '50-59.5' if r.line<60 else '60+')
            for dimension,key in dimensions.items():
                for label in sorted({key(r) for r in group}):segments.append(dict(week=week,market=market,dimension=dimension,bucket=label,**prior.metrics([r for r in group if key(r)==label])))
    predict={}; correlations={}; distributions={}
    for cohort,allowed in [('W5-8_EXPLORATORY',(5,6,7,8)),('W7-8_SEALED_RANKS',(7,8)),('W8_NEW_PROSPECTIVE_HOLDOUT',(8,))]:
        for market in ('ATS','TOTAL'):
            group=[r for r in rows if r.week in allowed and r.market==market]
            predict[cohort+'/'+market]={field:prior.predictive(group,field,permutations=999) for field in ('edge','score')}
        a={ (r.week,r.game_id):r for r in rows if r.week in allowed and r.market=='ATS'}
        t={ (r.week,r.game_id):r for r in rows if r.week in allowed and r.market=='TOTAL'}
        keys=sorted(a)
        correlations[cohort]={'n_games':len(keys),'signed_margin_total_error':prior.pearson([a[k].error for k in keys],[t[k].error for k in keys]),
            'absolute_margin_total_error':prior.pearson([abs(a[k].error) for k in keys],[abs(t[k].error) for k in keys]),
            'ats_top5_total_top5_overlap':sum(a[k].rank<=5 and t[k].rank<=5 for k in keys),
            'ats_win_total_win':prior.pearson([float(a[k].result=='WIN') for k in keys],[float(t[k].result=='WIN') for k in keys])}
        errors=sorted(t[k].error for k in keys)
        def q(p):
            pos=(len(errors)-1)*p; lo=int(pos); hi=min(lo+1,len(errors)-1)
            return errors[lo]+(pos-lo)*(errors[hi]-errors[lo])
        distributions[cohort]={'n':len(errors),'min':min(errors),'p10':q(.1),'median':q(.5),'p90':q(.9),'max':max(errors),'abs_error_20_plus':sum(abs(e)>=20 for e in errors),'abs_error_30_plus':sum(abs(e)>=30 for e in errors)}
    return {'weekly':weekly,'nonoverlapping_rank_segments':bands,'segments':segments,'predictive_discrimination':predict,
        'error_correlations':correlations,'total_error_distribution':distributions,
        'owner_review':{'week8':'NO_APPROVAL_ARTIFACT;NO_HUMAN_SUBSTITUTION_EFFECT_ESTIMABLE','week7':'Owner 2-3 versus ATS research 3-2; descriptive one-win difference, not causal evidence'},
        'evidence_boundary':'W5-6 use pregame forecasts but retrospective score ordering. W7-8 ranks were sealed pregame. W8 is prospective validation of existing policies; all new analyses, subgroups and proposals are exploratory.',
        'units':'Hypothetical risk 1 unit per selection at -110: win +10/11, loss -1, push 0. No actual wagers asserted.'}

def markdown(d):
    text=['# Week 5-8 diagnostic tables','','All numbers use immutable pregame forecasts and locked contest lines. '+d['evidence_boundary'],'',
          '| Week | Market | N | W-L-P | Hit rate | MAE | RMSE | Bias actual minus forecast | -110 units |','|---|---|---:|---|---:|---:|---:|---:|---:|']
    for r in d['weekly']:
        text.append(f"| {r['week']} | {r['market']} | {r['n']} | {r['wins']}-{r['losses']}-{r['pushes']} | {r['hit_rate']:.1%} | {r['mae']:.3f} | {r['rmse']:.3f} | {r['bias_actual_minus_prediction']:+.3f} | {r['units_minus110']:+.3f} |")
    text+=['','## Nonoverlapping ranking segments','','| Week | Market | Rank segment | N | W-L-P | Hit rate | -110 units |','|---|---|---|---:|---|---:|---:|']
    for r in d['nonoverlapping_rank_segments']:
        text.append(f"| {r['week']} | {r['market']} | {r['rank_segment']} | {r['n']} | {r['wins']}-{r['losses']}-{r['pushes']} | {r['hit_rate']:.1%} | {r['units_minus110']:+.3f} |")
    text+=['','## Segments','','| Week | Market | Dimension | Bucket | N | W-L-P | Hit rate | -110 units |','|---|---|---|---|---:|---|---:|---:|']
    for r in d['segments']:
        text.append(f"| {r['week']} | {r['market']} | {r['dimension']} | {r['bucket']} | {r['n']} | {r['wins']}-{r['losses']}-{r['pushes']} | {r['hit_rate']:.1%} | {r['units_minus110']:+.3f} |")
    text+=['','Discrimination, Brier/log loss, permutation tests, error correlations and total-error quantiles are in cross_week_diagnostics.json. Tests are exploratory; permutation results are not robust to repeated-team clustering. CLV remains INCOMPLETE for every historical week lacking qualifying closes.']
    return '\n'.join(text)+'\n'
