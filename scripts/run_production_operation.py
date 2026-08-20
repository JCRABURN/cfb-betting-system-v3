"""Run one guarded production operation through the governed V3 adapter."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path

from operations import (
    PRODUCTION_OPERATIONS,
    execute_production_operation,
    load_production_settings,
    load_weekly_configuration,
    merge_weekly_environment,
    run_production_preflight,
)


ROOT = Path(__file__).resolve().parents[1]
PERSIST_CONFIRMATION = "EXECUTE_V3_OPERATION"
DRY_RUN_CONFIRMATION = "DRY_RUN_V3_OPERATION"


def _commit_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip().casefold()


def _write_json(path: Path | None, payload: dict[str, object]) -> bool:
    if path is None:
        return True
    output = path.resolve()
    if not output.parent.is_dir():
        print("output parent directory does not exist", file=sys.stderr)
        return False
    output.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", required=True, choices=PRODUCTION_OPERATIONS)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--weekly-config", type=Path)
    parser.add_argument(
        "--mode",
        choices=("read-only", "dry-run", "persist"),
        default="read-only",
    )
    parser.add_argument("--confirmation")
    parser.add_argument("--preflight-output", type=Path)
    parser.add_argument("--result-output", type=Path)
    args = parser.parse_args(argv)

    if args.weekly_config is None:
        print("weekly configuration file is required", file=sys.stderr)
        return 2

    if args.mode == "persist" and args.confirmation != PERSIST_CONFIRMATION:
        print("persist mode requires the exact execution confirmation", file=sys.stderr)
        return 2
    if args.mode == "dry-run" and args.confirmation != DRY_RUN_CONFIRMATION:
        print("dry-run mode requires the exact dry-run confirmation", file=sys.stderr)
        return 2
    try:
        configuration = load_weekly_configuration(
            args.weekly_config,
            repository_root=ROOT,
        )
        environment = merge_weekly_environment(os.environ, configuration)
        settings = load_production_settings(
            environment,
            repository_root=ROOT,
            operation=args.operation,
            database_path=args.database,
        )
        if args.mode == "read-only":
            report = run_production_preflight(settings)
            payload = asdict(report)
            if not _write_json(args.preflight_output, payload):
                return 2
            print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            return 0 if report.production_ready else 1
        result, report = execute_production_operation(
            settings,
            configuration,
            code_commit_sha=_commit_sha(),
            dry_run=args.mode == "dry-run",
        )
        if not _write_json(args.preflight_output, asdict(report)):
            return 2
        result_payload = asdict(result)
        if not _write_json(args.result_output, result_payload):
            return 2
        print(json.dumps(result_payload, sort_keys=True, separators=(",", ":")))
        return 0
    except (
        OSError,
        sqlite3.Error,
        subprocess.SubprocessError,
        RuntimeError,
        ValueError,
    ) as exc:
        print(f"production operation rejected: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
