import copy
from datetime import datetime,timezone
import pytest
from scripts import prepare_week12_source as source
from scripts.capture_week12_context import eligible_games

@pytest.fixture(scope='module')
def captured():return source.load_capture()[1:]

def test_stale_context_schedule_rejected(captured):
    records,data=captured
    with pytest.raises(ValueError,match='fresh'):eligible_games(data,records,datetime(2026,11,19,14,tzinfo=timezone.utc))

def test_fresh_context_excludes_earlier_frozen_kickoff(captured):
    records,data=captured;records=copy.deepcopy(records);data=copy.deepcopy(data)
    now=datetime(2026,11,19,14,tzinfo=timezone.utc)
    for r in records.values():r['received_at_utc']=now.isoformat()
    # Source kickoff remains authoritative even if a provider still labels Wednesday pregame.
    games,rows=eligible_games(data,records,now)
    assert len(games)==61 and len(rows)==66
    assert sum(r['status'].startswith('ELAPSED') for r in rows)==5

def test_future_schedule_receipt_rejected(captured):
    records,data=captured
    with pytest.raises(ValueError,match='fresh'):eligible_games(data,records,datetime(2026,11,17,14,tzinfo=timezone.utc))

@pytest.mark.parametrize('provider',['cfbd-games-all','espn-schedule'])
def test_each_schedule_must_be_fresh(captured,provider):
    records,data=captured;records=copy.deepcopy(records)
    now=datetime(2026,11,19,14,tzinfo=timezone.utc)
    for name,r in records.items():
        if name!=provider:r['received_at_utc']=now.isoformat()
    with pytest.raises(ValueError,match='fresh'):eligible_games(data,records,now)

@pytest.fixture
def refresh_review(monkeypatch):
    from scripts import review_week12_context as review
    base=source.ROOT/'outputs/2026-week12-context'
    monkeypatch.setattr(review,'CAP',base/'20261119-morning')
    monkeypatch.setattr(review,'CONF',base/'20261119-conference')
    monkeypatch.setattr(review,'DATA_CAPTURE',source.ROOT/'outputs/2026-week12-readiness/20261119-morning')
    return review

def test_refresh_rejects_different_schedule_provenance(refresh_review,monkeypatch):
    monkeypatch.setattr(refresh_review,'DATA_CAPTURE',source.CAPTURE)
    with pytest.raises(ValueError,match='provenance'):refresh_review.build()

def test_refresh_rejects_postkickoff_conference_evidence(refresh_review,monkeypatch):
    original=refresh_review.conference_rows
    def future(manifest):
        rows=original(manifest)
        for row in rows:row['retrieved_at_utc']='2026-11-23T00:00:00Z'
        return rows
    monkeypatch.setattr(refresh_review,'conference_rows',future)
    with pytest.raises(ValueError,match='postkickoff conference'):refresh_review.build()

def test_thursday_replay_preserves_complete_card():
    from scripts.review_week12_thursday import build,OUT
    for name,raw in build().items():assert raw==(OUT/name).read_bytes()
