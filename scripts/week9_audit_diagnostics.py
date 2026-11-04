"""Deterministic descriptive diagnostics; every new comparison is RESEARCH ONLY."""
from __future__ import annotations

import math
import random
from collections import Counter
from fractions import Fraction

from scripts import research_week7_acceptance as prior
from scripts.week9_audit_sources import ROOT, read_csv
from scripts.week9_audit_grading import spread_bucket, total_bucket


def mean(values):
    return math.fsum(values) / len(values) if values else None


def rounded(value):
    return None if value is None else round(value, 6)


def wilson(wins, n):
    if not n:
        return [None, None]
    z = 1.959963984540054
    p = wins / n
    center = (p + z*z/(2*n)) / (1 + z*z/n)
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
    return [rounded(center-half), rounded(center+half)]


def metrics(rows):
    counts = Counter(r['result'] for r in rows)
    w, l, p = (counts[k] for k in ('WIN', 'LOSS', 'PUSH'))
    units = Fraction(w*10, 11) - l
    errors = [float(r['actual_model_target']) - float(r['raw_projection']) for r in rows]
    # Locked totals / implied home margins are comparators, never replacement inputs.
    baseline = [float(r['actual_model_target']) - (float(r['locked_line']) if r['market'] == 'TOTAL' else -float(r['locked_home_spread'])) for r in rows]
    result = dict(n=len(rows), wins=w, losses=l, pushes=p, hit_rate=rounded(w/(w+l)) if w+l else None,
                hit_rate_wilson95=wilson(w, w+l), units_minus110=rounded(float(units)), units_exact=str(units),
                roi=rounded(float(units)/len(rows)) if rows else None,
                mae=rounded(mean([abs(e) for e in errors])), rmse=rounded(math.sqrt(mean([e*e for e in errors]))) if rows else None,
                bias_actual_minus_prediction=rounded(mean(errors)),
                locked_line_baseline_mae=rounded(mean([abs(e) for e in baseline])),
                locked_line_baseline_rmse=rounded(math.sqrt(mean([e*e for e in baseline]))) if rows else None,
                abs_error_20_plus=sum(abs(e) >= 20 for e in errors), abs_error_30_plus=sum(abs(e) >= 30 for e in errors))
    if len({r['market'] for r in rows}) > 1:
        for field in ('mae', 'rmse', 'bias_actual_minus_prediction', 'locked_line_baseline_mae', 'locked_line_baseline_rmse'):
            result[field] = None
        result['mixed_target_metrics'] = 'NOT_POOLED_ACROSS_MARGIN_AND_TOTAL'
    return result


def historical_rows():
    rows = []
    for week in (5, 6, 7):
        for p in prior.load_modern(week):
            card = dict(week=week, game_id=p.game_id, market=p.market, selection=p.selection,
                        locked_line=p.line, raw_projection=p.projection, actual_model_target=p.actual,
                        result=p.result, confidence=p.confidence, research_rank=p.rank,
                        research_score_not_calibrated=p.score, selected_forecast_edge=p.edge,
                        location=p.location, favorite_dog=p.favorite, governed_top5=str(p.governed_top5),
                        rank_provenance=p.provenance, game=p.game)
            # Pick.line is the selected ATS line; recover the home line by location.
            if p.market == 'ATS':
                frozen = next(r for r in prior.read(prior.ROOT / 'outputs' / prior.PRE[week] / f'week{week}_ats_full_card.csv') if r['game_id'] == p.game_id)
                card['locked_home_spread'] = float(frozen['locked_home_spread'])
            else:
                card['locked_home_spread'] = ''
            rows.append(card)
    for market, name in [('ATS', 'ats'), ('TOTAL', 'totals')]:
        for r in read_csv(ROOT / f'outputs/2026-week8-postgame-audit/week8_{name}_audit.csv'):
            rows.append(dict(week=8, game_id=r['game_id'], market=market, selection=r['selection'],
                             locked_line=float(r['locked_line']), raw_projection=float(r['raw_projection']),
                             actual_model_target=float(r['actual_model_target']), result=r['result'],
                             confidence=int(r['confidence']), research_rank=int(r['research_rank']),
                             research_score_not_calibrated=float(r['research_score_not_calibrated']),
                             selected_forecast_edge=abs(float(r['raw_projection']) + float(r['locked_home_spread'])) if market == 'ATS' else abs(float(r['raw_projection']) - float(r['locked_line'])),
                             location=r.get('location', 'NOT_APPLICABLE'), favorite_dog=r.get('favorite_dog', 'NOT_APPLICABLE'),
                             locked_home_spread=r.get('locked_home_spread', ''), governed_top5=r.get('governed_top5', 'False'),
                             rank_provenance='SEALED_PREGAME_RANK', game=f"{r['away']} @ {r['home']}"))
    return rows


def pearson(x, y):
    if len(x) < 2:
        return None
    mx, my = mean(x), mean(y)
    vx, vy = math.fsum((v-mx)**2 for v in x), math.fsum((v-my)**2 for v in y)
    return math.fsum((a-mx)*(b-my) for a, b in zip(x, y)) / math.sqrt(vx*vy) if vx and vy else None


def discrimination(rows, field):
    rows = [r for r in rows if r['result'] != 'PUSH']
    x, y = [float(r[field]) for r in rows], [int(r['result'] == 'WIN') for r in rows]
    corr = pearson(x, y)
    wins = [v for v, outcome in zip(x, y) if outcome]
    losses = [v for v, outcome in zip(x, y) if not outcome]
    auc = mean([1.0 if w > l else .5 if w == l else 0.0 for w in wins for l in losses])
    rng = random.Random(290905)
    exceed = 0
    for _ in range(999):
        perm = list(y)
        rng.shuffle(perm)
        trial = pearson(x, perm)
        if corr is not None and trial is not None and abs(trial) >= abs(corr):
            exceed += 1
    return dict(n=len(rows), field=field, point_biserial_r=rounded(corr), auc_tie_half=rounded(auc),
                exploratory_permutation_p=rounded((1+exceed)/1000) if corr is not None else None,
                permutations=999, seed=290905, repeated_team_clustering_not_accounted_for=True)


def walk_forward(rows):
    """New hypothetical forecast comparisons only. Train strictly on earlier weeks."""
    trials = []
    for market in ('ATS', 'TOTAL'):
        for week in range(6, 10):
            train = [r for r in rows if r['market'] == market and r['week'] < week]
            test = [r for r in rows if r['market'] == market and r['week'] == week]
            bias = mean([float(r['actual_model_target']) - float(r['raw_projection']) for r in train])
            for candidate in ('HALF_PRIOR_BIAS', 'HALF_LOCKED_LINE_BLEND'):
                changed = []
                for r in test:
                    projected = float(r['raw_projection'])
                    baseline = float(r['locked_line']) if market == 'TOTAL' else -float(r['locked_home_spread'])
                    estimate = projected + .5*bias if candidate == 'HALF_PRIOR_BIAS' else .5*(projected+baseline)
                    changed.append(dict(r, raw_projection=estimate))
                # Selections stay the original ones: reported returns are NOT candidate returns.
                m = metrics(changed)
                trials.append(dict(candidate=candidate, market=market, evaluation_week=week, train_weeks=sorted({r['week'] for r in train}),
                                   train_n=len(train), test_n=len(test), training_bias=rounded(bias),
                                   baseline_mae=metrics(test)['mae'], baseline_rmse=metrics(test)['rmse'],
                                   candidate_mae=m['mae'], candidate_rmse=m['rmse'], candidate_bias=m['bias_actual_minus_prediction'],
                                   status='RESEARCH_ONLY_RETROSPECTIVELY_SPECIFIED_TEMPORALLY_ORDERED', selections_changed=False))
    return trials


def analyze(grades, members):
    rows = historical_rows() + [dict(r, rank_provenance='SEALED_PREGAME_RANK', game=f"{r['away']} @ {r['home']}") for r in grades]
    weekly, ranks, segments, calibration, predictive, correlations = [], [], [], [], [], []
    groups = [(str(w), {w}) for w in range(5, 10)] + [('5-9', set(range(5, 10))), ('7-9', {7, 8, 9})]
    for label, weeks in groups:
        for market in ('ATS', 'TOTAL'):
            group = [r for r in rows if r['week'] in weeks and r['market'] == market]
            weekly.append(dict(week=label, market=market, **metrics(group)))
            for segment, lower, upper in [('1-5', 1, 5), ('6-10', 6, 10), ('11+', 11, 999)]:
                ranks.append(dict(week=label, market=market, rank_segment=segment, **metrics([r for r in group if lower <= r['research_rank'] <= upper])))
            dimensions = dict(confidence=lambda r: str(r['confidence']),
                              edge=lambda r: '<3' if float(r['selected_forecast_edge']) < 3 else '3-6.999' if float(r['selected_forecast_edge']) < 7 else '7-9.999' if float(r['selected_forecast_edge']) < 10 else '10+',
                              research_score=lambda r: '<0.55' if float(r['research_score_not_calibrated']) < .55 else '0.55-0.599' if float(r['research_score_not_calibrated']) < .6 else '0.60-0.699' if float(r['research_score_not_calibrated']) < .7 else '0.70+')
            if market == 'ATS':
                dimensions.update(favorite_dog=lambda r: r['favorite_dog'].upper(), location=lambda r: r['location'].upper(),
                                  road_favorite=lambda r: str(r['favorite_dog'].upper() == 'FAVORITE' and r['location'].upper() == 'AWAY'),
                                  spread_size=lambda r: spread_bucket(r['locked_line']))
            else:
                dimensions.update(direction=lambda r: r['selection'].lower(), total_size=lambda r: total_bucket(r['locked_line']))
            for dimension, key in dimensions.items():
                for bucket in sorted({key(r) for r in group}):
                    selected = [r for r in group if key(r) == bucket]
                    segments.append(dict(week=label, market=market, dimension=dimension, bucket=bucket, **metrics(selected)))
                    if dimension in ('confidence', 'research_score'):
                        scored = [r for r in selected if r['result'] != 'PUSH']
                        scores = [float(r['research_score_not_calibrated']) for r in scored]
                        outcome = [int(r['result'] == 'WIN') for r in scored]
                        calibration.append(dict(week=label, market=market, dimension=dimension, bucket=bucket, n=len(scored),
                                                mean_research_score=rounded(mean(scores)), actual_win_rate=rounded(mean(outcome)),
                                                brier_descriptive_uncalibrated=rounded(mean([(s-y)**2 for s, y in zip(scores, outcome)])),
                                                log_loss_descriptive_uncalibrated=rounded(mean([-math.log(s if y else 1-s) for s, y in zip(scores, outcome)])),
                                                status='NOT_VALIDATED_PROBABILITY_CALIBRATION'))
            if label in ('9', '5-9', '7-9'):
                for field in ('selected_forecast_edge', 'research_score_not_calibrated'):
                    predictive.append(dict(week=label, market=market, **discrimination(group, field)))
        a = {(r['week'], r['game_id']): r for r in rows if r['week'] in weeks and r['market'] == 'ATS'}
        t = {(r['week'], r['game_id']): r for r in rows if r['week'] in weeks and r['market'] == 'TOTAL'}
        keys = sorted(a)
        if set(a) != set(t):
            raise ValueError('cross-market cohort mismatch')
        ae = [float(a[k]['actual_model_target']) - float(a[k]['raw_projection']) for k in keys]
        te = [float(t[k]['actual_model_target']) - float(t[k]['raw_projection']) for k in keys]
        correlations.append(dict(week=label, n_games=len(keys), signed_error_r=rounded(pearson(ae, te)),
                                 absolute_error_r=rounded(pearson(list(map(abs, ae)), list(map(abs, te)))),
                                 win_indicator_r=rounded(pearson([int(a[k]['result'] == 'WIN') for k in keys], [int(t[k]['result'] == 'WIN') for k in keys])),
                                 ats_totals_research_top5_overlap=sum(a[k]['research_rank'] <= 5 and t[k]['research_rank'] <= 5 for k in keys)))
    by_key = {(r['market'], str(r['game_id'])): r for r in grades}
    cohorts = [dict(cohort=c, **metrics([by_key[(m['market'], m['game_id'])] for m in members if m['cohort'] == c])) for c in sorted({m['cohort'] for m in members})]
    extremes = sorted([r for r in grades], key=lambda r: (-abs(float(r['forecast_error_actual_minus_predicted'])), r['market'], r['game_id']))
    uncertainty = []
    for market in ('ATS', 'TOTAL'):
        selected = [r for r in grades if r['market'] == market]
        errors = sorted(abs(float(r['forecast_error_actual_minus_predicted'])) for r in selected)
        uncertainty.append(dict(market=market, n=len(selected),
                                within_one_archived_sigma=sum(abs(float(r['forecast_error_actual_minus_predicted'])) <= float(r['uncertainty_points']) for r in selected),
                                within_two_archived_sigma=sum(abs(float(r['forecast_error_actual_minus_predicted'])) <= 2*float(r['uncertainty_points']) for r in selected),
                                empirical_absolute_error_nearest_rank_p90=rounded(errors[math.ceil(.9*len(errors))-1]),
                                empirical_absolute_error_nearest_rank_p95=rounded(errors[math.ceil(.95*len(errors))-1]),
                                status='DESCRIPTIVE_COVERAGE_NOT_A_NEW_INTERVAL_POLICY'))
    return dict(status='RESEARCH_ONLY', weekly=weekly, nonoverlapping_rank_segments=ranks, segments=segments,
                confidence_calibration=calibration, predictive_discrimination=predictive, error_correlations=correlations,
                frozen_cohorts=cohorts, extreme_errors=extremes, uncertainty_coverage=uncertainty, walk_forward_candidates=walk_forward(rows),
                evidence_boundary='Weeks 5-6 have pregame forecasts but retrospectively constructed research ordering; Weeks 7-9 have sealed pregame ranks. All new subgroup tests and candidate formulas were specified after outcomes and are exploratory, including temporally ordered replay. Repeated teams and overlapping cohorts are not independent trials.',
                precision='Raw frozen forecasts retained verbatim; decimal grades exact; derived statistics use math.fsum and report six decimals, with no tolerance in byte replay.',
                units='Hypothetical risk 1 per pick at -110: win +10/11, loss -1, push 0. No actual wager or profitability assertion.')
