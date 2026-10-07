"""Capture replayable Week 6 CFBD schedule, identities, and pregame EPA."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests


ROOT = Path(__file__).resolve().parents[1]
BASE = "https://api.collegefootballdata.com"
SPECS = (
    ("cfbd-2026-games", "/games", {"year": 2026, "classification": "fbs"}),
    ("cfbd-2026-fbs-teams", "/teams/fbs", {"year": 2026}),
    ("cfbd-week5-advanced", "/stats/season/advanced",
     {"year": 2026, "endWeek": 5, "excludeGarbageTime": "true"}),
)


def _key() -> str:
    if os.environ.get("CFBD_API_KEY"):
        return os.environ["CFBD_API_KEY"]
    for env_path in (ROOT / ".env", ROOT.parents[1] / ".env"):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("CFBD_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError("CFBD_API_KEY is missing")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-directory", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_directory.resolve()
    if not output.is_relative_to(ROOT) or output.exists() or not output.parent.is_dir():
        parser.error("output must be a new directory inside this isolated worktree")
    output.mkdir()
    manifest: list[dict[str, object]] = []
    session = requests.Session()
    key = _key()
    for name, endpoint, params in SPECS:
        requested_at = datetime.now(timezone.utc).isoformat()
        try:
            response = session.get(
                BASE + endpoint,
                headers={"Authorization": f"Bearer {key}"},
                params=params,
                timeout=40,
            )
            response.raise_for_status()
            records = response.json()
        except requests.RequestException as exc:
            raise RuntimeError(f"CFBD capture failed for {name}: {type(exc).__name__}") from None
        if not isinstance(records, list):
            raise RuntimeError(f"CFBD capture returned a non-list for {name}")
        raw = json.dumps(records, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        filename = f"{name}.json"
        (output / filename).write_bytes(raw)
        manifest.append({
            "name": name, "endpoint": BASE + endpoint,
            "parameters": params, "requested_at": requested_at,
            "path": filename, "sha256": hashlib.sha256(raw).hexdigest(),
            "records": len(records), "status": "captured",
        })
    (output / "capture-manifest.json").write_text(
        json.dumps({"requests": manifest}, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({item["name"]: item["records"] for item in manifest}))


if __name__ == "__main__":
    main()
