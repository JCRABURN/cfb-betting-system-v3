"""Resolve a manual or scheduled V3 operation without credentials or API calls."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from production_scheduling import (
    PRODUCTION_OPERATIONS,
    ProductionSchedule,
    ProductionScheduleError,
    ScheduleResolution,
    load_production_schedule,
    operation_instance_is_valid,
    resolve_production_schedule,
)


ROOT = Path(__file__).resolve().parents[1]
WEEKLY_CONFIGURATION_VERSION = "v3-weekly-production-v1"
EXPECTED_REPOSITORY = "JCRABURN/cfb-betting-system-v3"


def _load_schedule_identity(
    path: Path,
) -> tuple[int, int, ProductionSchedule | None]:
    config_path = path.resolve()
    try:
        inside = config_path.is_relative_to(ROOT)
    except ValueError:
        inside = False
    if not inside or not config_path.is_file():
        raise ProductionScheduleError(
            "weekly configuration must be a file inside the V3 repository"
        )
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionScheduleError(
            "weekly configuration is not valid UTF-8 JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise ProductionScheduleError("weekly configuration must be a JSON object")
    if payload.get("configuration_version") != WEEKLY_CONFIGURATION_VERSION:
        raise ProductionScheduleError(
            f"configuration_version must be {WEEKLY_CONFIGURATION_VERSION}"
        )
    if payload.get("repository") != EXPECTED_REPOSITORY:
        raise ProductionScheduleError(
            f"repository must be exactly {EXPECTED_REPOSITORY}"
        )
    season = payload.get("season")
    week = payload.get("week")
    if (
        isinstance(season, bool)
        or not isinstance(season, int)
        or not 1869 <= season <= 9999
        or isinstance(week, bool)
        or not isinstance(week, int)
        or not 0 <= week <= 20
    ):
        raise ProductionScheduleError("weekly configuration season/week is invalid")
    schedule = load_production_schedule(
        payload.get("production_schedule"),
        season=season,
    )
    return season, week, schedule


def _write_outputs(path: Path, values: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for name, value in values.items():
            rendered = (
                "true"
                if value is True
                else "false"
                if value is False
                else str(value or "")
            )
            if "\n" in rendered or "\r" in rendered:
                raise ProductionScheduleError("schedule output must be one line")
            output.write(f"{name.replace('_', '-')}={rendered}\n")


def _manual_resolution(
    *,
    operation: str,
    operation_instance: str,
) -> ScheduleResolution:
    if operation not in PRODUCTION_OPERATIONS:
        raise ProductionScheduleError("manual operation is not governed")
    instance = operation_instance.strip()
    if not operation_instance_is_valid(operation, instance):
        raise ProductionScheduleError(
            "manual sportsbook_refresh requires YYYYMMDDTHHMMZ operation_instance; "
            "other operations must leave it empty"
        )
    return ScheduleResolution(
        status="due",
        reason="owner-confirmed manual production operation",
        operation=operation,
        operation_instance=instance,
        scheduled_for=None,
        next_scheduled_refresh=None,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--event-name",
        required=True,
        choices=("schedule", "workflow_dispatch"),
    )
    parser.add_argument("--weekly-config", required=True, type=Path)
    parser.add_argument("--manual-operation", default="")
    parser.add_argument("--manual-operation-instance", default="")
    parser.add_argument("--manual-season", default="")
    parser.add_argument("--manual-week", default="")
    parser.add_argument("--now")
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        season, week, schedule = _load_schedule_identity(args.weekly_config)
        if args.event_name == "workflow_dispatch":
            try:
                manual_season = int(args.manual_season)
                manual_week = int(args.manual_week)
            except ValueError as exc:
                raise ProductionScheduleError(
                    "manual season and week must be integers"
                ) from exc
            if (season, week) != (manual_season, manual_week):
                raise ProductionScheduleError(
                    "manual season/week conflicts with the weekly configuration"
                )
            resolution = _manual_resolution(
                operation=args.manual_operation,
                operation_instance=args.manual_operation_instance,
            )
        else:
            if schedule is None:
                raise ProductionScheduleError(
                    "scheduled execution requires production_schedule in the weekly config"
                )
            now = (
                datetime.fromisoformat(args.now.replace("Z", "+00:00"))
                if args.now
                else datetime.now(timezone.utc)
            )
            resolution = resolve_production_schedule(
                schedule,
                now=now,
            )
        values: dict[str, object] = {
            **asdict(resolution),
            "should_run": resolution.should_run,
            "season": season,
            "week": week,
        }
        output_path = args.github_output
        if output_path is None:
            raw_output = os.environ.get("GITHUB_OUTPUT", "").strip()
            output_path = Path(raw_output) if raw_output else None
        if output_path is not None:
            _write_outputs(output_path, values)
        print(json.dumps(values, sort_keys=True, separators=(",", ":")))
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"production schedule rejected: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
