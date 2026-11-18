"""Descriptive calibration and paired forecast diagnostics; no postgame tuning."""
from __future__ import annotations

import math
import random
import statistics
from collections import Counter, defaultdict
from scripts.week10_audit_diagnostics import historical_rows, mean, metrics
from scripts.week10_audit_sources import read_csv
from scripts.week10_research_metrics import auc, percentile, wilson
from scripts.week11_audit_inputs import ROOT, BOARD, board_csv


def summary(rows):
    result = metrics(rows)
    result.update(evaluation_weeks=len({int(r['week']) for r in rows}),
                  average_confidence=mean([float(r['confidence']) for r in rows if r.get('confidence') not in ('', None)]),
                  mean_predicted_edge=mean([float(r['selected_forecast_edge']) for r in rows]),
                  mean_uncertainty=mean([float(r['uncertainty_points']) for r in rows if r.get('uncertainty_points') not in ('', None)]),
                  mean_absolute_error_points=mean([abs(float(r['actual_model_target']) - float(r['raw_projection'])) for r in rows]),
                  small_sample=len(rows) < 100)
    w, l, p = result['wins'], result['losses'], result['pushes']
    lo, hi = wilson(w, w+l)
    result['roi_interval95_iid_wilson'] = [(21/11*x-1)*(w+l)/len(rows) for x in (lo, hi)] if w+l else [None, None]
    result['interval_caveat'] = 'Wilson and derived ROI intervals are descriptive; overlapping cohorts and repeated teams are not independent.'
    return result


def historical():
    rows = historical_rows()
    for market, name in [('ATS', 'ats'), ('TOTAL', 'totals')]:
        rows += [dict(r, week=10, confidence=int(r['confidence']), research_rank=int(r['research_rank']))
                 for r in read_csv(ROOT / f'outputs/2026-week10-postgame-audit/v2/week10_{name}_audit.csv')]
    # Preserve historical rank qualifications: Weeks5-6 score orders were retrospective.
    prefixes = {5: '2026-week5-execution-20260930-v4', 6: '2026-week6-execution-20261006T2133Z',
                7: '2026-week7-prospective-corrected-v2', 8: '2026-week8-prospective-v2',
                9: '2026-week9-prospective', 10: '2026-week10-prospective'}
    cards = {}
    for week, prefix in prefixes.items():
        for market, name in [('ATS', 'ats'), ('TOTAL', 'totals')]:
            for r in read_csv(ROOT / f'outputs/{prefix}/week{week}_{name}_full_card.csv'):
                cards[week, market, r['game_id']] = r
    for r in rows:
        c = cards[int(r['week']), r['market'], r['game_id']]
        r.update(uncertainty_points=c.get('shadow_uncertainty_points') if r['market'] == 'ATS' else c.get('uncertainty_points'),
                 production_uncertainty_points=c.get('uncertainty_points') or None,
                 selected_side=c.get('selected_side', ''), away=c['away'], home=c['home'],
                 custody='HISTORICAL_ORIGINAL_QUALIFICATIONS_PRESERVED')
    return rows


def edge_bucket(r):
    e = float(r['selected_forecast_edge'])
    return '0-2' if e <= 2 else '>2-4' if e <= 4 else '>4-7' if e <= 7 else '>7-10' if e <= 10 else '>10'


def segments(rows):
    result = []
    for market in ('ATS', 'TOTAL'):
        group = [r for r in rows if r['market'] == market]
        rules = {'edge': edge_bucket, 'confidence': lambda r:str(r['confidence']),
                 'rank': lambda r:'1-5' if int(r['research_rank']) <= 5 else '6-10' if int(r['research_rank']) <= 10 else '11+'}
        if market == 'ATS':
            rules.update(favorite=lambda r:r['favorite_dog'], location=lambda r:r['location'],
                         role=lambda r:r['location'] + '_' + r['favorite_dog'],
                         spread=lambda r:'0-3' if abs(float(r['locked_line'])) <= 3 else '3.5-7' if abs(float(r['locked_line'])) <= 7 else '7.5-14' if abs(float(r['locked_line'])) <= 14 else '14.5-21' if abs(float(r['locked_line'])) <= 21 else '>21')
        else:
            rules.update(direction=lambda r:r['selection'].upper(),
                         locked_total=lambda r:'<45' if float(r['locked_line']) < 45 else '45-54.5' if float(r['locked_line']) < 55 else '55-64.5' if float(r['locked_line']) < 65 else '65+')
        for name, fn in rules.items():
            for value in sorted({fn(r) for r in group}):
                result.append(dict(market=market, segment=name, value=value, **summary([r for r in group if fn(r) == value])))
    return result


def forecast(rows, draws=1500):
    if not rows:
        return {}
    if len({r['market'] for r in rows}) != 1:
        raise ValueError('Forecast targets must not be pooled across ATS and totals')
    error = [float(r['actual_model_target']) - float(r['raw_projection']) for r in rows]
    baseline = [float(r['actual_model_target']) - (float(r['locked_line']) if r['market'] == 'TOTAL' else -float(r['locked_home_spread'])) for r in rows]
    def distribution(e):
        return dict(mae=mean([abs(v) for v in e]), rmse=math.sqrt(mean([v*v for v in e])),
                    mean_signed_error_actual_minus_prediction=mean(e), median_absolute_error=statistics.median(abs(v) for v in e),
                    error_sample_sd=statistics.stdev(e) if len(e)>1 else None,
                    **{f'fraction_errors_gt_{k}': mean([abs(v)>k for v in e]) for k in (10,20,30)})
    differences = [abs(a)-abs(b) for a,b in zip(error, baseline)]
    squared = [a*a-b*b for a,b in zip(error, baseline)]
    rng = random.Random(20261116)
    game_samples = [mean(rng.choices(differences, k=len(rows))) for _ in range(draws)]
    week = defaultdict(list)
    for r, d in zip(rows, differences):
        week[int(r['week'])].append(d)
    block = []
    if len(week) > 1:
        for _ in range(draws):
            block.append(mean([d for w in rng.choices(sorted(week), k=len(week)) for d in week[w]]))
    interval = lambda values:[percentile(values,.025), percentile(values,.975)] if values else [None,None]
    return dict(n=len(rows), weeks=len(week), model=distribution(error), locked_line=distribution(baseline),
                paired_mae_difference_model_minus_line=mean(differences), paired_mse_difference_model_minus_line=mean(squared),
                game_bootstrap_mae_difference95=interval(game_samples), week_block_bootstrap_mae_difference95=interval(block),
                bootstrap_draws=draws, seed=20261116,
                caveat='Within-week game resampling does not account for repeated teams. Week-block interval uses all games within resampled weeks; a single week cannot estimate week-level uncertainty.')


def calibration(rows, layer):
    group = [dict(r) for r in rows]
    if layer == 'GOVERNED_ATS':
        for r in group:
            r['uncertainty_points'] = r.get('production_uncertainty_points')
    return [dict(layer=layer, confidence=confidence, **summary([r for r in group if int(r['confidence']) == confidence])) for confidence in range(1,6)]


def discrimination(rows, field='selected_forecast_edge'):
    group = [r for r in rows if r['result'] != 'PUSH']
    return dict(n=len(group), score=field, auc=auc([float(r[field]) for r in group], [int(r['result']=='WIN') for r in group]),
                status='DESCRIPTIVE_NOT_VALIDATION')


def historical_human(rows):
    lookup = {(int(r['week']),r['market'],r['game_id']):r for r in rows}
    result = []
    for week, version in ((9,'v1'), (10,'v2')):
        members = read_csv(ROOT / f'outputs/2026-week{week}-postgame-audit/{version}/frozen_cohort_membership.csv')
        names = sorted({r['cohort'] for r in members if r['cohort'].startswith('HUMAN_') and r['cohort'].endswith('_1-5')})
        if not names:
            continue
        # Latest pregame version only: repeated revisions must not inflate calibration sample.
        for m in [r for r in members if r['cohort'] == names[-1]]:
            result.append(dict(lookup[week,m['market'],m['game_id']], confidence=int(m['human_confidence']),
                               source_review=m['source_review'], human_cohort=m['cohort']))
    return result
