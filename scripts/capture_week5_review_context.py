"""Capture current Week 5 market, weather, and QB/injury evidence without changing v4."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "outputs/2026-week5-execution-20260930-v4"
OUT = ROOT / "outputs/2026-week5-review-20261001"
RAW = OUT / "provider-evidence"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
ESPN_INJURIES = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/injuries"
ODDS = "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"
WEATHER = "https://api.open-meteo.com/v1/forecast"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url)
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=25) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            time.sleep(attempt + 1)
    raise RuntimeError(f"provider request failed: {urllib.parse.urlsplit(url).netloc}") from last_error


def key_from_env(name: str) -> str:
    if os.getenv(name):
        return os.environ[name]
    env_path = ROOT.parents[2] / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError(f"missing {name}; no credential is written to evidence")


def main() -> None:
    if OUT.exists() and any(path.name != "provider-evidence" for path in OUT.iterdir()):
        raise RuntimeError("review evidence already exists; create a new version instead")
    RAW.mkdir(parents=True, exist_ok=True)
    existing = {path.name for path in RAW.iterdir()}
    if existing not in (set(), {"odds-draftkings-current.json"}):
        raise RuntimeError("only an interrupted odds capture may be resumed")
    games = list(csv.DictReader((V4 / "week5_ats_full_card.csv").open(encoding="utf-8", newline="")))
    if len(games) != 56:
        raise RuntimeError("v4 coverage changed")
    manifest: dict[str, object] = {"capture_started_at": utc_now(), "status": "IN_PROGRESS", "requests": []}
    odds_params = {
        "apiKey": key_from_env("ODDS_API_KEY"), "regions": "us", "markets": "spreads,totals",
        "bookmakers": "draftkings", "oddsFormat": "american", "dateFormat": "iso",
    }
    odds_path = RAW / "odds-draftkings-current.json"
    odds_time = (datetime.fromtimestamp(odds_path.stat().st_mtime, timezone.utc).isoformat()
                 if odds_path.exists() else utc_now())
    odds_bytes = (odds_path.read_bytes() if odds_path.exists()
                  else fetch(ODDS + "?" + urllib.parse.urlencode(odds_params)))
    odds = json.loads(odds_bytes)
    if not odds_path.exists():
        odds_path.write_bytes(odds_bytes)
    manifest["requests"].append({
        "provider": "The Odds API", "endpoint": ODDS,
        "parameters": {key: value for key, value in odds_params.items() if key != "apiKey"},
        "requested_at": odds_time, "sha256": sha(odds_bytes), "rows": len(odds),
    })
    injury_time = utc_now()
    injury_bytes = fetch(ESPN_INJURIES)
    injuries = json.loads(injury_bytes)
    (RAW / "espn-injuries.json").write_bytes(injury_bytes)
    manifest["requests"].append({
        "provider": "ESPN", "endpoint": ESPN_INJURIES, "requested_at": injury_time,
        "sha256": sha(injury_bytes), "team_groups": len(injuries.get("injuries", [])),
    })

    def preview(game: dict[str, str]) -> dict[str, object]:
        game_id = int(game["game_id"])
        requested_at = utc_now()
        source_url = ESPN_SUMMARY + "?" + urllib.parse.urlencode({"event": game_id})
        payload = fetch(source_url)
        parsed = json.loads(payload)
        team_leaders = []
        for team in parsed.get("leaders", []):
            passing = next((item for item in team.get("leaders", []) if item.get("name") == "passingYards"), None)
            athlete = (passing or {}).get("leaders", [{}])[0].get("athlete", {}) if passing and passing.get("leaders") else {}
            team_leaders.append({
                "team": team.get("team", {}).get("displayName"),
                "espn_team_id": team.get("team", {}).get("id"),
                "season_passing_leader": athlete.get("fullName"),
                "position": athlete.get("position", {}).get("abbreviation"),
                "athlete_status": athlete.get("status", {}).get("name"),
                "season_passing_yards": (passing or {}).get("leaders", [{}])[0].get("value") if passing and passing.get("leaders") else None,
            })
        return {"game_id": game_id, "requested_at": requested_at, "source": source_url,
                "response_sha256": sha(payload), "teams": team_leaders,
                "status": "PREVIEW_PASSING_LEADER_ONLY_NOT_CONFIRMED_STARTER"}

    preview_rows = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(preview, game): game["game_id"] for game in games}
        for future in as_completed(futures):
            preview_rows.append(future.result())
    preview_rows.sort(key=lambda item: item["game_id"])
    (RAW / "espn-game-preview-qb-evidence.json").write_text(json.dumps(preview_rows, indent=2) + "\n", encoding="utf-8")
    manifest["requests"].append({"provider": "ESPN", "endpoint": ESPN_SUMMARY,
                                 "captured_game_previews": len(preview_rows),
                                 "evidence_file": "espn-game-preview-qb-evidence.json"})

    previous_weather = json.loads((V4 / "provider-evidence/weather-manifest.json").read_text(encoding="utf-8"))
    schedule = {item["id"]: item for item in json.loads((V4 / "provider-evidence/cfbd-2026-games.json").read_text(encoding="utf-8"))}

    def forecast(item: dict[str, object]) -> dict[str, object]:
        game_id = int(item["game_id"])
        if item["status"] != "CAPTURED":
            return {"game_id": game_id, "status": item["status"], "requested_at": utc_now()}
        params = dict(item["parameters"])
        requested_at = utc_now()
        source_url = WEATHER + "?" + urllib.parse.urlencode(params)
        payload = fetch(source_url)
        parsed = json.loads(payload)
        hourly = parsed["hourly"]
        kickoff = datetime.fromisoformat(schedule[game_id]["startDate"].replace("Z", "+00:00"))
        times = [datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=timezone.utc) if "+" not in value and "Z" not in value else datetime.fromisoformat(value.replace("Z", "+00:00")) for value in hourly["time"]]
        index = min(range(len(times)), key=lambda idx: abs((times[idx] - kickoff).total_seconds()))
        if abs((times[index] - kickoff).total_seconds()) > 3600:
            return {"game_id": game_id, "status": "NO_KICKOFF_HOUR", "requested_at": requested_at,
                    "source": WEATHER, "response_sha256": sha(payload)}
        return {"game_id": game_id, "status": "CAPTURED", "requested_at": requested_at,
                "source": WEATHER, "parameters": params, "response_sha256": sha(payload),
                "forecast_hour_utc": times[index].isoformat(),
                "wind_mph": hourly["wind_speed_10m"][index],
                "precip_probability_pct": hourly["precipitation_probability"][index],
                "temperature_f": hourly["temperature_2m"][index],
                "weather_code": hourly["weather_code"][index]}

    weather_rows = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(forecast, item): item["game_id"] for item in previous_weather["records"]}
        for future in as_completed(futures):
            weather_rows.append(future.result())
    weather_rows.sort(key=lambda item: item["game_id"])
    (RAW / "weather-kickoff-review.json").write_text(json.dumps(weather_rows, indent=2) + "\n", encoding="utf-8")
    manifest["requests"].append({"provider": "Open-Meteo", "endpoint": WEATHER,
                                 "captured": sum(item["status"] == "CAPTURED" for item in weather_rows),
                                 "evidence_file": "weather-kickoff-review.json"})
    manifest["capture_completed_at"] = utc_now()
    manifest["status"] = "COMPLETE"
    (RAW / "capture-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"odds_events": len(odds), "espn_previews": len(preview_rows),
                      "weather_forecasts": sum(item["status"] == "CAPTURED" for item in weather_rows),
                      "injury_team_groups": len(injuries.get("injuries", []))}))


if __name__ == "__main__":
    main()
