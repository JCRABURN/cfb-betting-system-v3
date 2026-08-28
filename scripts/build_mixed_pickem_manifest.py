"""Build and export a Product B review manifest without approving or locking it."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from mixed_pickem import ManifestBuildRequest, build_manifest
from mixed_pickem.common import MixedPickemValidationError, utc_datetime


def _timestamp(value: str) -> datetime:
    try:
        return utc_datetime(datetime.fromisoformat(value), "timestamp")
    except (MixedPickemValidationError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            "timestamp must be an ISO-8601 value with an explicit UTC offset"
        ) from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Import a governed CSV/XLSX source into an existing Product B round "
            "and export its deterministic review manifest. This command cannot "
            "approve a manifest or lock contest lines."
        )
    )
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--media-type", required=True, choices=("CSV", "XLSX"))
    parser.add_argument("--worksheet")
    parser.add_argument("--contest-round-id", required=True, type=int)
    parser.add_argument("--import-key", required=True)
    parser.add_argument("--resolution-window-start", required=True, type=_timestamp)
    parser.add_argument("--resolution-window-end", required=True, type=_timestamp)
    parser.add_argument("--received-at", required=True, type=_timestamp)
    parser.add_argument("--imported-at", required=True, type=_timestamp)
    parser.add_argument("--generated-at", required=True, type=_timestamp)
    parser.add_argument("--actor", required=True)
    parser.add_argument("--provenance", required=True)
    parser.add_argument("--source-event-provider")
    parser.add_argument("--alias-provider", default="mixed_pickem_admin")
    parser.add_argument("--expected-source-row-count", type=int)
    parser.add_argument("--review-output", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    database = args.database.resolve()
    source = args.source.resolve()
    review_output = args.review_output.resolve()
    if not database.is_file():
        raise SystemExit("database must be an existing explicitly selected file")
    if review_output.exists():
        raise SystemExit("review output already exists; choose a new immutable path")
    if args.media_type == "XLSX" and not args.worksheet:
        raise SystemExit("--worksheet is required for XLSX; worksheet guessing is forbidden")
    if args.media_type == "CSV" and args.worksheet:
        raise SystemExit("--worksheet is valid only for XLSX")

    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=rw", uri=True)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        version = connection.execute(
            "SELECT MAX(version) FROM schema_migrations"
        ).fetchone()
        if version is None or version[0] is None or int(version[0]) < 20:
            raise SystemExit("database must have migration 20 applied explicitly")
        with connection:
            result = build_manifest(
                connection,
                ManifestBuildRequest(
                    source_path=source,
                    media_type=args.media_type,
                    worksheet=args.worksheet,
                    contest_round_id=args.contest_round_id,
                    import_key=args.import_key,
                    resolution_window_start_at=args.resolution_window_start,
                    resolution_window_end_at=args.resolution_window_end,
                    received_at=args.received_at,
                    imported_at=args.imported_at,
                    generated_at=args.generated_at,
                    actor=args.actor,
                    provenance=args.provenance,
                    expected_source_row_count=args.expected_source_row_count,
                    source_event_provider=args.source_event_provider,
                    alias_provider=args.alias_provider,
                ),
            )
    finally:
        connection.close()

    review_output.parent.mkdir(parents=True, exist_ok=True)
    with review_output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(result.review, output, indent=2, sort_keys=True)
        output.write("\n")
    print(
        json.dumps(
            {
                "accepted_count": result.accepted_count,
                "ambiguous_count": result.ambiguous_count,
                "deadline": result.earliest_kickoff_at,
                "duplicate_count": result.duplicate_count,
                "manifest_id": result.manifest_id,
                "manifest_sha256": result.manifest_sha256,
                "rejected_count": result.rejected_count,
                "review_output": review_output.name,
                "source_row_count": result.source_row_count,
                "source_sha256": result.source_sha256,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
