"""Initialize one isolated managed shadow-week stream from the governed seed."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

from operations.cloud_persistence import CloudPersistenceError, PostgreSQLSnapshotStore
from operations.config import EXPECTED_REPOSITORY
from operations.database_cutover import DatabaseCutoverError, migrate_and_register


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_CONFIRMATION = "INITIALIZE_V3_CLOUD_SHADOW_REHEARSAL"


def _commit_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip().casefold()


def _stream_key(season: int, week: int) -> str:
    return f"{EXPECTED_REPOSITORY}:shadow:{season}:week:{week}"


def _safe_shadow_environment(environment: dict[str, str]) -> bool:
    expected = {
        "CFB_V3_RUNTIME_MODE": "shadow",
        "CFB_V3_PRODUCTION_ENABLED": "false",
        "CFB_V3_OPERATION_EXECUTION_ENABLED": "false",
        "CFB_V3_KILL_SWITCH": "true",
        "CFB_V3_OWNER_CUTOVER_APPROVED": "false",
        "CFB_V3_SHADOW_REHEARSAL_ENABLED": "true",
        "CFB_V3_SHADOW_OPERATION_EXECUTION_ENABLED": "true",
        "CFB_V3_SHADOW_KILL_SWITCH": "false",
    }
    return all(environment.get(name, "").strip().casefold() == value for name, value in expected.items())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True, type=Path)
    parser.add_argument("--policy-config", required=True, type=Path)
    parser.add_argument("--season", required=True, type=int)
    parser.add_argument("--week", required=True, type=int)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--report-output", type=Path)
    args = parser.parse_args(argv)
    if args.confirmation != BOOTSTRAP_CONFIRMATION:
        print("shadow initialization requires the exact confirmation", file=sys.stderr)
        return 2
    if args.season < 1869 or not 0 <= args.week <= 20:
        print("shadow initialization requires a valid season/week", file=sys.stderr)
        return 2
    environment = dict(os.environ)
    if not _safe_shadow_environment(environment):
        print(
            "shadow initialization rejected: shadow guards or production isolation are unsafe",
            file=sys.stderr,
        )
        return 1
    database_url = environment.get("CFB_V3_DATABASE_URL", "")
    if not database_url.strip():
        print("shadow initialization rejected: CFB_V3_DATABASE_URL is missing", file=sys.stderr)
        return 1
    try:
        with tempfile.TemporaryDirectory(prefix="cfb-v3-cloud-shadow-bootstrap-") as directory:
            prepared = Path(directory) / "cfb.db"
            cutover = migrate_and_register(
                args.seed,
                prepared,
                args.policy_config,
                authoritative=False,
            )
            store = PostgreSQLSnapshotStore(database_url)
            migrations_applied = store.apply_migrations()
            stream_key = _stream_key(args.season, args.week)
            commit = store.bootstrap(
                prepared,
                stream_key=stream_key,
                actor=args.actor,
                code_commit_sha=_commit_sha(),
                metadata={
                    "execution_profile": "shadow",
                    "season": args.season,
                    "week": args.week,
                    "source_sha256": cutover.source_sha256_before,
                    "prepared_sha256": cutover.target_sha256_after,
                    "cutover_report_sha256": cutover.report_sha256,
                    "migration_inventory": cutover.migration_inventory,
                    "registered_policy_versions": cutover.registered_policy_versions,
                    "wagers_placed": 0,
                },
            )
        payload = {
            "execution_profile": "shadow",
            "persistence_backend": "managed_postgresql",
            "stream_key": stream_key,
            "cloud_migrations_applied": migrations_applied,
            "snapshot": asdict(commit.snapshot),
            "replayed": commit.replayed,
            "state_changed": commit.state_changed,
            "source_database_unchanged": cutover.source_unchanged,
            "source_sha256_before": cutover.source_sha256_before,
            "source_sha256_after": cutover.source_sha256_after,
            "runner_state_disposable": True,
            "live_api_calls": 0,
            "wagers_placed": 0,
        }
        if args.report_output is not None:
            output = args.report_output.resolve()
            if not output.parent.is_dir():
                print("report output parent does not exist", file=sys.stderr)
                return 2
            output.write_text(
                json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
        print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return 0
    except (
        CloudPersistenceError,
        DatabaseCutoverError,
        OSError,
        sqlite3.Error,
        subprocess.SubprocessError,
        ValueError,
    ) as exc:
        message = str(exc)
        if database_url and database_url in message:
            message = message.replace(database_url, "<redacted>")
        print(f"shadow initialization rejected: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
