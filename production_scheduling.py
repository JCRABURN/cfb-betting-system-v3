"""Fail-closed, quota-aware recurring production schedule resolution."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

SCHEDULE_POLICY_VERSION = "production-schedule-v1"
DISPATCH_INTERVAL_MINUTES = 15
DISPATCH_MINUTES = (7, 22, 37, 52)
SPORTSBOOK_REFRESH_OPERATION = "sportsbook_refresh"
PRODUCTION_OPERATIONS = (
    "tuesday_lock",
    "wednesday_refresh",
    "thursday_refresh",
    "friday_refresh",
    "saturday_final",
    SPORTSBOOK_REFRESH_OPERATION,
    "postgame_grading",
    "weekly_audit",
)
CARD_STAGE_OPERATIONS = PRODUCTION_OPERATIONS[:5]
API_FREE_OPERATIONS = ("postgame_grading", "weekly_audit")
OPERATION_INSTANCE_PATTERN = re.compile(r"^\d{8}T\d{4}Z$")
_EXPECTED_WEEKDAY = {
    "tuesday_lock": 1,
    "wednesday_refresh": 2,
    "thursday_refresh": 3,
    "friday_refresh": 4,
    "saturday_final": 5,
    "postgame_grading": 0,
    "weekly_audit": 0,
}


class ProductionScheduleError(RuntimeError):
    """Raised when the owner-reviewed production schedule is unsafe."""


@dataclass(frozen=True)
class OddsApiQuotaPolicy:
    monthly_credit_allowance: int
    minimum_remaining_credits: int
    maximum_paid_calls_per_week: int
    estimated_credits_per_call: int


@dataclass(frozen=True)
class ProductionScheduleEntry:
    operation: str
    run_at: datetime

    @property
    def operation_instance(self) -> str:
        if self.operation != SPORTSBOOK_REFRESH_OPERATION:
            return ""
        return self.run_at.strftime("%Y%m%dT%H%MZ")


@dataclass(frozen=True)
class ProductionSchedule:
    policy_version: str
    dispatcher_interval_minutes: int
    quota: OddsApiQuotaPolicy
    entries: tuple[ProductionScheduleEntry, ...]

    def next_pregame_entry_after(self, value: datetime) -> ProductionScheduleEntry | None:
        now = _utc(value, "schedule lookup time")
        return next(
            (
                entry
                for entry in self.entries
                if entry.run_at > now and entry.operation not in API_FREE_OPERATIONS
            ),
            None,
        )


@dataclass(frozen=True)
class ScheduleResolution:
    status: str
    reason: str
    operation: str | None
    operation_instance: str
    scheduled_for: str | None
    next_scheduled_refresh: str | None

    @property
    def should_run(self) -> bool:
        return self.status == "due"


def operation_instance_is_valid(operation: str, value: str) -> bool:
    """Require a slot identity only for independently repeatable refreshes."""
    if operation == SPORTSBOOK_REFRESH_OPERATION:
        return OPERATION_INSTANCE_PATTERN.fullmatch(value) is not None
    return value == ""


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ProductionScheduleError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ProductionScheduleError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return value


def _utc(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ProductionScheduleError(f"{field} must be ISO-8601") from exc
    else:
        raise ProductionScheduleError(f"{field} must be a UTC timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ProductionScheduleError(f"{field} must use UTC")
    return parsed.astimezone(timezone.utc)


def load_production_schedule(
    value: object,
    *,
    season: int | None = None,
) -> ProductionSchedule | None:
    """Validate an optional explicit schedule embedded in one weekly config."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ProductionScheduleError("production_schedule must be a JSON object")
    if value.get("policy_version") != SCHEDULE_POLICY_VERSION:
        raise ProductionScheduleError(
            f"production_schedule.policy_version must be {SCHEDULE_POLICY_VERSION}"
        )
    interval = _integer(
        value.get("dispatcher_interval_minutes"),
        "production_schedule.dispatcher_interval_minutes",
        DISPATCH_INTERVAL_MINUTES,
        DISPATCH_INTERVAL_MINUTES,
    )
    quota_value = value.get("odds_api_quota")
    if not isinstance(quota_value, Mapping):
        raise ProductionScheduleError(
            "production_schedule.odds_api_quota must be a JSON object"
        )
    quota = OddsApiQuotaPolicy(
        monthly_credit_allowance=_integer(
            quota_value.get("monthly_credit_allowance"),
            "production_schedule.odds_api_quota.monthly_credit_allowance",
            1,
            1_000_000,
        ),
        minimum_remaining_credits=_integer(
            quota_value.get("minimum_remaining_credits"),
            "production_schedule.odds_api_quota.minimum_remaining_credits",
            0,
            999_999,
        ),
        maximum_paid_calls_per_week=_integer(
            quota_value.get("maximum_paid_calls_per_week"),
            "production_schedule.odds_api_quota.maximum_paid_calls_per_week",
            1,
            10_000,
        ),
        estimated_credits_per_call=_integer(
            quota_value.get("estimated_credits_per_call"),
            "production_schedule.odds_api_quota.estimated_credits_per_call",
            1,
            1,
        ),
    )
    if quota.minimum_remaining_credits >= quota.monthly_credit_allowance:
        raise ProductionScheduleError(
            "Odds API minimum remaining credits must be below the monthly allowance"
        )

    raw_entries = value.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise ProductionScheduleError(
            "production_schedule.entries must be a non-empty array"
        )
    entries: list[ProductionScheduleEntry] = []
    for index, item in enumerate(raw_entries):
        if not isinstance(item, Mapping):
            raise ProductionScheduleError(
                f"production_schedule.entries[{index}] must be a JSON object"
            )
        operation = item.get("operation")
        if operation not in PRODUCTION_OPERATIONS:
            raise ProductionScheduleError(
                f"production_schedule.entries[{index}].operation is not governed"
            )
        run_at = _utc(
            item.get("run_at"),
            f"production_schedule.entries[{index}].run_at",
        )
        if run_at.second or run_at.microsecond or run_at.minute not in DISPATCH_MINUTES:
            raise ProductionScheduleError(
                "scheduled entries must align to the GitHub dispatcher minutes "
                + ", ".join(str(minute) for minute in DISPATCH_MINUTES)
            )
        expected_weekday = _EXPECTED_WEEKDAY.get(str(operation))
        if expected_weekday is not None and run_at.weekday() != expected_weekday:
            raise ProductionScheduleError(
                f"{operation} must run on its governed UTC weekday"
            )
        if operation == SPORTSBOOK_REFRESH_OPERATION and run_at.weekday() not in range(1, 6):
            raise ProductionScheduleError(
                "sportsbook_refresh must run Tuesday through Saturday UTC"
            )
        entries.append(ProductionScheduleEntry(str(operation), run_at))
    entries.sort(key=lambda entry: entry.run_at)
    if season is not None and any(
        entry.run_at.year not in (season, season + 1) for entry in entries
    ):
        raise ProductionScheduleError(
            "scheduled entry year must match the configured season or its postseason year"
        )
    for prior, current in zip(entries, entries[1:]):
        if current.run_at - prior.run_at < timedelta(minutes=DISPATCH_INTERVAL_MINUTES * 2):
            raise ProductionScheduleError(
                "scheduled entries must be at least 30 minutes apart"
            )

    for operation in _EXPECTED_WEEKDAY:
        count = sum(entry.operation == operation for entry in entries)
        if count != 1:
            raise ProductionScheduleError(
                f"production schedule requires exactly one {operation} entry"
            )
    refreshes = [
        entry for entry in entries if entry.operation == SPORTSBOOK_REFRESH_OPERATION
    ]
    if not refreshes:
        raise ProductionScheduleError(
            "production schedule requires at least one governed sportsbook_refresh"
        )
    by_operation = {
        entry.operation: entry
        for entry in entries
        if entry.operation != SPORTSBOOK_REFRESH_OPERATION
    }
    ordered_core = tuple(_EXPECTED_WEEKDAY)
    core_times = [by_operation[operation].run_at for operation in ordered_core]
    if core_times != sorted(core_times):
        raise ProductionScheduleError(
            "production stage timestamps must follow the governed operation order"
        )
    if core_times[-1] - core_times[0] > timedelta(days=7):
        raise ProductionScheduleError(
            "production stage timestamps must describe one seven-day operating week"
        )
    if any(
        entry.run_at <= by_operation["tuesday_lock"].run_at
        or entry.run_at >= by_operation["saturday_final"].run_at
        for entry in refreshes
    ):
        raise ProductionScheduleError(
            "sportsbook_refresh entries must fall after Tuesday lock and before Saturday final"
        )

    paid_calls = sum(
        entry.operation not in API_FREE_OPERATIONS for entry in entries
    )
    if paid_calls > quota.maximum_paid_calls_per_week:
        raise ProductionScheduleError(
            "configured schedule exceeds maximum_paid_calls_per_week"
        )
    projected_credits = paid_calls * quota.estimated_credits_per_call
    usable_credits = quota.monthly_credit_allowance - quota.minimum_remaining_credits
    if projected_credits > usable_credits:
        raise ProductionScheduleError(
            "configured schedule exceeds the declared Odds API allowance and reserve"
        )
    return ProductionSchedule(
        policy_version=SCHEDULE_POLICY_VERSION,
        dispatcher_interval_minutes=interval,
        quota=quota,
        entries=tuple(entries),
    )


def resolve_production_schedule(
    schedule: ProductionSchedule,
    *,
    now: datetime,
) -> ScheduleResolution:
    """Resolve one dispatcher heartbeat without calling any provider."""
    checked_at = _utc(now, "schedule resolution time")
    interval = timedelta(minutes=schedule.dispatcher_interval_minutes)
    due = [
        entry
        for entry in schedule.entries
        if timedelta(0) <= checked_at - entry.run_at < interval
    ]
    if len(due) > 1:
        raise ProductionScheduleError("more than one production operation is due")
    upcoming = schedule.next_pregame_entry_after(checked_at)
    next_refresh = upcoming.run_at.isoformat() if upcoming is not None else None
    if due:
        entry = due[0]
        return ScheduleResolution(
            status="due",
            reason="one owner-reviewed production schedule entry is due",
            operation=entry.operation,
            operation_instance=entry.operation_instance,
            scheduled_for=entry.run_at.isoformat(),
            next_scheduled_refresh=next_refresh,
        )
    return ScheduleResolution(
        status="idle",
        reason="no owner-reviewed production schedule entry is due",
        operation=None,
        operation_instance="",
        scheduled_for=None,
        next_scheduled_refresh=next_refresh,
    )
