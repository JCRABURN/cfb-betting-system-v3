"""Source, identity and point-in-time failure modes for the Week 12 intake."""
import copy
import json
from datetime import datetime, timezone

import pytest

from scripts import prepare_week12_source as source
from scripts.run_week12_execution import eligibility


def pages():
    return json.loads((source.SOURCE/'extracted-pages.json').read_bytes())


def test_exact_source_replay():
    source.main(True)


@pytest.mark.parametrize('old,new', [
    ('+14.5', '-14.5'), ('Under 46.5', 'Under 45.5'),
    ('11/17/26, 2:22', '11/18/26, 2:22'), ('Tue 5:00pm', 'Tue 25:00pm'),
    ('EMU @ WMU', 'EMU AT WMU'),
])
def test_source_corruption_rejected(old, new):
    value = pages(); value[0] = value[0].replace(old, new, 1)
    with pytest.raises(ValueError):
        source.parse_pages(value)


def test_duplicate_game_rejected():
    value = pages(); value[1] = value[2]
    with pytest.raises(ValueError):
        source.parse_pages(value)


@pytest.fixture(scope='module')
def evidence():
    return source.load_capture()[2]


def test_unknown_team_rejected(evidence):
    rows = source.parse_pages(pages()); rows[0]['raw_away'] = 'Fictional team'
    with pytest.raises(ValueError, match='unrecognized team'):
        source.reconcile(rows, evidence, datetime.now(timezone.utc))


def test_reversed_game_rejected(evidence):
    rows = source.parse_pages(pages()); r = rows[0]
    r['raw_away'], r['raw_home'] = r['raw_home'], r['raw_away']
    with pytest.raises(ValueError, match='provider matchup'):
        source.reconcile(rows, evidence, datetime.now(timezone.utc))


def test_earlier_source_kickoff_prevents_revival(evidence):
    rows = source.parse_pages(pages())
    rows[3]['source_kickoff_utc'] = '2026-11-17T00:00:00+00:00'
    result, _ = source.reconcile(rows, evidence, datetime(2026,11,18,19,tzinfo=timezone.utc))
    assert result[3]['status'] == 'ELAPSED_NO_PROSPECTIVE_FORECAST'
    assert result[3]['issues'] == 'KICKOFF_DIFFERENCE_PRESERVE_SOURCE'


def test_provider_team_conflict_rejected(evidence):
    data = copy.deepcopy(evidence)
    data['espn-schedule']['events'][0]['competitions'][0]['competitors'][0]['team']['id'] = '999999'
    with pytest.raises(ValueError):
        source.reconcile(source.parse_pages(pages()), data, datetime(2026,11,18,19,tzinfo=timezone.utc))


def test_stale_status_cannot_authorize_execution(evidence):
    with pytest.raises(ValueError, match='five minutes'):
        eligibility(source.parse_pages(pages()), evidence,
                    datetime(2026,11,18,18,tzinfo=timezone.utc), datetime(2026,11,18,19,tzinfo=timezone.utc))


def test_started_games_excluded_without_losing_source_rows(evidence):
    now=datetime(2026,11,18,19,10,tzinfo=timezone.utc)
    upcoming,elapsed=eligibility(source.parse_pages(pages()),evidence,now,now)
    assert len(upcoming)==63 and len(elapsed)==3
    assert len({r['game_id'] for r in upcoming+elapsed})==66
