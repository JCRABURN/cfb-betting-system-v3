"""Capture replayable ESPN Week 5 final-score and game-summary evidence."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CARD = ROOT / "outputs/2026-week5-execution-20260930-v4/week5_ats_full_card.csv"
EVIDENCE = ROOT / "outputs/2026-week5-postgame-audit/provider-evidence"
SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/college-football/"
    "scoreboard?year=2026&week=5&seasontype=2&groups=80&limit=300"
)
SUMMARY_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/college-football/"
    "summary?event={}"
)
NCAA_SCOREBOARD_URL = "https://ncaa-api.henrygd.me/scoreboard/football/fbs/2026/05/all-conf"


def _fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "cfb-week5-audit/1.0"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read()
    return payload, datetime.now(timezone.utc).isoformat()


def _entry(url: str, payload: bytes, retrieved_at: str, path: str,
           provider: str = "ESPN") -> dict[str, object]:
    return {
        "provider": provider,
        "endpoint": url,
        "retrieved_at_utc": retrieved_at,
        "parser_version": "espn-week5-postgame-v1",
        "raw_sha256": hashlib.sha256(payload).hexdigest(),
        "raw_bytes": len(payload),
        "stored_gzip_path": path,
    }


def capture() -> dict[str, object]:
    with CARD.open(encoding="utf-8", newline="") as stream:
        card = list(csv.DictReader(stream))
    game_ids = [row["game_id"] for row in card]
    if len(game_ids) != 56 or len(set(game_ids)) != 56:
        raise ValueError("frozen ATS card must contain 56 unique game IDs")

    scoreboard_raw, scoreboard_at = _fetch(SCOREBOARD_URL)
    scoreboard = json.loads(scoreboard_raw)
    events = {str(event["id"]): event for event in scoreboard["events"]}
    missing = sorted(set(game_ids) - set(events))
    not_final = sorted(
        game_id for game_id in game_ids
        if game_id in events
        and not events[game_id]["status"]["type"].get("completed", False)
    )
    if missing or not_final:
        raise ValueError(f"scoreboard gate failed: missing={missing}, not_final={not_final}")
    ncaa_raw, ncaa_at = _fetch(NCAA_SCOREBOARD_URL)
    ncaa = json.loads(ncaa_raw)
    if len(ncaa.get("games", [])) < len(game_ids):
        raise ValueError("NCAA-derived scoreboard has too few games")

    def fetch_summary(game_id: str) -> tuple[str, bytes, str]:
        raw, fetched_at = _fetch(SUMMARY_URL.format(game_id))
        summary = json.loads(raw)
        competition = summary["header"]["competitions"][0]
        if str(competition["id"]) != game_id or not competition["status"]["type"].get("completed", False):
            raise ValueError(f"game {game_id} summary is not the matching completed game")
        return game_id, raw, fetched_at

    with ThreadPoolExecutor(max_workers=8) as executor:
        summaries = list(executor.map(fetch_summary, game_ids))

    EVIDENCE.mkdir(parents=True, exist_ok=True)
    scoreboard_path = EVIDENCE / "espn-week5-scoreboard.json.gz"
    scoreboard_path.write_bytes(gzip.compress(scoreboard_raw, mtime=0))
    ncaa_path = EVIDENCE / "ncaa-derived-week5-scoreboard.json.gz"
    ncaa_path.write_bytes(gzip.compress(ncaa_raw, mtime=0))
    entries = []
    for game_id, raw, fetched_at in sorted(summaries):
        path = EVIDENCE / f"espn-game-{game_id}.json.gz"
        path.write_bytes(gzip.compress(raw, mtime=0))
        entries.append(_entry(SUMMARY_URL.format(game_id), raw, fetched_at, path.relative_to(ROOT).as_posix()))
    manifest = {
        "capture_status": "complete",
        "provider": "ESPN",
        "scoreboard": _entry(SCOREBOARD_URL, scoreboard_raw, scoreboard_at, scoreboard_path.relative_to(ROOT).as_posix()),
        "ncaa_derived_scoreboard": _entry(NCAA_SCOREBOARD_URL, ncaa_raw, ncaa_at, ncaa_path.relative_to(ROOT).as_posix(), "NCAA_DATA_VIA_HENRYGD_PROXY"),
        "ncaa_derived_event_count": len(ncaa["games"]),
        "scoreboard_event_count": len(events),
        "locked_game_count": len(game_ids),
        "summary_rows_accepted": len(entries),
        "summary_rows_rejected": 0,
        "rejection_reasons": [],
        "summaries": entries,
    }
    (EVIDENCE / "capture-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


if __name__ == "__main__":
    result = capture()
    print(f"Captured {result['summary_rows_accepted']} completed ESPN summaries")
