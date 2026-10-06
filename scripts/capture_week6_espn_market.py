"""Capture ESPN scoreboard's displayed DraftKings lines as context, never locks."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

import requests

from scripts.capture_week6_context import RAW


URL = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
PARAMS = {"dates": "2026", "week": 6, "limit": 500, "groups": 80}


def number(value: object) -> float | None:
    try:
        return float(str(value).lstrip("ou"))
    except (TypeError, ValueError):
        return None


def main() -> None:
    if not RAW.is_dir():
        raise RuntimeError("context capture must run first")
    retrieved = datetime.now(timezone.utc).isoformat()
    response = requests.get(URL, params=PARAMS, timeout=30)
    response.raise_for_status()
    raw = response.content
    (RAW / "espn-week6-scoreboard-raw.json").write_bytes(raw)
    rows = []
    for event in response.json().get("events", []):
        competition = event["competitions"][0]
        entries = [item for item in competition.get("odds", [])
                   if item.get("provider", {}).get("name") == "DraftKings"]
        if len(entries) > 1:
            raise ValueError(f"duplicate DraftKings context for {event['id']}")
        odds = entries[0] if entries else {}
        spread = odds.get("pointSpread", {}).get("home", {}).get("close", {}).get("line")
        total = odds.get("total", {}).get("over", {}).get("close", {}).get("line")
        current_spread, current_total = number(spread), number(total)
        rows.append({"game_id": int(event["id"]), "home": next(
            item["team"]["displayName"] for item in competition["competitors"]
            if item["homeAway"] == "home"),
            "away": next(item["team"]["displayName"] for item in competition["competitors"]
                         if item["homeAway"] == "away"),
            "market_provider": "DraftKings via ESPN", "retrieved_at": retrieved,
            "provider_observation_timestamp": None,
            "current_home_spread": current_spread,
            "current_total": current_total,
            "status": "OBSERVED_UNTIMESTAMPED" if current_spread is not None and current_total is not None
            else "MISSING_MARKET"})
    rows.sort(key=lambda row: row["game_id"])
    (RAW / "espn-draftkings-current.json").write_text(json.dumps(rows, indent=2) + "\n")
    manifest = json.loads((RAW / "capture-manifest.json").read_text())
    manifest["requests"].append({"name": "espn-draftkings-current", "provider": "ESPN",
        "underlying_market_provider": "DraftKings", "endpoint": URL, "parameters": PARAMS,
        "requested_at": retrieved, "raw_path": "espn-week6-scoreboard-raw.json",
        "raw_sha256": hashlib.sha256(raw).hexdigest(),
        "summary_path": "espn-draftkings-current.json", "records": len(rows),
        "complete_market_events": sum(row["status"] == "OBSERVED_UNTIMESTAMPED" for row in rows),
        "status": "CAPTURED"})
    (RAW / "capture-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"events": len(rows), "complete_market_events":
                      sum(row["status"] == "OBSERVED_UNTIMESTAMPED" for row in rows)}))


if __name__ == "__main__":
    main()
