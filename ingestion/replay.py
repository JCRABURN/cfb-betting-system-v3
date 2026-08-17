"""Replay a recorded provider fixture into a disposable SQLite database.

This command never performs network access and deliberately refuses to write to
the repository's authoritative ``data/cfb.db``.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

import db
from ingestion.custody import (
    IngestionRequest,
    OddsSpreadParser,
    ProviderIngestionService,
)
from migrations.runner import apply_migrations


def _request_parameters(values: list[str]) -> dict[str, object]:
    parameters: dict[str, object] = {}
    for value in values:
        key, separator, raw_value = value.partition("=")
        if not separator or not key.strip():
            raise ValueError(f"request parameter must be KEY=VALUE: {value}")
        try:
            parsed: object = json.loads(raw_value)
        except json.JSONDecodeError:
            parsed = raw_value
        parameters[key.strip()] = parsed
    return parameters


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--provider", default="fixture_odds")
    parser.add_argument("--endpoint", default="fixture://odds/spreads")
    parser.add_argument("--requested-at", required=True)
    parser.add_argument("--parser-version", default="odds_spread_v1")
    parser.add_argument("--expected-sha256")
    parser.add_argument(
        "--request-parameter",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="non-secret request metadata; credential-named keys are removed from custody",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database = args.database.resolve()
    authoritative = Path(db.DB_PATH).resolve()
    if database == authoritative:
        raise SystemExit("refusing to replay a fixture into authoritative data/cfb.db")
    if not args.fixture.is_file():
        raise SystemExit(f"fixture does not exist: {args.fixture}")

    try:
        parameters = _request_parameters(args.request_parameter)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    payload = args.fixture.read_bytes()
    database.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        apply_migrations(conn)
        request = IngestionRequest(
            provider=args.provider,
            endpoint=args.endpoint,
            request_parameters=parameters,
            requested_at=args.requested_at,
            parser_version=args.parser_version,
            raw_payload_reference=f"fixture:{args.fixture.resolve()}",
            data_type="odds",
            expected_payload_sha256=args.expected_sha256,
        )
        summary = ProviderIngestionService().ingest_payload(
            conn,
            request,
            payload,
            OddsSpreadParser(args.parser_version),
        )
    finally:
        conn.close()

    print(json.dumps(asdict(summary), sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
