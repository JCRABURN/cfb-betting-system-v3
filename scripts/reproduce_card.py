"""Read-only deterministic replay of a prior card from persisted run identifiers."""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from business_entities.common import BusinessEntityError
from business_entities.contextual_adjustments import (
    get_card_adjustment_policy,
    list_card_adjustment_snapshots,
    list_pick_adjustment_items,
)
from business_entities.reproducibility import (
    get_card_run_manifest,
    list_card_adjustment_history,
    reproduce_card,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "cfb.db"


def _read_only_connection(database: Path) -> sqlite3.Connection:
    resolved = database.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"database does not exist: {resolved}")
    conn = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA query_only = ON")
    return conn


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Reproduce and verify a prior contest card without changing the database."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=DEFAULT_DATABASE,
        help="SQLite database to open in read-only mode",
    )
    parser.add_argument("--card-key", required=True, help="immutable contest card key")
    parser.add_argument(
        "--model-run-key",
        required=True,
        help="immutable model run key recorded by the card",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        conn = _read_only_connection(args.database)
        try:
            result = reproduce_card(
                conn,
                card_key=args.card_key,
                model_run_key=args.model_run_key,
            )
            manifest = get_card_run_manifest(conn, result.card.id)
            adjustments = list_card_adjustment_history(conn, result.card.id)
            adjustment_policy = get_card_adjustment_policy(conn, result.card.id)
            adjustment_snapshots = list_card_adjustment_snapshots(
                conn, result.card.id
            )
            verification = asdict(result.report)
            verification.update(
                side_complete=result.report.side_complete,
                contest_complete=result.report.contest_complete,
                official_ready=result.report.official_ready,
            )
            payload = {
                "card": asdict(result.card),
                "model_run_key": args.model_run_key,
                "manifest": asdict(manifest),
                "adjustment_history": [
                    asdict(adjustment) for adjustment in adjustments
                ],
                "adjustment_policy": asdict(adjustment_policy),
                "adjusted_projections": [
                    {
                        **asdict(snapshot),
                        "adjustment_items": [
                            asdict(item)
                            for item in list_pick_adjustment_items(
                                conn, snapshot.contest_pick_id
                            )
                        ],
                    }
                    for snapshot in adjustment_snapshots
                ],
                "picks": [asdict(pick) for pick in result.picks],
                "verification": verification,
            }
            print(
                json.dumps(
                    payload,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                )
            )
            return 0
        finally:
            conn.close()
    except (BusinessEntityError, FileNotFoundError, sqlite3.DatabaseError) as exc:
        print(f"Card reproduction failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
