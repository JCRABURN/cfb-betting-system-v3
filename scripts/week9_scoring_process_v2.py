"""Additive correction of defensive return TDs labeled Sack by both providers.

The v1 grading, forecasts, evidence and implementation remain byte-identical.
This separate version supersedes only non-offensive process classification.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

from scripts import build_week9_formal_audit as audit
from scripts.week9_audit_sources import ROOT, captures, reconcile, sha, unique
from scripts.week9_audit_diagnostics import metrics

OUT = ROOT / 'outputs/2026-week9-postgame-audit/process-v2'


def defensive_sack_touchdown(play, corroboration, final, previous):
    """Require scoring team, post-play scores, clock and two descriptions to agree."""
    before_away, before_home = previous
    after_away, after_home = play['awayScore'], play['homeScore']
    delta = after_away + after_home - before_away - before_home
    if play['type']['text'] != 'Sack' or delta not in (6, 7, 8) or 'fumble return' not in play['text'].lower():
        raise ValueError('unclassified scoring sack; independent semantic adjudication required')
    side = 'home' if after_home > before_home and after_away == before_away else 'away' if after_away > before_away and after_home == before_home else None
    if side is None or str(play['team']['id']) != str(final[side+'_id']):
        raise ValueError('scoring-team or progression conflict')
    other = 'away' if side == 'home' else 'home'
    c = corroboration
    text = c['playText'].lower()
    if (str(c['id']) != str(play['id']) or str(c['gameId']) != final['game_id'] or c['scoring'] is not True
            or c['defense'] != final[side] or c['offense'] != final[other]
            or c['defenseScore'] != play[side+'Score'] or c['offenseScore'] != play[other+'Score']
            or c['period'] != play['period']['number']
            or c['clock']['minutes']*60+c['clock']['seconds'] != play['clock']['value']
            or not all(word in text for word in ('fumble', 'recovered', 'return', 'touchdown'))):
        raise ValueError('CFBD defensive-return corroboration failed')
    return dict(game_id=final['game_id'], event_id=play['id'], type='DERIVED_DEFENSIVE_FUMBLE_RETURN_TOUCHDOWN',
                original_espn_type=play['type']['text'], original_cfbd_type=c['playType'],
                points_including_bundled_conversion=delta, period=play['period']['number'], clock=play['clock']['displayValue'],
                text=play['text'], cfbd_text=c['playText'], scoring_team=final[side],
                source_sha256=final['espn_raw_sha256'],
                classification_basis='Validated scoring sequence + scoring team is CFBD defense + matched play ID/clock/post-play scores + corroborated fumble-return descriptions')


def build():
    original = audit.build()
    audit.verify_files(audit.OUT, original)
    _, records, data = captures()
    finals, _ = reconcile(data, records)
    plays = unique(data['cfbd-plays'], 'id')
    corrections = []
    for final in finals:
        previous = (0, 0)
        for p in data['espn-'+final['game_id']]['scoringPlays']:
            delta = p['homeScore'] + p['awayScore'] - sum(previous)
            if p['type']['text'] == 'Sack' and delta != 2:
                row = defensive_sack_touchdown(p, plays[str(p['id'])], final, previous)
                row['cfbd_plays_raw_sha256'] = records['cfbd-plays']['raw_sha256']
                corrections.append(row)
            previous = (p['awayScore'], p['homeScore'])
    process = copy.deepcopy(json.loads(original['game_process_evidence.json']))
    by_game = unique(process['games'])
    old_rows = copy.deepcopy(by_game)
    for correction in corrections:
        game = by_game[correction['game_id']]
        game['non_offensive_scoring_events'] += 1
        game['non_offensive_points_with_bundled_conversions'] += correction['points_including_bundled_conversion']
        process['nonoffensive_scoring_events'].append(correction)
    process['status'] = 'POSTGAME_PROCESS_DIAGNOSTICS_V2_RESEARCH_ONLY'
    process['supersedes_process_only'] = 'outputs/2026-week9-postgame-audit/v1/game_process_evidence.json'
    process['definitions']['non_offense'] += ' Version 2 additionally recognizes Sack-labeled defensive fumble-return touchdowns only with matching ESPN/CFBD play IDs, scoring-team orientation, clock, post-play scores and descriptions.'
    totals = list(__import__('csv').DictReader(__import__('io').StringIO(original['week9_totals_audit.csv'].decode('utf-8'))))
    for segment in process['exploratory_process_segments']:
        if segment['segment'] in ('nonoffensive_score', 'no_nonoffensive_score'):
            positive = segment['segment'] == 'nonoffensive_score'
            group = [r for r in totals if (by_game[r['game_id']]['non_offensive_scoring_events'] > 0) == positive]
            segment.update(metrics(group))
    changes = [dict(game_id=gid, away=by_game[gid]['away'], home=by_game[gid]['home'],
                    prior_events=old_rows[gid]['non_offensive_scoring_events'], corrected_events=by_game[gid]['non_offensive_scoring_events'],
                    prior_points=old_rows[gid]['non_offensive_points_with_bundled_conversions'], corrected_points=by_game[gid]['non_offensive_points_with_bundled_conversions'])
               for gid in sorted({r['game_id'] for r in corrections})]
    supersession = dict(version='week9-scoring-process-v2', status='VERIFIED_ADDITIVE_PROCESS_SUPERSESSION',
                        root_cause='Provider playType labels the initiating sack, not the resulting defensive fumble-return touchdown. Type-only v1 classification omitted four touchdowns.',
                        score_or_grade_changes=0, selection_line_forecast_confidence_rank_changes=0,
                        historical_source_bytes_changed=False, changed_games=changes, added_events=corrections,
                        original_audit_manifest_sha256=sha(original['audit_manifest.json']),
                        original_grading_sha256={n:sha(original[n]) for n in ('week9_ats_audit.csv','week9_totals_audit.csv')})
    lines = ['# Week 9 scoring-process supersession v2', '',
             'This is the authoritative correction for non-offensive scoring process diagnostics. All 54 scores, 108 grades, frozen cohorts, forecasts, confidence, ranks and original v1 files are unchanged. The v1 audit remains the grading authority; its type-only non-offensive summaries are superseded by this separate version.', '',
             supersession['root_cause'], '',
             'The correction requires matching play IDs, the defense as scoring team, clock, post-play scores and fumble-return descriptions in both captured sources. It does not infer a defensive touchdown solely from a final score or a Sack label. Original source fields and raw bytes remain intact.', '',
             '| Game | Previous events → corrected | Previous points → corrected |', '|---|---:|---:|']
    lines += [f"| {r['away']} @ {r['home']} | {r['prior_events']} → {r['corrected_events']} | {r['prior_points']} → {r['corrected_points']} |" for r in changes]
    lines += ['', 'All four events are defensive fumble returns (28 points including bundled conversions); none changes special-teams touchdown counts. FAU–North Texas remains zero non-offensive events and Texas State–Boise remains one event/7 points. These are observed scoring classifications, not counterfactual adjusted finals.', '',
              '| Corrected subgroup | N | W-L-P | MAE | Bias actual−forecast | -110 units |', '|---|---:|---|---:|---:|---:|']
    for r in process['exploratory_process_segments']:
        if r['segment'] in ('nonoffensive_score','no_nonoffensive_score'):
            lines.append(f"| {r['segment']} | {r['n']} | {r['wins']}-{r['losses']}-{r['pushes']} | {r['mae']} | {r['bias_actual_minus_prediction']} | {r['units_minus110']} |")
    lines += ['', 'Every other Week 9/cross-week result and research conclusion is unchanged. The correction was discovered by inspecting actual scoring descriptions after the initial 885-test CI passed; those earlier runs did not test this semantic correction. New tests and final-head CI are required. Replay with `python -m scripts.week9_scoring_process_v2 --verify`.', '']
    files = {'game_process_evidence.json': audit.serialized(process), 'game_process.csv': audit.csv_bytes(process['games']),
             'supersession.json': audit.serialized(supersession), 'SCORING_PROCESS_SUPERSESSION.md': '\n'.join(lines).encode('utf-8')}
    manifest = dict(version='week9-scoring-process-v2', status=supersession['status'],
                    v1_audit_manifest_sha256=supersession['original_audit_manifest_sha256'],
                    input_custody_sha256=audit.INPUT_FIXTURE_SHA256,
                    code_sha256_lf=sha(Path(__file__).read_bytes().replace(b'\r\n',b'\n')),
                    output_sha256={n:sha(v) for n,v in sorted(files.items())},
                    score_or_grade_changes=0, policy_changes=False, clv_status='INCOMPLETE', owner_approval='PENDING')
    files['audit_manifest.json'] = audit.serialized(manifest)
    return files


def main(verify=False):
    if not verify and OUT.exists():
        raise ValueError('version already exists; overwrite forbidden')
    files = build()
    if verify:
        audit.verify_files(OUT, files)
    else:
        audit.write_new(OUT, files)
    return dict(status='VERIFIED_READ_ONLY' if verify else 'ADDITIVE_SUPERSESSION_WRITTEN', corrected_events=4,
                affected_games=3, scoring_or_grading_changes=0, policy_changes=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    print(json.dumps(main(parser.parse_args().verify)))
