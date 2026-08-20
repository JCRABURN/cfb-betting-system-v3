"""Rehearse or explicitly approve the governed V3 database cutover."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from operations.database_cutover import DatabaseCutoverError, migrate_and_register


ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE = (ROOT / "data" / "cfb.db").resolve()
AUTHORITATIVE_CONFIRMATION = "MIGRATE_V3_AUTHORITATIVE_DATABASE"


def _inside_original_repository(path: Path) -> bool:
    return any(parent.name.casefold() == "cfb-betting-system" for parent in (path, *path.parents))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=AUTHORITATIVE)
    parser.add_argument("--policy-config", type=Path, required=True)
    parser.add_argument("--rehearsal-output", type=Path)
    parser.add_argument("--apply-authoritative", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--confirmation")
    parser.add_argument("--report-output", type=Path)
    args = parser.parse_args(argv)
    if args.apply_authoritative == (args.rehearsal_output is not None):
        print(
            "choose exactly one of --rehearsal-output or --apply-authoritative",
            file=sys.stderr,
        )
        return 2
    source = args.source.resolve()
    requested_paths = [source]
    if args.rehearsal_output is not None:
        requested_paths.append(args.rehearsal_output.resolve())
    if args.backup is not None:
        requested_paths.append(args.backup.resolve())
    if ROOT.name != "cfb-betting-system-v3" or any(
        _inside_original_repository(path) for path in requested_paths
    ):
        print("database cutover is restricted away from the original repository", file=sys.stderr)
        return 2
    if args.apply_authoritative:
        guards = (
            ROOT.name == "cfb-betting-system-v3",
            source == AUTHORITATIVE,
            args.confirmation == AUTHORITATIVE_CONFIRMATION,
            os.environ.get("CFB_V3_OWNER_DATABASE_MIGRATION_APPROVED") == "true",
            os.environ.get("CFB_V3_KILL_SWITCH") == "true",
            os.environ.get("CFB_V3_OPERATION_EXECUTION_ENABLED") == "false",
            os.environ.get("CFB_V3_PRODUCTION_ENABLED") == "false",
            args.backup is not None,
        )
        if not all(guards):
            print(
                "authoritative migration requires the exact V3 path, confirmation, "
                "owner migration approval, engaged kill switch, disabled execution "
                "and production flags, and a new backup path",
                file=sys.stderr,
            )
            return 2
        target = source
    else:
        assert args.rehearsal_output is not None
        target = args.rehearsal_output.resolve()
    try:
        report = migrate_and_register(
            source,
            target,
            args.policy_config,
            authoritative=args.apply_authoritative,
            backup_path=args.backup,
        )
    except (OSError, DatabaseCutoverError, sqlite3.Error) as exc:
        print(f"database cutover rejected: {exc}", file=sys.stderr)
        return 1
    payload = asdict(report)
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


if __name__ == "__main__":
    raise SystemExit(main())
