"""Run one V3 operation with durable PostgreSQL state on a cloud runner."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path

from operations import (
    PRODUCTION_OPERATIONS,
    load_production_settings,
    load_weekly_configuration,
    merge_weekly_environment,
)
from operations.cloud_execution import execute_cloud_production_operation
from operations.cloud_persistence import CloudPersistenceError, PostgreSQLSnapshotStore
from operations.providers import ProductionProviderError, capture_live_provider_bundle


ROOT = Path(__file__).resolve().parents[1]
PERSIST_CONFIRMATION = "EXECUTE_V3_CLOUD_OPERATION"
SHADOW_PERSIST_CONFIRMATION = "EXECUTE_V3_CLOUD_SHADOW_REHEARSAL"


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


def _capture_line_type(runtime_mode: str, operation: str) -> str:
    if runtime_mode == "shadow":
        return "current"
    return "opening" if operation == "tuesday_lock" else "current"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operation", required=True, choices=PRODUCTION_OPERATIONS)
    parser.add_argument("--weekly-config", required=True, type=Path)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--capture-provider-data", action="store_true")
    parser.add_argument("--provider-confirmation")
    parser.add_argument("--preflight-output", type=Path)
    parser.add_argument("--result-output", type=Path)
    args = parser.parse_args(argv)
    runtime_mode = os.environ.get("CFB_V3_RUNTIME_MODE", "").strip()
    required_confirmation = (
        SHADOW_PERSIST_CONFIRMATION
        if runtime_mode == "shadow"
        else PERSIST_CONFIRMATION
    )
    if args.confirmation != required_confirmation:
        print("cloud persist mode requires the exact execution confirmation", file=sys.stderr)
        return 2
    database_url = os.environ.get("CFB_V3_DATABASE_URL", "")
    if not database_url.strip():
        print("production operation rejected: CFB_V3_DATABASE_URL is missing", file=sys.stderr)
        return 1
    try:
        runtime_environment = dict(os.environ)
        configuration = load_weekly_configuration(
            args.weekly_config,
            repository_root=ROOT,
        )
        if args.capture_provider_data and args.operation != "weekly_audit":
            if args.provider_confirmation != "CAPTURE_V3_PROVIDER_PAYLOADS":
                print("provider capture requires the exact confirmation", file=sys.stderr)
                return 2
            if (
                runtime_environment.get(
                    "CFB_V3_PROVIDER_CONNECTIVITY_AUTHORIZED", ""
                ).casefold()
                != "true"
            ):
                print("provider capture rejected: connectivity is not authorized", file=sys.stderr)
                return 1
            evidence_parent = ROOT / "data" / "provider_evidence"
            evidence_parent.mkdir(parents=True, exist_ok=True)
            evidence_directory = evidence_parent / (
                f"cloud-{args.operation}-{uuid.uuid4().hex}"
            )
            capture_scope = (
                "postgame" if args.operation == "postgame_grading" else "pregame"
            )
            line_type = _capture_line_type(runtime_mode, args.operation)
            captured_at = datetime.now(timezone.utc)
            provider_bundle = capture_live_provider_bundle(
                runtime_environment,
                repository_root=ROOT,
                output_directory=evidence_directory,
                season=configuration.season,
                week=configuration.week,
                line_type=line_type,
                capture_scope=capture_scope,
                authorized=True,
                captured_at=captured_at,
            )
            runtime_environment["CFB_V3_PROVIDER_CONNECTIVITY_VERIFIED_AT"] = (
                captured_at.isoformat()
            )
            configuration = replace(
                configuration,
                provider_bundle_path=provider_bundle,
            )
        environment = merge_weekly_environment(runtime_environment, configuration)
        settings = load_production_settings(
            environment,
            repository_root=ROOT,
            operation=args.operation,
        )
        store = PostgreSQLSnapshotStore(database_url)
        result, preflight = execute_cloud_production_operation(
            store,
            settings,
            configuration,
            code_commit_sha=_commit_sha(),
        )
        if not _write_json(args.preflight_output, asdict(preflight)):
            return 2
        result_payload = asdict(result)
        if not _write_json(args.result_output, result_payload):
            return 2
        print(json.dumps(result_payload, sort_keys=True, separators=(",", ":")))
        if runtime_mode == "shadow" and args.operation == "weekly_audit":
            report = result_payload["operation"].get("shadow_rehearsal_report")
            if not isinstance(report, dict) or report.get("successful") is not True:
                print(
                    "shadow operation rejected: final rehearsal acceptance gates are unmet",
                    file=sys.stderr,
                )
                return 1
        return 0
    except (
        CloudPersistenceError,
        ProductionProviderError,
        OSError,
        sqlite3.Error,
        subprocess.SubprocessError,
        RuntimeError,
        ValueError,
    ) as exc:
        message = str(exc)
        if database_url and database_url in message:
            message = message.replace(database_url, "<redacted>")
        print(f"production operation rejected: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
