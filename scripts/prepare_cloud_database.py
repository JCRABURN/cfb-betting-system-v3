"""Initialize the managed production stream from a governed SQLite seed."""

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

from operations.cloud_execution import PRODUCTION_STREAM_KEY
from operations.cloud_persistence import CloudPersistenceError, PostgreSQLSnapshotStore
from operations.database_cutover import DatabaseCutoverError, migrate_and_register


ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_CONFIRMATION = "INITIALIZE_V3_CLOUD_STATE"


def _commit_sha() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip().casefold()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", required=True, type=Path)
    parser.add_argument("--policy-config", required=True, type=Path)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--report-output", type=Path)
    args = parser.parse_args(argv)
    if args.confirmation != BOOTSTRAP_CONFIRMATION:
        print("cloud initialization requires the exact confirmation", file=sys.stderr)
        return 2
    database_url = os.environ.get("CFB_V3_DATABASE_URL", "")
    if not database_url.strip():
        print("cloud initialization rejected: CFB_V3_DATABASE_URL is missing", file=sys.stderr)
        return 1
    try:
        with tempfile.TemporaryDirectory(prefix="cfb-v3-cloud-bootstrap-") as directory:
            prepared = Path(directory) / "cfb.db"
            cutover = migrate_and_register(
                args.seed,
                prepared,
                args.policy_config,
                authoritative=False,
            )
            store = PostgreSQLSnapshotStore(database_url)
            migrations_applied = store.apply_migrations()
            commit = store.bootstrap(
                prepared,
                stream_key=PRODUCTION_STREAM_KEY,
                actor=args.actor,
                code_commit_sha=_commit_sha(),
                metadata={
                    "source_sha256": cutover.source_sha256_before,
                    "prepared_sha256": cutover.target_sha256_after,
                    "cutover_report_sha256": cutover.report_sha256,
                    "migration_inventory": cutover.migration_inventory,
                    "registered_policy_versions": cutover.registered_policy_versions,
                },
            )
        payload = {
            "persistence_backend": "managed_postgresql",
            "stream_key": PRODUCTION_STREAM_KEY,
            "cloud_migrations_applied": migrations_applied,
            "snapshot": asdict(commit.snapshot),
            "replayed": commit.replayed,
            "state_changed": commit.state_changed,
            "source_database_unchanged": cutover.source_unchanged,
            "source_sha256_before": cutover.source_sha256_before,
            "source_sha256_after": cutover.source_sha256_after,
            "runner_state_disposable": True,
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
        print(f"cloud initialization rejected: {message}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
