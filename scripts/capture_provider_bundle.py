"""Capture replayable live provider evidence after explicit owner authorization."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from operations.providers import ProductionProviderError, capture_live_provider_bundle


ROOT = Path(__file__).resolve().parents[1]
CONFIRMATION = "CAPTURE_V3_PROVIDER_PAYLOADS"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--week", type=int, required=True)
    parser.add_argument("--line-type", choices=("opening", "current", "closing"), required=True)
    parser.add_argument(
        "--capture-scope", choices=("pregame", "postgame"), default="pregame"
    )
    parser.add_argument("--output-directory", type=Path, required=True)
    parser.add_argument("--confirmation", required=True)
    args = parser.parse_args(argv)
    if args.confirmation != CONFIRMATION:
        print("live provider capture authorization phrase is invalid", file=sys.stderr)
        return 2
    try:
        bundle = capture_live_provider_bundle(
            os.environ,
            repository_root=ROOT,
            output_directory=args.output_directory,
            season=args.season,
            week=args.week,
            line_type=args.line_type,
            capture_scope=args.capture_scope,
            authorized=True,
            captured_at=datetime.now(timezone.utc),
        )
    except ProductionProviderError as exc:
        print(f"provider capture rejected: {exc}", file=sys.stderr)
        return 1
    print(f"provider_bundle={bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
