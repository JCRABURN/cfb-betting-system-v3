"""Challenge every Week 5 Top-5 candidate using recorded pregame evidence."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/2026-week5-execution-20260930-v4"


def read_csv(name: str) -> list[dict]:
    with (OUT / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    games = json.loads((OUT / "provider-evidence/cfbd-2026-games.json").read_text(encoding="utf-8"))
    by_game = {game["id"]: game for game in games}
    historical_ats = json.loads((OUT / "prior-evidence/week3-ats-card.json").read_text(encoding="utf-8"))
    context = {int(row["game_id"]): row for row in read_csv("week5_context_review.csv")}
    ats = {int(row["game_id"]): row for row in read_csv("week5_ats_full_card.csv")}
    totals = {int(row["game_id"]): row for row in read_csv("week5_totals_full_card.csv")}
    pool = [("ATS_OFFICIAL_POLICY", row) for row in read_csv("week5_official_ats_top5.csv")]
    pool += [("ATS_SHADOW_UNCERTAINTY", row) for row in read_csv("week5_shadow_ats_top5.csv")]
    pool += [("TOTAL", row) for row in read_csv("week5_shadow_totals_top5.csv")]
    output = []
    for market, candidate in pool:
        game_id = int(candidate["game_id"])
        game = by_game[game_id]
        ctx = context[game_id]
        team_review = {}
        for team in (candidate["away"], candidate["home"]):
            previous = [item for item in games if item.get("completed") and item["week"] < 5 and team in (item["awayTeam"], item["homeTeam"])]
            previous.sort(key=lambda item: item["startDate"])
            fcs_opponents = [
                item["homeTeam"] if item["awayTeam"] == team else item["awayTeam"]
                for item in previous
                if item.get("awayClassification") != "fbs" or item.get("homeClassification") != "fbs"
            ]
            biggest_margin = max((abs(item["homePoints"]-item["awayPoints"]) for item in previous), default=None)
            week3_errors = []
            for prior in historical_ats:
                target = by_game.get(prior["game_id"])
                if target and prior["prediction_home_margin"] is not None and team in (target["awayTeam"], target["homeTeam"]):
                    observed = target["homePoints"]-target["awayPoints"]
                    week3_errors.append(round(prior["prediction_home_margin"]-observed, 1))
            team_review[team] = {
                "completed_games": len(previous), "fcs_opponents": fcs_opponents,
                "largest_prior_final_margin_points": biggest_margin,
                "week3_model_home_margin_errors_when_available": week3_errors,
            }
        margin = float(ats[game_id]["projected_home_margin"])
        total = float(totals[game_id]["projected_total"])
        locked_advantage = float(ctx["ats_selected_locked_line_advantage"] if market.startswith("ATS") else ctx["totals_selected_locked_line_advantage"])
        output.append({
            "game_id": game_id, "game": f"{candidate['away']} @ {candidate['home']}",
            "market": market, "pick": candidate["pick"],
            "provider_kickoff_utc": game["startDate"], "prior_team_review": team_review,
            "implied_away_points_from_independent_models": round((total-margin)/2, 1),
            "implied_home_points_from_independent_models": round((total+margin)/2, 1),
            "game_script_physical_sanity": "PASS" if total >= abs(margin) else "FAIL_NEGATIVE_IMPLIED_SCORE",
            "fcs_contamination_risk": "UNQUANTIFIED_CFBD_AGGREGATE_MAY_INCLUDE_FCS",
            "forecast_wind_mph": ctx["wind_mph_at_kickoff"] or None,
            "away_rest_days": ctx["away_rest_days"], "home_rest_days": ctx["home_rest_days"],
            "away_travel_miles": ctx["away_travel_miles_from_prior_venue"],
            "home_travel_miles": ctx["home_travel_miles_from_prior_venue"],
            "quarterback_status": "UNVERIFIED", "injury_coverage": "INCOMPLETE_ESPN_THREE_TEAM_FEED",
            "pace_feature_status": "NOT_IN_SANCTIONED_MODEL",
            "locked_line_advantage_vs_draftkings_points": locked_advantage,
            "clv_direction_so_far": "FAVORABLE" if locked_advantage > 0 else "ADVERSE" if locked_advantage < 0 else "UNCHANGED",
            "market_agreement": "MATERIAL_DISAGREEMENT" if locked_advantage <= -2 else "MOVED_IN_FAVOR" if locked_advantage >= 2 else "NEAR_LOCKED_LINE",
            "context_numeric_adjustments": 0,
            "note": "Diagnostic review only; no source line, forecast, or pick rewritten.",
        })
    if len(output) != 15 or any(row["game_script_physical_sanity"] != "PASS" for row in output):
        raise ValueError("Top-pick adversarial review failed")
    (OUT / "week5_top_pick_adversarial_review.json").write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"reviewed": len(output), "unique_games": len({row["game_id"] for row in output}), "material_market_disagreement": [row["game"] for row in output if row["market_agreement"] == "MATERIAL_DISAGREEMENT"]}))


if __name__ == "__main__":
    main()
