"""Run the deterministic Milestone 16 rehearsal without source-database writes."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from business_entities.historical_rehearsal import run_historical_rehearsal


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay 2024 Week 15 in memory through official cards, audit, and "
            "weekly diagnostics."
        )
    )
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--code-commit-sha", required=True)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = run_historical_rehearsal(
            args.database,
            code_commit_sha=args.code_commit_sha,
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    payload = asdict(report)
    payload["successful"] = report.successful
    print(
        json.dumps(
            payload,
            sort_keys=True,
            indent=2 if args.pretty else None,
            separators=None if args.pretty else (",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
