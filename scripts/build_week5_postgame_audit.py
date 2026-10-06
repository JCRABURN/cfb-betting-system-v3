"""Replay the Week 5 postgame audit from frozen cards and captured evidence."""

from __future__ import annotations

import csv
import difflib
import gzip
import hashlib
import json
import re
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from scripts.week5_postgame_core import (
    classify_late_score, clv_ats, clv_total, edge_bucket, grade_ats,
    grade_total, hook_key_classification, pearson, record, spread_bucket,
)


ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "outputs/2026-week5-execution-20260930-v4"
REVIEW = ROOT / "outputs/2026-week5-review-20261001"
OUTPUT = ROOT / "outputs/2026-week5-postgame-audit"
EVIDENCE = OUTPUT / "provider-evidence"


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def _json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(name: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"{name} cannot be empty")
    path = OUTPUT / name
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_json(name: str, data: object) -> None:
    (OUTPUT / name).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_captured(entry: dict[str, object]) -> dict[str, object]:
    path = ROOT / str(entry["stored_gzip_path"])
    raw = gzip.decompress(path.read_bytes())
    if hashlib.sha256(raw).hexdigest() != entry["raw_sha256"]:
        raise ValueError(f"captured provider evidence hash changed: {path}")
    return json.loads(raw)


def _frozen_inputs() -> tuple[dict[str, object], dict[str, str]]:
    custody = _json(REVIEW / "v4-custody-manifest.json")
    assert isinstance(custody, dict)
    for item in custody["v4_files"]:
        if _sha(ROOT / item["path"]) != item["sha256"]:
            raise ValueError(f"frozen pregame file changed: {item['path']}")
    source_db = _sha(ROOT / "data/cfb.db")
    if source_db != custody["source_database_sha256"]:
        raise ValueError("source database changed from pregame custody")
    model = _json(V4 / "week5_model_manifest.json")
    assert isinstance(model, dict)
    locked = ROOT / "production-weeks/2026-week5-splashsports.csv"
    locked_canonical_hash = hashlib.sha256(locked.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    if locked_canonical_hash != model["locked_source_csv_sha256"]:
        raise ValueError("locked SplashSports source changed")
    review_files = {
        path.relative_to(ROOT).as_posix(): _sha(path)
        for path in REVIEW.rglob("*") if path.is_file()
    }
    return model, {"source_database_sha256": source_db,
                   "locked_source_csv_sha256": locked_canonical_hash,
                   "pregame_v4_files_verified": len(custody["v4_files"]),
                   "review_file_hashes": review_files}


def _market_close(summary: dict[str, object]) -> tuple[str, str, str]:
    """Store provider-labeled close as evidence, not timestamp-qualified CLV."""
    for quote in summary.get("pickcenter", []):
        if quote.get("provider", {}).get("name") != "DraftKings":
            continue
        spread = quote.get("pointSpread", {}).get("home", {}).get("close", {}).get("line", "")
        total = quote.get("total", {}).get("over", {}).get("close", {}).get("line", "")
        return "DraftKings", str(spread), str(total).removeprefix("o")
    return "", "", ""


def _passing_leaders(summary: dict[str, object]) -> dict[str, str]:
    competition = summary["header"]["competitions"][0]
    team_ids = {item["team"]["id"]: item["homeAway"] for item in competition["competitors"]}
    leaders = {"home": "", "away": ""}
    for team in summary.get("boxscore", {}).get("players", []):
        side = team_ids.get(team.get("team", {}).get("id"))
        if side is None:
            continue
        passing = next((item for item in team.get("statistics", []) if item.get("name") == "passing"), None)
        if passing and passing.get("athletes"):
            leaders[side] = passing["athletes"][0]["athlete"]["displayName"]
    return leaders


def _segments(rows: list[dict[str, object]], result_key: str, key: str) -> dict[str, dict[str, object]]:
    groups: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        groups[str(row[key])].append(str(row[result_key]))
    return {name: record(values) for name, values in sorted(groups.items())}


def _score_reconciliation(
    card: list[dict[str, str]], capture: dict[str, object],
) -> tuple[list[dict[str, object]], dict[str, dict[str, object]]]:
    scoreboard = _load_captured(capture["scoreboard"])
    ncaa_scoreboard = _load_captured(capture["ncaa_derived_scoreboard"])
    ncaa_games = [item["game"] for item in ncaa_scoreboard["games"]]
    events = {str(item["id"]): item for item in scoreboard["events"]}
    summaries = {str(item["endpoint"]).split("event=")[-1]: item
                 for item in capture["summaries"]}
    if len(card) != 56 or len({row["game_id"] for row in card}) != 56:
        raise ValueError("ATS card is not 56 unique games")
    if set(row["game_id"] for row in card) - set(events) or set(row["game_id"] for row in card) - set(summaries):
        raise ValueError("ESPN capture does not cover every locked game")
    results: list[dict[str, object]] = []
    summary_by_id: dict[str, dict[str, object]] = {}
    used_ncaa_ids: set[str] = set()

    def name_key(name: str) -> str:
        ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
        return re.sub("[^a-z0-9]", "", ascii_name.replace("state", "st"))

    def similarity(first: str, second: str) -> float:
        return difflib.SequenceMatcher(None, name_key(first), name_key(second)).ratio()

    for row in card:
        game_id = row["game_id"]
        event = events[game_id]
        summary_entry = summaries[game_id]
        summary = _load_captured(summary_entry)
        summary_by_id[game_id] = summary
        event_comp = event["competitions"][0]
        summary_comp = summary["header"]["competitions"][0]
        scoreboard_teams = {item["homeAway"]: item for item in event_comp["competitors"]}
        summary_teams = {item["homeAway"]: item for item in summary_comp["competitors"]}
        away_score, home_score = (int(scoreboard_teams[side]["score"]) for side in ("away", "home"))
        summary_scores = tuple(int(summary_teams[side]["score"]) for side in ("away", "home"))
        if (away_score, home_score) != summary_scores:
            raise ValueError(f"scoreboard/summary score conflict for game {game_id}")
        ranked_ncaa = sorted(
            [(
                similarity(row["away"], game["away"]["names"]["short"])
                + similarity(row["home"], game["home"]["names"]["short"]),
                game,
            ) for game in ncaa_games],
            key=lambda item: item[0],
        )
        ncaa_score, ncaa_game = ranked_ncaa[-1]
        runner_up = ranked_ncaa[-2][0]
        ncaa_id = str(ncaa_game["gameID"])
        if ncaa_score < 1.15 or ncaa_score - runner_up < 0.3 or ncaa_id in used_ncaa_ids:
            raise ValueError(f"ambiguous NCAA-derived matchup reconciliation for game {game_id}")
        used_ncaa_ids.add(ncaa_id)
        if ncaa_game["gameState"] != "final" or (
            int(ncaa_game["away"]["score"]), int(ncaa_game["home"]["score"])
        ) != (away_score, home_score):
            raise ValueError(f"ESPN/NCAA-derived score or completion conflict for game {game_id}")
        status = event["status"]["type"]
        summary_status = summary_comp["status"]["type"]
        if not status.get("completed") or status["name"] != "STATUS_FINAL" or not summary_status.get("completed"):
            raise ValueError(f"game {game_id} is not officially final")
        away_name = scoreboard_teams["away"]["team"].get("location", "")
        home_name = scoreboard_teams["home"]["team"].get("location", "")
        if (away_name, home_name) == (row["away"], row["home"]):
            orientation = "EXACT"
        elif game_id == "401864513" and away_name == row["away"] and home_name == "San Jos� State" and row["home"] == "San José State":
            orientation = "ESPN_ENCODING_RECONCILED_BY_GAME_ID_AND_HOME_AWAY"
        else:
            raise ValueError(f"home/away orientation conflict for game {game_id}: {away_name} @ {home_name}")
        results.append({
            "game_id": game_id, "away": row["away"], "home": row["home"],
            "away_score": away_score, "home_score": home_score,
            "game_status": status["name"], "official_completion_status": "COMPLETED",
            "overtime": str(int(event["status"].get("period", 4)) > 4 or "OT" in status.get("detail", "")),
            "overtime_periods": max(0, int(event["status"].get("period", 4)) - 4),
            "kickoff_utc": event_comp["date"], "orientation_status": orientation,
            "scoreboard_source": capture["scoreboard"]["endpoint"],
            "summary_source": summary_entry["endpoint"],
            "scoreboard_retrieved_at_utc": capture["scoreboard"]["retrieved_at_utc"],
            "summary_retrieved_at_utc": summary_entry["retrieved_at_utc"],
            "scoreboard_payload_sha256": capture["scoreboard"]["raw_sha256"],
            "summary_payload_sha256": summary_entry["raw_sha256"],
            "ncaa_derived_game_id": ncaa_id,
            "ncaa_derived_status": ncaa_game["gameState"],
            "ncaa_derived_name_match_score": round(ncaa_score, 6),
            "ncaa_derived_source": capture["ncaa_derived_scoreboard"]["endpoint"],
            "ncaa_derived_retrieved_at_utc": capture["ncaa_derived_scoreboard"]["retrieved_at_utc"],
            "ncaa_derived_payload_sha256": capture["ncaa_derived_scoreboard"]["raw_sha256"],
        })
    return results, summary_by_id


def _prior_sample_flags() -> dict[str, dict[str, object]]:
    games = _json(V4 / "provider-evidence/cfbd-2026-games.json")
    teams: dict[str, dict[str, object]] = defaultdict(lambda: {"fcs_games": 0, "max_margin": 0, "completed_games": 0})
    for game in games:
        if game.get("week", 99) > 4 or not game.get("completed"):
            continue
        for side, opponent in (("home", "away"), ("away", "home")):
            team = str(game[f"{side}Team"])
            sample = teams[team]
            sample["completed_games"] += 1
            sample["fcs_games"] += int(game.get(f"{opponent}Classification") == "fcs")
            if game.get("homePoints") is not None and game.get("awayPoints") is not None:
                sample["max_margin"] = max(sample["max_margin"], abs(int(game["homePoints"]) - int(game["awayPoints"])))
    return teams


def build() -> dict[str, object]:
    model, custody = _frozen_inputs()
    capture = _json(EVIDENCE / "capture-manifest.json")
    assert isinstance(capture, dict)
    card = _csv(V4 / "week5_ats_full_card.csv")
    totals = _csv(V4 / "week5_totals_full_card.csv")
    results, summaries = _score_reconciliation(card, capture)
    if len(totals) != 56 or {row["game_id"] for row in totals} != {row["game_id"] for row in card}:
        raise ValueError("totals card does not match all 56 locked ATS games")
    by_total = {row["game_id"]: row for row in totals}
    by_result = {row["game_id"]: row for row in results}
    decision = {row["game_id"]: row for row in _csv(REVIEW / "week5_decision_shortlist.csv")}
    analytical_ids = {row["game_id"] for row in _csv(REVIEW / "week5_analytical_ats_shortlist.csv")}
    shadow_top_ids = {row["game_id"] for row in _csv(V4 / "week5_shadow_totals_top5.csv")}
    governed_ids = {row["game_id"] for row in _csv(V4 / "week5_official_ats_top5.csv")}
    market = {row["game_id"]: row for row in _csv(REVIEW / "week5_market_weather_review.csv")}
    qb = {row["game_id"]: row for row in _csv(REVIEW / "week5_qb_injury_review.csv")}
    edge_review = {row["game_id"]: row for row in _csv(REVIEW / "week5_large_ats_edge_adjudication.csv")}
    prior_flags = _prior_sample_flags()
    ats_rows: list[dict[str, object]] = []
    totals_rows: list[dict[str, object]] = []
    clv_rows: list[dict[str, object]] = []
    hook_rows: list[dict[str, object]] = []
    late_rows: list[dict[str, object]] = []
    logic_rows: list[dict[str, object]] = []
    large_rows: list[dict[str, object]] = []
    decision_rows: list[dict[str, object]] = []

    for row in card:
        game_id = row["game_id"]
        result = by_result[game_id]
        total = by_total[game_id]
        summary = summaries[game_id]
        market_row = market[game_id]
        qb_row = qb[game_id]
        actual_home_margin = int(result["home_score"]) - int(result["away_score"])
        actual_total = int(result["home_score"]) + int(result["away_score"])
        ats_result, ats_margin = grade_ats(row["selected_side"], row["locked_home_spread"], actual_home_margin)
        total_result, total_margin = grade_total(total["pick"], total["locked_total"], actual_total)
        selected_spread = row["pick_spread"]
        edge = abs(float(row["home_ats_edge"]))
        projection_error = actual_home_margin - float(row["projected_home_margin"])
        away_sample = prior_flags.get(row["away"], {})
        home_sample = prior_flags.get(row["home"], {})
        fcs_count = int(away_sample.get("fcs_games", 0)) + int(home_sample.get("fcs_games", 0))
        max_prior_margin = max(int(away_sample.get("max_margin", 0)), int(home_sample.get("max_margin", 0)))
        qb_status = "PROBABLE/PROBABLE" if qb_row["away_qb_status"] == qb_row["home_qb_status"] == "PROBABLE" else "QB_UNCERTAINTY_PRESENT"
        favorite = "favorite" if float(selected_spread) < 0 else "underdog" if float(selected_spread) > 0 else "pickem"
        book, provider_close_home, provider_close_total = _market_close(summary)
        close_source = next(item["endpoint"] for item in capture["summaries"] if item["endpoint"].endswith(f"event={game_id}"))
        close_retrieved_at = next(item["retrieved_at_utc"] for item in capture["summaries"] if item["endpoint"].endswith(f"event={game_id}"))
        ats_indicative = (
            str(clv_ats(row["selected_side"], row["locked_home_spread"], provider_close_home))
            if provider_close_home else ""
        )
        total_indicative = (
            str(clv_total(total["pick"], total["locked_total"], provider_close_total))
            if provider_close_total else ""
        )
        common = {"game_id": game_id, "away": row["away"], "home": row["home"]}
        ats_rows.append({
            **common, "locked_home_spread": row["locked_home_spread"],
            "selected_side": row["selected_side"], "pick": row["pick"],
            "selected_spread": selected_spread, "projected_home_margin": row["projected_home_margin"],
            "raw_home_ats_edge": row["home_ats_edge"], "raw_selected_ats_edge": edge,
            "shadow_uncertainty_points": row["shadow_uncertainty_points"],
            "confidence": row["confidence"], "rank": row["rank"], "governed_top_five": row["top_five"],
            "analytical_shortlist": str(game_id in analytical_ids), "decision_shortlist": str(game_id in decision),
            "final_away_score": result["away_score"], "final_home_score": result["home_score"],
            "actual_home_margin": actual_home_margin, "ats_result": ats_result,
            "ats_grading_margin": str(ats_margin), "model_home_margin_error": projection_error,
            "favorite_status": favorite, "location": row["selected_side"],
            "spread_bucket": spread_bucket(selected_spread), "raw_edge_bucket": edge_bucket(edge),
            "fcs_contaminated_prior_sample": str(fcs_count > 0), "prior_fcs_games": fcs_count,
            "prior_blowout_35_plus": str(max_prior_margin >= 35), "qb_status": qb_status,
            "oct1_market_locked_advantage": market_row["ats_selected_locked_advantage"],
            "closing_clv_status": "UNAVAILABLE_NO_TIMESTAMPED_CLOSE",
            "score_source": result["summary_source"], "score_retrieved_at_utc": result["summary_retrieved_at_utc"],
        })
        totals_rows.append({
            **common, "locked_splash_total": total["locked_total"],
            "projected_total": total["projected_total"], "selected_total": total["pick"],
            "raw_point_edge": total["raw_point_edge"],
            "raw_selected_probability": total["raw_selected_probability"],
            "probability_status": total["probability_status"], "confidence": total["confidence"],
            "final_away_score": result["away_score"], "final_home_score": result["home_score"],
            "actual_total": actual_total, "total_result": total_result,
            "total_grading_margin": str(total_margin),
            "projection_error_actual_minus_model": actual_total - float(total["projected_total"]),
            "raw_edge_bucket": edge_bucket(total["raw_point_edge"]),
            "shadow_top_five": str(game_id in shadow_top_ids),
            "status": "SHADOW_NOT_PRODUCTION_ELIGIBLE", "closing_clv_status": "UNAVAILABLE_NO_TIMESTAMPED_CLOSE",
            "score_source": result["summary_source"], "score_retrieved_at_utc": result["summary_retrieved_at_utc"],
        })
        for market_name, selection, locked, provider_close, indicative in (
            ("ATS", row["selected_side"], row["locked_home_spread"], provider_close_home, ats_indicative),
            ("TOTAL", total["pick"], total["locked_total"], provider_close_total, total_indicative),
        ):
            clv_rows.append({
                **common, "market": market_name, "selection": selection, "locked_line": locked,
                "closing_book": book, "provider_labeled_close_line": provider_close,
                "provider_close_retrieved_at_utc": close_retrieved_at,
                "provider_close_quote_observed_at_utc": "", "provider_close_source": close_source,
                "indicative_locked_minus_provider_close_points": indicative,
                "clv_points": "", "clv_direction": "UNAVAILABLE",
                "clv_status": "UNAVAILABLE_NO_TIMESTAMPED_CLOSE",
            })
        hook = hook_key_classification(selected_spread, actual_home_margin, ats_margin)
        hook_rows.append({**common, "pick": row["pick"], "selected_spread": selected_spread,
                          "actual_home_margin": actual_home_margin, "ats_grading_margin": str(ats_margin), **hook})
        plays = summary.get("scoringPlays", [])
        sequence_complete = bool(plays) and (
            int(plays[-1]["awayScore"]), int(plays[-1]["homeScore"])
        ) == (int(result["away_score"]), int(result["home_score"]))
        late = classify_late_score(plays, row["selected_side"],
                                   row["locked_home_spread"], int(result["away_score"]), int(result["home_score"]))
        if not sequence_complete:
            late = {"classification": "NOT_EVALUATED_NO_PBP", "decisive_score": "", "game_clock": "", "period": "",
                    "score_before_late_play": "", "score_after_late_play": ""}
        late_rows.append({**common, "pick": row["pick"], "ats_result": ats_result,
                          **late, "scoring_sequence_status": "COMPLETE" if sequence_complete else "PARTIAL_OR_UNAVAILABLE_FINAL_SCORE_MISMATCH",
                          "source": result["summary_source"],
                          "source_payload_sha256": result["summary_payload_sha256"]})
        priority = [name for name, selected in (
            ("RAW_EDGE_GE_7", edge >= 7), ("DECISION_SHORTLIST", game_id in decision),
            ("GOVERNED_TOP_FIVE", game_id in governed_ids),
            ("ANALYTICAL_SHORTLIST", game_id in analytical_ids),
            ("SHADOW_TOTALS_TOP_FIVE", game_id in shadow_top_ids),
        ) if selected]
        logic_code = "MODEL_PROJECTION_FAILURE" if abs(projection_error) >= 14 else "NO_CLEAR_LOGIC_FAILURE"
        logic_rows.append({
            **common, "review_scope": ";".join(priority) or "FULL_CARD_SCREEN",
            "ats_result": ats_result, "model_home_margin_error": projection_error,
            "failure_code": logic_code,
            "failure_code_basis": "ABS_HOME_MARGIN_ERROR_GE_14_POINT_MEASUREMENT_ONLY" if logic_code == "MODEL_PROJECTION_FAILURE" else "NO_CAUSAL_FAILURE_VERIFIED",
            "fcs_prior_games": fcs_count, "prior_blowout_35_plus": str(max_prior_margin >= 35),
            "qb_status_at_review": qb_status, "late_score_classification": late["classification"],
            "causal_explanation_status": "UNVERIFIED;NO_SPECULATIVE_TAXONOMY_ASSIGNED",
            "score_source": result["summary_source"],
        })
        if edge >= 7:
            original = edge_review.get(game_id, {})
            large_rows.append({
                **common, "pick": row["pick"], "ats_result": ats_result,
                "raw_selected_edge": edge, "ats_grading_margin": str(ats_margin),
                "model_home_margin_error": projection_error,
                "clv_status": "UNAVAILABLE_NO_TIMESTAMPED_CLOSE",
                "fcs_prior_games": fcs_count, "prior_blowout_35_plus": str(max_prior_margin >= 35),
                "qb_status_at_review": qb_status,
                "opponent_strength_adjustment_availability": original.get("opponent_strength_adjustment", "NOT_IN_BASELINE"),
                "structural_warnings": original.get("structural_warnings", ""),
            })
        if game_id in decision:
            advantage = float(market_row["ats_selected_locked_advantage"])
            movement = "AGREED_WITH_SELECTION" if advantage > 0 else "DISAGREED_WITH_SELECTION" if advantage < 0 else "NEUTRAL"
            passers = _passing_leaders(summary)
            expected_away_qb = qb_row["expected_away_qb"]
            expected_home_qb = qb_row["expected_home_qb"]
            qb_role_comparison = (
                "EXPECTED_HOME_QB_NOT_POSTGAME_PASSING_LEADER"
                if passers["home"] and passers["home"] not in expected_home_qb
                else "EXPECTED_AWAY_QB_NOT_POSTGAME_PASSING_LEADER"
                if passers["away"] and passers["away"] not in expected_away_qb
                else "PREGAME_QB_NAMES_MATCH_POSTGAME_PASSING_LEADERS"
            )
            qb_note = (
                f"ESPN boxscore passing leaders: away {passers['away'] or 'UNAVAILABLE'}; "
                f"home {passers['home'] or 'UNAVAILABLE'}; participation only, "
                "not verified starting assignment or injury status"
            )
            decision_rows.append({
                **common, "decision_rank": decision[game_id]["rank"], "pick": row["pick"],
                "locked_spread": selected_spread, "closing_book": book,
                "closing_market_line": "UNAVAILABLE_NO_TIMESTAMPED_CLOSE",
                "provider_labeled_home_close": provider_close_home,
                "final_away_score": result["away_score"], "final_home_score": result["home_score"],
                "ats_result": ats_result, "ats_grading_margin": str(ats_margin),
                "clv_points": "", "clv_direction": "UNAVAILABLE",
                "model_projected_home_margin": row["projected_home_margin"], "raw_selected_ats_edge": edge,
                "oct1_market_movement_vs_selection": movement,
                "pregame_expected_away_qb": expected_away_qb,
                "pregame_expected_home_qb": expected_home_qb,
                "postgame_away_passing_leader": passers["away"],
                "postgame_home_passing_leader": passers["home"],
                "qb_role_comparison": qb_role_comparison,
                "post_review_qb_injury_information": qb_note,
                "weather_relevance": "NO_VERIFIED_GAME_DAY_CAUSAL_EVIDENCE",
                "original_rationale_assessment": (
                    "DIRECTIONAL_EDGE_REALIZED;CONTEXTUAL_RATIONALE_UNVERIFIED" if ats_result == "WIN"
                    else "DIRECTIONAL_EDGE_NOT_REALIZED;CONTEXT_CAUSE_UNVERIFIED"
                ),
                "result_quality": ats_result,
                "decision_quality": (
                    "QB_EXPECTATION_WEAKENED;CAUSAL_EFFECT_UNVERIFIED"
                    if qb_role_comparison != "PREGAME_QB_NAMES_MATCH_POSTGAME_PASSING_LEADERS"
                    else "INDETERMINATE_WITHOUT_VERIFIED_CONTEXT_AND_CLV"
                ),
                "primary_result_reason": f"FINAL_HOME_MARGIN_{actual_home_margin}_VERSUS_LOCKED_HOME_SPREAD_{row['locked_home_spread']}",
                "causal_reason_status": "UNDETERMINED;DO_NOT_INFER_FROM_RESULT",
                "score_source": result["summary_source"],
            })

    if len(ats_rows) != 56 or len(totals_rows) != 56 or len(decision_rows) != 5 or len(large_rows) != 23:
        raise ValueError("postgame output coverage gate failed")
    if any(not row["score_source"] for row in ats_rows + totals_rows):
        raise ValueError("missing result provenance")
    decision_rows.sort(key=lambda row: int(row["decision_rank"]))
    for name, rows in (
        ("week5_final_results.csv", results), ("week5_ats_audit.csv", ats_rows),
        ("week5_totals_audit.csv", totals_rows),
        ("week5_decision_shortlist_audit.csv", decision_rows),
        ("week5_clv_audit.csv", clv_rows),
        ("week5_hook_key_number_audit.csv", hook_rows),
        ("week5_late_score_audit.csv", late_rows),
        ("week5_logic_failure_audit.csv", logic_rows),
        ("week5_large_edge_diagnostics.csv", large_rows),
    ):
        _write_csv(name, rows)
    return _finish(model, custody, capture, results, ats_rows, totals_rows,
                   decision_rows, large_rows, logic_rows, late_rows)


def _combined(*parts: dict[str, object]) -> dict[str, object]:
    all_results: list[str] = []
    for part in parts:
        all_results.extend(["WIN"] * int(part["win"]))
        all_results.extend(["LOSS"] * int(part["loss"]))
        all_results.extend(["PUSH"] * int(part["push"]))
    return record(all_results)


def _finish(
    model: dict[str, object], custody: dict[str, object], capture: dict[str, object],
    results: list[dict[str, object]], ats: list[dict[str, object]],
    totals: list[dict[str, object]], decision: list[dict[str, object]],
    large: list[dict[str, object]], logic: list[dict[str, object]],
    late: list[dict[str, object]],
) -> dict[str, object]:
    ats_all = record(str(row["ats_result"]) for row in ats)
    totals_all = record(str(row["total_result"]) for row in totals)
    governed = [row for row in ats if row["governed_top_five"] == "True"]
    analytical = [row for row in ats if row["analytical_shortlist"] == "True"]
    decision_ats = [row for row in ats if row["decision_shortlist"] == "True"]
    shadow_top = [row for row in totals if row["shadow_top_five"] == "True"]
    remaining_ats = [row for row in ats if row["governed_top_five"] != "True"]
    remaining_totals = [row for row in totals if row["shadow_top_five"] != "True"]
    raw_edge_top_five = sorted(ats, key=lambda row: (-float(row["raw_selected_ats_edge"]), str(row["game_id"])))[:5]
    if len(governed) != 5 or len(analytical) != 7 or len(decision_ats) != 5 or len(shadow_top) != 5:
        raise ValueError("pregame shortlist coverage changed")

    ats_by_location_favorite = defaultdict(list)
    for row in ats:
        ats_by_location_favorite[f"{row['location']}_{row['favorite_status']}"].append(row["ats_result"])
    ats_diagnostics = {
        "all": ats_all,
        "favorite_status": _segments(ats, "ats_result", "favorite_status"),
        "location": _segments(ats, "ats_result", "location"),
        "location_favorite_status": {key: record(values) for key, values in sorted(ats_by_location_favorite.items())},
        "spread_bucket": _segments(ats, "ats_result", "spread_bucket"),
        "raw_edge_bucket": _segments(ats, "ats_result", "raw_edge_bucket"),
        "confidence": {str(level): record(row["ats_result"] for row in ats if row["confidence"] == str(level))
                       for level in range(1, 6)},
        "governed_deterministic_top_five": record(row["ats_result"] for row in governed),
        "analytical_ats_shortlist": record(row["ats_result"] for row in analytical),
        "pregame_raw_edge_top_five_comparator": record(row["ats_result"] for row in raw_edge_top_five),
        "pregame_raw_edge_top_five_game_ids": [row["game_id"] for row in raw_edge_top_five],
        "decision_shortlist": record(row["ats_result"] for row in decision_ats),
        "remaining_card": record(row["ats_result"] for row in remaining_ats),
        "fcs_contaminated_prior_sample": _segments(ats, "ats_result", "fcs_contaminated_prior_sample"),
        "qb_status_at_oct1_review": _segments(ats, "ats_result", "qb_status"),
        "clv_positive": record([]), "clv_negative": record([]),
    }
    total_diagnostics = {
        "all": totals_all,
        "direction": _segments(totals, "total_result", "selected_total"),
        "raw_edge_bucket": _segments(totals, "total_result", "raw_edge_bucket"),
        "confidence": {str(level): record(row["total_result"] for row in totals if row["confidence"] == str(level))
                       for level in range(1, 6)},
        "shadow_top_five": record(row["total_result"] for row in shadow_top),
        "remaining_card": record(row["total_result"] for row in remaining_totals),
        "clv_positive": record([]), "clv_negative": record([]),
    }
    ats_nonpush = [row for row in ats if row["ats_result"] != "PUSH"]
    win_indicator = [float(row["ats_result"] == "WIN") for row in ats_nonpush]
    errors = [float(row["model_home_margin_error"]) for row in ats]
    mean_error = sum(errors) / len(errors)
    correlations = {
        "raw_selected_edge_vs_ats_win": {
            "r": pearson([float(row["raw_selected_ats_edge"]) for row in ats_nonpush], win_indicator),
            "n": len(ats_nonpush),
        },
        "shadow_uncertainty_vs_ats_win": {
            "r": pearson([float(row["shadow_uncertainty_points"]) for row in ats_nonpush], win_indicator),
            "n": len(ats_nonpush),
        },
        "oct1_locked_advantage_vs_ats_win": {
            "r": pearson([float(row["oct1_market_locked_advantage"]) for row in ats_nonpush], win_indicator),
            "n": len(ats_nonpush),
        },
        "timestamp_qualified_clv_vs_ats_win": {"r": None, "n": 0, "reason": "NO_TIMESTAMPED_CLOSE"},
        "model_home_margin_error_sample_variance": sum((value - mean_error) ** 2 for value in errors) / (len(errors) - 1),
        "governed_confidence_variance": 0,
    }
    large_record = record(row["ats_result"] for row in large)
    nonlarge_record = record(row["ats_result"] for row in ats if float(row["raw_selected_ats_edge"]) < 7)
    large_summary = {
        "edge_ge_7": large_record,
        "edge_lt_7": nonlarge_record,
        "mean_raw_edge_ge_7": sum(float(row["raw_selected_edge"]) for row in large) / len(large),
        "mean_grading_margin_ge_7": sum(float(row["ats_grading_margin"]) for row in large) / len(large),
        "fcs_flagged_ge_7": sum(int(row["fcs_prior_games"]) > 0 for row in large),
        "prior_blowout_flagged_ge_7": sum(row["prior_blowout_35_plus"] == "True" for row in large),
        "qb_uncertain_ge_7": sum(row["qb_status_at_review"] != "PROBABLE/PROBABLE" for row in large),
        "clv_available_ge_7": 0,
        "threshold_inference": "DESCRIPTIVE_ONLY;NO_NEW_RULE_FROM_ONE_WEEK",
    }
    week1_rows = [row for row in _csv(V4 / "prior-evidence/week1-postgame-audit.csv")
                  if row["ats_result"] in {"WIN", "LOSS", "PUSH"} and row["model_ats_edge"]]
    large_summary["prior_week1_recorded_draft_edge_ge_7"] = record(
        row["ats_result"] for row in week1_rows if abs(float(row["model_ats_edge"])) >= 7
    )
    large_summary["prior_week1_recorded_draft_edge_lt_7"] = record(
        row["ats_result"] for row in week1_rows if abs(float(row["model_ats_edge"])) < 7
    )
    large_summary["prior_comparability_limit"] = (
        "WEEK1_LOCAL_DRAFT_COMPARABLE_DIRECTIONALLY;WEEK2_RAW_EDGES_AND_WEEK3_ROW_LEVEL_GRADE_NOT_IN_FROZEN_AUDIT"
    )
    human_groups = {
        "full_card": ats, "governed_deterministic_top_five": governed,
        "analytical_ats_shortlist": analytical, "human_decision_shortlist": decision_ats,
        "raw_edge_top_five_comparator": raw_edge_top_five,
    }
    human_comparison = {
        name: {
            "record": record(row["ats_result"] for row in group),
            "mean_ats_grading_margin": round(sum(float(row["ats_grading_margin"]) for row in group) / len(group), 4),
            "measured_14_plus_margin_error_count": sum(abs(float(row["model_home_margin_error"])) >= 14 for row in group),
            "qualified_clv": "UNAVAILABLE_NO_TIMESTAMPED_CLOSE",
            "game_ids": [row["game_id"] for row in group],
        }
        for name, group in human_groups.items()
    }
    diagnostics = {
        "scope": "2026_WEEK5_LOCAL_GOVERNED_DRAFT_AND_SHADOW;NO_WAGERS_ASSUMED",
        "roi_method": "one_unit_risked_per_selection_at_-110;win=10/11_units;loss=-1;push=0;denominator_includes_pushes",
        "ats": ats_diagnostics,
        "shadow_totals": total_diagnostics,
        "large_edge": large_summary,
        "human_layer_comparison": human_comparison,
        "correlations": correlations,
        "clv_status": "UNAVAILABLE_FOR_ALL_112_SELECTIONS_NO_TIMESTAMPED_CLOSE",
        "late_score_counts": dict(sorted(Counter(row["classification"] for row in late).items())),
        "measured_14_plus_model_margin_misses": sum(row["failure_code"] == "MODEL_PROJECTION_FAILURE" for row in logic),
    }
    _write_json("week5_diagnostics.json", diagnostics)

    prior = _json(V4 / "week5_prior_performance_audit.json")
    ats_by_week = {week: _combined(counts) for week, counts in prior["ats_by_week"].items()}
    ats_by_week["5"] = ats_all
    total_by_week = {week: _combined(counts) for week, counts in prior["totals_by_week"].items()}
    total_by_week["5"] = totals_all
    top_by_week = {week: _combined(counts) for week, counts in prior["ats_top_five_by_week"].items()}
    top_by_week["5"] = ats_diagnostics["governed_deterministic_top_five"]
    cumulative = {
        "source": (V4 / "week5_prior_performance_audit.json").relative_to(ROOT).as_posix(),
        "week_1_2_recorded_local_drafts": _combined(ats_by_week["1"], ats_by_week["2"]),
        "week_3_provisional": ats_by_week["3"],
        "week_4": "NO_RECORDED_REPLAY_SAFE_PICKS;EXCLUDED",
        "week_5": ats_all,
        "ats_by_week": ats_by_week,
        "ats_all_recorded_including_provisional_week3": _combined(*ats_by_week.values()),
        "governed_top_five_by_week": top_by_week,
        "governed_top_five_all_recorded_including_provisional_week3": _combined(*top_by_week.values()),
        "decision_shortlist_recorded_only_week5": ats_diagnostics["decision_shortlist"],
        "shadow_totals_by_week": total_by_week,
        "shadow_totals_all_recorded": _combined(*total_by_week.values()),
        "shadow_totals_top_five": "ONLY_WEEK5_STORED_TOP_FIVE;PRIOR_WEEKS_NOT_RETRO_RANKED",
        "clv": "UNAVAILABLE_NO_TIMESTAMPED_CLOSE_FOR_WEEK5;PRIOR_ARCHIVED_CLOSE_TIMESTAMP_CUSTODY_INCOMPLETE",
        "cumulative_segmentation_limit": "PRIOR_AGGREGATE_CUTS_USE_DIFFERENT_14_PLUS_BUCKET_AND_LACK_RAW_EDGE;DO_NOT_COMBINE_INCOMPATIBLE_BUCKETS",
        "prior_ats_cuts_as_recorded": prior["ats_cuts_all_recorded"],
        "week5_ats_cuts": {name: ats_diagnostics[name] for name in ("favorite_status", "location", "location_favorite_status", "spread_bucket", "raw_edge_bucket")},
    }
    prior_cuts = prior["ats_cuts_all_recorded"]
    combined_cuts = {
        "favorite_status": {
            key: _combined(prior_cuts["favorite_status"][key], ats_diagnostics["favorite_status"].get(key, record([])))
            for key in ("favorite", "underdog")
        },
        "location": {
            key: _combined(prior_cuts["selected_side"][key], ats_diagnostics["location"].get(key, record([])))
            for key in ("home", "away")
        },
        "road_favorite": _combined(
            prior_cuts["road_favorite"]["True"],
            ats_diagnostics["location_favorite_status"].get("away_favorite", record([])),
        ),
        "spread_bucket_comparable": {
            "0-2.5": _combined(prior_cuts["spread_bucket"]["under_3"], ats_diagnostics["spread_bucket"].get("0-2.5", record([]))),
            "3-6.5": _combined(prior_cuts["spread_bucket"]["3_to_6_5"], ats_diagnostics["spread_bucket"].get("3-6.5", record([]))),
            "7-13.5": _combined(prior_cuts["spread_bucket"]["7_to_9_5"], prior_cuts["spread_bucket"]["10_to_13_5"], ats_diagnostics["spread_bucket"].get("7-13.5", record([]))),
            "14+_cannot_split_prior_weeks": _combined(prior_cuts["spread_bucket"]["14_plus"], ats_diagnostics["spread_bucket"].get("14-20.5", record([])), ats_diagnostics["spread_bucket"].get("21+", record([]))),
        },
        "top_five": _combined(*top_by_week.values()),
        "remaining_card": _combined(
            {key: prior["ats_all_recorded_including_provisional_week3"][key] - prior["ats_top_five_including_provisional_week3"][key]
             for key in ("win", "loss", "push")},
            ats_diagnostics["remaining_card"],
        ),
        "raw_edge_bucket": "UNAVAILABLE_IN_COMPLETE_PRIOR_WEEK_AGGREGATE",
    }
    cumulative["combined_comparable_cuts"] = combined_cuts
    _write_json("week5_cumulative_2026_diagnostics.json", cumulative)
    return _reports(model, custody, capture, results, ats, totals, decision,
                    large, logic, late, diagnostics, cumulative)


def _record_text(value: dict[str, object]) -> str:
    roi = value["roi_minus110"]
    return f"{value['win']}-{value['loss']}-{value['push']} ({'n/a' if roi is None else f'{100 * roi:.2f}%' } ROI at -110)"


def _reports(
    model: dict[str, object], custody: dict[str, object], capture: dict[str, object],
    results: list[dict[str, object]], ats: list[dict[str, object]],
    totals: list[dict[str, object]], decision: list[dict[str, object]],
    large: list[dict[str, object]], logic: list[dict[str, object]],
    late: list[dict[str, object]],
    diagnostics: dict[str, object], cumulative: dict[str, object],
) -> dict[str, object]:
    a = diagnostics["ats"]
    t = diagnostics["shadow_totals"]
    large_summary = diagnostics["large_edge"]
    correlations = diagnostics["correlations"]
    human_comparison = diagnostics["human_layer_comparison"]
    ordered_decision = sorted(decision, key=lambda row: float(row["ats_grading_margin"]), reverse=True)
    material_misses = sorted(
        (row for row in logic if row["failure_code"] == "MODEL_PROJECTION_FAILURE"),
        key=lambda row: abs(float(row["model_home_margin_error"])), reverse=True,
    )
    decision_table = "\n".join(
        f"| {row['decision_rank']} | {row['away']} @ {row['home']} | {row['pick']} {float(row['locked_spread']):+g} | "
        f"{row['final_away_score']}-{row['final_home_score']} | {row['ats_result']} | "
        f"{row['ats_grading_margin']} | UNAVAILABLE | {row['decision_quality']} |"
        for row in decision
    )
    material_table = "\n".join(
        f"| {row['away']} @ {row['home']} | {row['ats_result']} | {float(row['model_home_margin_error']):+.1f} | "
        f"{row['failure_code']} |"
        for row in material_misses[:12]
    ) or "| None | — | — | — |"
    human_table = "\n".join(
        f"| {name.replace('_', ' ')} | {_record_text(details['record'])} | "
        f"{details['mean_ats_grading_margin']:+.2f} | {details['measured_14_plus_margin_error_count']}/{details['record']['n']} | UNAVAILABLE |"
        for name, details in human_comparison.items()
    )
    overtime = [row for row in results if row["overtime"] == "True"]
    late_counts = diagnostics["late_score_counts"]
    ats_by_game = {row["game_id"]: row for row in ats}
    backdoor_failure_table = "\n".join(
        f"| {row['away']} @ {row['home']} | {row['pick']} {float(ats_by_game[row['game_id']]['selected_spread']):+g} | "
        f"{row['score_before_late_play']} | {row['score_after_late_play']} | "
        f"{ats_by_game[row['game_id']]['final_away_score']}-{ats_by_game[row['game_id']]['final_home_score']} | "
        f"{row['ats_result']} |"
        for row in late if row["classification"] == "BACKDOOR_FAILURE"
    ) or "| None | — | — | — | — | — |"
    summary = (
        "# WEEK 5 2026 POSTGAME AUDIT\n\n"
        "This grades the frozen local governed-draft ATS card and shadow-only totals card; it does not create wagers or alter pregame selections. "
        "All results are from the captured ESPN Week 5 scoreboard and 56 game summaries, independently reconciled to an NCAA-derived scoreboard feed. "
        "Each provider response was retrieved after completion and preserved with raw SHA-256 and UTC retrieval time.\n\n"
        "## Frozen pregame state\n\n"
        f"Contest: `{model['contest_key']}`. Pregame code SHA: `{model['code_commit_sha']}`. "
        f"Card generated: `{model['generated_at_utc']}`. ATS model: `{model['ats']['version']}`; "
        f"ATS data hash: `{model['ats']['data_snapshot_sha256']}`. Totals model: `{model['totals']['version']}`; "
        f"totals data hash: `{model['totals']['data_snapshot_sha256']}`. "
        f"Locked-line snapshot: `{model['locked_line_snapshot_sha256']}`. "
        f"Source DB hash: `{custody['source_database_sha256']}`. "
        "The 56 ATS picks, 56 shadow totals, deterministic governed ATS Top 5, seven-game analytical ATS shortlist, "
        "five-game human decision shortlist, shadow totals watchlist and combined shadow Top 5 are read from the unchanged pregame files. "
        "The governed ATS Top 5 is lock-ID ordered, not strength ranked. All governed Week 5 Confidence values are 1.\n\n"
        "## Result and grading gates\n\n"
        f"56/56 locked game IDs have unique completed final scores; duplicate IDs 0, missing scores 0, postponed/cancelled graded 0. "
        f"ESPN scoreboard, ESPN game summary and NCAA-derived final scores agree for all 56. Overtime games: {len(overtime)}. "
        "Home/away orientation matches the locked card except ESPN's malformed `San Jos� State` text, "
        "reconciled explicitly by identical game ID, away name and provider home/away assignment; the locked name was not changed. "
        "For a home ATS pick, grading margin = actual home margin + locked home spread; for an away pick, it is the negative of that quantity. "
        "For Over, grading margin = actual total − locked total; Under uses its negative. Positive wins, zero pushes, negative loses. "
        "One unit is risked at -110 per selection; a win earns 10/11 units, loss costs 1, push earns 0, and ROI divides by all graded selections.\n\n"
        "## Week 5 records\n\n"
        f"- All ATS: **{_record_text(a['all'])}**; units {a['all']['units_minus110']}.\n"
        f"- Shadow totals: **{_record_text(t['all'])}**; units {t['all']['units_minus110']}; **SHADOW / NOT PRODUCTION ELIGIBLE**.\n"
        f"- Governed deterministic ATS Top 5: **{_record_text(a['governed_deterministic_top_five'])}**.\n"
        f"- Analytical ATS shortlist: **{_record_text(a['analytical_ats_shortlist'])}**.\n"
        f"- Human decision shortlist: **{_record_text(a['decision_shortlist'])}**.\n"
        f"- Shadow totals Top 5: **{_record_text(t['shadow_top_five'])}**.\n\n"
        "## Human decision shortlist: result quality versus decision quality\n\n"
        "| Review rank | Game | Frozen SplashSports selection | Final away-home | ATS result | Grading margin | Qualified CLV | Decision quality |\n"
        "| ---: | --- | --- | --- | --- | ---: | --- | --- |\n"
        f"{decision_table}\n\n"
        "All five are graded at their frozen SplashSports numbers. The October 1 DraftKings observations are preserved separately. "
        "Post-review QB/injury changes and game-day weather causation are not established by the captured evidence, so a cover is not treated as proof of good logic and a miss is not treated as proof of bad logic. "
        "Each row's mechanical outcome is determined by actual home margin plus its locked home spread; specific causal claims remain unverified. "
        "One concrete QB-role mismatch emerged: the Oct 1 review listed Nick Minicucci as Delaware's probable QB, "
        "while ESPN's postgame boxscore identifies EJ Archield Jr. as Delaware's leading passer. "
        "That weakens the review's QB certainty premise but does not establish who started, an injury, or the cause of the ATS loss.\n\n"
        "The best observed decision outcomes by locked ATS grading margin were "
        f"{ordered_decision[0]['pick']} (+{ordered_decision[0]['ats_grading_margin']} points) and "
        f"{ordered_decision[1]['pick']} (+{ordered_decision[1]['ats_grading_margin']} points); "
        "the worst were "
        f"{ordered_decision[-1]['pick']} ({ordered_decision[-1]['ats_grading_margin']} points) and "
        f"{ordered_decision[-2]['pick']} ({ordered_decision[-2]['ats_grading_margin']} points). "
        "This ranks results, not decision quality.\n\n"
        "### Human layer versus pregame comparators\n\n"
        "The raw-edge Top 5 comparator sorts only frozen pregame absolute edges; it is not an official or retrospectively altered card.\n\n"
        "| Group | W-L-P and ROI | Mean ATS grading margin | Measured 14+ model misses | Qualified CLV |\n"
        "| --- | --- | ---: | ---: | --- |\n"
        f"{human_table}\n\n"
        "## CLV and close provenance\n\n"
        "ESPN game summaries contain DraftKings `open` and `close` fields, but do not provide a quote-observed or closing timestamp. "
        "The audit records those provider-labeled numbers and an explicitly *indicative* locked-versus-provider difference, but all 112 qualified ATS/totals CLV values are **UNAVAILABLE**. "
        "The ESPN retrieval time is after the games and is not substituted for a pre-kickoff close timestamp. "
        "Thus ATS CLV-positive/negative records, decision-shortlist CLV, Top-5 CLV, shadow totals CLV and CLV/outcome correlation are unavailable, not zero.\n\n"
        "## Hook, key number, and late-score evidence\n\n"
        "Hook classifications require the actual ATS grading margin to equal ±0.5 on a half-point selection. "
        "Key-number classifications require a final margin of exactly 3 or 7 and a grading margin within one point of the boundary. "
        "The detailed game-by-game table records one-point boundaries separately. Late-score classification uses ESPN scoring-play sequence, clock and before/after cover state; it never infers a backdoor solely from the final. "
        "The late window is the final five minutes of regulation or overtime. BACKDOOR_COVER requires a selected-team score from an outright deficit into an ATS win while still losing outright. "
        "BACKDOOR_FAILURE requires a selected-team score from an outright deficit that improves the locked-line ATS margin, with a final ATS loss. "
        "LATE_FRONTDOOR_COVER requires a selected-team score into an ATS win without the backdoor-cover conditions. "
        "Other late scores are LATE_SCORE_NONDETERMINATIVE; absent or incomplete scoring sequences are NOT_EVALUATED_NO_PBP; no late score is NOT_APPLICABLE. "
        "UTEP–New Mexico's ESPN scoring-play list ends 7–60 while both final-score feeds say 7–61, so its late-score class is withheld as NOT_EVALUATED_NO_PBP with a partial-sequence flag. "
        f"Observed late-score class counts: `{json.dumps(late_counts, sort_keys=True)}`.\n\n"
        "### Scoring-sequence-backed backdoor failures\n\n"
        "Scores are away-home. The late score is the score immediately after the identified scoring play.\n\n"
        "| Game | Frozen pick | Before late play | Late score | Final score | Final ATS |\n"
        "| --- | --- | --- | --- | --- | --- |\n"
        f"{backdoor_failure_table}\n\n"
        "## Large edges, calibration, and model misses\n\n"
        f"All 23 absolute raw ATS edges ≥7 points: **{_record_text(large_summary['edge_ge_7'])}**, "
        f"versus **{_record_text(large_summary['edge_lt_7'])}** below 7. "
        f"Mean large edge {large_summary['mean_raw_edge_ge_7']:.2f} points; mean ATS grading margin "
        f"{large_summary['mean_grading_margin_ge_7']:.2f}. "
        f"Prior FCS exposure is flagged in {large_summary['fcs_flagged_ge_7']}/23, "
        f"prior 35+ point blowout in {large_summary['prior_blowout_flagged_ge_7']}/23, and QB uncertainty in "
        f"{large_summary['qb_uncertain_ge_7']}/23. These are pregame exposure flags, not proven causes. "
        f"For context, the recorded Week 1 local draft was {_record_text(large_summary['prior_week1_recorded_draft_edge_ge_7'])} "
        f"at edge ≥7 and {_record_text(large_summary['prior_week1_recorded_draft_edge_lt_7'])} below 7; "
        "complete comparable edge cuts for Weeks 2–3 are unavailable in the frozen prior audit. "
        f"Raw-edge/ATS-win Pearson r={correlations['raw_selected_edge_vs_ats_win']['r']} (n={correlations['raw_selected_edge_vs_ats_win']['n']}); "
        f"shadow-uncertainty/win r={correlations['shadow_uncertainty_vs_ats_win']['r']}; "
        f"October 1 locked market advantage/win r={correlations['oct1_locked_advantage_vs_ats_win']['r']}. "
        "All ATS Confidence values are 1, so confidence monotonicity cannot be assessed. "
        f"Measured home-margin error variance is {correlations['model_home_margin_error_sample_variance']:.2f} points squared. "
        "No large-edge threshold is promoted from this one week.\n\n"
        "### Largest measured model-margin misses (14+ points)\n\n"
        "`MODEL_PROJECTION_FAILURE` here denotes a measured 14+ point home-margin error, not a proven causal failure. "
        "The FCS, opponent-strength, QB, weather, turnovers and game-script hypotheses remain unassigned without game-specific causal evidence.\n\n"
        "| Game | ATS result | Actual minus projected home margin | Code |\n| --- | --- | ---: | --- |\n"
        f"{material_table}\n\n"
        "## Cumulative 2026 and totals gate\n\n"
        f"Recorded local-draft Weeks 1–2 ATS: {_record_text(cumulative['week_1_2_recorded_local_drafts'])}. "
        f"Week 3 provisional ATS: {_record_text(cumulative['week_3_provisional'])}. "
        "Week 4 has no replay-safe stored picks and is excluded. "
        f"With Week 5, all recorded/provisional ATS: {_record_text(cumulative['ats_all_recorded_including_provisional_week3'])}; "
        f"Top 5: {_record_text(cumulative['governed_top_five_all_recorded_including_provisional_week3'])}. "
        f"Recorded shadow totals Weeks 2, 3 and 5: {_record_text(cumulative['shadow_totals_all_recorded'])}. "
        "The historical totals OOS ledger (2019–2025) remains separate: 1,897-1,784-38, -1.62% ROI, "
        "with archival opening-quote time custody unverified. Week 5 does not satisfy a predefined promotion gate; totals stay SHADOW_ONLY. "
        "Prior-week aggregate spread bins differ from the requested Week 5 bins and do not expose a complete raw-edge segmentation; incompatible bins are not silently pooled.\n\n"
        "Combined comparable cuts: favorite "
        f"{_record_text(cumulative['combined_comparable_cuts']['favorite_status']['favorite'])}, "
        "underdog "
        f"{_record_text(cumulative['combined_comparable_cuts']['favorite_status']['underdog'])}, "
        "home "
        f"{_record_text(cumulative['combined_comparable_cuts']['location']['home'])}, "
        "away "
        f"{_record_text(cumulative['combined_comparable_cuts']['location']['away'])}, "
        "road favorite "
        f"{_record_text(cumulative['combined_comparable_cuts']['road_favorite'])}, "
        "and remaining card "
        f"{_record_text(cumulative['combined_comparable_cuts']['remaining_card'])}. "
        "See `week5_diagnostics.json` and `week5_cumulative_2026_diagnostics.json` for every computable segment, units, win rate and ROI.\n\n"
        "## Audit limitations and recovery\n\n"
        "No timestamp-qualified closing market feed, verified post-review QB/injury ledger or observed game-day weather ledger was available in the captured evidence. "
        "Those missing observations limit decision-process, CLV and causal attribution conclusions. "
        "The pregame card, policies, locked lines, source DB, and master prompt were not edited. "
        "Rollback: close the audit PR or revert its commit; the frozen Week 5 files and source DB remain intact.\n"
    )
    (OUTPUT / "week5_postgame_report.md").write_text(summary, encoding="utf-8")

    lessons = (
        "# WEEK 5 LESSONS LEARNED\n\n"
        "## SUPPORTED\n\n"
        f"- The frozen card was fully gradeable: 56/56 final games, ATS {_record_text(a['all'])}, "
        f"shadow totals {_record_text(t['all'])}. The result and grading rows have source IDs and hashes.\n"
        "- Governed Confidence was 1 for all 56; it conveyed no within-week ordering. "
        f"The measured model home-margin error variance was {correlations['model_home_margin_error_sample_variance']:.2f} points squared.\n"
        "- Qualified CLV could not be calculated for any selection because the provider-labeled closes lacked quote timestamps. "
        "The Oct 1 market capture remains a pregame diagnostic, not a close.\n\n"
        "## WEAK EVIDENCE\n\n"
        f"- Raw edge ≥7 was {_record_text(large_summary['edge_ge_7'])} versus "
        f"{_record_text(large_summary['edge_lt_7'])} below 7 in Week 5; recorded Week 1 large edges were "
        f"{_record_text(large_summary['prior_week1_recorded_draft_edge_ge_7'])}. "
        "Weeks 2–3 lack complete comparable edge cuts, so no threshold is warranted.\n"
        f"- The human decision five were {_record_text(a['decision_shortlist'])} versus "
        f"the deterministic five {_record_text(a['governed_deterministic_top_five'])}; "
        "overlap, unverified context and missing CLV prevent a causal claim that review improved decisions.\n"
        f"- Prior FCS exposure affected {large_summary['fcs_flagged_ge_7']}/23 large edges and "
        f"prior blowouts {large_summary['prior_blowout_flagged_ge_7']}/23; exposure is not proof that either caused misses.\n\n"
        "## NOT SUPPORTED\n\n"
        "- A v2.9 FCS exclusion, blowout shrinkage, opponent-strength coefficient, QB penalty, "
        "market-disagreement penalty, road-favorite penalty, raw-edge cap or totals promotion is not justified by this audit alone. "
        "Each would require a predefined walk-forward comparison against the frozen baseline.\n"
        "- A backdoor explanation from final score alone is not accepted; only scoring-play-backed classifications appear in the late-score ledger.\n"
    )
    (OUTPUT / "week5_lessons_learned.md").write_text(lessons, encoding="utf-8")

    recommendations = (
        "# MASTER PROMPT v2.9 RECOMMENDATIONS — WEEK 5 POSTGAME\n\n"
        "**Approve: none.** Master Prompt v2.8 remains active. This task makes no policy or model change. "
        "The authoritative v2.8 prompt text is not present in this repository, so its exact current numeric rules cannot be verified. "
        "No candidate is represented as an implementable v2.9 replacement without that baseline and out-of-sample evaluation.\n\n"
        "| Candidate | Current v2.8 rule | Proposed v2.9 rule and numeric threshold | Week 5 and cumulative evidence | Expected benefit | Overfitting risk | Decision |\n"
        "| --- | --- | --- | --- | --- | --- | --- |\n"
        f"| Promote shadow totals | Unverified prompt text; current research status SHADOW_ONLY | No change; retain SHADOW_ONLY | Historical OOS 1,897-1,784-38, -1.62% ROI; Week 5 {_record_text(t['all'])} | None established | High if one week overrides OOS | REJECT |\n"
        f"| Hard cutoff on ATS raw edge ≥7 | Unverified prompt text; current card does not rank by raw edge | No new threshold | 23 Week 5 games {_record_text(large_summary['edge_ge_7'])}; Week 1 local-draft large edges {_record_text(large_summary['prior_week1_recorded_draft_edge_ge_7'])}; Weeks 2–3 edge cuts unavailable | None established | High from post hoc threshold | REJECT |\n"
        "| FCS, blowout, QB, opponent strength, market, road-favorite or weather adjustment | Unverified prompt text; no verified v2.8 numeric rule | No numeric change proposed | Week 5 pregame exposure flags and outcomes cannot establish causal coefficient; no walk-forward comparison | Unknown | High | NEED_MORE_DATA |\n\n"
        "A future proposal must first locate and freeze the exact v2.8 text, define a numeric candidate and acceptance metric before fitting, "
        "then run point-in-time walk-forward validation against the current baseline. "
        "The owner must approve any resulting new version.\n"
    )
    (OUTPUT / "week5_v29_recommendations.md").write_text(recommendations, encoding="utf-8")

    output_hashes = {
        path.relative_to(ROOT).as_posix(): _sha(path)
        for path in OUTPUT.rglob("*") if path.is_file() and path.name != "week5_postgame_manifest.json"
    }
    manifest = {
        "status": "POSTGAME_AUDIT_REPLAYABLE_LOCAL_DRAFT",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "contest": model["contest_key"], "season": 2026, "week": 5,
        "pregame_code_sha": model["code_commit_sha"],
        "pregame_model_versions": {"ats": model["ats"]["version"], "totals": model["totals"]["version"]},
        "pregame_data_hashes": {"ats": model["ats"]["data_snapshot_sha256"],
                                "totals": model["totals"]["data_snapshot_sha256"]},
        "locked_line_snapshot_sha256": model["locked_line_snapshot_sha256"],
        "locked_source_csv_sha256": custody["locked_source_csv_sha256"],
        "source_database_sha256": custody["source_database_sha256"],
        "pregame_v4_files_verified": custody["pregame_v4_files_verified"],
        "pregame_review_file_hashes": custody["review_file_hashes"],
        "result_providers": [capture["provider"], "NCAA_DATA_VIA_HENRYGD_PROXY"],
        "result_capture_manifest_sha256": _sha(EVIDENCE / "capture-manifest.json"),
        "result_retrieval_status": "56_FINAL_ESPN_SCOREBOARD_SUMMARY_AND_NCAA_DERIVED_MATCHED",
        "locked_games": 56, "ats_rows": len(ats), "shadow_totals_rows": len(totals),
        "decision_rows": len(decision), "duplicate_game_rows": 0,
        "qualified_clv_rows": 0, "clv_unavailable_reason": "NO_TIMESTAMPED_CLOSE",
        "audit_script_sha256": _sha(Path(__file__)),
        "grading_module_sha256": _sha(ROOT / "scripts/week5_postgame_core.py"),
        "output_sha256": output_hashes,
    }
    _write_json("week5_postgame_manifest.json", manifest)
    return manifest


if __name__ == "__main__":
    completed = build()
    print(f"Week 5 audit replayed: {completed['ats_rows']} ATS, {completed['shadow_totals_rows']} shadow totals")
