"""Descriptive supplements. No candidate, tuning, or prospective output changes."""
import argparse
import csv
import io
import itertools
import json
import math
from pathlib import Path
from .data import HERE, load
from .engine import mean, select
from .metrics import summarize, percentile, wilson
from .run import canonical, replay


def paired_error_ci(model, baseline):
    weeks = sorted({r['week'] for r in model})
    reference = {(r['week'], r['game_id']): r for r in baseline}
    groups = {w: [abs(r['actual']-r['candidate_forecast'])-
                  abs(reference[w, r['game_id']]['actual']-reference[w, r['game_id']]['candidate_forecast'])
                  for r in model if r['week'] == w] for w in weeks}
    samples = [mean([d for w in draw for d in groups[w]]) for draw in itertools.product(weeks, repeat=len(weeks))]
    return [percentile(samples, .025), percentile(samples, .975)]


def build():
    rows, protocol = load()
    predicted, _, fits = replay(rows, protocol)
    result = {'status': 'DESCRIPTIVE_RESEARCH_ONLY_NO_NEW_CANDIDATES', 'prior_only_base_rate': [],
              'forecast_error_decomposition': [], 'nonoverlapping_segments': [], 'rank_overlap': [],
              'governed_ats_top5': [], 'threshold_counts': {}, 'market_comparison': []}
    bins = protocol['probability_bins']
    for market in protocol['markets']:
        frozen = [r for r in predicted if r['market'] == market and r['candidate'] == 'FROZEN_V28']
        line = [r for r in predicted if r['market'] == market and r['candidate'] == 'LOCKED_LINE']
        base = []
        for row in frozen:
            train = fits[row['week'], market].train
            decided = [r for r in train if r['result'] != 'PUSH']
            probability = (sum(r['result'] == 'WIN' for r in decided)+1)/(len(decided)+2)
            base.append(dict(row, probability=probability))
        result['prior_only_base_rate'].append(dict(market=market, smoothing='(prior wins+1)/(prior decided+2)', **summarize(base, bins)))
        gaps = [r['forecast']-r['market_forecast'] for r in frozen]
        residuals = [r['actual']-r['market_forecast'] for r in frozen]
        result['forecast_error_decomposition'].append(dict(market=market, n=len(frozen),
            mse_model_minus_line=mean([d*d-2*d*e for d, e in zip(gaps, residuals)]),
            mean_squared_model_gap=mean([d*d for d in gaps]),
            twice_mean_gap_times_market_residual=2*mean([d*e for d, e in zip(gaps, residuals)]),
            meaning='Extra model displacement is not offset by sufficient directional alignment with actual-minus-line residuals. This does not identify a causal missing feature.'))
        for name in protocol['candidates']:
            group = [r for r in predicted if r['market'] == market and r['candidate'] == name]
            result['market_comparison'].append(dict(market=market, candidate=name,
                paired_mae_difference_vs_line=summarize(group, bins)['mae']-summarize(line, bins)['mae'],
                paired_mae_difference_week_block95=paired_error_ci(group, line)))
            if name == 'LOCKED_LINE': continue
            segments = [[], [], []]
            for week in protocol['evaluation_weeks']:
                weekly = [r for r in group if r['week'] == week]
                ordered = select(weekly, n=len(weekly), original=name in ('FROZEN_V28', 'FIXED_25_PERCENT_MODEL'))
                for i, segment in enumerate((ordered[:5], ordered[5:10], ordered[10:])): segments[i] += segment
            for label, segment in zip(('1-5', '6-10', '11-rest'), segments):
                result['nonoverlapping_segments'].append(dict(market=market, candidate=name, segment=label, **summarize(segment, bins)))
        if market == 'ATS':
            governed = [r for r in frozen if r['governed_top5']]
            result['governed_ats_top5'].append(dict(weeks='6-9', **summarize(governed, bins)))
    for week in protocol['evaluation_weeks']:
        original = select([r for r in predicted if r['week'] == week and r['candidate'] == 'FROZEN_V28'])
        base = {(r['game_id'], r['market'], r['candidate_sign']) for r in original}
        for name in protocol['candidates']:
            if name == 'LOCKED_LINE': continue
            selected = select([r for r in predicted if r['week'] == week and r['candidate'] == name])
            keys = {(r['game_id'], r['market'], r['candidate_sign']) for r in selected}
            result['rank_overlap'].append(dict(week=week, candidate=name, same_selections=len(keys & base),
                                               jaccard=len(keys & base)/len(keys | base), includes_direction=True))
    for label in ('confidence3', 'confidence4', 'confidence5'):
        gate = protocol['gates'][label]; n = gate['bucket_min_decided']
        wins = next(w for w in range(n+1) if wilson(w, n)[0] > gate['wilson95_lower_min'])
        result['threshold_counts'][label] = dict(minimum_n=n, minimum_wins_for_wilson_gate=wins,
                                                observed_rate=wins/n, gate=gate, authorized=False)
    return canonical(result)


def artifacts(supplement):
    results = json.loads((HERE/'results/v1/results.json').read_bytes())
    files = {'supplement.json': (json.dumps(supplement, indent=2, sort_keys=True)+'\n').encode()}
    for filename, records in [('full_card.csv', results['summaries']), ('top5.csv', results['top5']),
                              ('confidence.csv', results['original_confidence']), ('segments.csv', supplement['nonoverlapping_segments'])]:
        columns = [k for k, v in records[0].items() if not isinstance(v, (list, dict))]
        stream = io.StringIO(newline=''); writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n', extrasaction='ignore')
        writer.writeheader(); writer.writerows(records); files[filename] = stream.getvalue().encode()
    return files


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--verify', action='store_true'); args = parser.parse_args()
    for filename, raw in artifacts(build()).items():
        path = HERE/'results/v1'/filename
        if args.verify:
            if path.read_bytes() != raw: raise ValueError('supplement replay mismatch: '+filename)
        else:
            with path.open('xb') as stream: stream.write(raw)
    print('SUPPLEMENT_VERIFIED' if args.verify else 'SUPPLEMENT_WRITTEN')
