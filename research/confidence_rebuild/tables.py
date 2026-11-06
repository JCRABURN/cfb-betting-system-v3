"""Render recorded research metrics without fitting or changing any candidate."""
import argparse
import json
from .data import HERE


def render():
    r = json.loads((HERE/'results/v1/results.json').read_bytes())
    s = json.loads((HERE/'results/v1/supplement.json').read_bytes())
    lines = ['# Recorded research tables', '', 'RESEARCH ONLY. Chronological evaluation: Weeks 6–9, 223 games per market; Week 5 seeds training. Units risk 1 to win 10/11. No pushes in this sample.', '']
    def table(title, columns, records):
        lines.extend(['## '+title, '', '| '+' | '.join(label for label, key in columns)+' |', '| '+' | '.join('---' for _ in columns)+' |'])
        for row in records:
            values = [row.get(key) for _, key in columns]
            lines.append('| '+' | '.join('—' if v is None else f'{v:.4f}' if isinstance(v, float) else str(v) for v in values)+' |')
        lines.append('')
    table('Full card', [('Market','market'),('Candidate','candidate'),('W','wins'),('L','losses'),('Hit','hit_rate'),('Units','units_minus110'),('MAE','mae'),('RMSE','rmse'),('AUC','auc'),('Brier','brier'),('ECE','ece')], r['summaries'])
    table('Top 5 per week', [('Scope','scope'),('Candidate','candidate'),('W','wins'),('L','losses'),('Hit','hit_rate'),('Units','units_minus110'),('Wilson95','wilson95')], r['top5'])
    table('Paired combined Top 5 gain versus frozen research ordering', [('Candidate','candidate'),('Unit gain','total_unit_difference'),('Four-week block95','paired_week_block95')], [x for x in r['paired_top5_gains'] if x['scope']=='COMBINED'])
    table('Original confidence, Weeks 5–9 (279 per market)', [('Market','market'),('Confidence','confidence'),('N','n'),('W','wins'),('L','losses'),('Hit','hit_rate'),('Units','units_minus110'),('Wilson95','wilson95')], [x for x in r['original_confidence'] if x['weeks']=='5-9'])
    table('Nonoverlapping ranks', [('Market','market'),('Candidate','candidate'),('Segment','segment'),('N','n'),('W','wins'),('L','losses'),('Units','units_minus110')], s['nonoverlapping_segments'])
    table('Probability reliability (proposed probabilities, not authorized Confidence labels)', [('Market','market'),('Candidate','candidate'),('Lower','lower'),('Upper','upper'),('N','n'),('Mean p','mean_probability'),('Observed hit','hit_rate'),('Wilson95','wilson95')], [dict(b,market=x['market'],candidate=x['candidate']) for x in r['summaries'] for b in x['reliability']])
    table('Interval coverage (empirical prior-error radii, no guaranteed coverage)', [('Market','market'),('Candidate','candidate'),('Coverage 80/90','interval_coverage'),('Mean width 80/90','mean_interval_width')], r['summaries'])
    table('AUC uncertainty: four-week blocks, no multiplicity correction', [('Market','market'),('Candidate','candidate'),('AUC','auc'),('Block95','auc_week_block95')], r['summaries'])
    table('Combined selection membership stability (100 training-week resamples)', [('Week','week'),('Candidate','candidate'),('Mean Jaccard','mean_jaccard'),('Minimum','minimum_jaccard'),('Training clusters','training_week_clusters')], [x for x in r['selection_stability'] if x['scope']=='COMBINED'])
    table('Paired MAE difference from locked line; negative is better', [('Market','market'),('Candidate','candidate'),('Difference','paired_mae_difference_vs_line'),('Block95','paired_mae_difference_week_block95')], s['market_comparison'])
    return '\n'.join(lines)+'\n'


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--verify', action='store_true'); args = p.parse_args()
    path = HERE/'TABLES.md'; raw = render().encode()
    if args.verify:
        if path.read_bytes().replace(b'\r\n', b'\n') != raw: raise ValueError('table replay mismatch')
    else:
        with path.open('xb') as stream: stream.write(raw)
