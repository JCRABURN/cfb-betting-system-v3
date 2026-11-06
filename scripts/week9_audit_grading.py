"""Independent decimal grading and frozen-cohort reconciliation; no model writes."""
from __future__ import annotations

from decimal import Decimal

from scripts.week9_audit_sources import BOARD, PRELIMINARY, ROOT, read_csv, read_json, unique
from scripts.week5_postgame_core import classify_late_score
from scripts.week8_scoring_sequence_review import validate_sequence
from scripts.verify_week9_owner_review import validate as validate_review


def decimal(value) -> Decimal:
    if isinstance(value, bool):
        raise ValueError('boolean numeric value')
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('nonfinite numeric value')
    return result


def grade(cover: Decimal) -> str:
    return 'WIN' if cover > 0 else 'LOSS' if cover < 0 else 'PUSH'


def spread_bucket(value) -> str:
    value = abs(decimal(value))
    return '0-2.5' if value < 3 else '3-6.5' if value < 7 else '7-13.5' if value < 14 else '14-20.5' if value < 21 else '21+'


def total_bucket(value) -> str:
    value = decimal(value)
    return '<50' if value < 50 else '50-59.5' if value < 60 else '60-69.5' if value < 70 else '70+'


def grade_selection(row: dict, market: str, final: dict, lock: dict) -> dict:
    if row['away'] != final['away'] or row['home'] != final['home'] or int(row['game_id']) != int(lock['game_id']):
        raise ValueError('grade identity mismatch')
    if market == 'ATS':
        if row['selected_side'] not in ('home', 'away') or row['pick'] != row[row['selected_side']]:
            raise ValueError('invalid ATS selection')
        home_line = decimal(row['locked_home_spread'])
        if home_line != decimal(lock['home_spread']):
            raise ValueError('unauthorized home line replacement')
        line = decimal(row['pick_spread'])
        if line != home_line * (1 if row['selected_side'] == 'home' else -1):
            raise ValueError('unauthorized selected line replacement')
        actual = final['home_score'] - final['away_score']
        cover = decimal(actual) * (1 if row['selected_side'] == 'home' else -1) + line
        projection = row['projected_home_margin']
        if decimal(row['context_adjustment_points']) != 0 or decimal(row['adjusted_home_margin']) != decimal(projection):
            raise ValueError('unexpected historical manual adjustment')
        score, rank = row['ats_shadow_score_not_calibrated'], row['ats_research_rank']
        location = 'NEUTRAL' if final['neutral_site'] else row['selected_side'].upper()
        favorite = 'FAVORITE' if line < 0 else 'UNDERDOG' if line > 0 else 'PICKEM'
        edge = abs(decimal(projection) + home_line)
    elif market == 'TOTAL':
        if row['pick'] not in ('over', 'under'):
            raise ValueError('invalid total selection')
        line = decimal(row['locked_total'])
        if line != decimal(lock['locked_total']):
            raise ValueError('unauthorized total replacement')
        actual = final['home_score'] + final['away_score']
        cover = (decimal(actual) - line) * (1 if row['pick'] == 'over' else -1)
        projection = row['projected_total']
        score, rank = row['raw_selected_probability'], row['totals_research_rank']
        location = favorite = 'NOT_APPLICABLE'
        edge = abs(decimal(projection) - line)
    else:
        raise ValueError('unknown market')
    confidence = int(row['confidence'])
    if not 1 <= confidence <= 5:
        raise ValueError('confidence bounds')
    outcome = grade(cover)
    return dict(week=9, game_id=row['game_id'], market=market, away=row['away'], home=row['home'],
                selection=row['pick'], locked_line=str(line), raw_projection=projection,
                actual_model_target=actual, away_score=final['away_score'], home_score=final['home_score'],
                result=outcome, cover_margin=str(cover), forecast_error_actual_minus_predicted=str(decimal(actual) - decimal(projection)),
                hypothetical_units_minus110='10/11' if outcome == 'WIN' else '-1' if outcome == 'LOSS' else '0',
                confidence=confidence, research_rank=int(rank), research_score_not_calibrated=score,
                selected_forecast_edge=str(edge), uncertainty_points=row['shadow_uncertainty_points' if market == 'ATS' else 'uncertainty_points'],
                selected_side=row.get('selected_side', ''), locked_home_spread=row.get('locked_home_spread', ''),
                governed_top5=row.get('top_five', 'False'), governed_rank=row.get('rank', ''),
                location=location, favorite_dog=favorite, road_favorite=(location == 'AWAY' and favorite == 'FAVORITE'),
                spread_or_total_bucket=spread_bucket(line) if market == 'ATS' else total_bucket(line),
                raw_result=outcome, manual_adjustment_points='0', adjusted_projection=projection,
                qualified_closing_line=None, qualified_clv=None, clv_status='INCOMPLETE',
                key_number_crossing='UNVERIFIABLE_NO_QUALIFIED_CLOSE', owner_approval='PENDING')


def build_grades(finals, data):
    locks = unique(read_json(BOARD / 'week9_locked_line_snapshot.json')['lines'])
    final_by_id = unique(finals)
    grades, comparisons, sequences = [], [], []
    for market, name in [('ATS', 'ats'), ('TOTAL', 'totals')]:
        card = read_csv(BOARD / f'week9_{name}_full_card.csv')
        prior = unique(read_csv(PRELIMINARY / f'week9_{name}_grades_preliminary.csv'))
        if set(prior) != set(final_by_id):
            raise ValueError('preliminary grade coverage mismatch')
        for row in sorted(card, key=lambda x: x['game_id']):
            gid = row['game_id']
            final = final_by_id[gid]
            result = grade_selection(row, market, final, locks[gid])
            plays = data['espn-' + gid].get('scoringPlays', [])
            try:
                validate_sequence(plays, final['away_score'], final['home_score'])
                sequence_status = 'VALIDATED'
            except (ValueError, KeyError, TypeError):
                sequence_status = 'UNAVAILABLE_OR_CONTRADICTORY'
            result['scoring_sequence_status'] = sequence_status
            boundary = abs(decimal(result['cover_margin'])) == Decimal('0.5') and abs(decimal(result['locked_line'])) % 1 == Decimal('0.5')
            result['hook_classification'] = ('WINNING_HOOK' if result['result'] == 'WIN' else 'LOSING_HOOK') if boundary and sequence_status == 'VALIDATED' else 'UNVERIFIABLE' if boundary else 'NOT_APPLICABLE'
            result['key_number_near_3_or_7'] = bool(market == 'ATS' and any(abs(abs(decimal(result['locked_line'])) - k) <= Decimal('.5') for k in (3, 7)))
            late = classify_late_score(plays, row['selected_side'], row['locked_home_spread'], final['away_score'], final['home_score']) if market == 'ATS' and sequence_status == 'VALIDATED' else {'classification': 'NOT_APPLICABLE_TOTAL' if market == 'TOTAL' else 'UNVERIFIABLE'}
            result['backdoor_status'] = late['classification']
            if market == 'ATS':
                sequences.append(dict(game_id=gid, sequence_status=sequence_status, source_sha256=final['espn_raw_sha256'], **late))
            result['failure_taxonomy'] = 'NO_SELECTION_LOSS' if result['result'] != 'LOSS' else 'FORECAST_SELECTION_LOSS;CAUSAL_ATTRIBUTION_NOT_ESTABLISHED'
            before = prior[gid]
            line_key = 'locked_pick_spread' if market == 'ATS' else 'locked_total'
            error_key = 'home_margin_forecast_error' if market == 'ATS' else 'total_forecast_error'
            matches = dict(grade=before['grade'] == result['result'],
                           line=decimal(before[line_key]) == decimal(result['locked_line']),
                           cover=decimal(before['cover_margin']) == decimal(result['cover_margin']),
                           forecast_error_to_preliminary_six_decimals=decimal(before[error_key]) == decimal(result['forecast_error_actual_minus_predicted']).quantize(Decimal('.000001')))
            comparisons.append(dict(game_id=gid, market=market, matches=matches,
                                    preliminary_grade=before['grade'], independent_grade=result['result']))
            grades.append(result)
        if sorted(r['research_rank'] for r in grades if r['market'] == market) != list(range(1, 55)):
            raise ValueError('research rank coverage')
    return grades, comparisons, sequences


def cohort_membership(grades):
    by_key = {(r['market'], str(r['game_id'])): r for r in grades}
    members = []

    def add(cohort, row, rank, **metadata):
        members.append(dict(cohort=cohort, cohort_rank=rank, market=row['market'], game_id=row['game_id'],
                            selection=row['selection'], locked_line=row['locked_line'], result=row['result'],
                            confidence=row['confidence'], owner_approval='PENDING', **metadata))

    for row in grades:
        rank = row['research_rank']
        add(row['market'] + '_RESEARCH_' + ('1-5' if rank <= 5 else '6-10' if rank <= 10 else '11+'), row, rank)
        if row['governed_top5'] == 'True':
            add('GOVERNED_ATS_TOP5', row, int(row['governed_rank']))
    for r in read_csv(BOARD / 'week9_legacy_mixed_research_top5.csv'):
        row = by_key[(r['market'], r['game_id'])]
        if r['pick'] != row['selection'] or decimal(r['locked_line']) != decimal(row['locked_line']) or decimal(r['projection']) != decimal(row['raw_projection']):
            raise ValueError('mixed frozen cohort mismatch')
        add('ORIGINAL_COMBINED_RESEARCH_TOP5', row, int(r['rank']))
    for r in read_csv(BOARD / 'week9_human_review_shortlist.csv'):
        row = by_key[(r['market'], r['game_id'])]
        if r['selection'] != row['selection'] or decimal(r['locked_line']) != decimal(row['locked_line']):
            raise ValueError('initial candidate shortlist mismatch')
        add('INITIAL_FROZEN_TEN_CANDIDATES_NO_COMBINED_ORDER', row, int(r['within_market_rank']))
    reviews = sorted([(read_json(p), p) for p in (ROOT / 'outputs/2026-week9-owner-review').glob('*/owner_review_shortlist.json')], key=lambda pair: pair[0]['created_at_utc'])
    for review, path in reviews:
        validate_review(review)
        for r in review['selections']:
            row = by_key[(r['market'], str(r['game_id']))]
            add('HUMAN_' + path.parent.name + ('_1-5' if r['recommended_five'] else '_6-10'), row, r['owner_review_rank'],
                revision_created_at_utc=review['created_at_utc'], decision_created_at_utc=r['created_at_utc'],
                human_confidence=r['human_review_confidence_1_to_5'], frozen_original_market_rank=r['original_market_research_rank'],
                source_review=path.relative_to(ROOT).as_posix(), numeric_projection_adjustment=r['numeric_projection_adjustment'])
    return members
