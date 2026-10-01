"""Grade only previously generated Week 1–3 cards against captured final scores."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

from business_entities.complete_audits import _spread_bucket


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/2026-week5-execution-20260930-v3"
EVIDENCE = OUTPUT / "prior-evidence"
GAMES = OUTPUT / "provider-evidence/cfbd-2026-games.json"


def summary(rows: list[dict]) -> dict:
    counts = Counter(row["result"].lower() for row in rows)
    return {"n": len(rows), "win": counts["win"], "loss": counts["loss"], "push": counts["push"]}


def cuts(rows: list[dict], fields: tuple[str, ...]) -> dict:
    result = {}
    for field in fields:
        groups: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            groups[str(row.get(field, "not_available"))].append(row)
        result[field] = {key: summary(value) for key, value in sorted(groups.items())}
    return result


def main() -> None:
    games = {game["id"]: game for game in json.loads(GAMES.read_text(encoding="utf-8"))}
    week1 = list(csv.DictReader((EVIDENCE / "week1-postgame-audit.csv").open(encoding="utf-8", newline="")))
    week2 = json.loads((EVIDENCE / "week2-audit.json").read_text(encoding="utf-8"))
    week3_ats = json.loads((EVIDENCE / "week3-ats-card.json").read_text(encoding="utf-8"))
    week3_totals = json.loads((EVIDENCE / "week3-totals-card.json").read_text(encoding="utf-8"))
    ats: list[dict] = []
    totals: list[dict] = []
    for row in week1:
        ats.append({
            "week": 1, "status": "RECORDED_LOCAL_DRAFT", "result": row["ats_result"].lower(),
            "top_five": row["is_top_five"] == "YES", "selected_side": row["selected_side"],
            "favorite_status": row["favorite_status"], "location": row["location_status"],
            "road_favorite": row["location_status"] == "away" and row["favorite_status"] == "favorite",
            "spread_bucket": row["spread_bucket"], "confidence": int(row["confidence"]),
            "hook_outcome": row["hook_outcome"], "selected_spread": float(row["selected_spread"]),
        })
    for row in week2["ats_rows"]:
        ats.append({
            "week": 2, "status": "RECORDED_LOCAL_DRAFT", "result": row["result"],
            "top_five": row["top_five"], "selected_side": row["location"],
            "favorite_status": row["favorite_status"], "location": row["location"],
            "road_favorite": row["road_favorite"], "spread_bucket": row["spread_bucket"],
            "confidence": row["confidence"], "hook_outcome": row["hook_outcome"],
            "selected_spread": row["locked_spread"],
        })
    for row in week2["totals"]["details"]:
        totals.append({"week": 2, "status": "RECORDED_SHADOW", "result": row["result"],
                       "direction": row["selected_direction"].lower(), "confidence": row["confidence"]})
    for row in week3_ats:
        if row["pick"] is None:
            continue
        game = games[row["game_id"]]
        if game["week"] != 3 or not game.get("completed"):
            raise ValueError("Week 3 final score missing")
        selected_home = row["pick"] == game["homeTeam"]
        margin = game["homePoints"] - game["awayPoints"]
        cover = (margin + row["home_spread"]) if selected_home else (-margin - row["home_spread"])
        result = "win" if cover > 0 else "loss" if cover < 0 else "push"
        spread = row["home_spread"] if selected_home else -row["home_spread"]
        ats.append({
            "week": 3, "status": "RECORDED_PREKICKOFF_PROVISIONAL", "result": result,
            "top_five": row["provisional_top_five"], "selected_side": "home" if selected_home else "away",
            "favorite_status": "favorite" if spread < 0 else "underdog" if spread > 0 else "pickem",
            "location": "neutral" if game.get("neutralSite") else "home" if selected_home else "away",
            "road_favorite": not selected_home and spread < 0 and not game.get("neutralSite"),
            "spread_bucket": _spread_bucket(row["home_spread"]), "confidence": row["confidence"],
            "hook_outcome": ("won_by_hook" if cover > 0 else "lost_by_hook") if abs(cover) == .5 and abs(row["home_spread"] * 2) % 2 == 1 else "not_hook",
            "selected_spread": spread,
        })
    for row in week3_totals:
        if not row.get("selected_direction"):
            continue
        game = games[row["game_id"]]
        if game["week"] != 3 or not game.get("completed"):
            raise ValueError("Week 3 total final score missing")
        difference = game["homePoints"] + game["awayPoints"] - row["locked_total"]
        direction = row["selected_direction"].lower()
        result = "push" if difference == 0 else "win" if (difference > 0 and direction == "over") or (difference < 0 and direction == "under") else "loss"
        totals.append({"week": 3, "status": "RECORDED_PREKICKOFF_PROVISIONAL_SHADOW", "result": result,
                       "direction": direction, "confidence": row.get("shadow_confidence")})
    if Counter(row["week"] for row in ats) != {1: 43, 2: 49, 3: 56} or Counter(row["week"] for row in totals) != {2: 49, 3: 56}:
        raise ValueError("prior-card evidence coverage mismatch")
    report = {
        "source_sha256": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in EVIDENCE.iterdir()},
        "score_source_sha256": hashlib.sha256(GAMES.read_bytes()).hexdigest(),
        "ats_by_week": {str(week): summary([row for row in ats if row["week"] == week]) for week in (1, 2, 3)},
        "ats_recorded_local_draft_weeks1_2": summary([row for row in ats if row["week"] <= 2]),
        "ats_all_recorded_including_provisional_week3": summary(ats),
        "ats_top_five_by_week": {str(week): summary([row for row in ats if row["week"] == week and row["top_five"]]) for week in (1, 2, 3)},
        "ats_top_five_recorded_local_draft_weeks1_2": summary([row for row in ats if row["week"] <= 2 and row["top_five"]]),
        "ats_top_five_including_provisional_week3": summary([row for row in ats if row["top_five"]]),
        "totals_by_week": {str(week): summary([row for row in totals if row["week"] == week]) for week in (2, 3)},
        "totals_all_shadow": summary(totals),
        "totals_top_five": "NO_STORED_TOP_FIVE_ACROSS_BOTH_WEEKS;RETROSPECTIVE_RANK_NOT_CLAIMED",
        "ats_cuts_all_recorded": cuts(ats, ("favorite_status", "selected_side", "road_favorite", "spread_bucket", "confidence", "hook_outcome")),
        "totals_cuts_all_recorded": cuts(totals, ("direction", "confidence")),
        "week4": "NO_PREEXISTING_PICK_CARD;RESULTS_ONLY;NO_RETROACTIVE_PICKS",
        "limitations": ["Week 1 archived closing timestamps do not satisfy governed CLV custody", "Week 2 and 3 complete closing-line custody is absent", "Week 3 cards were provisional, not officially published", "No Week 4 pregame card is available"],
    }
    (OUTPUT / "week5_prior_performance_audit.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ats_recorded_1_2": report["ats_recorded_local_draft_weeks1_2"], "ats_with_week3": report["ats_all_recorded_including_provisional_week3"], "totals": report["totals_all_shadow"]}))


if __name__ == "__main__":
    main()
