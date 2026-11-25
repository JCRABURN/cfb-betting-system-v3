"""Source, identity and point-in-time failure modes for the Week 13 intake."""
import copy
import json
from datetime import datetime, timezone

import pytest

from scripts import prepare_week13_source as source
from scripts.run_week13_execution import eligibility


def pages():
    return json.loads((source.SOURCE/'extracted-pages.json').read_bytes())


def test_exact_source_replay():
    source.main(True)


@pytest.mark.parametrize('old,new', [
    ('+6.5', '-6.5'), ('Under 46.5', 'Under 45.5'),
    ('11/25/26, 8:39', '11/24/26, 8:39'), ('Tue 6:00pm', 'Tue 25:00pm'),
    ('M-OH @ WMU', 'M-OH AT WMU'),
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
    rows[3]['source_kickoff_utc'] = '2026-11-24T00:00:00+00:00'
    result, _ = source.reconcile(rows, evidence, datetime(2026,11,25,19,tzinfo=timezone.utc))
    assert result[3]['status'] == 'ELAPSED_NO_PROSPECTIVE_FORECAST'
    assert result[3]['issues'] == 'KICKOFF_DIFFERENCE_PRESERVE_SOURCE'


def test_provider_team_conflict_rejected(evidence):
    data = copy.deepcopy(evidence)
    data['espn-schedule']['events'][0]['competitions'][0]['competitors'][0]['team']['id'] = '999999'
    with pytest.raises(ValueError):
        source.reconcile(source.parse_pages(pages()), data, datetime(2026,11,25,19,tzinfo=timezone.utc))


def test_stale_status_cannot_authorize_execution(evidence):
    with pytest.raises(ValueError, match='five minutes'):
        eligibility(source.parse_pages(pages()), evidence,
                    datetime(2026,11,25,18,tzinfo=timezone.utc), datetime(2026,11,25,19,tzinfo=timezone.utc))


def test_started_games_excluded_without_losing_source_rows(evidence):
    now=datetime(2026,11,25,19,10,tzinfo=timezone.utc)
    upcoming,elapsed=eligibility(source.parse_pages(pages()),evidence,now,now)
    assert len(upcoming)==67 and len(elapsed)==2
    assert len({r['game_id'] for r in upcoming+elapsed})==69


def test_exact_spread_total_and_last_page():
    rows = source.parse_pages(pages())
    assert rows[0]['home_spread'] == -6.5 and rows[0]['locked_total'] == 46.5
    assert rows[-1]['raw_away'] == 'Sacramento State'
    assert rows[-1]['home_spread'] == -13.5 and rows[-1]['locked_total'] == 39.5
    assert rows[-1]['source_kickoff_utc'] == '2026-11-29T04:00:00+00:00'


def test_upcoming_scores_rejected(evidence):
    data = copy.deepcopy(evidence)
    row = source.reconcile(source.parse_pages(pages()), data, datetime(2026,11,25,19,tzinfo=timezone.utc))[0][2]
    game = next(g for g in data['cfbd-games-all'] if g['id']==row['game_id'])
    game['homePoints'] = 99
    with pytest.raises(ValueError, match='score contamination'):
        source.reconcile(source.parse_pages(pages()), data, datetime(2026,11,25,19,tzinfo=timezone.utc))


def test_upcoming_kickoff_conflict_blocks_execution(evidence):
    rows = source.parse_pages(pages())
    rows[2]['source_kickoff_utc'] = '2026-11-27T02:00:00+00:00'
    now = datetime(2026,11,25,19,tzinfo=timezone.utc)
    with pytest.raises(ValueError, match='provider conflicts'):
        eligibility(rows, evidence, now, now)


def test_future_capture_blocks_execution(evidence):
    now = datetime(2026,11,25,19,tzinfo=timezone.utc)
    with pytest.raises(ValueError, match='five minutes'):
        eligibility(source.parse_pages(pages()), evidence,
                    datetime(2026,11,25,20,tzinfo=timezone.utc), now)
