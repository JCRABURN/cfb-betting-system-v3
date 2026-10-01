"""Analyze fresh market, weather, and rest/travel evidence without changing locks."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from ingestion import CanonicalTeamResolver


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "outputs/2026-week5-execution-20260930-v3/provider-evidence"


def timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def haversine(a: dict, b: dict) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a["latitude"], a["longitude"], b["latitude"], b["longitude"]))
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 3958.8 * 2 * math.asin(min(1.0, math.sqrt(value)))


def market_line(event: dict) -> tuple[float | None, float | None, str | None]:
    books = [book for book in event.get("bookmakers", []) if book.get("key") == "draftkings"]
    if len(books) != 1:
        return None, None, None
    book = books[0]
    spread = total = None
    for market in book.get("markets", []):
        if market.get("key") == "spreads":
            home = [outcome for outcome in market.get("outcomes", []) if outcome.get("name") == event["home_team"]]
            if len(home) == 1:
                spread = float(home[0]["point"])
        if market.get("key") == "totals":
            over = [outcome for outcome in market.get("outcomes", []) if outcome.get("name", "").casefold() == "over"]
            if len(over) == 1:
                total = float(over[0]["point"])
    return spread, total, book.get("last_update")


def main() -> None:
    out = ROOT / "outputs/2026-week5-execution-20260930-v3"
    database = ROOT / "data/production_inputs/2026-week5-execution/execution-v3.db"
    conn = sqlite3.connect(database)
    resolver = CanonicalTeamResolver.from_connection(conn)
    schedule = json.loads((EVIDENCE / "cfbd-2026-games.json").read_text(encoding="utf-8"))
    venues = {venue["id"]: venue for venue in json.loads((EVIDENCE / "cfbd-venues.json").read_text(encoding="utf-8"))}
    odds = json.loads((EVIDENCE / "odds-draftkings-current.json").read_text(encoding="utf-8"))
    forecast_manifest = json.loads((EVIDENCE / "weather-manifest.json").read_text(encoding="utf-8"))
    forecast_records = {item["game_id"]: item for item in forecast_manifest["records"]}
    by_game = {game["id"]: game for game in schedule}
    by_matchup: dict[tuple[str, str], dict] = {}
    for event in odds:
        away = resolver.resolve("the_odds_api", event["away_team"])
        home = resolver.resolve("the_odds_api", event["home_team"])
        if away.status == home.status == "resolved":
            key = (away.canonical_name, home.canonical_name)
            if key in by_matchup:
                raise ValueError(f"duplicate odds matchup: {key}")
            by_matchup[key] = event
    ats = list(csv.DictReader((out / "week5_ats_full_card.csv").open(newline="", encoding="utf-8")))
    totals = {int(item["game_id"]): item for item in csv.DictReader((out / "week5_totals_full_card.csv").open(newline="", encoding="utf-8"))}
    rows: list[dict] = []
    for pick in ats:
        game_id = int(pick["game_id"])
        game = by_game[game_id]
        venue = venues[game["venueId"]]
        event = by_matchup.get((pick["away"], pick["home"]))
        current_spread, current_total, market_updated = market_line(event) if event else (None, None, None)
        locked_spread = float(pick["locked_home_spread"])
        locked_total = float(totals[game_id]["locked_total"])
        ats_locked_advantage = None if current_spread is None else ((locked_spread-current_spread) if pick["selected_side"] == "home" else (current_spread-locked_spread))
        total_locked_advantage = None if current_total is None else ((current_total-locked_total) if totals[game_id]["pick"] == "over" else (locked_total-current_total))
        weather = forecast_records[game_id]
        wind = precip = temperature = None
        if weather["status"] == "CAPTURED":
            raw = (EVIDENCE / weather["path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != weather["sha256"]:
                raise ValueError(f"weather checksum mismatch: {game_id}")
            hourly = json.loads(raw)["hourly"]
            kickoff = timestamp(game["startDate"])
            hours = [timestamp(hour) for hour in hourly["time"]]
            index = min(range(len(hours)), key=lambda item: abs((hours[item]-kickoff).total_seconds()))
            if abs((hours[index]-kickoff).total_seconds()) <= 3600:
                wind = hourly["wind_speed_10m"][index]
                precip = hourly["precipitation_probability"][index]
                temperature = hourly["temperature_2m"][index]
        context = {}
        for side in ("home", "away"):
            team = game[side + "Team"]
            prior = [item for item in schedule if item.get("completed") and team in (item.get("homeTeam"), item.get("awayTeam")) and timestamp(item["startDate"]) < timestamp(game["startDate"])]
            if prior:
                latest = max(prior, key=lambda item: timestamp(item["startDate"]))
                context[side + "_rest_days"] = round((timestamp(game["startDate"])-timestamp(latest["startDate"])).total_seconds()/86400, 1)
                previous_venue = venues.get(latest.get("venueId"))
                context[side + "_travel_miles_from_prior_venue"] = round(haversine(previous_venue, venue)) if previous_venue and previous_venue.get("latitude") is not None else None
            else:
                context[side + "_rest_days"] = None
                context[side + "_travel_miles_from_prior_venue"] = None
        rows.append({
            "game_id": game_id, "away": pick["away"], "home": pick["home"],
            "locked_home_spread": locked_spread, "current_draftkings_home_spread": current_spread,
            "current_minus_locked_home_spread": None if current_spread is None else current_spread-locked_spread,
            "ats_selected_locked_line_advantage": ats_locked_advantage,
            "locked_total": locked_total, "current_draftkings_total": current_total,
            "current_minus_locked_total": None if current_total is None else current_total-locked_total,
            "totals_selected_locked_line_advantage": total_locked_advantage,
            "market_updated_at": market_updated, "weather_status": weather["status"],
            "wind_mph_at_kickoff": wind, "precip_probability_pct_at_kickoff": precip,
            "temperature_f_at_kickoff": temperature, "venue_dome": bool(venue.get("dome")),
            "venue_elevation_m": venue.get("elevation"), **context,
            "injury_status": "INCOMPLETE_ESPN_COVERAGE;QB_UNVERIFIED",
        })
    if len(rows) != 56:
        raise ValueError("context row count mismatch")
    with (out / "week5_context_review.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    captured_at = datetime.now(timezone.utc)
    freshness = {
        "reviewed_at": captured_at.isoformat(),
        "game_status": {"captured_at": json.loads((EVIDENCE / "capture-manifest.json").read_text())["requests"][0]["requested_at"], "week1_through_4_completed_fbs_games": 215, "week5_provider_games": 56},
        "epa": {"snapshot_week": 4, "teams": 138, "source": "CFBD advanced season stats endWeek=4", "capture_file": "cfbd-week4-advanced.json"},
        "market": {"provider": "The Odds API / DraftKings", "captured_games": sum(row["current_draftkings_home_spread"] is not None for row in rows), "missing_games": [row["game_id"] for row in rows if row["current_draftkings_home_spread"] is None], "capture_file": "odds-draftkings-current.json"},
        "weather": {"outdoor_forecasts": forecast_manifest["captured"], "indoor_domes": forecast_manifest["indoors"], "failed": forecast_manifest["failed"]},
        "injuries": {"espn_team_groups": len(json.loads((EVIDENCE / "espn-injuries.json").read_text())["injuries"]), "coverage": "INCOMPLETE", "no_row_does_not_mean_healthy": True},
        "quarterbacks": "UNVERIFIED_FOR_ALL_GAMES_WITHOUT_SEPARATE_CREDIBLE_EVIDENCE",
        "coaching_motivation": "NO_NUMERIC_ADJUSTMENTS;NO_OWNER_EVIDENCE",
    }
    (out / "week5_data_freshness.json").write_text(json.dumps(freshness, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "market_matched": freshness["market"]["captured_games"], "wind_20_plus": sum((row["wind_mph_at_kickoff"] or 0) >= 20 for row in rows)}))


if __name__ == "__main__":
    main()
