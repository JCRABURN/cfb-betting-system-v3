"""Capture replayable, timestamped Week 7 pregame schedule and Week 6 EPA inputs.

This writes only to a new isolated output directory. It does not ingest lines,
run models, or touch the source database. Capture may run before lock receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests

from scripts.capture_week6_core import BASE, ROOT, _key


SPECS = (
    ("cfbd-2026-games", "/games", {"year": 2026, "classification": "fbs"}),
    ("cfbd-2026-fbs-teams", "/teams/fbs", {"year": 2026}),
    ("cfbd-week6-advanced", "/stats/season/advanced",
     {"year": 2026, "endWeek": 6, "excludeGarbageTime": "true"}),
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def capture(output: Path, *, session: requests.Session | None = None) -> dict:
    output = output.resolve()
    if not output.is_relative_to(ROOT) or output.exists() or not output.parent.is_dir():
        raise ValueError("capture target must be a new directory inside this worktree")
    output.mkdir()
    session = session or requests.Session()
    key = _key()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    manifest = []
    try:
        for name, endpoint, params in SPECS:
            requested = utc_now()
            response = session.get(BASE + endpoint, headers={"Authorization": f"Bearer {key}"},
                                   params=params, timeout=40)
            response.raise_for_status()
            received = utc_now()
            records = response.json()
            if not isinstance(records, list):
                raise ValueError(f"non-list CFBD response: {name}")
            payload = json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            filename = f"{name}.json"
            (output / filename).write_bytes(payload)
            manifest.append({"name": name, "provider": "collegefootballdata",
                             "endpoint": BASE + endpoint, "parameters": params,
                             "requested_at_utc": requested, "received_at_utc": received,
                             "path": filename, "sha256": hashlib.sha256(payload).hexdigest(),
                             "records": len(records), "status": "captured"})
    except Exception:
        # Preserve partial captures and their timestamps for forensic review.
        (output / "capture-manifest.json").write_text(
            json.dumps({"status": "INCOMPLETE", "requests": manifest}, indent=2) + "\n",
            encoding="utf-8", newline="\n")
        raise
    result = {"status": "COMPLETE", "captured_at_utc": utc_now(),
              "code_commit_sha": commit, "requests": manifest}
    (output / "capture-manifest.json").write_text(
        json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    result = capture(args.output_directory)
    print(json.dumps({item["name"]: item["records"] for item in result["requests"]}))


if __name__ == "__main__":
    main()
