import copy
from datetime import datetime, timezone

import pytest

from scripts import seal_week11_board as board


def test_complete_128_selection_board_replays_without_policy_promotion():
    result = board.validate(sealed_at='2026-11-11T16:00:00+00:00')
    assert result['eligible_games'] == result['ats_selections'] == result['total_selections'] == 64
    assert result['excluded_elapsed_games'] == 3
    assert not result['model_policy_change']
    assert result['combined_top5'] == 'UNCALIBRATED_RESEARCH_ONLY'


@pytest.mark.parametrize('mutation', ['line', 'projection', 'confidence', 'missing', 'ranking', 'promote'])
def test_board_replay_rejects_material_or_selection_changes(monkeypatch, mutation):
    original = board.csv_rows
    def rows(name):
        result = copy.deepcopy(original(name))
        if name == 'week11_ats_full_card.csv':
            if mutation == 'line': result[0]['locked_home_spread'] = '99.5'
            elif mutation == 'projection': result[0]['projected_home_margin'] = str(float(result[0]['projected_home_margin']) + .001)
            elif mutation == 'confidence': result[0]['confidence'] = '5'
            elif mutation == 'missing': result.pop()
        if name == 'week11_ats_research_full_board.csv' and mutation == 'ranking': result.reverse()
        if name == 'week11_legacy_mixed_research_top5.csv' and mutation == 'promote': result[0]['status'] = 'APPROVED'
        return result
    monkeypatch.setattr(board, 'csv_rows', rows)
    with pytest.raises(ValueError):
        board.validate(sealed_at='2026-11-11T16:00:00+00:00')


def test_seal_at_kickoff_is_rejected():
    with pytest.raises(ValueError, match='pregame'):
        board.validate(sealed_at='2026-11-12T00:30:00+00:00')


def test_late_capture_explicitly_disqualifies_wednesday_pregame_seal():
    result = board.validate(sealed_at='2026-11-12T12:08:05+00:00', custody_mode='late_capture')
    assert result['status'] == 'LATE_CUSTODY_CAPTURE_NOT_FULL_PREGAME_SEAL'
    assert result['capture_after_recorded_kickoff_game_ids'] == ['401866461', '401866462', '401866463']
    assert result['capture_before_recorded_kickoff_count'] == 61
    assert not any(row['pregame_external_seal_proven'] for row in result['game_custody_timing'])


def test_unknown_mode_and_backdated_capture_fail_closed():
    with pytest.raises(ValueError, match='unknown custody'):
        board.validate(sealed_at='2026-11-12T12:08:05+00:00', custody_mode='APPROVED')
    with pytest.raises(ValueError, match='precedes card'):
        board.validate(sealed_at='2026-11-10T12:08:05+00:00', custody_mode='late_capture')
