"""Build the complete Week 6 draft review package from sealed model ledgers."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/2026-week6-execution-20261006T2133Z"
DB = ROOT / "data/production_inputs/2026-week6-execution/execution-v8.db"
RAW = OUT / "provider-evidence/context"


def read_csv(name: str) -> list[dict]:
    with (OUT / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(name: str, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"empty output: {name}")
    with (OUT / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_json(name: str, value: object) -> None:
    (OUT / name).write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n")


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def market_advantage(market: str, selection: str, locked: float, current: float | None) -> float | None:
    if current is None:
        return None
    if market == "ATS":
        return locked - current if selection == "home" else current - locked
    return current - locked if selection == "over" else locked - current


def travel_miles(previous: dict | None, current: dict | None) -> float | None:
    if not previous or not current or any(item.get(key) is None for item, key in
        ((previous, "latitude"), (previous, "longitude"),
         (current, "latitude"), (current, "longitude"))):
        return None
    lat1, lon1, lat2, lon2 = map(math.radians,
        (previous["latitude"], previous["longitude"], current["latitude"], current["longitude"]))
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return round(3958.8 * 2 * math.asin(min(1.0, math.sqrt(value))), 1)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=DB)
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.is_relative_to(ROOT / "data/production_inputs/2026-week6-execution"):
        parser.error("expected an isolated Week 6 execution database")
    conn = sqlite3.connect(database)
    conn.row_factory = sqlite3.Row
    ats = read_csv("week6_ats_full_card.csv")
    totals = read_csv("week6_totals_full_card.csv")
    if len(ats) != 58 or len(totals) != 58 or any(not row["pick"] for row in totals):
        raise ValueError("58/58 ATS and 58/58 totals gate failed")
    if {row["game_id"] for row in ats} != {row["game_id"] for row in totals}:
        raise ValueError("market game sets differ")
    games = {int(row["id"]): row for row in json.loads(
        (OUT / "provider-evidence/core/cfbd-2026-games.json").read_text())}
    venues = {int(row["id"]): row for row in json.loads(
        (RAW / "cfbd-venues.json").read_text())}
    locked = {row["game_id"]: row for row in json.loads(
        (OUT / "week6_locked_line_snapshot.json").read_text())["lines"]}
    market = {row["game_id"]: row for row in json.loads(
        (RAW / "espn-draftkings-current.json").read_text())}
    weather = {row["game_id"]: row for row in json.loads(
        (RAW / "weather-kickoff.json").read_text())}
    previews = {row["game_id"]: row for row in json.loads(
        (RAW / "espn-game-preview-qb-evidence.json").read_text())}
    injuries = json.loads((RAW / "espn-injuries.json").read_text())
    evidence = json.loads((RAW / "capture-manifest.json").read_text())
    ats_by_game = {int(row["game_id"]): row for row in ats}
    total_by_game = {int(row["game_id"]): row for row in totals}
    context_rows = []
    qb_rows = []
    market_weather_rows = []
    for game_id in sorted(ats_by_game):
        a, t, lock = ats_by_game[game_id], total_by_game[game_id], locked[game_id]
        game, price, forecast, preview = games[game_id], market[game_id], weather[game_id], previews[game_id]
        kickoff = timestamp(lock["source_kickoff_utc"])
        prior: dict[str, list[dict]] = {}
        for side in ("away", "home"):
            team = game[side + "Team"]
            prior[side] = [item for item in games.values() if item.get("completed")
                           and team in (item.get("homeTeam"), item.get("awayTeam"))
                           and timestamp(item["startDate"]) < kickoff]
        fbs_samples = {side: sum(item.get("homeClassification") == item.get("awayClassification") == "fbs"
                                 for item in prior[side]) for side in ("away", "home")}
        fcs_exposure = {side: sum("fcs" in (item.get("homeClassification"), item.get("awayClassification"))
                                  for item in prior[side]) for side in ("away", "home")}
        blowouts = {side: sum(item.get("homePoints") is not None and item.get("awayPoints") is not None
                              and abs(item["homePoints"] - item["awayPoints"]) >= 35
                              for item in prior[side]) for side in ("away", "home")}
        latest = {side: max(prior[side], key=lambda item: timestamp(item["startDate"]))
                  if prior[side] else None for side in ("away", "home")}
        rest_days = {side: round((kickoff-timestamp(latest[side]["startDate"])).total_seconds()/86400, 1)
                     if latest[side] else None for side in ("away", "home")}
        travel = {side: travel_miles(venues.get(latest[side].get("venueId")) if latest[side] else None,
                                    venues.get(game.get("venueId"))) for side in ("away", "home")}
        current_spread, current_total = price["current_home_spread"], price["current_total"]
        ats_advantage = market_advantage("ATS", a["selected_side"], float(a["locked_home_spread"]), current_spread)
        total_advantage = market_advantage("TOTAL", t["pick"], float(t["locked_total"]), current_total)
        def passing_leader(side: str) -> str:
            expected = a[side].casefold()
            matched = [item for item in preview.get("leaders", [])
                       if (item.get("team") or "").casefold().startswith(expected + " ")
                       or (item.get("team") or "").casefold() == expected]
            return matched[0].get("season_passing_leader") or "" if len(matched) == 1 else ""
        qb_status = "UNVERIFIED"  # Passing leader is not a confirmed Week 6 starter.
        injury_status = "UNVERIFIED_INCOMPLETE_ESPN_COVERAGE"
        weather_status = forecast["status"]
        flags = []
        if fbs_samples["away"] < 4 or fbs_samples["home"] < 4:
            flags.append("LIMITED_FBS_SAMPLE")
        if fcs_exposure["away"] or fcs_exposure["home"]:
            flags.append("PRIOR_FCS_EXPOSURE")
        if blowouts["away"] or blowouts["home"]:
            flags.append("PRIOR_35_PLUS_BLOWOUT")
        if current_spread is None or current_total is None:
            flags.append("MARKET_MISSING")
        if qb_status == "UNVERIFIED":
            flags.append("QB_UNVERIFIED")
        if weather_status not in ("CAPTURED", "DOME_WEATHER_NONFACTOR"):
            flags.append("WEATHER_UNVERIFIED")
        if forecast.get("wind_mph", 0) >= 15 or forecast.get("gust_mph", 0) >= 25:
            flags.append("WIND_WARNING")
        if forecast.get("precip_probability_pct", 0) >= 50:
            flags.append("PRECIPITATION_WARNING")
        if forecast.get("temperature_f") is not None and (
            forecast["temperature_f"] <= 32 or forecast["temperature_f"] >= 95):
            flags.append("EXTREME_TEMPERATURE")
        context_rows.append({"game_id": game_id, "away": a["away"], "home": a["home"],
            "kickoff_utc": kickoff.isoformat(), "venue_id": game.get("venueId"),
            "game_status": "SCHEDULED" if not game.get("completed") else "COMPLETED",
            "away_fbs_games_before_week6": fbs_samples["away"],
            "home_fbs_games_before_week6": fbs_samples["home"],
            "away_prior_fcs_games": fcs_exposure["away"], "home_prior_fcs_games": fcs_exposure["home"],
            "away_prior_35_plus_blowouts": blowouts["away"],
            "home_prior_35_plus_blowouts": blowouts["home"],
            "away_rest_days": rest_days["away"], "home_rest_days": rest_days["home"],
            "away_travel_miles_from_prior_venue": travel["away"],
            "home_travel_miles_from_prior_venue": travel["home"],
            "qb_status": qb_status, "injury_status": injury_status,
            "market_status": price["status"], "weather_status": weather_status,
            "structural_warnings": ";".join(flags),
            "opponent_strength_adjustment_availability": "NOT_IN_ACTIVE_MODEL",
            "coaching_context": "UNVERIFIED_NO_NUMERIC_ADJUSTMENT",
            "travel_context": "VENUE_AND_PRIOR_GAME_AVAILABLE_NO_NUMERIC_ADJUSTMENT",
            "schedule_source": "CFBD 2026 FBS games capture",
            "qb_source": preview.get("source", "ESPN preview unavailable"),
            "injury_source": "ESPN injury feed; incomplete 3-team coverage",
            "market_source": "DraftKings via ESPN scoreboard; provider observation time absent",
            "weather_source": forecast.get("endpoint", weather_status)})
        qb_rows.append({"game_id": game_id, "away": a["away"], "home": a["home"],
            "expected_away_qb": "", "expected_home_qb": "",
            "away_season_passing_leader": passing_leader("away"),
            "away_qb_status": qb_status,
            "home_season_passing_leader": passing_leader("home"),
            "home_qb_status": qb_status, "preview_status": preview["status"],
            "major_injury_status": injury_status, "injury_groups_in_feed": len(injuries.get("injuries", [])),
            "retrieved_at": preview["requested_at"], "source": preview.get("source", ""),
            "warning": "Passing leader is not a confirmed starter; absent injury row is not healthy evidence"})
        market_weather_rows.append({"game_id": game_id, "away": a["away"], "home": a["home"],
            "locked_home_spread": a["locked_home_spread"], "current_home_spread": current_spread,
            "ats_selected_lock_advantage": ats_advantage,
            "ats_move_1_5_plus": current_spread is not None and abs(current_spread-float(a["locked_home_spread"])) >= 1.5,
            "crossed_3": current_spread is not None and min(abs(current_spread), abs(float(a["locked_home_spread"]))) <= 3 <= max(abs(current_spread), abs(float(a["locked_home_spread"]))) and abs(current_spread) != abs(float(a["locked_home_spread"])),
            "crossed_7": current_spread is not None and min(abs(current_spread), abs(float(a["locked_home_spread"]))) <= 7 <= max(abs(current_spread), abs(float(a["locked_home_spread"]))) and abs(current_spread) != abs(float(a["locked_home_spread"])),
            "locked_total": t["locked_total"], "current_total": current_total,
            "total_selected_lock_advantage": total_advantage,
            "total_move_2_5_plus": current_total is not None and abs(current_total-float(t["locked_total"])) >= 2.5,
            "market_status": price["status"], "market_retrieved_at": price["retrieved_at"],
            "market_provider_observation_time": price["provider_observation_timestamp"],
            "weather_status": weather_status, "forecast_hour_utc": forecast.get("forecast_hour_utc"),
            "temperature_f": forecast.get("temperature_f"),
            "precip_probability_pct": forecast.get("precip_probability_pct"),
            "wind_mph": forecast.get("wind_mph"), "gust_mph": forecast.get("gust_mph"),
            "weather_retrieved_at": forecast.get("requested_at"),
            "weather_flags": ";".join(flag for flag in flags if flag in
                                      ("WIND_WARNING", "PRECIPITATION_WARNING", "WEATHER_UNVERIFIED", "EXTREME_TEMPERATURE"))})
    write_csv("week6_context_status.csv", context_rows)
    write_csv("week6_qb_injury_review.csv", qb_rows)
    write_csv("week6_market_weather_review.csv", market_weather_rows)
    context = {row["game_id"]: row for row in context_rows}
    market_weather = {row["game_id"]: row for row in market_weather_rows}

    evaluations = {row["game_id"]: dict(row) for row in conn.execute(
        "SELECT * FROM ats_shadow_calibrated_evaluations")}
    components = {row["game_id"]: dict(row) for row in conn.execute(
        "SELECT p.game_id,c.projected_home_points,c.projected_away_points "
        "FROM total_score_component_predictions c JOIN total_model_predictions p "
        "ON p.id=c.total_model_prediction_id")}
    total_candidates = {row["game_id"]: dict(row) for row in conn.execute(
        "SELECT * FROM total_card_candidates")}
    unified = [dict(row) for row in conn.execute(
        "SELECT * FROM unified_top_five_candidates ORDER BY pool_rank")]
    if len(evaluations) != 58 or len(components) != 58 or len(total_candidates) != 58 or len(unified) != 116:
        raise ValueError("stored model ledger does not cover 116 selections")
    if len({(row["game_id"], row["market_type"]) for row in unified}) != 116:
        raise ValueError("duplicate game/market in unified pool")
    if [row["candidate_score"] for row in unified] != sorted(
        [row["candidate_score"] for row in unified], reverse=True):
        raise ValueError("unified ranking is not sorted by stored candidate score")
    if sum(row["is_top_five"] for row in unified) != 5:
        raise ValueError("combined Top 5 does not contain five")
    ats_enriched, total_enriched, calibration_rows, pool = [], [], [], []
    for raw in ats:
        game_id = int(raw["game_id"])
        ctx, price, evaluation = context[game_id], market_weather[game_id], evaluations[game_id]
        selected_edge = abs(float(raw["home_ats_edge"]))
        ats_enriched.append({**raw, "selected_side_ats_edge": selected_edge,
            "raw_confidence": raw["confidence"], "final_confidence": raw["confidence"],
            "current_market_home_spread": price["current_home_spread"],
            "selected_side_lock_advantage": price["ats_selected_lock_advantage"],
            "qb_evidence": ctx["qb_status"], "injury_evidence": ctx["injury_status"],
            "weather_evidence": ctx["weather_status"],
            "sample_quality_warning": ctx["structural_warnings"],
            "provenance": "sealed ATS model; immutable SplashSports lock; separate context review"})
        calibration_rows.append({"game_id": game_id, "away": raw["away"], "home": raw["home"],
            "selection": raw["pick"], "selected_spread": raw["pick_spread"],
            "selected_margin_advantage_points": evaluation["selected_margin_advantage_points"],
            "calibrated_selected_side_probability": evaluation["calibrated_selected_side_probability"],
            "candidate_score": evaluation["calibrated_selected_side_probability"],
            "reliability_policy_version": evaluation["reliability_policy_version"],
            "calibration_method": "conservative_linear_margin_v1",
            "empirical_validation": "NOT_EMPIRICALLY_VALIDATED"})
    for raw in totals:
        game_id = int(raw["game_id"])
        ctx, price, candidate, component = (context[game_id], market_weather[game_id],
                                            total_candidates[game_id], components[game_id])
        total_enriched.append({**raw, "projected_home_points": component["projected_home_points"],
            "projected_away_points": component["projected_away_points"],
            "raw_over_probability": candidate["raw_over_probability"],
            "calibrated_over_probability": candidate["calibrated_over_probability"],
            "selected_probability": candidate["selected_probability"],
            "reliability_policy_version": candidate["reliability_policy_version"],
            "current_market_total": price["current_total"],
            "selected_direction_lock_advantage": price["total_selected_lock_advantage"],
            "sample_quality_warning": ctx["structural_warnings"],
            "status": "SHADOW_NOT_PRODUCTION_ELIGIBLE",
            "provenance": "sealed totals component model; immutable SplashSports lock; separate context review"})
    write_csv("week6_ats_full_card.csv", ats_enriched)
    write_csv("week6_totals_full_card.csv", total_enriched)
    write_csv("week6_ats_shadow_calibration.csv", calibration_rows)
    ats_enriched_by_game = {int(row["game_id"]): row for row in ats_enriched}
    total_enriched_by_game = {int(row["game_id"]): row for row in total_enriched}
    for item in unified:
        game_id, kind = item["game_id"], item["market_type"].upper()
        source = ats_enriched_by_game[game_id] if kind == "ATS" else total_enriched_by_game[game_id]
        price, ctx = market_weather[game_id], context[game_id]
        pool.append({"game_id": game_id, "away": source["away"], "home": source["home"],
            "market_type": kind, "selection": source["pick"],
            "locked_line": source["pick_spread"] if kind == "ATS" else source["locked_total"],
            "projection": source["projected_home_margin"] if kind == "ATS" else source["projected_total"],
            "raw_edge": source["selected_side_ats_edge"] if kind == "ATS" else source["raw_point_edge"],
            "selected_probability": item["calibrated_probability"],
            "candidate_score": item["candidate_score"], "confidence": source["confidence"],
            "uncertainty": source["uncertainty_points"],
            "reliability_policy_version": item["reliability_policy_version"],
            "current_market_line": (price["current_home_spread"] if kind == "ATS"
                                    else price["current_total"]),
            "lock_advantage": (price["ats_selected_lock_advantage"] if kind == "ATS"
                               else price["total_selected_lock_advantage"]),
            "qb_status": ctx["qb_status"], "injury_status": ctx["injury_status"],
            "weather_status": ctx["weather_status"], "structural_warning": ctx["structural_warnings"],
            "pool_rank": item["pool_rank"], "is_combined_top5": bool(item["is_top_five"]),
            "combined_top5_rank": item["top_five_rank"] or "",
            "score_status": "CROSS_MARKET_SHADOW_NOT_EMPIRICALLY_VALIDATED"})
    write_csv("week6_combined_candidate_pool.csv", pool)
    mixed = sorted((row for row in pool if row["is_combined_top5"]),
                   key=lambda row: int(row["combined_top5_rank"]))
    write_csv("week6_mixed_market_shadow_top5.csv", mixed)
    official = sorted((row for row in ats_enriched if row["top_five"] == "True"),
                      key=lambda row: -int(row["rank"]))
    if len(official) != 5:
        raise ValueError("governed ATS Top 5 count failed")
    write_csv("week6_official_ats_top5.csv", [
        {**row, "ranking_basis": "DETERMINISTIC_POLICY_TOP5_NOT_STRENGTH_RANKED"}
        for row in official])
    write_csv("week6_shadow_totals_top5.csv", sorted(total_enriched,
        key=lambda row: -float(row["selected_probability"]))[:5])

    large = []
    for row in ats_enriched:
        if float(row["selected_side_ats_edge"]) < 7:
            continue
        game_id = int(row["game_id"])
        ctx, price = context[game_id], market_weather[game_id]
        sample_min = min(int(ctx["away_fbs_games_before_week6"]),
                         int(ctx["home_fbs_games_before_week6"]))
        label = ("VERY_FRAGILE" if sample_min < 3 else "FRAGILE_SAMPLE" if sample_min < 4
                 else "MARKET_CONFLICT" if price["ats_selected_lock_advantage"] is not None
                 and float(price["ats_selected_lock_advantage"]) < -1.5
                 else "QB_UNCERTAINTY" if ctx["qb_status"] == "UNVERIFIED"
                 else "CLEANER_SIGNAL")
        large.append({"game_id": game_id, "away": row["away"], "home": row["home"],
            "selection": row["pick"], "locked_spread": row["pick_spread"],
            "projected_home_margin": row["projected_home_margin"],
            "raw_selected_edge": row["selected_side_ats_edge"],
            "away_fbs_sample": ctx["away_fbs_games_before_week6"],
            "home_fbs_sample": ctx["home_fbs_games_before_week6"],
            "prior_fcs_exposure": int(ctx["away_prior_fcs_games"]) + int(ctx["home_prior_fcs_games"]),
            "prior_35_plus_blowout_exposure": int(ctx["away_prior_35_plus_blowouts"]) +
                int(ctx["home_prior_35_plus_blowouts"]),
            "qb_certainty": ctx["qb_status"],
            "opponent_strength_adjustment_availability": ctx["opponent_strength_adjustment_availability"],
            "current_market_spread": price["current_home_spread"],
            "market_agreement": price["ats_selected_lock_advantage"],
            "structural_warnings": ctx["structural_warnings"],
            "analytical_classification": label,
            "classification_is_audit_only": True})
    if large:
        write_csv("week6_large_ats_edge_adjudication.csv", large)
    else:
        write_csv("week6_large_ats_edge_adjudication.csv", [{"status": "NO_EDGE_GE_7"}])

    # Review ordering uses stored within-market scores, then avoids the most
    # fragile samples. It does not change sealed model choices or policies.
    ats_pool = sorted((row for row in pool if row["market_type"] == "ATS"),
        key=lambda row: ("VERY_FRAGILE" in row["structural_warning"],
                         -float(row["candidate_score"]), int(row["game_id"])))
    totals_pool = sorted((row for row in pool if row["market_type"] == "TOTAL"),
        key=lambda row: (-float(row["candidate_score"]), int(row["game_id"])))
    analytical_ats = [{**row, "review_rank": i,
                       "review_note": "QB unverified; compare sample and current market before any owner choice"}
                      for i, row in enumerate(ats_pool[:10], 1)]
    analytical_totals = [{**row, "review_rank": i,
        "review_note": "Shadow totals 23-33 in Week 5; model score is not validated"}
        for i, row in enumerate(totals_pool[:10], 1)]
    write_csv("week6_analytical_ats_shortlist.csv", analytical_ats)
    write_csv("week6_analytical_totals_shortlist.csv", analytical_totals)
    counts = Counter(row["market_type"] for row in mixed)
    card_manifest = json.loads((OUT / "week6_card_manifest.json").read_text())
    card_manifest["coverage"] = {"locked_games": 58, "ats_candidates": 58, "ats_skips": 0,
        "totals_candidates": 58, "totals_skips": 0, "combined_market_selections": 116,
        "official_ats_top5": 5, "mixed_market_shadow_top5": 5}
    card_manifest["mixed_composition"] = dict(counts)
    card_manifest["context_capture_manifest_sha256"] = hashlib.sha256(
        (RAW / "capture-manifest.json").read_bytes()).hexdigest()
    card_manifest["no_manual_adjustments"] = True
    write_json("week6_card_manifest.json", card_manifest)
    # The decision/reporting layer is a separate qualitative review of sealed
    # pregame artifacts, never a copy of the mixed shadow score leaders.
    from scripts.review_week6_decision import write_review_outputs
    write_review_outputs(update_checksums=False)
    print(json.dumps({"ats": len(ats_enriched), "totals": len(total_enriched),
                      "pool": len(pool), "mixed_ats": counts["ATS"],
                      "mixed_totals": counts["TOTAL"], "large_edges": len(large),
                      "market_complete": sum(row["status"] == "OBSERVED_UNTIMESTAMPED"
                                             for row in market.values())}))


if __name__ == "__main__":
    main()
