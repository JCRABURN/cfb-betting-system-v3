import copy
import json
import shutil

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


CAPTURE = gate.PARENT / '20261111T151538Z-eligibility'
PINNED = {
    'capture-manifest.json': 'f3fe8d342262e1e16129a7c7c78ea371b44dd36a9ac393f646cd050168ea40dd',
    'cfbd.json.gz': '6ada3fef576ef5eeed895323ed6e6277ed7c76ab99929d930f10e78884277fdf',
    'espn.json.gz': '2cbf7de4239b745a838c980e0443ba66e735090f9fdd9c5898b7b75b777833a3',
    'eligibility.json': 'ffb50db8bc69947f1a504af035d98f442336b14fb5218a34fbaba1172aa51f00',
}


def test_frozen_live_snapshot_exact_custody_and_replay():
    assert {p.name for p in CAPTURE.iterdir()} == set(PINNED)
    assert {p.name: gate.digest(p.read_bytes()) for p in CAPTURE.iterdir()} == PINNED
    result = gate.verify(CAPTURE)
    assert result['upcoming_schedule_only'] == 64
    assert result['excluded_started_or_elapsed'] == 3
    assert result['blocked_provider_conflict'] == 0
    assert all(r['espn_state'] == 'post' and r['cfbd_completed'] for r in result['games']
               if r['eligibility'].startswith('EXCLUDED'))


@pytest.mark.parametrize('mutation', ['checksum_entry', 'raw_byte', 'status', 'future_receipt',
                                   'parameters', 'extra_file', 'output_line', 'output_eligibility'])
def test_capture_replay_rejects_adversarial_mutations(tmp_path, mutation):
    folder = tmp_path / 'copy'
    shutil.copytree(CAPTURE, folder)
    manifest_path = folder / 'capture-manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    if mutation == 'checksum_entry':
        del manifest['records'][0]['stored_sha256']
    elif mutation == 'raw_byte':
        path = folder / 'cfbd.json.gz'
        raw = path.read_bytes()
        path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    elif mutation == 'status':
        manifest['predictions_generated'] = True
    elif mutation == 'future_receipt':
        manifest['records'][0]['received_at_utc'] = '2026-11-20T00:00:00Z'
    elif mutation == 'parameters':
        manifest['records'][0]['parameters']['week'] = 10
    elif mutation == 'extra_file':
        (folder / 'extra.json').write_bytes(b'{}')
    else:
        path = folder / 'eligibility.json'
        ledger = json.loads(path.read_bytes())
        if mutation == 'output_line':
            ledger['games'][0]['original_total'] = '99.5'
        else:
            ledger['games'][0]['model_eligible'] = True
        path.write_bytes(gate.serialized(ledger))
    manifest_path.write_bytes(gate.serialized(manifest))
    with pytest.raises((ValueError, KeyError, OSError)):
        gate.verify(folder)
