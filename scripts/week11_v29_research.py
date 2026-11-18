"""Retrospectively specified chronological residual/ranking experiment, never production."""
from __future__ import annotations

import math
import statistics
from scripts.week11_audit_metrics import mean, summary
from scripts.week11_audit_research import probability_metrics, confidence_candidate

PROTOCOL = dict(version='v2.9-research-proposal-1', specified_after_week=11,
                training='Expanding Weeks5..evaluation_week-1; Week5 seed only; all eligible games retained.',
                ridge_penalty=10.0, probability_prior_cases=20, probability_prior_mean=.5,
                confidence_boundaries=[.525,.55,.58,.62],
                calibrated_confidence_gate='Research bucket only; production Confidence3-5 prohibited until prospective minimum500 decided bucket cases (800 for5),20 weeks,two seasons,ECE<=.03,lower95 bound>.52381,stable folds,and owner approval.',
                prospective_promotion='At least20 untouched future evaluation weeks; paired week-block95 MAE difference<0 versus line and baseline in each promoted market, Brier improvement, ranking AUC lower95>.5, combined-five unit difference lower95>0 versus strongest preregistered incumbent, no unexplained severe subgroup instability. Familywise multiple-candidate adjustment required. No threshold tuning on holdout.',
                fallback='Mandatory contest picks may remain Confidence1. When calibrated ranking unavailable, mark the whole ranking UNVALIDATED_FALLBACK and sort by market,canonical matchup,side for reproducibility only. Never describe tie-break order as quality.',
                dependence='At most one selection per game. Report shared teams across weeks and pairwise overlap. No forced ATS/totals allocation.',
                model_status='RESEARCH_ONLY_NOT_PROMOTED')


def line_forecast(row):
    return float(row['locked_line']) if row['market']=='TOTAL' else -float(row['locked_home_spread'])


def fit(train, evaluation_week):
    if not train or any(int(r['week'])>=evaluation_week for r in train):
        raise ValueError('Training leaks evaluation week')
    x=[float(r['raw_projection'])-line_forecast(r) for r in train]
    y=[float(r['actual_model_target'])-line_forecast(r) for r in train]
    mx,my=mean(x),mean(y)
    # Fixed L2 penalty; no post-outcome grid search or candidate selection.
    slope=math.fsum((a-mx)*(b-my) for a,b in zip(x,y))/(math.fsum((a-mx)**2 for a in x)+PROTOCOL['ridge_penalty']*len(x))
    intercept=my-slope*mx
    residuals=[b-intercept-slope*a for a,b in zip(x,y)]
    return dict(slope=slope,intercept=intercept,residual_sd=statistics.stdev(residuals),train_n=len(train),train_max_week=max(int(r['week']) for r in train))


def run(rows):
    predictions=[]; folds=[]; selected=[]; histories={'ATS':[],'TOTAL':[]}
    for week in range(6,12):
        weekly=[]
        for market in ('ATS','TOTAL'):
            train=[r for r in rows if r['market']==market and int(r['week'])<week]
            targets=[r for r in rows if r['market']==market and int(r['week'])==week]
            model=fit(train,week)
            out=[]
            for r in targets:
                line=line_forecast(r); x=float(r['raw_projection'])-line
                prediction=line+model['intercept']+model['slope']*x
                direction=1 if prediction>=line else -1
                actual=float(r['actual_model_target']); cover=(actual-line)*direction
                outcome='WIN' if cover>0 else 'LOSS' if cover<0 else 'PUSH'
                standardized=abs(prediction-line)/model['residual_sd']
                bucket=0 if standardized<.25 else 1 if standardized<.5 else 2
                previous=[p for p in histories[market] if p['standardized_bucket']==bucket and p['result']!='PUSH']
                # Calibration sees only predictions evaluated in earlier folds, never current outcomes.
                probability=(sum(p['result']=='WIN' for p in previous)+10)/(len(previous)+20)
                ranking_status='PRIOR_OOF_CALIBRATION_SMALL_SAMPLE' if previous else 'NO_PRIOR_OOF_CALIBRATION_FALLBACK'
                selection=('over' if direction>0 else 'under') if market=='TOTAL' else r['home' if direction>0 else 'away']
                row=dict(r,raw_projection=prediction,selection=selection,result=outcome,probability=probability,
                         selected_forecast_edge=abs(prediction-line),uncertainty_points=model['residual_sd'],
                         confidence=1,candidate_confidence_research_only=confidence_candidate(probability),
                         candidate='MARKET_RESIDUAL_RIDGE_OOF_FREQUENCY',standardized_bucket=bucket,
                         ranking_status=ranking_status,calibration_n=len(previous),calibration_max_week=max((int(p['week']) for p in previous),default=None),
                         fit=model,week=week,design_status='RETROSPECTIVE_CHRONOLOGICAL;WEEK11_IS_DEVELOPMENT_NOT_HOLDOUT')
                row.update(cover_margin=cover,forecast_error_actual_minus_predicted=actual-prediction,
                           absolute_forecast_error=abs(actual-prediction),squared_forecast_error=(actual-prediction)**2,
                           governed_top5='False',governed_rank='',production_uncertainty_points=None,
                           hypothetical_units_minus110='10/11' if outcome=='WIN' else '-1' if outcome=='LOSS' else '0')
                if market=='ATS':
                    row['locked_line']=float(r['locked_home_spread'])*direction
                    row['selected_side']='home' if direction>0 else 'away'
                out.append(row)
            predictions+=out; weekly+=out
            folds.append(dict(week=week,market=market,**summary(out),**probability_metrics(out),fit=model))
        # Both markets share the same empirical probability scale; no uncalibrated ATS-vs-total edge mixing.
        chosen=[];seen=set()
        for r in sorted(weekly,key=lambda r:(-r['probability'],r['market'],r.get('away',''),r.get('home',''),r['selection'])):
            if r['game_id'] in seen:
                continue
            chosen.append(r);seen.add(r['game_id'])
            if len(chosen)==5:
                break
        selected += [dict(r,cohort_rank=i) for i,r in enumerate(chosen,1)]
        # Update calibration ledger only after both market predictions for the week are fixed.
        for market in histories:
            histories[market]+=[r for r in weekly if r['market']==market]
    catalog=[dict(architecture=name,status=status,required_validation=validation) for name,status,validation in [
        ('Market-anchored residual','IMPLEMENTED_RETROSPECTIVE_RESEARCH','Simple fixed-penalty ridge on frozen forecast-minus-line; future holdout required.'),
        ('Opponent-adjusted efficiency','BLOCKED_COMPARABLE_PIT_FEATURE_LEDGER','Build weekly opponent schedule-adjusted offensive/defensive ledger through sanctioned PIT accessor.'),
        ('Offense-defense matchup interactions','BLOCKED_COMPARABLE_PIT_FEATURE_LEDGER','Regularized interactions only after point-in-time base features and fold sample audit.'),
        ('Recency weighting','BLOCKED_COMPARABLE_PIT_FEATURE_LEDGER','Require game-level EPA timestamps and consistent garbage-time definition.'),
        ('Home-field and travel','PARTIAL_HOME_MARGIN_BASELINE_ONLY','Need neutral-site, stadium coordinates and known schedule/rest history; no fabricated travel.'),
        ('Pace and possessions','FROZEN14_GAME_PROTOTYPE_GRADED_SEPARATELY','Resolve drive score quarantine before feature inclusion; exclude overtime consistently.'),
        ('Expected points per drive','BLOCKED_DRIVE_ADJUDICATION','Separate offensive points from return/defensive points; validate conversion attribution.'),
        ('Explosive offense versus defense','BLOCKED_COMPARABLE_PIT_FEATURE_LEDGER','Stable rush10/pass20 definitions; no game-total or season-final contamination.'),
        ('Red-zone efficiency','BLOCKED_COMPARABLE_PIT_FEATURE_LEDGER','Standardize trip and touchdown definitions; shrink small denominators.'),
        ('QB and personnel','BLOCKED_HISTORICAL_PIT_EVIDENCE','Only timestamped availability and snap expectations; observed postgame usage is not pregame knowledge.')]]
    return dict(protocol=PROTOCOL,folds=folds,predictions=predictions,top5=selected,catalog=catalog,promotion='REJECTED_NO_UNTOUCHED_HOLDOUT_EVIDENCE')
