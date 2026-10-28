"""Verify a separate owner-review artifact against the immutable research board."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
from scripts.review_week9_context import ROOT, BOARD, instant
from scripts.seal_week9_board import main as verify_board

def validate(review):
    verify_board(True)
    seal = BOARD / 'week9_initial_seal_manifest.json'
    if review['sealed_board_sha256'] != hashlib.sha256(seal.read_bytes()).hexdigest():
        raise ValueError('review seal mismatch')
    if review['owner_approval'] != 'PENDING' or review['model_policy_changed']:
        raise ValueError('review cannot fabricate approval or policy change')
    locked = {g['game_id']: g for g in json.loads((BOARD/'week9_locked_line_snapshot.json').read_text())['lines']}
    boards = {}
    for market, filename in [('ATS','week9_ats_research_full_board.csv'),('TOTAL','week9_totals_research_full_board.csv')]:
        boards[market] = {int(r['game_id']):r for r in csv.DictReader((BOARD/filename).open(encoding='utf-8'))}
    rows = review['selections']
    if len(rows) != 10 or len({r['game_id'] for r in rows}) != 10:
        raise ValueError('shortlist coverage or duplicate')
    for rank, row in enumerate(rows, 1):
        if row['owner_review_rank'] != rank or row['recommended_five'] != (rank <= 5):
            raise ValueError('review rank or five membership')
        if not 1 <= row['human_review_confidence_1_to_5'] <= 5 or row['numeric_projection_adjustment'] != 0 or row['owner_approval'] != 'PENDING':
            raise ValueError('confidence adjustment or approval')
        cutoff = instant(locked[row['game_id']]['source_kickoff_utc'])
        created = instant(row['created_at_utc'])
        if created != instant(review['created_at_utc']) or created >= cutoff:
            raise ValueError('late recommendation')
        for source in row['sources']:
            if source.get('captured_at_utc') and instant(source['captured_at_utc']) > created:
                raise ValueError('future evidence')
        original = boards[row['market']][row['game_id']]
        is_ats = row['market'] == 'ATS'
        mapping = {'locked_line':'pick_spread' if is_ats else 'locked_total',
                   'frozen_projection_home_margin_or_total':'projected_home_margin' if is_ats else 'projected_total',
                   'frozen_confidence':'confidence',
                   'original_market_research_rank':'ats_research_rank' if is_ats else 'totals_research_rank',
                   'research_score_not_calibrated':'ats_shadow_score_not_calibrated' if is_ats else 'raw_selected_probability'}
        for target, field in mapping.items():
            if float(row[target]) != float(original[field]):
                raise ValueError('frozen value mismatch: '+target)
        edge = abs(float(original['home_ats_edge' if is_ats else 'raw_point_edge']))
        if row['selected_forecast_edge'] != edge or row['selection'] != original['pick'] or any(row[k] != original[k] for k in ('away','home')):
            raise ValueError('selection identity or edge mismatch')
    return {'verified_candidates':10,'recommended_five':5,'owner_approval':'PENDING','frozen_values_unchanged':True}

def main(path):
    return validate(json.loads(Path(path).read_text(encoding='utf-8')))

if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('path',type=Path)
    print(json.dumps(main(parser.parse_args().path),indent=2))
