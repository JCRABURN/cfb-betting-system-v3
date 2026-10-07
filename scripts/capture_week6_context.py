"""Capture Week 6 market, venue, weather and roster context as fallible evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests

from scripts.capture_week6_core import BASE, ROOT, _key


OUT = ROOT / "outputs/2026-week6-execution-20261006T2133Z"
RAW = OUT / "provider-evidence/context"
ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
ESPN_INJURIES = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/injuries"
ODDS = "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds"
WEATHER = "https://api.open-meteo.com/v1/forecast"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_key(name: str) -> str:
    if os.environ.get(name):
        return os.environ[name]
    for env_path in (ROOT / ".env", ROOT.parents[1] / ".env"):
        if not env_path.is_file():
            continue
        for line in env_path.read_text(encoding="utf-8").splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip().strip('"')
    raise RuntimeError(f"missing {name}")


def save(name: str, payload: object, *, provider: str, endpoint: str,
         parameters: dict | None = None, requested_at: str | None = None) -> dict:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    (RAW / f"{name}.json").write_bytes(raw)
    return {"name": name, "provider": provider, "endpoint": endpoint,
            "parameters": parameters or {}, "requested_at": requested_at or now(),
            "path": f"{name}.json", "sha256": hashlib.sha256(raw).hexdigest(),
            "records": len(payload) if isinstance(payload, list) else None, "status": "CAPTURED"}


def request_json(url: str, *, params: dict | None = None, headers: dict | None = None) -> object:
    response = requests.get(url, params=params, headers=headers, timeout=25)
    response.raise_for_status()
    return response.json()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUT)
    args = parser.parse_args()
    output = args.output.resolve()
    if output != OUT.resolve() or not output.is_dir() or RAW.exists():
        parser.error("expected the uncollected Week 6 output directory")
    RAW.mkdir(parents=True)
    reconciliation = json.loads((OUT / "week6_locked_line_snapshot.json").read_text())["lines"]
    records: list[dict] = []
    failures: list[dict] = []

    def attempt(name: str, provider: str, endpoint: str, params: dict | None = None,
                headers: dict | None = None) -> object | None:
        requested = now()
        try:
            payload = request_json(endpoint, params=params, headers=headers)
            records.append(save(name, payload, provider=provider, endpoint=endpoint,
                                parameters={key: value for key, value in (params or {}).items()
                                            if key != "apiKey"}, requested_at=requested))
            return payload
        except (requests.RequestException, ValueError) as exc:
            failures.append({"name": name, "provider": provider, "endpoint": endpoint,
                             "requested_at": requested, "status": "UNAVAILABLE",
                             "error_type": type(exc).__name__})
            return None

    venues = attempt("cfbd-venues", "CFBD", BASE + "/venues",
                     headers={"Authorization": f"Bearer {_key()}"})
    odds = attempt("odds-draftkings-current", "The Odds API", ODDS,
                   params={"apiKey": read_key("ODDS_API_KEY"), "regions": "us",
                           "markets": "spreads,totals", "bookmakers": "draftkings",
                           "oddsFormat": "american", "dateFormat": "iso"})
    injuries = attempt("espn-injuries", "ESPN", ESPN_INJURIES)

    def preview(row: dict) -> dict:
        game_id = row["game_id"]
        requested = now()
        try:
            data = request_json(ESPN_SUMMARY, params={"event": game_id})
            leaders = []
            for team in data.get("leaders", []):
                passing = next((item for item in team.get("leaders", [])
                                if item.get("name") == "passingYards"), None)
                first = (passing or {}).get("leaders", [])
                athlete = first[0].get("athlete", {}) if first else {}
                leaders.append({"team": team.get("team", {}).get("displayName"),
                                "season_passing_leader": athlete.get("fullName"),
                                "position": athlete.get("position", {}).get("abbreviation"),
                                "athlete_status": athlete.get("status", {}).get("name")})
            return {"game_id": game_id, "requested_at": requested, "status": "CAPTURED",
                    "leaders": leaders, "source": ESPN_SUMMARY,
                    "warning": "season passing leader is not a confirmed starter"}
        except (requests.RequestException, ValueError) as exc:
            return {"game_id": game_id, "requested_at": requested, "status": "UNAVAILABLE",
                    "error_type": type(exc).__name__}

    previews = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for future in as_completed([executor.submit(preview, row) for row in reconciliation]):
            previews.append(future.result())
    previews.sort(key=lambda row: row["game_id"])
    records.append(save("espn-game-preview-qb-evidence", previews, provider="ESPN",
                        endpoint=ESPN_SUMMARY))

    venue_by_id = {item["id"]: item for item in venues} if isinstance(venues, list) else {}
    games = {item["id"]: item for item in json.loads(
        (OUT / "provider-evidence/core/cfbd-2026-games.json").read_text())}

    def forecast(row: dict) -> dict:
        game_id = row["game_id"]
        game = games[game_id]
        venue = venue_by_id.get(game.get("venueId"))
        if venue is None:
            return {"game_id": game_id, "status": "MISSING_VENUE", "requested_at": now()}
        if venue.get("dome"):
            return {"game_id": game_id, "status": "DOME_WEATHER_NONFACTOR",
                    "venue": venue.get("name"), "requested_at": now()}
        if venue.get("latitude") is None or venue.get("longitude") is None:
            return {"game_id": game_id, "status": "MISSING_VENUE_COORDINATES",
                    "venue": venue.get("name"), "requested_at": now()}
        requested = now()
        params = {"latitude": venue["latitude"], "longitude": venue["longitude"],
                  "hourly": "temperature_2m,precipitation_probability,wind_speed_10m,wind_gusts_10m",
                  "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "timezone": "UTC",
                  "forecast_days": 7}
        try:
            data = request_json(WEATHER, params=params)
            hours = data["hourly"]["time"]
            kickoff = datetime.fromisoformat(row["source_kickoff_utc"])
            hour_times = [datetime.fromisoformat(value).replace(tzinfo=timezone.utc) for value in hours]
            index = min(range(len(hours)), key=lambda i: abs((hour_times[i] - kickoff).total_seconds()))
            if abs((hour_times[index] - kickoff).total_seconds()) > 3600:
                return {"game_id": game_id, "status": "NO_KICKOFF_HOUR", "requested_at": requested}
            hourly = data["hourly"]
            return {"game_id": game_id, "status": "CAPTURED", "requested_at": requested,
                    "provider": "Open-Meteo", "endpoint": WEATHER, "parameters": params,
                    "forecast_hour_utc": hour_times[index].isoformat(),
                    "temperature_f": hourly["temperature_2m"][index],
                    "precip_probability_pct": hourly["precipitation_probability"][index],
                    "wind_mph": hourly["wind_speed_10m"][index],
                    "gust_mph": hourly["wind_gusts_10m"][index]}
        except (requests.RequestException, ValueError, KeyError) as exc:
            return {"game_id": game_id, "status": "UNAVAILABLE", "requested_at": requested,
                    "error_type": type(exc).__name__}

    weather = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        for future in as_completed([executor.submit(forecast, row) for row in reconciliation]):
            weather.append(future.result())
    weather.sort(key=lambda row: row["game_id"])
    records.append(save("weather-kickoff", weather, provider="Open-Meteo", endpoint=WEATHER))
    manifest = {"completed_at": now(), "requests": records, "failures": failures,
                "market_events": len(odds) if isinstance(odds, list) else 0,
                "injury_groups": len(injuries.get("injuries", [])) if isinstance(injuries, dict) else 0,
                "espn_previews": sum(row["status"] == "CAPTURED" for row in previews),
                "weather_forecasts": sum(row["status"] == "CAPTURED" for row in weather)}
    (RAW / "capture-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({key: manifest[key] for key in
                      ("market_events", "injury_groups", "espn_previews", "weather_forecasts")}))


if __name__ == "__main__":
    main()
