"""Validate an owner-reviewed SplashSports model import and materialize its slate."""

from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from migrations.runner import MigrationError, apply_migrations
from operations.splashsports import (
    OWNER_MODEL_IMPORT_FORMAT,
    SplashSportsImportError,
    SplashSportsImportRequest,
    build_splashsports_manifest,
    ingest_owner_reviewed_schedule,
)


ROOT = Path(__file__).resolve().parents[1]


def _utc(value: str) -> datetime:
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must be timezone-aware UTC")
    if parsed.utcoffset().total_seconds() != 0:
        raise argparse.ArgumentTypeError("timestamp must use a UTC offset")
    return parsed.astimezone(timezone.utc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=Path("data/cfb.db"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--contest-key", required=True)
    parser.add_argument("--contest-name", required=True)
    parser.add_argument("--source-contest-id", required=True)
    parser.add_argument("--expected-lined-game-count", type=int, required=True)
    parser.add_argument("--captured-at", type=_utc, required=True)
    parser.add_argument("--imported-at", type=_utc, required=True)
    parser.add_argument("--imported-by", required=True)
    parser.add_argument("--provenance", required=True)
    args = parser.parse_args(argv)

    database = args.database.resolve()
    output = args.output.resolve()
    if not database.is_relative_to(ROOT) or not output.is_relative_to(ROOT):
        parser.error("database and output must remain inside this repository worktree")
    if output.exists():
        parser.error("output already exists; immutable manifests are never overwritten")
    if not output.parent.is_dir():
        parser.error("output parent directory does not exist")
    request = SplashSportsImportRequest(
        source_path=args.input,
        input_format=OWNER_MODEL_IMPORT_FORMAT,
        season=args.season,
        week=args.week,
        contest_key=args.contest_key,
        contest_name=args.contest_name,
        source_contest_id=args.source_contest_id,
        expected_lined_game_count=args.expected_lined_game_count,
        captured_at=args.captured_at,
        imported_by=args.imported_by,
        provenance=args.provenance,
    )
    conn = sqlite3.connect(database)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        applied = apply_migrations(conn)
        schedule = ingest_owner_reviewed_schedule(
            conn, request, imported_at=args.imported_at
        )
        manifest = build_splashsports_manifest(conn, request)
        output.write_text(manifest.canonical_json, encoding="utf-8")
        conn.commit()
    except (MigrationError, OSError, sqlite3.Error, SplashSportsImportError) as exc:
        conn.rollback()
        if output.exists():
            output.unlink()
        print(f"SplashSports owner import rejected: {exc}")
        return 1
    finally:
        conn.close()
    print(f"source_sha256={schedule.source_sha256}")
    print(f"requested_count={schedule.requested_count}")
    print(f"inserted_game_count={schedule.inserted_count}")
    print(f"existing_game_count={schedule.existing_count}")
    print(f"manifest={output}")
    print(f"manifest_sha256={manifest.sha256}")
    print(f"applied_migrations={[item.version for item in applied]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
