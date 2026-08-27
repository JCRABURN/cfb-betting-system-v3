import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest

from operations.config import load_production_settings
from operations.providers import ProductionProviderError, capture_live_provider_bundle
from production_scheduling import (
    ProductionScheduleError,
    load_production_schedule,
    resolve_production_schedule,
)


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = json.loads(
    (ROOT / "config" / "weekly_operation.example.json").read_text(encoding="utf-8")
)


def _schedule_payload():
    return copy.deepcopy(EXAMPLE["production_schedule"])


def test_explicit_schedule_resolves_due_then_returns_to_idle_without_polling():
    schedule = load_production_schedule(_schedule_payload(), season=2099)
    assert schedule is not None
    refresh = next(
        entry for entry in schedule.entries if entry.operation == "sportsbook_refresh"
    )

    due = resolve_production_schedule(schedule, now=refresh.run_at + timedelta(minutes=4))
    idle = resolve_production_schedule(schedule, now=refresh.run_at + timedelta(minutes=31))
    later_idle = resolve_production_schedule(
        schedule, now=refresh.run_at + timedelta(minutes=20)
    )

    assert due.should_run is True
    assert due.operation == "sportsbook_refresh"
    assert due.operation_instance == refresh.run_at.strftime("%Y%m%dT%H%MZ")
    assert idle.status == "idle"
    assert later_idle.status == "idle"


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload["odds_api_quota"].update(
                maximum_paid_calls_per_week=9
            ),
            "maximum_paid_calls_per_week",
        ),
        (
            lambda payload: payload["entries"].pop(),
            "weekly_audit",
        ),
        (
            lambda payload: payload["entries"][0].update(
                run_at="2099-08-25T15:20:00+00:00"
            ),
            "dispatcher minutes",
        ),
    ],
)
def test_schedule_rejects_quota_stage_and_dispatch_drift(mutator, message):
    payload = _schedule_payload()
    mutator(payload)
    with pytest.raises(ProductionScheduleError, match=message):
        load_production_schedule(payload, season=2099)


def test_repeatable_refresh_has_auditable_operation_instance(tmp_path):
    root = tmp_path / "cfb-betting-system-v3"
    root.mkdir()
    settings = load_production_settings(
        {"CFB_V3_OPERATION_INSTANCE": "20990825T2122Z"},
        repository_root=root,
        operation="sportsbook_refresh",
    )
    assert (
        settings.idempotency_key
        == "v3:missing-season:week:missing-week:sportsbook_refresh:20990825T2122Z"
    )


class _Response:
    status_code = 200

    def __init__(self, payload, headers=None):
        self.payload = payload
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _QuotaSession:
    def __init__(self, remaining):
        self.remaining = remaining
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/sports"):
            return _Response(
                [],
                {
                    "x-requests-remaining": str(self.remaining),
                    "x-requests-used": "25",
                    "x-requests-last": "0",
                },
            )
        if url.endswith("/games"):
            return _Response([])
        return _Response(
            [],
            {
                "x-requests-remaining": str(self.remaining - 1),
                "x-requests-used": "26",
                "x-requests-last": "1",
            },
        )


def test_quota_reserve_blocks_before_paid_or_cfbd_calls(tmp_path):
    root = tmp_path / "cfb-betting-system-v3"
    parent = root / "data" / "provider_evidence"
    parent.mkdir(parents=True)
    session = _QuotaSession(100)

    with pytest.raises(ProductionProviderError, match="quota reserve blocks"):
        capture_live_provider_bundle(
            {"CFBD_API_KEY": "fixture-cfbd", "ODDS_API_KEY": "fixture-odds"},
            repository_root=root,
            output_directory=parent / "blocked",
            season=2099,
            week=1,
            line_type="current",
            authorized=True,
            session=session,
            odds_api_minimum_remaining_credits=100,
            odds_api_estimated_call_cost=1,
        )

    assert len(session.calls) == 1
    assert session.calls[0][0].endswith("/sports")
    assert not (parent / "blocked").exists()


def test_quota_evidence_is_recorded_without_credentials(tmp_path):
    root = tmp_path / "cfb-betting-system-v3"
    parent = root / "data" / "provider_evidence"
    parent.mkdir(parents=True)
    session = _QuotaSession(200)
    output = parent / "captured"

    bundle_path = capture_live_provider_bundle(
        {"CFBD_API_KEY": "fixture-cfbd", "ODDS_API_KEY": "fixture-odds"},
        repository_root=root,
        output_directory=output,
        season=2099,
        week=1,
        line_type="current",
        authorized=True,
        session=session,
        odds_api_minimum_remaining_credits=100,
        odds_api_estimated_call_cost=1,
    )
    payload = json.loads(bundle_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)

    assert payload["odds_api_quota"]["before"]["remaining"] == 200
    assert payload["odds_api_quota"]["after"]["remaining"] == 199
    assert len(session.calls) == 3
    assert "fixture-cfbd" not in serialized
    assert "fixture-odds" not in serialized
