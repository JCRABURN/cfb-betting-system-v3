"""Adversarial controls for the additive formal audit, not model-policy tests."""
import copy
import json
from decimal import Decimal

import pytest

from scripts import build_week9_formal_audit as audit
from scripts import week9_audit_sources as sources
from scripts.week9_audit_grading import build_grades, cohort_membership, decimal, grade_selection
from scripts.week9_audit_diagnostics import metrics, walk_forward
from scripts.week8_scoring_sequence_review import validate_sequence
from scripts.verify_week9_owner_review import validate as validate_review


@pytest.fixture(scope='module')
def captured():
    manifest, records, data = sources.captures()
    finals, supersession = sources.reconcile(data, records)
    return manifest, records, data, finals, supersession


@pytest.fixture(scope='module')
def built():
    return audit.build()


def test_full_offline_replay_and_exact_card_coverage(built):
    audit.verify_files(audit.OUT, built)
    manifest = json.loads(built['audit_manifest.json'])
    assert (manifest['game_count'], manifest['ats_count'], manifest['totals_count']) == (54, 54, 54)
    assert manifest['audit_status'] == 'FORMAL_GRADING_COMPLETE'
    assert manifest['clv_status'] == 'INCOMPLETE'
    assert manifest['owner_approval'] == 'PENDING'
    assert not manifest['historical_artifacts_changed']


def test_all_preliminary_results_reconciled_without_using_them_as_authority(captured):
    _, _, data, finals, supersession = captured
    grades, comparisons, sequences = build_grades(finals, data)
    assert supersession['score_discrepancies'] == []
    assert len(grades) == len(comparisons) == 108
    assert all(all(r['matches'].values()) for r in comparisons)
    assert all(r['sequence_status'] == 'VALIDATED' for r in sequences)
    assert metrics([r for r in grades if r['market'] == 'ATS'])['units_exact'] == '-6/11'
    assert metrics([r for r in grades if r['market'] == 'TOTAL'])['units_exact'] == '15/11'


@pytest.mark.parametrize('mutation', ['score', 'team_orientation', 'not_final', 'wrong_week', 'missing', 'duplicate'])
def test_reconciliation_rejects_provider_conflicts(captured, mutation):
    _, records, data, finals, _ = captured
    broken = dict(data)
    broken['cfbd-games'] = copy.deepcopy(data['cfbd-games'])
    gid = int(finals[0]['game_id'])
    row = next(r for r in broken['cfbd-games'] if r['id'] == gid)
    if mutation == 'score': row['homePoints'] += 1
    elif mutation == 'team_orientation': row['homeId'], row['awayId'] = row['awayId'], row['homeId']
    elif mutation == 'not_final': row['completed'] = False
    elif mutation == 'wrong_week': row['week'] = 10
    elif mutation == 'missing': broken['cfbd-games'].remove(row)
    elif mutation == 'duplicate': broken['cfbd-games'].append(row)
    with pytest.raises((ValueError, KeyError)):
        sources.reconcile(broken, records)


@pytest.mark.parametrize('value', [True, 1.1, -1, '3.0'])
def test_score_type_is_strict(value):
    with pytest.raises(ValueError): sources.nonnegative_score(value)


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-Infinity', True])
def test_nonfinite_grading_input_rejected(value):
    with pytest.raises(ValueError): decimal(value)


@pytest.mark.parametrize('market,field', [('ATS','pick_spread'),('ATS','locked_home_spread'),('TOTAL','locked_total')])
def test_unauthorized_line_replacement_fails(captured, market, field):
    final = captured[3][0]
    name = 'ats' if market == 'ATS' else 'totals'
    row = next(r for r in sources.read_csv(sources.BOARD/f'week9_{name}_full_card.csv') if r['game_id'] == final['game_id'])
    lock = next(r for r in sources.read_json(sources.BOARD/'week9_locked_line_snapshot.json')['lines'] if str(r['game_id']) == final['game_id'])
    row[field] = str(decimal(row[field]) + Decimal('.5'))
    with pytest.raises(ValueError): grade_selection(row, market, final, lock)


def test_input_checksum_entry_cannot_be_removed(monkeypatch, tmp_path):
    original = sources.read_json(audit.FIXTURE)
    original['sha256_by_path'].pop(next(iter(original['sha256_by_path'])))
    path = tmp_path/'altered-custody.json'
    path.write_bytes(audit.serialized(original))
    monkeypatch.setattr(audit, 'FIXTURE', path)
    with pytest.raises(ValueError, match='checksum coverage'): audit.custody()


def test_altered_source_bytes_fail(monkeypatch, tmp_path):
    fixture = sources.read_json(audit.FIXTURE)
    path = tmp_path/'data/cfb.db'
    path.parent.mkdir()
    path.write_bytes(b'altered original source')
    monkeypatch.setattr(audit, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='protected input checksum mismatch'): audit.custody()


def copy_outputs(tmp_path, built):
    for name, raw in built.items(): (tmp_path/name).write_bytes(raw)


@pytest.mark.parametrize('mutation', ['missing_hash', 'missing_output', 'extra_output', 'contradictory_status', 'material_metric', 'confidence'])
def test_exact_replay_rejects_tampering(tmp_path, built, mutation):
    copy_outputs(tmp_path, built)
    manifest = sources.read_json(tmp_path/'audit_manifest.json')
    if mutation == 'missing_hash':
        manifest['output_sha256'].pop('week9_ats_audit.csv')
    elif mutation == 'contradictory_status':
        manifest['clv_status'] = 'COMPLETE'
    elif mutation == 'missing_output':
        (tmp_path/'week9_ats_audit.csv').unlink()
    elif mutation == 'extra_output':
        (tmp_path/'unauthorized.csv').write_bytes(b'')
    elif mutation == 'material_metric':
        report = sources.read_json(tmp_path/'cross_week_diagnostics.json')
        report['weekly'][0]['mae'] += 1
        (tmp_path/'cross_week_diagnostics.json').write_bytes(audit.serialized(report))
    elif mutation == 'confidence':
        path = tmp_path/'week9_ats_audit.csv'
        path.write_bytes(path.read_bytes().replace(b',1,', b',5,', 1))
    (tmp_path/'audit_manifest.json').write_bytes(audit.serialized(manifest))
    with pytest.raises(ValueError): audit.verify_files(tmp_path, built)


def test_writer_fails_closed_before_computation(monkeypatch, tmp_path):
    prior = tmp_path/'original.txt'
    prior.write_bytes(b'protected')
    monkeypatch.setattr(audit, 'build', lambda: pytest.fail('writer must refuse before building'))
    with pytest.raises(ValueError, match='overwrite forbidden'): audit.main(False, tmp_path)
    assert prior.read_bytes() == b'protected'


def test_writer_refuses_outside_version_directory(tmp_path):
    with pytest.raises(ValueError): audit.write_new(tmp_path/'other', {'x': b'x'})


def test_sequence_is_not_inferred_from_final(captured):
    final = captured[3][0]
    seq = copy.deepcopy(captured[2]['espn-'+final['game_id']]['scoringPlays'])
    seq[0]['homeScore'] = 999
    with pytest.raises(ValueError): validate_sequence(seq, final['away_score'], final['home_score'])
    with pytest.raises(ValueError): validate_sequence([], final['away_score'], final['home_score'])


def test_started_human_row_cannot_change_membership_or_rank():
    review = sources.read_json(sources.ROOT/'outputs/2026-week9-owner-review/20261030-friday-morning/owner_review_shortlist.json')
    troy = next(r for r in review['selections'] if r['game_id'] == 401869963)
    troy['risk_and_exclusion_reason'] += ' retrospective alteration'
    with pytest.raises(ValueError, match='started-game'): validate_review(review)


def test_no_fabricated_owner_approval():
    review = sources.read_json(sources.ROOT/'outputs/2026-week9-owner-review/20261029-morning-decision/owner_review_shortlist.json')
    review['owner_approval'] = 'APPROVED'
    with pytest.raises(ValueError, match='fabricate approval'): validate_review(review)


def test_cohort_segments_are_nonoverlapping_and_human_revisions_not_summed(captured):
    grades, _, _ = build_grades(captured[3], captured[2])
    members = cohort_membership(grades)
    for market in ('ATS','TOTAL'):
        groups = [{r['game_id'] for r in members if r['cohort'] == market+'_RESEARCH_'+name} for name in ('1-5','6-10','11+')]
        assert list(map(len, groups)) == [5, 5, 44]
        assert len(set.union(*groups)) == 54
    for name in {r['cohort'] for r in members if r['cohort'].startswith('HUMAN_')}:
        assert len([r for r in members if r['cohort']==name]) == 5


def test_walk_forward_uses_only_earlier_weeks(built):
    results = json.loads(built['cross_week_diagnostics.json'])['walk_forward_candidates']
    assert len(results) == 16
    for r in results:
        assert max(r['train_weeks']) < r['evaluation_week']
        assert r['train_n'] == {6:56,7:114,8:173,9:225}[r['evaluation_week']]
        assert r['selections_changed'] is False


def test_current_market_observations_are_not_closing_lines(built):
    clv = json.loads(built['clv_evidence.json'])
    assert clv['qualified_closes'] == 0 and clv['status'] == 'INCOMPLETE'
    assert len(clv['games']) == 54
    assert all(r['ats_clv'] is None and r['total_clv'] is None for r in clv['games'])
