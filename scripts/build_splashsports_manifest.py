"""Build one validated SplashSports lock manifest from manual weekly input."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

from operations.splashsports import (
    SUPPORTED_INPUT_FORMATS,
    SplashSportsImportError,
    SplashSportsImportRequest,
    build_splashsports_manifest,
)


ROOT = Path(__file__).resolve().parents[1]


def _utc(value: str) -> datetime:
    raw = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(raw)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must be timezone-aware UTC")
    converted = parsed.astimezone(timezone.utc)
    if parsed.utcoffset().total_seconds() != 0:
        raise argparse.ArgumentTypeError("timestamp must use a UTC offset")
    return converted


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(path.resolve().as_posix(), safe='/:')}?mode=ro"
    connection = sqlite3.connect(uri, uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--input-format", choices=SUPPORTED_INPUT_FORMATS, required=True)
    parser.add_argument("--database", type=Path, default=Path("data/cfb.db"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--contest-key", required=True)
    parser.add_argument("--contest-name", required=True)
    parser.add_argument("--source-contest-id", required=True)
    parser.add_argument("--expected-lined-game-count", type=int, required=True)
    parser.add_argument("--captured-at", type=_utc, required=True)
    parser.add_argument("--imported-by", required=True)
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--screenshot-evidence", type=Path, action="append", default=[])
    parser.add_argument("--screenshot-reviewed-by")
    parser.add_argument("--screenshot-reviewed-at", type=_utc)
    args = parser.parse_args(argv)

    output = args.output.resolve()
    database = args.database.resolve()
    if ROOT.name != "cfb-betting-system-v3":
        print("manual import is restricted to the V3 repository", file=sys.stderr)
        return 2
    if not output.is_relative_to(ROOT) or not database.is_relative_to(ROOT):
        print("output and database must remain inside the V3 repository", file=sys.stderr)
        return 2
    if output.exists():
        print("output already exists; immutable manifests are never overwritten", file=sys.stderr)
        return 2
    if not output.parent.is_dir():
        print("output parent directory does not exist", file=sys.stderr)
        return 2
    try:
        connection = _read_only_connection(database)
        try:
            manifest = build_splashsports_manifest(
                connection,
                SplashSportsImportRequest(
                    source_path=args.input,
                    input_format=args.input_format,
                    season=args.season,
                    week=args.week,
                    contest_key=args.contest_key,
                    contest_name=args.contest_name,
                    source_contest_id=args.source_contest_id,
                    expected_lined_game_count=args.expected_lined_game_count,
                    captured_at=args.captured_at,
                    imported_by=args.imported_by,
                    provenance=args.provenance,
                    screenshot_evidence_paths=tuple(args.screenshot_evidence),
                    screenshot_reviewed_by=args.screenshot_reviewed_by,
                    screenshot_reviewed_at=args.screenshot_reviewed_at,
                ),
            )
        finally:
            connection.close()
    except (OSError, sqlite3.Error, SplashSportsImportError) as exc:
        print(f"SplashSports import rejected: {exc}", file=sys.stderr)
        return 1
    output.write_text(manifest.canonical_json, encoding="utf-8")
    print(
        f"manifest={output}\nsha256={manifest.sha256}\n"
        f"parsed_line_count={manifest.parsed_line_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
