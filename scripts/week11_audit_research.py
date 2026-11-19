"""Grade frozen Week11 candidates without fitting, tuning or changing membership."""
from __future__ import annotations

import math
from scripts.week11_audit_inputs import source_json
from scripts.week11_audit_metrics import summary, mean, auc, wilson
from scripts.week10_audit_sources import instant


def probability_metrics(rows):
    decided = [r for r in rows if r['result'] in ('WIN','LOSS')]
    probabilities = [float(r['probability']) for r in decided]
    if any(not math.isfinite(p) or not 0 < p < 1 for p in probabilities):
        raise ValueError('Invalid frozen probability')
    outcomes = [int(r['result']=='WIN') for r in decided]
    bins = [0,.5,.525,.55,.58,.62,.7,.8,.9,1]
    reliability = []
    for low, high in zip(bins,bins[1:]):
        chosen = [(p,y) for p,y in zip(probabilities,outcomes) if low <= p < high]
        if chosen:
            reliability.append(dict(lower=low, upper=high, n=len(chosen), mean_probability=mean([p for p,y in chosen]),
                                    hit_rate=mean([y for p,y in chosen]), wilson95=wilson(sum(y for p,y in chosen),len(chosen))))
    return dict(n_probability=len(decided), brier=mean([(p-y)**2 for p,y in zip(probabilities,outcomes)]),
                log_loss=mean([-math.log(p if y else 1-p) for p,y in zip(probabilities,outcomes)]),
                ranking_auc=auc(probabilities,outcomes),
                calibration_error_ece=math.fsum(r['n']*abs(r['mean_probability']-r['hit_rate']) for r in reliability)/len(decided) if decided else None,
                reliability=reliability)


def confidence_candidate(probability):
    if not math.isfinite(probability) or not 0 <= probability <= 1:
        raise ValueError('Invalid probability')
    return 1 + sum(probability >= p for p in (.525,.55,.58,.62))


def evaluate(grades):
    frozen = source_json('research/week11_validation/forward-v1.json')
    if frozen['training_max_week'] != 10 or len(frozen['included_game_ids']) != 61 or len(frozen['predictions']) != 610:
        raise ValueError('Frozen research coverage or training cutoff changed')
    lookup = {(r['market'],r['game_id']):r for r in grades}
    rows = []
    identities = set()
    for p in frozen['predictions']:
        identity = (p['candidate'],p['market'],p['game_id'])
        if identity in identities or p['train_max_week'] >= p['week'] or p['week'] != 11:
            raise ValueError('Research duplicate or leakage')
        identities.add(identity)
        base = lookup[p['market'],p['game_id']]
        if base['custody'] != 'FORWARD_SEALED_61' or instant(frozen['registered_at_utc']) >= instant(base['kickoff_utc']):
            raise ValueError('Research prediction not forward eligible')
        if p['selection'] != base['selection'] or float(p['contest_line']) != float(base['locked_line']):
            raise ValueError('Frozen selection or locked line mismatch')
        if abs(float(p['forecast'])-float(base['raw_projection'])) > 1e-7:
            raise ValueError('Frozen raw forecast mismatch')
        if p['candidate'] != 'LOCKED_LINE' and (p['candidate_forecast'] - p['line_forecast']) * p['sign'] < -1e-7:
            raise ValueError('Unexpected frozen candidate pick reversal')
        candidate_error=float(base['actual_model_target'])-p['candidate_forecast']
        rows.append(dict(base, raw_projection=p['candidate_forecast'], candidate=p['candidate'], probability=p['probability'],
                         frozen_original_projection=p['forecast'], candidate_forecast=p['candidate_forecast'],
                         forecast_error_actual_minus_predicted=candidate_error,absolute_forecast_error=abs(candidate_error),
                         squared_forecast_error=candidate_error*candidate_error,
                         selected_forecast_edge=abs(p['candidate_forecast']-p['line_forecast']),
                         hypothetical_units_minus110='0' if p['candidate']=='LOCKED_LINE' else base['hypothetical_units_minus110'],
                         candidate_confidence_research_only=confidence_candidate(p['probability']),
                         registered_at_utc=frozen['registered_at_utc'], train_max_week=p['train_max_week'],
                         training_n=p['train_n'], no_bet=p['candidate']=='LOCKED_LINE'))
    full, top_results, memberships, reliability = [], [], [], []
    for method in frozen['methods']:
        candidates = [r for r in rows if r['candidate']==method]
        for market in ('ATS','TOTAL'):
            group = [r for r in candidates if r['market']==market]
            if len(group) != 61:
                raise ValueError('61 records per candidate-market required')
            stats = dict(method=method, market=market, **summary(group), **probability_metrics(group))
            if method == 'LOCKED_LINE':
                stats.update(wins=0,losses=0,pushes=0,hit_rate=None,units_minus110=0,roi=None,
                             units_exact='0',hit_rate_wilson95=[None,None],roi_interval95_iid_wilson=[None,None],
                             return_status='NO_BET; probability evaluated on original frozen selection outcomes only')
            full.append(stats)
            reliability += [dict(method=method,market=market,**r) for r in stats['reliability']]
        if method == 'LOCKED_LINE':
            continue
        original = next(x for x in frozen['top5'] if x['method']==method)
        for scope in ('ATS','TOTAL','COMBINED'):
            if scope == 'COMBINED':
                chosen = [next(r for r in candidates if r['game_id']==p['game_id'] and r['market']==p['market']) for p in original['selections']]
                membership_status = 'EXACT_FROZEN_COMBINED_MEMBERSHIP'
            else:
                chosen = sorted([r for r in candidates if r['market']==scope],key=lambda r:(-r['probability'],r['market'],r['game_id']))[:5]
                membership_status = 'FROZEN_PROBABILITY_RULE_APPLIED_WITHIN_MARKET;NO_OUTCOME_RANKING'
            if len({r['game_id'] for r in chosen}) != 5:
                raise ValueError('Dependent duplicate game in research five')
            name = method+'_'+scope
            memberships += [dict(r,cohort=name,cohort_rank=i,membership_status=membership_status) for i,r in enumerate(chosen,1)]
            top_results.append(dict(method=method,scope=scope,**summary(chosen),**probability_metrics(chosen)))
    drive = []
    for p in frozen['drive_predictions']:
        if p['status'] != 'UNVALIDATED_FORWARD_PROTOTYPE':
            continue
        for market, field in [('ATS','projected_home_margin'),('TOTAL','projected_total')]:
            row = lookup[market,p['game_id']]
            drive.append(dict(game_id=p['game_id'],market=market,forecast=p[field],actual=row['actual_model_target'],
                              absolute_error=abs(p[field]-row['actual_model_target']),
                              line_absolute_error=abs(row['line_implied_forecast']-row['actual_model_target']),
                              expected_possessions_per_team=p['expected_possessions_per_team'],
                              status='FROZEN_POINT_FORECAST_ONLY;NO_ORIGINAL_PICKS_PROBABILITIES_OR_TOP5'))
    return dict(full=full, top5=top_results, memberships=memberships, all_rows=rows, reliability=reliability, drive=drive,
                parameters=frozen['parameters'], training_rows_sha256=frozen['training_rows_sha256'],
                pr50='No separately sealed Week11 PR50 prediction artifact found in inspected PR50 head; Week10 holdout remains in its prior audit.',
                interpretation='Positive linear shrinkage preserves original selection direction. Top5 methods overlap and are one prospective week, not independent replications. No method promoted.')
