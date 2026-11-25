"""Independent coverage, source custody and adversarial sealed-output checks."""
import copy

import pytest

from scripts import verify_week13_results as results


def test_complete_saved_model_run():
    actual = results.verify()
    assert actual['upcoming_forecasts'] == 67
    assert actual['elapsed_exclusions'] == 2
    assert actual['model_fallbacks'] == actual['feature_fallbacks'] == 0


@pytest.mark.parametrize('field,value,error', [
    ('confidence','5','confidence'),
    ('fallback_code','unrecorded','confidence'),
    ('projected_home_margin','999','numerical replay'),
    ('locked_home_spread','99','spread changed'),
    ('pick_spread','99','spread sign'),
])
def test_mutated_ats_rejected(monkeypatch, field, value, error):
    original = results.read_csv
    def altered(name):
        rows = original(name)
        if name == 'week13_ats_full_card.csv':
            rows[0][field] = value
        return rows
    monkeypatch.setattr(results, 'read_csv', altered)
    with pytest.raises(ValueError,match=error):
        results.verify()


@pytest.mark.parametrize('kind,error', [
    ('future_feature','feature cutoff'),
    ('late_prediction','late forecast'),
    ('altered_line','PDF line changed'),
    ('elapsed_revived','elapsed games'),
])
def test_lookahead_and_source_changes_rejected(monkeypatch, kind, error):
    original = results.load
    def altered(name):
        value = copy.deepcopy(original(name))
        if name == 'week13_raw_model_components.json':
            game = value['games'][0]
            if kind == 'future_feature':
                game['raw_point_in_time_package']['home_stats']['as_of_week'] = 13
            if kind == 'late_prediction':
                game['ats']['prediction_generated_at'] = game['kickoff_utc']
        if name == 'week13_locked_line_snapshot.json':
            if kind == 'altered_line':
                value['lines'][0]['home_spread'] += 1
            if kind == 'elapsed_revived':
                value['excluded'][0]['status'] = 'UPCOMING'
        return value
    monkeypatch.setattr(results,'load',altered)
    with pytest.raises(ValueError,match=error):
        results.verify()


def test_report_exposes_coverage_and_calibration_limits():
    report = results.report()
    assert 'Complete 69-game intake' in report
    assert report.count('Elapsed before intake') == 2
    assert 'Confidence' in report and 'tie-breaks' in report
    assert 'No card was submitted or published' in report
