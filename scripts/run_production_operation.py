"""Guard every V3 operating stage; no live execution adapter is enabled yet."""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from operations import (
    PRODUCTION_OPERATIONS,
    load_production_settings,
    run_production_preflight,
)


ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply all V3 cutover guards before an operating-stage mutation."
    )
    parser.add_argument("--operation", required=True, choices=PRODUCTION_OPERATIONS)
    parser.add_argument("--database", type=Path)
    parser.add_argument("--preflight-output", type=Path)
    args = parser.parse_args(argv)

    settings = load_production_settings(
        os.environ,
        repository_root=ROOT,
        operation=args.operation,
        database_path=args.database,
    )
    report = run_production_preflight(settings)
    payload = json.dumps(asdict(report), sort_keys=True, separators=(",", ":"))
    if args.preflight_output is not None:
        output = args.preflight_output.resolve()
        if not output.parent.is_dir():
            print(
                "preflight output parent directory does not exist",
                file=sys.stderr,
            )
            return 2
        output.write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if not report.production_ready:
        print(report.production_ready_status, file=sys.stderr)
        return 1

    print(
        "Production mutation refused: no owner-authorized live execution adapter "
        "or persistence step is installed.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
