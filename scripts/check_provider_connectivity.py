"""Run minimal credential-safe provider auth checks after explicit authorization."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from operations.providers import (
    ProductionProviderError,
    run_controlled_connectivity_checks,
)


CONFIRMATION = "AUTHORIZE_V3_CONNECTIVITY"
ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.confirmation != CONFIRMATION:
        print("live connectivity authorization phrase is invalid", file=sys.stderr)
        return 2
    output = args.output.resolve()
    if (
        ROOT.name != "cfb-betting-system-v3"
        or not output.is_relative_to(ROOT)
        or output.exists()
        or not output.parent.is_dir()
    ):
        print(
            "output must be a new file in an existing V3 directory",
            file=sys.stderr,
        )
        return 2
    try:
        report = run_controlled_connectivity_checks(
            os.environ,
            season=args.season,
            authorized=True,
        )
    except ProductionProviderError as exc:
        print(f"connectivity rejected: {exc}", file=sys.stderr)
        return 1
    output.write_text(
        json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        f"connectivity=passed\nchecked_at={report['checked_at']}\n"
        f"report_sha256={report['report_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
