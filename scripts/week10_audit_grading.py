"""Week10 decimal grades and exact frozen cohorts; no forecast generation."""
from decimal import Decimal
from scripts.week10_audit_sources import BOARD, ROOT, read_csv, read_json, unique
from scripts.week9_audit_grading import decimal, grade_selection
from scripts.week5_postgame_core import classify_late_score
from scripts.week8_scoring_sequence_review import validate_sequence
from scripts.verify_week10_owner_review import validate as validate_review

def build_grades(finals, data):
    locks = unique(read_json(BOARD / 'week10_locked_line_snapshot.json')['lines'])
    final_by_id = unique(finals)
    grades, comparisons, sequences = [], [], []
    for market, name in [('ATS', 'ats'), ('TOTAL', 'totals')]:
        card = read_csv(BOARD / f'week10_{name}_full_card.csv')
        for row in sorted(card, key=lambda x: x['game_id']):
            gid = row['game_id']
            final = final_by_id[gid]
            result = dict(grade_selection(row, market, final, locks[gid]), week=10)
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
            grades.append(result)
        if sorted(r['research_rank'] for r in grades if r['market'] == market) != list(range(1, 58)):
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
    for r in read_csv(BOARD / 'week10_legacy_mixed_research_top5.csv'):
        row = by_key[(r['market'], r['game_id'])]
        if r['pick'] != row['selection'] or decimal(r['locked_line']) != decimal(row['locked_line']) or decimal(r['projection']) != decimal(row['raw_projection']):
            raise ValueError('mixed frozen cohort mismatch')
        add('ORIGINAL_COMBINED_RESEARCH_TOP5', row, int(r['rank']))
    for r in read_csv(BOARD / 'week10_human_review_shortlist.csv'):
        row = by_key[(r['market'], r['game_id'])]
        if r['selection'] != row['selection'] or decimal(r['locked_line']) != decimal(row['locked_line']):
            raise ValueError('initial candidate shortlist mismatch')
        add('INITIAL_FROZEN_TEN_CANDIDATES_NO_COMBINED_ORDER', row, int(r['within_market_rank']))
    reviews = sorted([(read_json(p), p) for p in (ROOT / 'outputs/2026-week10-owner-review').glob('*/owner-review.json')], key=lambda pair: pair[0]['created_at_utc'])
    for review, path in reviews:
        validate_review(review)
        for r in review['selections']:
            row = by_key[(r['market'], str(r['game_id']))]
            add('HUMAN_' + path.parent.name + ('_1-5' if r['recommended_five'] else '_6-10'), row, r['owner_review_rank'],
                revision_created_at_utc=review['created_at_utc'], decision_created_at_utc=r['created_at_utc'],
                human_confidence=r['human_review_confidence_1_to_5'], frozen_original_market_rank=r['original_market_research_rank'],
                source_review=path.relative_to(ROOT).as_posix(), numeric_projection_adjustment=r['numeric_projection_adjustment'])
    return members
