import copy
import json

import pytest

from scripts import prepare_week11_readiness as readiness
from scripts import week11_eligibility as gate


@pytest.fixture
def inputs():
    _, _, data, _ = readiness.load()
    return [copy.deepcopy([g for g in data['cfbd-games-all'] if g['week'] == 11]),
            copy.deepcopy(data['espn-complete']),
            json.loads((readiness.OUT / 'schedule.json').read_bytes()),
            copy.deepcopy(gate.load_source()), '2026-11-11T15:00:00+00:00']


def target(inputs):
    upcoming = next(g for g in inputs[0] if readiness.timestamp(g['startDate']) > readiness.timestamp(inputs[-1])
                    and g['homeClassification'] == 'fbs')
    event = next(e for e in inputs[1]['events'] if e['id'] == str(upcoming['id']))
    return upcoming, event['competitions'][0]


def result_row(inputs, game):
    return next(r for r in gate.reconcile(*inputs)['games'] if r['game_id'] == str(game['id']))


def test_original_67_lines_remain_three_elapsed_never_create_picks(inputs):
    result = gate.reconcile(*inputs)
    assert result['source_rows'] == 67
    assert result['upcoming_schedule_only'] == 64
    assert result['excluded_started_or_elapsed'] == 3
    assert result['blocked_provider_conflict'] == 0
    assert not result['predictions_generated']
    assert all(r['model_eligible'] is False for r in result['games'])
    original = {r['game_id']: s for s, r in zip(inputs[3][0], inputs[3][3])}
    assert all((r['original_home_spread'], r['original_total']) ==
               (original[r['game_id']]['Spread'], original[r['game_id']]['Total']) for r in result['games'])


@pytest.mark.parametrize('mutation', ['missing_cfbd', 'missing_espn', 'duplicate', 'orientation',
                                   'classification', 'season', 'espn_week', 'unknown_state',
                                   'new_fbs_fcs', 'nonboolean_completed', 'source_line'])
def test_conflicting_identities_or_source_fail_closed(inputs, mutation):
    g, competition = target(inputs)
    if mutation == 'missing_cfbd':
        inputs[0].remove(g)
    elif mutation == 'missing_espn':
        inputs[1]['events'].pop()
    elif mutation == 'duplicate':
        inputs[0].append(copy.deepcopy(g))
    elif mutation == 'orientation':
        competition['competitors'][0]['team']['id'] = '999999'
    elif mutation == 'classification':
        g['awayClassification'] = 'fcs'
    elif mutation == 'season':
        g['season'] = 2025
    elif mutation == 'espn_week':
        inputs[1]['week']['number'] = 12
    elif mutation == 'unknown_state':
        competition['status']['type']['state'] = 'unknown'
    elif mutation == 'new_fbs_fcs':
        added = copy.deepcopy(g)
        added.update(id=9999999, awayClassification='fcs')
        inputs[0].append(added)
    elif mutation == 'nonboolean_completed':
        g['completed'] = 'false'
    elif mutation == 'source_line':
        inputs[3][0][0]['Spread'] = '999'
    with pytest.raises(ValueError):
        gate.reconcile(*inputs)


@pytest.mark.parametrize('mutation,reason', [
    ('changed_time', 'KICKOFF_CHANGED_OR_CONTRADICTORY'),
    ('tbd', 'KICKOFF_TBD'), ('cfbd_score', 'PREGAME_CFBD_SCORE'),
    ('espn_score', 'PREGAME_ESPN_SCORE'), ('postponed', 'NOT_CONFIRMED_SCHEDULED'),
])
def test_upcoming_conflicts_block_without_replacing_originals(inputs, mutation, reason):
    g, competition = target(inputs)
    if mutation == 'changed_time':
        g['startDate'] = '2026-11-15T00:00:00Z'
    elif mutation == 'tbd':
        g['startTimeTBD'] = True
    elif mutation == 'cfbd_score':
        g['homePoints'] = 7
    elif mutation == 'espn_score':
        competition['competitors'][0]['score'] = '7'
    elif mutation == 'postponed':
        competition['status']['type']['name'] = 'STATUS_POSTPONED'
    row = result_row(inputs, g)
    assert row['eligibility'] == 'BLOCKED_PROVIDER_CONFLICT'
    assert any(r.startswith(reason) for r in row['issues'])


@pytest.mark.parametrize('state', ['in', 'post'])
def test_started_provider_excludes_even_if_scheduled_time_is_future(inputs, state):
    g, competition = target(inputs)
    competition['status']['type'].update(state=state, completed=state == 'post')
    row = result_row(inputs, g)
    assert row['eligibility'].startswith('EXCLUDED')
    assert not row['model_eligible']
    if state == 'post':
        assert 'PROVIDER_COMPLETION_DISAGREEMENT' in row['issues']


def test_exact_kickoff_and_later_advertised_time_never_revive_elapsed_game(inputs):
    g, competition = target(inputs)
    inputs[-1] = g['startDate']
    assert result_row(inputs, g)['eligibility'].startswith('EXCLUDED')
    g['startDate'] = competition['date'] = '2026-11-20T00:00:00Z'
    assert result_row(inputs, g)['eligibility'].startswith('EXCLUDED')


def test_status_contradiction_never_becomes_eligible(inputs):
    g, competition = target(inputs)
    competition['status']['type']['completed'] = True
    row = result_row(inputs, g)
    assert row['eligibility'].startswith('EXCLUDED')
    assert 'ESPN_STATUS_CONTRADICTION' in row['issues']


def test_existing_directory_rejected_before_network(tmp_path):
    with pytest.raises(ValueError, match='never overwrite'):
        gate.capture(tmp_path)


def test_missing_image_custody_cannot_be_silently_upgraded(inputs):
    result = gate.reconcile(*inputs)
    assert result['original_images_verified'] == 0
    assert result['status'] == 'OBSERVATION_ONLY_IMAGE_CUSTODY_AND_EXECUTION_PENDING'
    assert result['model_input_use'].startswith('PROHIBITED')
