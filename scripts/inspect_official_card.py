"""Read-only inspection for one authoritative official-card publication."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote

from business_entities.weekly_controller import inspect_official_card


def _read_only_connection(database: Path) -> sqlite3.Connection:
    resolved = database.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"database does not exist: {resolved}")
    uri = f"file:{quote(resolved.as_posix(), safe='/:')}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA query_only = ON")
    return conn


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inspect and reproduce an official card without database writes."
    )
    parser.add_argument("--database", type=Path, required=True)
    identity = parser.add_mutually_exclusive_group(required=True)
    identity.add_argument("--publication-id", type=int)
    identity.add_argument("--publication-key")
    args = parser.parse_args(argv)

    try:
        conn = _read_only_connection(args.database)
        try:
            inspection = inspect_official_card(
                conn,
                publication_id=args.publication_id,
                publication_key=args.publication_key,
            )
        finally:
            conn.close()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    payload = {
        "publication": asdict(inspection.publication),
        "controller_run": asdict(inspection.controller_run),
        "card": asdict(inspection.card),
        "picks": [asdict(pick) for pick in inspection.picks],
        "manifest": asdict(inspection.manifest),
        "freshness": [asdict(item) for item in inspection.freshness],
        "sportsbook_recommendations": [
            asdict(item) for item in inspection.sportsbook_recommendations
        ],
        "line_batch": asdict(inspection.line_batch),
        "verification": {
            **asdict(inspection.completeness_report),
            "publication_manifest_matches": inspection.publication_manifest_matches,
            "publication_counts_match": inspection.publication_counts_match,
            "is_latest_official_version": inspection.is_latest_official_version,
            "valid": inspection.valid,
        },
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if inspection.valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
