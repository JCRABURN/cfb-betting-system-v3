import json
import pytest
from scripts import review_week11_refresh as refresh
from scripts import review_week11_context as prior


def test_friday_replay_and_no_changes_to_previous_choices():
    assert refresh.main(True)['recommendations'] == 5
    saved = refresh.read(refresh.OUT / 'review.json')
    assert saved['choices'] == refresh.read(prior.OUT / 'review.json')['choices']
    assert not saved['numeric_adjustments']


@pytest.mark.parametrize('field,value', [('contest_line', 11.5), ('frozen_projection', 0.0),
                                      ('human_confidence', 5), ('rank', 5)])
def test_reject_changed_selection_numbers(tmp_path, monkeypatch, field, value):
    saved = refresh.read(refresh.OUT / 'review.json')
    saved['choices'][0][field] = value
    (tmp_path / 'review.json').write_text(json.dumps(saved))
    monkeypatch.setattr(refresh, 'OUT', tmp_path)
    with pytest.raises(ValueError, match='exact replay'):
        refresh.main(True)


def test_reject_source_rehash_or_backdated_review(monkeypatch):
    with pytest.raises(ValueError, match='precede evidence'):
        refresh.build('2026-11-12T00:00:00Z')
    monkeypatch.setattr(refresh, 'sha', lambda path: '0'*64)
    with pytest.raises(ValueError, match='source identity'):
        refresh.build('2026-11-13T14:00:00Z')


def test_started_rows_are_carried_exactly_without_new_context():
    value = refresh.build('2026-11-16T00:00:00Z')
    previous = refresh.read(prior.OUT / 'review.json')
    assert value['choices'] == previous['choices']
    assert [r['previous_row'] for r in value['candidate_updates']] == previous['candidates']
    assert all('teams' not in r and 'separate_market_observation' not in r for r in value['candidate_updates'])
