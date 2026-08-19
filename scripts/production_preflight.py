"""Run the read-only, fail-closed V3 production cutover preflight."""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

from operations import (
    PRODUCTION_OPERATIONS,
    load_production_settings,
    run_production_preflight,
)


ROOT = Path(__file__).resolve().parents[1]


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Verify V3 production configuration, database, workflow, policy, "
            "line-lock, and kill-switch readiness without writing or calling APIs."
        )
    )
    parser.add_argument("--operation", required=True, choices=PRODUCTION_OPERATIONS)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Return zero after emitting a truthful not-ready report.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_production_settings(
        os.environ,
        repository_root=ROOT,
        operation=args.operation,
        database_path=args.database,
    )
    report = run_production_preflight(settings)
    payload = asdict(report)
    text = json.dumps(
        payload,
        sort_keys=True,
        indent=2 if args.pretty else None,
        separators=None if args.pretty else (",", ":"),
    )
    if args.output is not None:
        output = args.output.resolve()
        if not output.parent.is_dir():
            raise SystemExit("preflight output parent directory does not exist")
        output.write_text(text + "\n", encoding="utf-8")
    print(text)
    if report.production_ready or args.report_only:
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
