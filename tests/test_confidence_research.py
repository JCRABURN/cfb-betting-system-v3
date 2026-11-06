"""Research integrity and leakage tests, separate from all production policy."""
import copy
import hashlib
import json
import shutil
import pytest
from research.confidence_rebuild import data
from research.confidence_rebuild.engine import Fit, Ridge, select
from research.confidence_rebuild.metrics import auc, summarize, top5, wilson
from research.confidence_rebuild.run import analyze, canonical, prospective, replay
from research.confidence_rebuild.verify import verify_holdout


@pytest.fixture(scope='module')
def pack():
    return data.load()


@pytest.fixture(scope='module')
def fitted(pack):
    rows, protocol = pack
    return Fit([r for r in rows if r['week'] == 5 and r['market'] == 'ATS'], 6, protocol)


def test_exact_pack_counts_and_no_week10_results(pack):
    rows, _ = pack
    assert len(rows) == 672
    assert all(r['actual'] is None and r['result'] is None for r in rows if r['week'] == 10)
    assert all(r['personnel_features'] == 'UNAVAILABLE_NOT_IMPUTED' for r in rows)


@pytest.mark.parametrize('mutation', ['line', 'forecast', 'result', 'future', 'duplicate', 'missing', 'prospective_score'])
def test_reject_corrupt_observations(pack, mutation):
    rows = copy.deepcopy(pack[0])
    if mutation == 'line': rows[0]['market_forecast'] += 1
    if mutation == 'forecast': rows[0]['forecast'] += 1
    if mutation == 'result': rows[0]['result'] = 'PUSH'
    if mutation == 'future': rows[0]['source_stats_through_week'] = rows[0]['week']
    if mutation == 'duplicate': rows.append(copy.deepcopy(rows[0]))
    if mutation == 'missing': rows.pop(0)
    if mutation == 'prospective_score': next(r for r in rows if r['week'] == 10)['actual'] = 42
    with pytest.raises(ValueError): data.validate_rows(rows)


@pytest.mark.parametrize('mutation', ['source_byte', 'missing_checksum', 'changed_hash', 'extra_source', 'status'])
def test_custody_fail_closed(tmp_path, monkeypatch, mutation):
    copied = tmp_path/'pack'
    shutil.copytree(data.HERE, copied)
    if mutation == 'source_byte':
        source = next((copied/'sources').glob('*.gz'))
        source.write_bytes(source.read_bytes()+b'altered')
    elif mutation == 'extra_source': (copied/'sources/extra.gz').write_bytes(b'unknown')
    elif mutation == 'status':
        obj = json.loads((copied/'protocol.json').read_bytes()); obj['status'] = 'APPROVED'
        (copied/'protocol.json').write_text(json.dumps(obj))
    else:
        obj = json.loads((copied/'input_seal.json').read_bytes())
        if mutation == 'missing_checksum': obj['sha256'].pop('observations.json')
        else: obj['sha256']['observations.json'] = '0'*64
        (copied/'input_seal.json').write_text(json.dumps(obj))
    monkeypatch.setattr(data, 'HERE', copied)
    with pytest.raises(ValueError): data.load()


def test_same_week_and_future_training_rejected(pack):
    rows, protocol = pack
    for target in (4, 5):
        with pytest.raises(ValueError): Fit([rows[0]], target, protocol)
    with pytest.raises(ValueError): Fit([r for r in rows if r['week'] == 10], 11, protocol)


def test_test_outcomes_cannot_change_forecast_or_ranking(pack, fitted):
    row = copy.deepcopy(next(r for r in pack[0] if r['week'] == 6 and r['market'] == 'ATS'))
    changed = dict(row, actual=10000, result='WIN', cover=10000)
    for candidate in pack[1]['candidates']:
        before, after = fitted.predict(row, candidate), fitted.predict(changed, candidate)
        for key in ('candidate_forecast', 'candidate_sign', 'probability', 'ranking_score', 'candidate_sigma', 'interval_radii'):
            assert before[key] == after[key]


def test_missing_features_fail_visibly(pack, fitted):
    row = copy.deepcopy(next(r for r in pack[0] if r['week'] == 6 and r['market'] == 'ATS'))
    del row['features']['plays_per_drive']
    with pytest.raises(KeyError): fitted.predict(row, 'MARKET_RESIDUAL_RIDGE')


def test_shrinkage_cannot_create_betting_improvement(pack, fitted):
    rows = [r for r in pack[0] if r['week'] == 6 and r['market'] == 'ATS']
    original = [fitted.predict(r, 'FROZEN_V28') for r in rows]
    shrunk = [fitted.predict(r, 'FIXED_25_PERCENT_MODEL') for r in rows]
    assert [r['game_id'] for r in top5(original, 'ATS')] == [r['game_id'] for r in top5(shrunk, 'ATS')]
    assert [r['candidate_result'] for r in original] == [r['candidate_result'] for r in shrunk]
    assert all(a['forecast'] == b['forecast'] for a, b in zip(original, shrunk))


def test_line_baseline_is_not_a_wager(pack, fitted):
    rows = [fitted.predict(r, 'LOCKED_LINE') for r in pack[0] if r['week'] == 6 and r['market'] == 'ATS']
    metrics = summarize(rows, pack[1]['probability_bins'])
    assert metrics['bets'] == 0 and metrics['units_minus110'] == 0 and metrics['hit_rate'] is None
    assert select(rows) == []


def test_metrics_known_values():
    assert auc([.1, .9], [0, 1]) == 1
    assert auc([.5, .5], [0, 1]) == .5
    assert auc([.1, .9], [1, 0]) == 0
    lo, hi = wilson(10, 20)
    assert lo < .5 < hi
    assert wilson(0, 0) == [None, None]
    fit = Ridge([[0], [1], [2]], [1, 3, 5], 0)
    assert fit.predict([3]) == pytest.approx(7, abs=1e-12)


def test_no_duplicate_game_in_combined_selection():
    rows = [dict(game_id=str(i//2), market=('ATS' if i%2 else 'TOTAL'), candidate_sign=1,
                 ranking_score=1-i/100, locked_line_id=i) for i in range(14)]
    selected = select(rows)
    assert len(selected) == len({r['game_id'] for r in selected}) == 5


def test_sealed_holdout_replay_and_no_overwrite():
    assert verify_holdout()['candidate_rows'] == 798
    with pytest.raises(ValueError, match='exists'): prospective(data.HERE/'holdout/20261106-v1')


def test_holdout_line_replacement_and_approval_rejected(tmp_path):
    src = data.HERE/'holdout/20261106-v1'
    for field, value in [('policy_changed', True), ('owner_approval', 'APPROVED')]:
        obj = json.loads((src/'prospective.json').read_bytes()); obj[field] = value
        (tmp_path/'prospective.json').write_text(json.dumps(obj))
        shutil.copyfile(src/'seal.json', tmp_path/'seal.json')
        with pytest.raises(ValueError): verify_holdout(tmp_path)
    obj = json.loads((src/'prospective.json').read_bytes()); obj['selections'][0]['line'] += 1
    (tmp_path/'prospective.json').write_text(json.dumps(obj))
    with pytest.raises(ValueError): verify_holdout(tmp_path)


def test_full_chronological_replay_is_read_only():
    target = data.HERE/'results/v1/results.json'
    before = hashlib.sha256(target.read_bytes()).hexdigest()
    analyze(target.parent, verify=True)
    assert hashlib.sha256(target.read_bytes()).hexdigest() == before


def test_supplement_and_original_combined_cohorts():
    from research.confidence_rebuild.supplement import build, artifacts
    from research.confidence_rebuild.cohorts import verify
    assert verify() == {str(w): 5 for w in range(5, 11)}
    for name, raw in artifacts(build()).items():
        assert (data.HERE/'results/v1'/name).read_bytes() == raw


def test_material_metric_change_rejected_without_overwrite(tmp_path, monkeypatch):
    from research.confidence_rebuild import run
    archived = json.loads((data.HERE/'results/v1/results.json').read_bytes())
    # This isolated corruption test reuses the already-verified expensive
    # stability result; the complete replay test above computes it independently.
    monkeypatch.setattr(run, 'stability', lambda *args: archived['selection_stability'])
    archived['summaries'][0]['mae'] += .1
    path = tmp_path/'results.json'
    path.write_text(json.dumps(archived), encoding='utf-8')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='replay mismatch'): analyze(tmp_path, verify=True)
    assert path.read_bytes() == before


def test_rendered_tables_match_recorded_results():
    from research.confidence_rebuild.tables import render
    assert (data.HERE/'TABLES.md').read_bytes().replace(b'\r\n', b'\n') == render().encode()


def test_failed_command_is_not_a_successful_verification(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from research.confidence_rebuild import capture_verification as capture
    monkeypatch.setattr(capture.subprocess, 'check_output', lambda *a, **k: 'TEST_SOURCE_ONLY\n')
    monkeypatch.setattr(capture.subprocess, 'run', lambda *a, **k: SimpleNamespace(stdout=b'failure fixture', stderr=b'', returncode=1))
    assert capture.capture(tmp_path/'receipt') == 'FAIL'
    receipt = json.loads((tmp_path/'receipt/receipt.json').read_bytes())
    assert receipt['database_before'] == receipt['database_after']
    assert all(c['exit_code'] == 1 for c in receipt['commands'])
    with pytest.raises(ValueError): capture.capture(tmp_path/'receipt')
