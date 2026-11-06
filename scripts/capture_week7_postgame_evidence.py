"""Capture final results separately from the immutable Week 7 pregame inputs."""

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
FROZEN = ROOT / "outputs/2026-week7-prospective-corrected-v2"
EVIDENCE = ROOT / "outputs/2026-week7-postgame-audit/provider-evidence"
SCOREBOARD = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard?year=2026&week=7&seasontype=2&groups=80&limit=300"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary?event={}"


def final_competition(payload: dict, game_id: str, *, summary: bool) -> dict:
    event = payload["header"] if summary else payload
    competition = event["competitions"][0]
    status = competition["status"] if summary else event["status"]
    if str(event["id"]) != game_id or str(competition["id"]) != game_id:
        raise ValueError(f"game identity mismatch: {game_id}")
    if not status["type"].get("completed"):
        raise ValueError(f"game not final: {game_id}")
    teams = competition["competitors"]
    if len(teams) != 2 or {team["homeAway"] for team in teams} != {"home", "away"}:
        raise ValueError(f"invalid home/away coverage: {game_id}")
    for team in teams:
        score = str(team.get("score", ""))
        if not score.isdigit():
            raise ValueError(f"missing/invalid score: {game_id}")
    return competition


def fetch(url: str) -> tuple[bytes, str]:
    request = urllib.request.Request(url, headers={"User-Agent": "cfb-week7-postgame-audit/1.0"})
    with urllib.request.urlopen(request, timeout=40) as response:
        payload = response.read()
    return payload, datetime.now(timezone.utc).isoformat()


def capture() -> dict:
    if EVIDENCE.exists():
        raise FileExistsError("Week 7 evidence already exists; never overwrite a capture")
    with (FROZEN / "week7_ats_full_card.csv").open(encoding="utf-8-sig", newline="") as stream:
        card = list(csv.DictReader(stream))
    ids = [row["game_id"] for row in card]
    if len(ids) != 59 or len(set(ids)) != 59:
        raise ValueError("expected 59 distinct locked games")
    raw, captured_at = fetch(SCOREBOARD)
    scoreboard = json.loads(raw)
    if scoreboard["season"]["year"] != 2026 or scoreboard["week"]["number"] != 7:
        raise ValueError("wrong scoreboard season/week")
    events = {str(event["id"]): event for event in scoreboard["events"]}
    if len(events) != len(scoreboard["events"]) or set(ids) - events.keys():
        raise ValueError("missing or duplicate scoreboard IDs")
    for game_id in ids:
        final_competition(events[game_id], game_id, summary=False)

    def get_summary(game_id: str) -> tuple[str, bytes, str]:
        payload, timestamp = fetch(SUMMARY.format(game_id))
        final_competition(json.loads(payload), game_id, summary=True)
        return game_id, payload, timestamp

    with ThreadPoolExecutor(max_workers=6) as executor:
        summaries = list(executor.map(get_summary, ids))
    EVIDENCE.mkdir(parents=True, exist_ok=False)

    def save(name: str, url: str, payload: bytes, timestamp: str) -> dict:
        path = EVIDENCE / name
        path.write_bytes(gzip.compress(payload, mtime=0))
        return {"provider": "ESPN", "endpoint": url, "retrieved_at_utc": timestamp,
                "parser_version": "week7-postgame-v1", "raw_sha256": hashlib.sha256(payload).hexdigest(),
                "raw_bytes": len(payload), "stored_gzip_path": path.relative_to(ROOT).as_posix()}

    manifest = {"capture_status": "complete", "season": 2026, "week": 7,
                "scoreboard": save("espn-week7-scoreboard.json.gz", SCOREBOARD, raw, captured_at),
                "scoreboard_event_count": len(events), "locked_game_count": 59,
                "summary_rows_accepted": 59, "summary_rows_rejected": 0, "rejection_reasons": [],
                "summaries": [save(f"espn-game-{game_id}.json.gz", SUMMARY.format(game_id), payload, timestamp)
                              for game_id, payload, timestamp in sorted(summaries)],
                "limitation": "Scoreboard and summaries are two endpoints from one provider, not independent providers."}
    (EVIDENCE / "capture-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


if __name__ == "__main__":
    result = capture()
    print(f"Captured {result['summary_rows_accepted']} completed Week 7 game summaries")
