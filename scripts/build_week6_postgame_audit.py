"""Replay Week 6 postgame grading from sealed cards and captured provider evidence."""

from __future__ import annotations

import csv
import difflib
import gzip
import hashlib
import json
import math
import re
import statistics
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path

from scripts.week5_postgame_core import (
    classify_late_score, clv_ats, clv_total, grade_ats, grade_total,
    hook_key_classification, record,
)

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "outputs/2026-week6-execution-20261006T2133Z"
OUTPUT = ROOT / "outputs/2026-week6-postgame-audit"
EVIDENCE = OUTPUT / "provider-evidence"
PRIOR = ROOT / "outputs/2026-week5-postgame-audit"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_csv(name: str, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"empty audit: {name}")
    with (OUTPUT / name).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_json(name: str, value: object) -> None:
    (OUTPUT / name).write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def load_raw(entry: dict) -> dict:
    path = ROOT / entry["stored_gzip_path"]
    raw = gzip.decompress(path.read_bytes())
    if hashlib.sha256(raw).hexdigest() != entry["raw_sha256"]:
        raise ValueError(f"provider evidence hash mismatch: {path}")
    return json.loads(raw)


def frozen_gate() -> dict:
    custody = read_json(FROZEN / "week6_artifact_checksums.json")
    # The signed custody file uses relative paths, not a mutable directory scan.
    files = custody.get("files", custody.get("artifacts"))
    if not isinstance(files, dict):
        raise ValueError("unknown frozen-artifact custody format")
    for name, digest in files.items():
        path = FROZEN / name
        if sha(path) != digest:
            raise ValueError(f"frozen Week 6 artifact changed: {path}")
    manifests = [read_json(FROZEN / name) for name in (
        "week6_locked_line_snapshot.json", "week6_card_manifest.json",
        "week6_model_manifest.json", "week6_ingestion_manifest.json",
    )]
    locked = manifests[0]["locked_line_snapshot_sha256"]
    if (manifests[1]["ats_card"]["locked_line_snapshot_sha256"] != locked
            or manifests[1]["totals_card"]["locked_line_snapshot_sha256"] != locked
            or manifests[2]["locked_line_snapshot_sha256"] != locked
            or manifests[3]["lock_snapshot_sha256"] != locked):
        raise ValueError("locked-line hash disagrees across frozen manifests")
    db_hash = sha(ROOT / "data/cfb.db")
    if db_hash != manifests[2]["source_database_sha256"]:
        raise ValueError("source database changed from frozen Week 6 execution")
    source_csv = ROOT / "production-weeks/2026-week6-splashsports.csv"
    source_csv_hash = hashlib.sha256(source_csv.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    if source_csv_hash != manifests[2]["locked_source_csv_sha256"] or source_csv_hash != manifests[0]["source_csv_sha256"]:
        raise ValueError("locked source CSV changed from frozen Week 6 execution")
    return {"frozen_files_verified": len(files), "frozen_artifact_custody_sha256": sha(FROZEN / "week6_artifact_checksums.json"),
            "locked_line_snapshot_sha256": locked, "source_database_sha256": db_hash,
            "locked_source_csv_sha256": source_csv_hash,
            "model_manifest": manifests[2], "card_manifest": manifests[1]}


def name_key(value: str) -> str:
    value = {"USC": "Southern California", "Army": "Army West Point",
             "Northern Illinois": "NIU"}.get(value, value)
    ascii_name = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    return re.sub("[^a-z0-9]", "", ascii_name.replace("state", "st"))


def reconcile(card: list[dict], capture: dict) -> tuple[list[dict], dict[str, dict]]:
    scoreboard = load_raw(capture["scoreboard"])
    ncaa = load_raw(capture["ncaa_derived_scoreboard"])
    events = {str(event["id"]): event for event in scoreboard["events"]}
    summary_entries = {entry["endpoint"].split("event=")[-1]: entry for entry in capture["summaries"]}
    if len(card) != 58 or len({row["game_id"] for row in card}) != 58:
        raise ValueError("frozen ATS card must contain 58 distinct games")
    if set(row["game_id"] for row in card) - (events.keys() & summary_entries.keys()):
        raise ValueError("missing Week 6 final or summary")
    results, summaries, used_ncaa = [], {}, set()
    for row in card:
        game_id = row["game_id"]
        event = events[game_id]
        summary = load_raw(summary_entries[game_id])
        summaries[game_id] = summary
        competition = event["competitions"][0]
        summary_comp = summary["header"]["competitions"][0]
        if str(summary_comp["id"]) != game_id:
            raise ValueError(f"summary identity conflict {game_id}")
        teams = {team["homeAway"]: team for team in competition["competitors"]}
        summary_teams = {team["homeAway"]: team for team in summary_comp["competitors"]}
        away, home = int(teams["away"]["score"]), int(teams["home"]["score"])
        if (teams["away"]["team"].get("location"), teams["home"]["team"].get("location")) != (row["away"], row["home"]):
            raise ValueError(f"matchup orientation conflict {game_id}")
        if (away, home) != (int(summary_teams["away"]["score"]), int(summary_teams["home"]["score"])):
            raise ValueError(f"ESPN scoreboard/summary conflict {game_id}")
        if not event["status"]["type"].get("completed") or not summary_comp["status"]["type"].get("completed"):
            raise ValueError(f"game not final {game_id}")
        choices = []
        for wrapper in ncaa["games"]:
            game = wrapper["game"]
            names = (game["away"]["names"]["short"], game["home"]["names"]["short"])
            score = sum(difflib.SequenceMatcher(None, name_key(a), name_key(b)).ratio()
                        for a, b in zip((row["away"], row["home"]), names))
            choices.append((score, game))
        choices.sort(key=lambda item: item[0], reverse=True)
        best_score, best = choices[0]
        ncaa_id = str(best["gameID"])
        if best_score < 1.15 or best_score - choices[1][0] < 0.3 or ncaa_id in used_ncaa:
            raise ValueError(f"ambiguous NCAA reconciliation: {game_id}, {best_score}")
        if best["gameState"] != "final" or (int(best["away"]["score"]), int(best["home"]["score"])) != (away, home):
            raise ValueError(f"ESPN/NCAA result conflict {game_id}")
        used_ncaa.add(ncaa_id)
        results.append({"game_id": game_id, "away": row["away"], "home": row["home"],
                        "away_score": away, "home_score": home, "status": "FINAL",
                        "kickoff_utc": competition["date"], "ncaa_game_id": ncaa_id,
                        "scoreboard_sha256": capture["scoreboard"]["raw_sha256"],
                        "summary_sha256": summary_entries[game_id]["raw_sha256"],
                        "ncaa_scoreboard_sha256": capture["ncaa_derived_scoreboard"]["raw_sha256"]})
    return results, summaries


def market_close(summary: dict) -> tuple[str, str, str]:
    for quote in summary.get("pickcenter", []):
        if quote.get("provider", {}).get("name") == "DraftKings":
            home = quote.get("pointSpread", {}).get("home", {}).get("close", {}).get("line", "")
            total = quote.get("total", {}).get("over", {}).get("close", {}).get("line", "")
            return "DraftKings", str(home), str(total).removeprefix("o")
    return "", "", ""


def quintile_map(rows: list[dict], key: str) -> dict[str, int]:
    ordered = sorted(rows, key=lambda row: (float(row[key]), row["game_id"]))
    return {row["game_id"]: min(5, (index * 5 // len(ordered)) + 1) for index, row in enumerate(ordered)}


def probability_bucket(probability: float) -> str:
    percent = probability * 100
    for top, label in ((52, "50-52"), (54, "52-54"), (56, "54-56"), (58, "56-58"), (60, "58-60")):
        if percent < top:
            return label
    return "60+"


def wilson(wins: int, losses: int) -> list[float] | None:
    n = wins + losses
    if not n:
        return None
    z, p = 1.96, wins / n
    center = (p + z*z/(2*n))/(1+z*z/n)
    half = z * math.sqrt(p*(1-p)/n+z*z/(4*n*n))/(1+z*z/n)
    return [round(center-half, 4), round(center+half, 4)]


def poisson_binomial_lower_tail(probabilities: list[float], observed_wins: int) -> float:
    """Conditional tail if stated independent win probabilities were honest."""
    masses = [1.0]
    for probability in probabilities:
        following = [0.0] * (len(masses) + 1)
        for wins, mass in enumerate(masses):
            following[wins] += mass * (1 - probability)
            following[wins + 1] += mass * probability
        masses = following
    return sum(masses[:observed_wins + 1])


def summarize(rows: list[dict], result_key: str) -> dict:
    item = record(row[result_key] for row in rows)
    item["wilson_95_ex_push"] = wilson(item["win"], item["loss"])
    return item


def segmented(rows: list[dict], result_key: str, key: str) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[str(row[key])].append(row)
    return {label: summarize(group, result_key) for label, group in sorted(groups.items())}


def calibrated(rows: list[dict], result_key: str) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[probability_bucket(float(row["selected_probability"]))].append(row)
    out = {}
    for label in ("50-52", "52-54", "54-56", "56-58", "58-60", "60+"):
        group = groups[label]
        expected = sum(float(row["selected_probability"]) for row in group)
        actual = sum(row[result_key] == "WIN" for row in group)
        n = len(group)
        out[label] = {"n": n, "expected_wins": round(expected, 4), "actual_wins": actual,
                      "expected_win_pct": round(expected/n, 4) if n else None,
                      "actual_win_pct": round(actual/n, 4) if n else None,
                      "calibration_error_pct_points": round(100*(actual-expected)/n, 2) if n else None}
    return out


def ranking_group(rank: int, size: int) -> str:
    if rank <= 5:
        return "Top 5"
    if rank <= 10:
        return "6-10"
    if rank <= 20:
        return "11-20"
    if rank <= 40:
        return "21-40"
    return f"41-{size}"


def ranking_table(rows: list[dict], result_key: str, rank_key: str) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[ranking_group(int(row[rank_key]), len(rows))].append(row)
    out = {}
    for name, group in groups.items():
        out[name] = {**summarize(group, result_key),
                     "mean_selected_probability": round(statistics.mean(float(row["selected_probability"]) for row in group), 4),
                     "qualified_mean_clv": None}
    return out


def grade() -> dict:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    custody = frozen_gate()
    capture = read_json(EVIDENCE / "capture-manifest.json")
    card = read_csv(FROZEN / "week6_ats_full_card.csv")
    totals = read_csv(FROZEN / "week6_totals_full_card.csv")
    pool = read_csv(FROZEN / "week6_combined_candidate_pool.csv")
    official = read_csv(FROZEN / "week6_official_ats_top5.csv")
    mixed = read_csv(FROZEN / "week6_mixed_market_shadow_top5.csv")
    decision = read_csv(FROZEN / "week6_decision_shortlist.csv")
    if not (len(card) == len(totals) == 58 and len(pool) == 116 and len(official) == len(mixed) == len(decision) == 5):
        raise ValueError("frozen card coverage mismatch")
    if {row["game_id"] for row in card} != {row["game_id"] for row in totals}:
        raise ValueError("ATS/totals game sets differ")
    results, summaries = reconcile(card, capture)
    result_by_id = {row["game_id"]: row for row in results}
    total_by_id = {row["game_id"]: row for row in totals}
    pool_by_key = {(row["market_type"], row["game_id"]): row for row in pool}
    ats_quintile = quintile_map([pool_by_key["ATS", row["game_id"]] for row in card], "candidate_score")
    total_quintile = quintile_map([pool_by_key["TOTAL", row["game_id"]] for row in totals], "candidate_score")
    market_ranks = {}
    for market in ("ATS", "TOTAL"):
        ranked = sorted((row for row in pool if row["market_type"] == market),
                        key=lambda row: (-float(row["candidate_score"]), int(row["pool_rank"])))
        market_ranks.update({(market, row["game_id"]): rank for rank, row in enumerate(ranked, 1)})
    ats_rows, total_rows, clv_rows = [], [], []
    for ats in card:
        game_id = ats["game_id"]
        total, result, summary = total_by_id[game_id], result_by_id[game_id], summaries[game_id]
        home_margin = result["home_score"] - result["away_score"]
        actual_total = result["home_score"] + result["away_score"]
        ats_result, ats_margin = grade_ats(ats["selected_side"], ats["locked_home_spread"], home_margin)
        total_result, total_margin = grade_total(total["pick"], total["locked_total"], actual_total)
        provider, close_spread, close_total = market_close(summary)
        ats_proxy = float(clv_ats(ats["selected_side"], ats["locked_home_spread"], close_spread)) if close_spread else None
        total_proxy = float(clv_total(total["pick"], total["locked_total"], close_total)) if close_total else None
        picked_spread = float(ats["pick_spread"])
        plays = summary.get("scoringPlays", [])
        late = classify_late_score(plays, ats["selected_side"], ats["locked_home_spread"], result["away_score"], result["home_score"])
        boundary = hook_key_classification(picked_spread, home_margin if ats["selected_side"] == "home" else -home_margin, ats_margin)
        ats_pool, total_pool = pool_by_key["ATS", game_id], pool_by_key["TOTAL", game_id]
        ats_bucket_value = abs(picked_spread)
        ats_bucket = "0-3" if ats_bucket_value <= 3 else "3.5-7" if ats_bucket_value <= 7 else "7.5-14" if ats_bucket_value <= 14 else "14.5+"
        total_line = float(total["locked_total"])
        total_bucket = "<45" if total_line < 45 else "45-49.5" if total_line < 50 else "50-54.5" if total_line < 55 else "55-59.5" if total_line < 60 else "60+"
        common = {"game_id": game_id, "game": f"{ats['away']} @ {ats['home']}", "away": ats["away"], "home": ats["home"],
                  "away_score": result["away_score"], "home_score": result["home_score"]}
        ats_rows.append({**common, "selection": ats["pick"], "selected_side": ats["selected_side"],
                         "locked_home_spread": ats["locked_home_spread"], "selected_spread": picked_spread,
                         "provider_labeled_close_home_spread": close_spread, "close_provider": provider,
                         "close_timestamp_qualified": False, "qualified_clv_points": "",
                         "indicative_unqualified_clv_points": ats_proxy if ats_proxy is not None else "",
                         "clv_direction_proxy": "POSITIVE" if ats_proxy is not None and ats_proxy > 0 else "NEGATIVE" if ats_proxy is not None and ats_proxy < 0 else "ZERO" if ats_proxy == 0 else "UNAVAILABLE",
                         "ats_result": ats_result, "ats_margin_vs_locked": float(ats_margin),
                         "projected_home_margin": ats["projected_home_margin"], "home_projection_error": home_margin-float(ats["projected_home_margin"]),
                         "model_selected_edge_points": ats["selected_side_ats_edge"], "selected_probability": ats_pool["selected_probability"],
                         "pregame_current_home_spread": ats["current_market_home_spread"],
                         "pregame_lock_advantage_points": ats["selected_side_lock_advantage"],
                         "probability_status": ats_pool["score_status"], "candidate_score": ats_pool["candidate_score"],
                         "confidence": ats["confidence"], "official_rank": ats["rank"], "shadow_pool_rank": ats_pool["pool_rank"],
                         "market_score_rank": market_ranks["ATS", game_id],
                         "governed_top5": ats["top_five"], "score_quintile": ats_quintile[game_id],
                         "favorite_dog": "FAVORITE" if picked_spread < 0 else "UNDERDOG" if picked_spread > 0 else "PICKEM",
                         "home_away": ats["selected_side"].upper(), "spread_bucket": ats_bucket,
                         "hook_classification": boundary["hook_classification"], "key_number_classification": boundary["key_number_classification"],
                         "late_score_classification": late["classification"], "late_play": late["decisive_score"],
                         "late_score_before": late["score_before_late_play"], "late_score_after": late["score_after_late_play"],
                         "sample_quality_warning": ats["sample_quality_warning"], "qb_evidence": ats["qb_evidence"],
                         "summary_sha256": result["summary_sha256"]})
        total_rows.append({**common, "selection": total["pick"].upper(), "locked_total": total["locked_total"],
                           "provider_labeled_close_total": close_total, "close_provider": provider,
                           "close_timestamp_qualified": False, "qualified_clv_points": "",
                           "indicative_unqualified_clv_points": total_proxy if total_proxy is not None else "",
                           "clv_direction_proxy": "POSITIVE" if total_proxy is not None and total_proxy > 0 else "NEGATIVE" if total_proxy is not None and total_proxy < 0 else "ZERO" if total_proxy == 0 else "UNAVAILABLE",
                           "actual_total": actual_total, "total_result": total_result, "total_margin_vs_locked": float(total_margin),
                           "projected_total": total["projected_total"], "total_projection_error": actual_total-float(total["projected_total"]),
                           "raw_point_edge": total["raw_point_edge"], "selected_probability": total["selected_probability"],
                           "pregame_current_total": total["current_market_total"],
                           "pregame_lock_advantage_points": total["selected_direction_lock_advantage"],
                           "probability_status": total["probability_status"], "candidate_score": total_pool["candidate_score"],
                           "confidence": total["confidence"], "shadow_pool_rank": total_pool["pool_rank"],
                           "market_score_rank": market_ranks["TOTAL", game_id],
                           "shadow_top5": total_pool["is_combined_top5"], "score_quintile": total_quintile[game_id],
                           "total_bucket": total_bucket, "sample_quality_warning": total["sample_quality_warning"],
                           "summary_sha256": result["summary_sha256"]})
        for market, proxy, quote in (("ATS", ats_proxy, close_spread), ("TOTAL", total_proxy, close_total)):
            clv_rows.append({"game_id": game_id, "market": market, "provider": provider, "provider_labeled_close": quote,
                             "provider_quote_timestamp": "", "postgame_retrieval_timestamp": next(item["retrieved_at_utc"] for item in capture["summaries"] if item["endpoint"].endswith(f"event={game_id}")),
                             "qualified_clv": "", "indicative_unqualified_clv": proxy if proxy is not None else "",
                             "status": "UNAVAILABLE_NO_TIMESTAMPED_CLOSE" if proxy is not None else "UNAVAILABLE_NO_QUOTE"})
    write_csv("week6_final_results.csv", results)
    write_csv("week6_ats_audit.csv", ats_rows)
    write_csv("week6_totals_audit.csv", total_rows)
    write_csv("week6_clv_audit.csv", clv_rows)
    return finish(custody, capture, ats_rows, total_rows, pool, official, mixed, decision)


def historical(ats_rows: list[dict], total_rows: list[dict]) -> dict:
    prior_summary = read_json(PRIOR / "week5_cumulative_2026_diagnostics.json")
    prior_ats = read_csv(PRIOR / "week5_ats_audit.csv")
    prior_totals = read_csv(PRIOR / "week5_totals_audit.csv")
    if len(prior_ats) != 56 or len(prior_totals) != 56:
        raise ValueError("prior Week 5 card incomplete")
    week5_ats = summarize(prior_ats, "ats_result")
    week5_totals = summarize(prior_totals, "total_result")
    by_week = prior_summary["ats_by_week"]
    earlier = {week: {**item, "wilson_95_ex_push": wilson(item["win"], item["loss"])}
               for week, item in by_week.items()}
    historical_ats = {"weeks_1_2_3_5": prior_summary["ats_all_recorded_including_provisional_week3"],
                      "by_week": earlier,
                      "week5_only_full_card": week5_ats,
                      "week6": summarize(ats_rows, "ats_result")}
    prior_by_favorite = segmented(prior_ats, "ats_result", "favorite_status")
    prior_by_location = segmented(prior_ats, "ats_result", "location")
    prior_road_fav = [row for row in prior_ats if row["favorite_status"] == "favorite" and row["location"] == "away"]
    high_totals = [row for row in prior_totals if float(row["raw_selected_probability"]) >= 0.6]
    high_expected = sum(float(row["raw_selected_probability"]) for row in high_totals)
    week6_high = [row for row in total_rows if float(row["selected_probability"]) >= 0.6]
    high_probabilities = ([float(row["raw_selected_probability"]) for row in high_totals]
                          + [float(row["selected_probability"]) for row in week6_high])
    high_observed = sum(row["total_result"] == "WIN" for row in high_totals + week6_high)
    prior_top5 = prior_summary["governed_top_five_all_recorded_including_provisional_week3"]
    data = {"ats": historical_ats,
            "totals_week5_only": week5_totals,
            "week5_favorite_status": prior_by_favorite,
            "week5_location": prior_by_location,
            "week5_road_favorites": summarize(prior_road_fav, "ats_result"),
            "week5_totals_probability_ge_60pct": summarize(high_totals, "total_result"),
            "week5_totals_probability_ge_60pct_expected_wins": round(high_expected, 4),
            "weeks5_6_totals_probability_ge_60pct": {
                "n": len(high_probabilities), "expected_wins": round(sum(high_probabilities), 4),
                "actual_wins": high_observed,
                "lower_tail_if_independent_and_honest": round(poisson_binomial_lower_tail(high_probabilities, high_observed), 6),
                "caveat": "Illustrative conditional tail assumes independent game outcomes and truthful, exchangeable shadow probabilities; correlated team/game risk and score model misspecification can invalidate the p-value."},
            "governed_top5_weeks_1_2_3_5": {**prior_top5, "wilson_95_ex_push": wilson(prior_top5["win"], prior_top5["loss"])},
            "governed_top5_by_prior_week": prior_summary["governed_top_five_by_week"],
            "historical_probability_limitation": "Weeks 1-3 lack a complete frozen cross-market probability and totals audit; Week 5 totals probabilities are uncalibrated shadow scores. Do not pool them as validated betting probabilities.",
            "week3_status": "PROVISIONAL as marked by prior cumulative diagnostics",
            "week4_status": "No complete frozen pregame card in repository"}
    return data


def finish(custody: dict, capture: dict, ats_rows: list[dict], total_rows: list[dict],
           pool: list[dict], official: list[dict], mixed: list[dict], decision: list[dict]) -> dict:
    ats_by_id = {row["game_id"]: row for row in ats_rows}
    total_by_id = {row["game_id"]: row for row in total_rows}
    graded_pool = []
    for row in pool:
        audit = ats_by_id[row["game_id"]] if row["market_type"] == "ATS" else total_by_id[row["game_id"]]
        result = audit["ats_result"] if row["market_type"] == "ATS" else audit["total_result"]
        graded_pool.append({"pool_rank": int(row["pool_rank"]), "game_id": row["game_id"],
                            "game": f"{row['away']} @ {row['home']}", "market": row["market_type"],
                            "selection": row["selection"], "locked_line": row["locked_line"],
                            "selected_probability": row["selected_probability"], "candidate_score": row["candidate_score"],
                            "confidence": row["confidence"], "result": result,
                            "combined_top5": row["is_combined_top5"],
                            "probability_status": audit["probability_status"]})
    graded_pool.sort(key=lambda row: row["pool_rank"])
    write_csv("week6_combined_board_audit.csv", graded_pool)
    top5_rows = []
    for index, frozen in enumerate(official, 1):
        row = ats_by_id[frozen["game_id"]]
        top5_rows.append({"top5_order": index, **row, "ranking_basis": frozen["ranking_basis"]})
    write_csv("week6_governed_ats_top5_audit.csv", top5_rows)
    mixed_rows = []
    for row in mixed:
        audited = ats_by_id[row["game_id"]] if row["market_type"] == "ATS" else total_by_id[row["game_id"]]
        mixed_rows.append({"shadow_rank": row["combined_top5_rank"], "market": row["market_type"],
                           "game": f"{row['away']} @ {row['home']}", "selection": row["selection"],
                           "locked_line": row["locked_line"], "candidate_score": row["candidate_score"],
                           "result": audited["ats_result"] if row["market_type"] == "ATS" else audited["total_result"]})
    write_csv("week6_mixed_shadow_top5_audit.csv", mixed_rows)
    decision_rows = []
    for row in decision:
        audited = ats_by_id[row["game_id"]] if row["market_type"] == "ATS" else total_by_id[row["game_id"]]
        decision_rows.append({"review_rank": row["decision_rank"], "market": row["market_type"],
                              "game": f"{row['away']} @ {row['home']}", "selection": row["selection"],
                              "locked_line": row["locked_line"], "result": audited["ats_result"] if row["market_type"] == "ATS" else audited["total_result"]})
    write_csv("week6_decision_review_audit.csv", decision_rows)
    # A true closing-market timestamp is absent from the ESPN postgame payload.
    # Keep the provider's labelled close visible, but do not promote it to qualified CLV.
    ats_proxy = [float(row["indicative_unqualified_clv_points"]) for row in ats_rows if row["indicative_unqualified_clv_points"] != ""]
    totals_proxy = [float(row["indicative_unqualified_clv_points"]) for row in total_rows if row["indicative_unqualified_clv_points"] != ""]
    def proxy_summary(rows: list[dict], values: list[float], result_key: str) -> dict:
        qualified = [row for row in rows if row["qualified_clv_points"] != ""]
        by_confidence = {}
        for confidence in sorted({str(row["confidence"]) for row in rows}):
            group = [float(row["indicative_unqualified_clv_points"]) for row in rows
                     if str(row["confidence"]) == confidence and row["indicative_unqualified_clv_points"] != ""]
            by_confidence[confidence] = {"n": len(group), "mean": round(statistics.mean(group), 4) if group else None}
        top5_group = [float(row["indicative_unqualified_clv_points"]) for row in rows
                      if str(row.get("governed_top5", row.get("shadow_top5", "False"))) == "True"
                      and row["indicative_unqualified_clv_points"] != ""]
        return {"qualified_n": len(qualified), "qualified_mean": None, "qualified_median": None,
                "qualified_positive_pct": None, "qualified_top5_mean": None,
                "qualified_by_confidence": None, "qualified_win_when_positive": None,
                "qualified_win_when_negative": None,
                "provider_labeled_unqualified_n": len(values),
                "provider_labeled_unqualified_mean": round(statistics.mean(values), 4) if values else None,
                "provider_labeled_unqualified_median": statistics.median(values) if values else None,
                "provider_labeled_unqualified_positive_pct": round(sum(x > 0 for x in values)/len(values), 4) if values else None,
                "provider_labeled_unqualified_by_confidence": by_confidence,
                "provider_labeled_unqualified_top5_mean": round(statistics.mean(top5_group), 4) if top5_group else None,
                "provider_labeled_unqualified_win_when_positive": summarize([r for r in rows if r["clv_direction_proxy"] == "POSITIVE"], result_key),
                "provider_labeled_unqualified_win_when_negative": summarize([r for r in rows if r["clv_direction_proxy"] == "NEGATIVE"], result_key)}
    clv = {"status": "NO_TIMESTAMP_QUALIFIED_CLOSE; PROCESS_VERDICT_WITHHELD",
           "ats": proxy_summary(ats_rows, ats_proxy, "ats_result"),
           "totals": proxy_summary(total_rows, totals_proxy, "total_result"),
           "reason": "ESPN postgame summary labels DraftKings close but supplies no quote timestamp; postgame retrieval time is not quote time. These figures are indicative only and cannot prove CLV or market process quality."}
    historical_data = historical(ats_rows, total_rows)
    ats_derived = []
    for row in ats_rows:
        item = dict(row)
        item["road_home_category"] = ("ROAD" if row["home_away"] == "AWAY" else "HOME") + "_" + row["favorite_dog"]
        ats_derived.append(item)
    metrics = {
        "ats": {"overall": summarize(ats_rows, "ats_result"),
                "governed_top5": summarize(top5_rows, "ats_result"),
                "by_favorite_dog": segmented(ats_rows, "ats_result", "favorite_dog"),
                "by_home_away": segmented(ats_rows, "ats_result", "home_away"),
                "by_road_home_category": segmented(ats_derived, "ats_result", "road_home_category"),
                "by_spread_bucket": segmented(ats_rows, "ats_result", "spread_bucket"),
                "by_confidence": segmented(ats_rows, "ats_result", "confidence"),
                "by_score_quintile": segmented(ats_rows, "ats_result", "score_quintile"),
                "calibration": calibrated(ats_rows, "ats_result"),
                "shadow_score_ranking": ranking_table(ats_rows, "ats_result", "market_score_rank"),
                "official_top5_ranking_basis": "FIRST_FIVE_LOCKED_GAMES;DETERMINISTIC_POLICY_NOT_STRENGTH_RANKED",
                "late_score_classifications": dict(Counter(row["late_score_classification"] for row in ats_rows)),
                "hook_classifications": dict(Counter(row["hook_classification"] for row in ats_rows))},
        "totals": {"overall": summarize(total_rows, "total_result"),
                   "by_direction": segmented(total_rows, "total_result", "selection"),
                   "by_confidence": segmented(total_rows, "total_result", "confidence"),
                   "by_score_quintile": segmented(total_rows, "total_result", "score_quintile"),
                   "by_total_bucket": segmented(total_rows, "total_result", "total_bucket"),
                   "calibration": calibrated(total_rows, "total_result"),
                   "shadow_score_ranking": ranking_table(total_rows, "total_result", "market_score_rank")},
        "combined": {"overall": summarize(graded_pool, "result"),
                     "mixed_shadow_top5": summarize(mixed_rows, "result"),
                     "decision_review_five": summarize(decision_rows, "result"),
                     "ranking": ranking_table(graded_pool, "result", "pool_rank"),
                     "top10_market_mix": dict(Counter(row["market"] for row in graded_pool[:10])),
                     "top5_market_mix": dict(Counter(row["market"] for row in graded_pool[:5])),
                     "top10_board": graded_pool[:10],
                     "mean_score_ats": round(statistics.mean(float(row["candidate_score"]) for row in graded_pool if row["market"] == "ATS"), 4),
                     "mean_score_totals": round(statistics.mean(float(row["candidate_score"]) for row in graded_pool if row["market"] == "TOTAL"), 4),
                     "totals_above_best_ats": sum(float(row["candidate_score"]) > max(float(other["candidate_score"]) for other in graded_pool if other["market"] == "ATS") for row in graded_pool if row["market"] == "TOTAL")},
        "clv": clv, "historical": historical_data,
    }
    write_json("week6_diagnostics.json", metrics)
    counterfactuals = counterfactual(graded_pool, ats_rows, total_rows)
    write_json("week6_counterfactual_top5.json", counterfactuals)
    report = make_report(custody, metrics, top5_rows, mixed_rows, decision_rows, counterfactuals)
    (OUTPUT / "week6_postgame_report.md").write_text(report, encoding="utf-8", newline="\n")
    (OUTPUT / "week6_top5_failure_analysis.md").write_text(make_top5_analysis(top5_rows), encoding="utf-8", newline="\n")
    manifest = {"audit_status": "FAIL_INCOMPLETE_CLV_CUSTODY_AND_RAW_COMPONENTS", "frozen": {k: v for k, v in custody.items() if k not in {"model_manifest", "card_manifest"}},
                "pregame_model_code_sha": custody["model_manifest"]["code_commit_sha"],
                "pregame_model_versions": {"ats": custody["model_manifest"]["ats"]["version"],
                                            "totals": custody["model_manifest"]["totals"]["version"]},
                "pregame_generation_timestamp_utc": custody["card_manifest"]["generated_at"],
                "frozen_at_capture": capture["scoreboard"]["retrieved_at_utc"],
                "ats_rows": len(ats_rows), "totals_rows": len(total_rows), "combined_rows": len(graded_pool),
                "official_ats_top5": [row["selection"] for row in top5_rows],
                "qualified_clv_rows": 0,
                "output_sha256": {path.relative_to(ROOT).as_posix(): sha(path) for path in sorted(OUTPUT.rglob("*"))
                                  if path.is_file() and path.name != "week6_postgame_manifest.json"}}
    write_json("week6_postgame_manifest.json", manifest)
    return metrics


def counterfactual(pool: list[dict], ats_rows: list[dict], total_rows: list[dict]) -> dict:
    def selection(rows: list[dict]) -> dict:
        chosen = rows[:5]
        return {"status": "IN_SAMPLE_DIAGNOSTIC_ONLY", "record": summarize(chosen, "result"),
                "picks": [{key: row[key] for key in ("market", "game", "selection", "locked_line", "selected_probability", "result")} for row in chosen]}
    ats = [row for row in pool if row["market"] == "ATS"]
    totals = [row for row in pool if row["market"] == "TOTAL"]
    capped = sorted(pool, key=lambda row: (-min(float(row["candidate_score"]), 0.60) if row["market"] == "TOTAL" else -float(row["candidate_score"]), row["pool_rank"]))
    shrink = sorted(pool, key=lambda row: (-0.5 - (float(row["candidate_score"])-0.5) * (0.5 if row["market"] == "TOTAL" else 1.0), row["pool_rank"]))
    diversified = ats[:2] + totals[:3]
    diversified.sort(key=lambda row: row["pool_rank"])
    return {"frozen_mixed_shadow": selection(pool), "ats_shadow_score_only": selection(ats),
            "totals_shadow_score_only": selection(totals),
            "illustrative_total_score_cap_60pct": selection(capped),
            "illustrative_total_excess_probability_half_shrink": selection(shrink),
            "illustrative_two_ats_three_totals_constraint": selection(diversified),
            "non_evaluable_rules": {"CLV_based": "No pre-kickoff timestamp-qualified closing line can exist at lock time; CLV cannot rank a contemporaneous board.",
                                    "empirically_calibrated_cross_market": "No validated common-scale ATS/totals mapping is frozen in prior weeks; fitting to Week 6 would be hindsight.",
                                    "confidence_filter": "Governed ATS confidence is 1 for all 58, so removal would delete the full ATS market."}}


def fmt_record(item: dict) -> str:
    rate = item["win_rate_ex_push"]
    return f"{item['win']}-{item['loss']}-{item['push']} (N={item['n']}; {rate*100:.1f}% W ex-push)" if rate is not None else f"0-0-0 (N={item['n']})"


def segment_table(title: str, rows: dict) -> str:
    lines = [f"### {title}", "", "| Segment | Record | Win % | N | 95% Wilson interval |", "|---|---:|---:|---:|---:|"]
    for label, item in rows.items():
        interval = item.get("wilson_95_ex_push")
        ci = f"{interval[0]*100:.1f}–{interval[1]*100:.1f}%" if interval else "—"
        rate = f"{item['win_rate_ex_push']*100:.1f}%" if item["win_rate_ex_push"] is not None else "—"
        lines.append(f"| {label} | {item['win']}-{item['loss']}-{item['push']} | {rate} | {item['n']} | {ci} |")
    return "\n".join(lines)


def calibration_table(title: str, rows: dict) -> str:
    lines = [f"### {title}", "", "| Predicted bucket | N | Expected W | Actual W | Expected % | Actual % | Actual − expected |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    for label, item in rows.items():
        expected = f"{item['expected_win_pct']*100:.1f}%" if item["expected_win_pct"] is not None else "—"
        actual = f"{item['actual_win_pct']*100:.1f}%" if item["actual_win_pct"] is not None else "—"
        err = f"{item['calibration_error_pct_points']:+.1f} pp" if item["calibration_error_pct_points"] is not None else "—"
        lines.append(f"| {label}% | {item['n']} | {item['expected_wins']:.2f} | {item['actual_wins']} | {expected} | {actual} | {err} |")
    return "\n".join(lines)


def rank_table(title: str, rows: dict) -> str:
    order = ("Top 5", "6-10", "11-20", "21-40")
    lines = [f"### {title}", "", "| Score rank | Record | N | Mean stated P | Qualified mean CLV |",
             "|---|---:|---:|---:|---:|"]
    for label in list(order) + sorted(key for key in rows if key not in order):
        if label not in rows:
            continue
        item = rows[label]
        lines.append(f"| {label} | {item['win']}-{item['loss']}-{item['push']} ({item['win_rate_ex_push']*100:.1f}%) | {item['n']} | {item['mean_selected_probability']*100:.1f}% | unavailable |")
    return "\n".join(lines)


def make_report(custody: dict, metrics: dict, top5: list[dict], mixed: list[dict],
                decision: list[dict], alternatives: dict) -> str:
    ats, totals, combined, hist = (metrics[key] for key in ("ats", "totals", "combined", "historical"))
    model = custody["model_manifest"]
    lines = ["# Week 6 2026 formal post-week audit", "",
             "## Executive verdict", "",
             "**C — Ranking/calibration is materially broken for the Top-5 objective.** The governed ATS Top 5 went "
             f"{fmt_record(ats['governed_top5'])}, while the full ATS card went {fmt_record(ats['overall'])}. "
             "The governed five were simply the first five locked games, with no strength ordering and Confidence 1 on every ATS game. "
             f"The separate mixed shadow Top 5 went {fmt_record(combined['mixed_shadow_top5'])}; all five were totals because "
             f"{combined['totals_above_best_ats']} totals scores exceeded the best ATS score. "
             "These observations do not establish that the EPA margin model is structurally broken; they directly indict the current selection and cross-market score custody. "
             "No timestamp-qualified closing lines were available, so true CLV and a process-quality verdict remain unresolved.", "",
             "**Operational recommendation: PATCH the Top-5 governance and develop/test v2.9 offline before any owner-approved cutover. "
             "Keep v2.8 frozen until a separately reviewed policy change passes prior-week walk-forward evaluation.** "
             "The Week 6 card was a local governed draft, and the totals/mixed board was shadow, not a sportsbook recommendation.", "",
             "## Frozen evidence and scope", "",
             f"- Model-run commit: `{model['code_commit_sha']}`; later PR #34 review packaging merged as `abb4eb26bd1140e66972d2f1143cd587e80960b4`. "
             "The latter is not a model rerun.",
             f"- ATS model `{model['ats']['version']}`; totals model `{model['totals']['version']}`; frozen generation `{model['generated_at_utc']}` UTC.",
             f"- Locked-line domain SHA-256 `{custody['locked_line_snapshot_sha256']}`; source database SHA-256 `{custody['source_database_sha256']}`.",
             f"- {custody['frozen_files_verified']}/{custody['frozen_files_verified']} sealed pregame files verified; 58 ATS candidates, 0 skips; 58 totals candidates, 0 skips; 116 combined selections.",
             "- Governed ATS Top 5, in stored order: " + "; ".join(f"{row['selection']} {row['selected_spread']:+g}" for row in top5) + ".",
             "- Current v2.8 master prompt is cited in prior audit but its full authoritative numeric rule text is not checked into this repository; proposed exact policy deltas require that baseline.", "",
             "## Full-card performance", "",
             f"ATS **{fmt_record(ats['overall'])}**, totals **{fmt_record(totals['overall'])}**, combined **{fmt_record(combined['overall'])}**. "
             "These are hypothetical selections against immutable contest lines, not verified sportsbook bets or real ROI. "
             "The CSVs `week6_ats_audit.csv` and `week6_totals_audit.csv` contain every graded selection, including all losses, score, line, projection, confidence, ranking, hook, and evidence pointers.", "",
             segment_table("ATS favorite/dog", ats["by_favorite_dog"]), "",
             segment_table("ATS home/away", ats["by_home_away"]), "",
             segment_table("ATS road/home × favorite/dog", ats["by_road_home_category"]), "",
             segment_table("ATS locked spread buckets", ats["by_spread_bucket"]), "",
             segment_table("ATS confidence", ats["by_confidence"]), "",
             segment_table("ATS score quintile (1 lowest)", ats["by_score_quintile"]), "",
             segment_table("Totals direction", totals["by_direction"]), "",
             segment_table("Totals confidence", totals["by_confidence"]), "",
             segment_table("Totals score quintile (1 lowest)", totals["by_score_quintile"]), "",
             segment_table("Totals locked-total buckets", totals["by_total_bucket"]), "",
             "## Governed ATS Top 5: exact ranking and failures", "",
             "The frozen `ranking_basis` for all five is `DETERMINISTIC_POLICY_TOP5_NOT_STRENGTH_RANKED`. "
             "They are the first five locked-line rows. The stored rank labels run 5→1 and do not measure probability or edge. "
             "Their combined shadow-pool ranks are shown below; none was a top-five strength candidate. "
             "The sealed card stores aggregate EPA-only projected margin and edge but not a per-team EPA component attribution. "
             "The per-pick question-by-question analysis is in `week6_top5_failure_analysis.md`; missing raw component attribution is an audit limitation. "
             "No timestamp-qualified close exists, so the indicative ESPN DraftKings quote is shown only as an unqualified proxy. "
             "All five carry unverified QB/injury context and sample-quality warnings; no manual adjustment was made.", "",
             "| Order | Pick / locked line | Final (away–home) | ATS margin | Stated P | Raw projected home margin | ATS edge pts | Pool rank | Indicative close / CLV* | Primary failure |",
             "|---:|---|---:|---:|---:|---:|---:|---:|---|---|"]
    failures = []
    for index, row in enumerate(top5):
        failure = "G — football variance / narrow margin" if index == 1 else "D — ranking/selection failure"
        failures.append(failure)
        quote = row["provider_labeled_close_home_spread"] or "—"
        proxy = row["indicative_unqualified_clv_points"]
        proxy_text = f"{float(proxy):+g}" if proxy != "" else "—"
        lines.append(f"| {row['top5_order']} | {row['selection']} {row['selected_spread']:+g} ({row['game']}) | {row['away_score']}–{row['home_score']} | {row['ats_margin_vs_locked']:+g} | {float(row['selected_probability'])*100:.1f}% | {float(row['projected_home_margin']):+.1f} | {float(row['model_selected_edge_points']):+.1f} | {row['shadow_pool_rank']}/116 | {quote} / {proxy_text} | {failure} |")
    lines += ["", "*ESPN postgame quote is provider-labeled ‘close’ without quote timestamp. CLV is unqualified; market direction/process claims are withheld.", "",
              "The primary D labels identify the actual mechanism that elevated these losses into the official five: card-row order despite low confidence and low shadow rank. "
              "They do not claim the projected football margin was otherwise correct. Jacksonville State lost ATS by 1.5 points as a roughly 51% side; a single such result is a plausible narrow-loss variance case (G). "
              "The other four missed the locked spread by 10.5–18.5 points and their ranking failure is demonstrable; isolated scores cannot identify a specific missing feature or coefficient. "
              "For every pick the positive pregame signals were the frozen selected margin edge and any captured lock advantage; the negative signals were the sample/QB/injury warnings and low 50–54% stated probabilities. "
              "The handicaps were wrong in realized margin on four games, but probability aggressiveness cannot be inferred from five binary outcomes. "
              "A disciplined bettor would not treat these Confidence-1, unverified-context, row-order picks as five strongest wagers. "
              "The scoring-play classification in the ATS CSV is evidence-based; it is not inferred from final score alone.", "",
              "## Shadow mixed Top 5 and combined board", "",
              f"The mixed Top 5 went {fmt_record(combined['mixed_shadow_top5'])}, and the separate human review five went {fmt_record(combined['decision_review_five'])}. "
              "These three five-pick lists are distinct products. The top ten combined scores are all totals; the first ATS candidate was displaced to pool rank "
              f"{min(int(row['pool_rank']) for row in read_csv(OUTPUT / 'week6_combined_board_audit.csv') if row['market'] == 'ATS')}. "
              f"Mean stated score: ATS {combined['mean_score_ats']:.3f}, totals {combined['mean_score_totals']:.3f}. "
              "Totals use an uncalibrated normal shadow score, while ATS uses a conservative shadow mapping; they were not validated on a common scale.", "",
              "| Pool rank | Market | Selection / line | Stated score | Result |", "|---:|---|---|---:|---|"]
    for row in combined["top10_board"]:
        lines.append(f"| {row['pool_rank']} | {row['market']} | {row['selection']} {row['locked_line']} — {row['game']} | {float(row['candidate_score'])*100:.1f}% | {row['result']} |")
    lines += ["", "## Probability calibration", "",
              "Treat each number as a stated shadow score, not as a proven fair-bet probability. "
              "A push would be excluded from binary calibration; Week 6 had none.", "",
              calibration_table("ATS", ats["calibration"]), "",
              calibration_table("Totals", totals["calibration"]), "",
              f"The totals 60%+ bucket was 11–12 (N=23) versus {totals['calibration']['60+']['expected_wins']:.2f} expected wins. "
              "Week 5's analogous uncalibrated 60%+ totals bucket went "
              f"{fmt_record(hist['week5_totals_probability_ge_60pct'])} versus {hist['week5_totals_probability_ge_60pct_expected_wins']:.2f} expected wins. "
              f"Together, the two high-score buckets delivered {hist['weeks5_6_totals_probability_ge_60pct']['actual_wins']}/"
              f"{hist['weeks5_6_totals_probability_ge_60pct']['n']} wins against "
              f"{hist['weeks5_6_totals_probability_ge_60pct']['expected_wins']:.2f} expected. "
              f"If the stated probabilities were honest and games independent, the Poisson-binomial chance of that few wins or fewer is "
              f"{hist['weeks5_6_totals_probability_ge_60pct']['lower_tail_if_independent_and_honest']*100:.2f}%; "
              "this conditional calculation does not account for correlated risk or validate the shadow scores. "
              "The high-score tail shows severe calibration failure if interpreted as a win probability; broad model structure remains unproven and no numeric shrink factor is justified yet. "
              "The Week 6 ATS probabilities were concentrated at 50–54%, so 28 wins versus approximately 30.5 expected is not severe ATS calibration drift.", "",
              "## Ranking power", "",
              "These are **shadow score ranks** within each market and the combined board; the governed ATS Top 5 is separately row-order based. "
              "Mean qualified CLV is unavailable in every rank band.", "",
              rank_table("ATS shadow score order", ats["shadow_score_ranking"]), "",
              rank_table("Totals shadow score order", totals["shadow_score_ranking"]), "",
              rank_table("Combined score order", combined["ranking"]), "",
              "The strongest-scored totals five lost four of five, while ranks 21–40 outperformed them. This is an observed ranking inversion, not yet a stable rule. "
              "The official ATS five were never strength-ranked; their 0–5 result should not be attributed to a failed ATS probability ranking algorithm.", "",
              "## Closing-line value and market process", "",
              "**Qualified CLV: 0/116.** The ESPN DraftKings postgame payload exposes a `close` field but no quote timestamp. "
              "Retrieval on the audit date cannot establish when those odds were available or whether they were a true final pre-kickoff quote. "
              "`week6_clv_audit.csv` preserves every provider-labeled field and provenance, while `week6_diagnostics.json` gives descriptive, unqualified proxy summaries. "
              f"The **unqualified proxy** mean/median/positive-share was ATS {metrics['clv']['ats']['provider_labeled_unqualified_mean']:+.2f}/"
              f"{metrics['clv']['ats']['provider_labeled_unqualified_median']:+.1f}/"
              f"{metrics['clv']['ats']['provider_labeled_unqualified_positive_pct']*100:.1f}% and totals "
              f"{metrics['clv']['totals']['provider_labeled_unqualified_mean']:+.2f}/"
              f"{metrics['clv']['totals']['provider_labeled_unqualified_median']:+.1f}/"
              f"{metrics['clv']['totals']['provider_labeled_unqualified_positive_pct']*100:.1f}%. "
              "The detailed proxy by confidence, Top 5 and win/loss sign appears in diagnostics; it is not accepted as true CLV. "
              "Accordingly mean/median true CLV, CLV+ rate, Top-5 CLV, confidence cuts, CLV+/CLV− outcome splits, and GOOD PROCESS/BAD RESULT versus BAD PROCESS are **not adjudicated**. "
              "The earlier captured `current_market_line` is a pregame comparison, not a close, and is not substituted for one.", "",
              "## Historical out-of-sample comparison", "",
              "Prior ATS cards available here: Week 1 local draft, Week 2 local draft, Week 3 provisional, and Week 5 frozen audit. Week 4 has no replay-safe frozen card. "
              f"Their combined ATS record was {fmt_record(hist['ats']['weeks_1_2_3_5'])}; Week 6 ATS was {fmt_record(ats['overall'])}. "
              f"The prior governed Top 5 was {fmt_record(hist['governed_top5_weeks_1_2_3_5'])}, now 7–18 including Week 6. "
              f"Week 5 totals were {fmt_record(hist['totals_week5_only'])}, compared with {fmt_record(totals['overall'])} in Week 6. "
              "Weeks 1–3 lack complete stored comparable ATS/totals probability cards, so their calibration, totals, and cross-market rankings cannot be reconstructed honestly. "
              "The historical intervals and segment cuts in `week6_diagnostics.json` are descriptive and small-sample; do not turn a Week 6 split into a permanent rule.", "",
              "## Counterfactual Top 5 — IN-SAMPLE DIAGNOSTIC ONLY", "",
              "Every alternative uses only frozen pregame fields and is graded afterward; none was optimized by final score. "
              "None is a proposed production rule without prior-week replay and owner approval.", "",
              "| Pregame rule | Week 6 record | Five selections (result) |", "|---|---:|---|"]
    for key, item in alternatives.items():
        if not isinstance(item, dict) or "picks" not in item:
            continue
        picks = "; ".join(f"{pick['selection']} {pick['locked_line']} {pick['result']}" for pick in item["picks"])
        lines.append(f"| {key.replace('_', ' ')} | {fmt_record(item['record'])} | {picks} |")
    lines += ["", "A 60% cap alone leaves the same five because all top totals tie at the cap and retain frozen tie order. "
              "The ATS-only 4–1 result is a one-week diagnostic, not evidence for forcing ATS market balance. "
              "A true calibrated cross-market alternative cannot be replayed with existing historical probability custody.", "",
              "## Five biggest problems, in order", "",
              "1. **CRITICAL — TOP-5 RANKING.** Official ATS Top 5 was deterministic card order, 0–5 this week, and 7–13 across prior recorded weeks. "
              "Cause is known policy behavior, not football variance. Requires a separately approved ranking-policy test, not an in-week edit.",
              "2. **HIGH — PROBABILITY CALIBRATION / TOTALS MODEL.** Week 6 totals ≥60% scored 11–12 against 14.69 expected; Week 5 analogous high bucket was 9–15; jointly 20/47 against 30.14 expected. "
              "High totals scores need walk-forward reliability study before use as probabilities. Do not assert coefficient failure from two weeks.",
              "3. **HIGH — ATS/TOTALS COMBINATION.** 25 totals outranked the best ATS score; mixed Top 5 was 5/5 totals and 1–4. "
              "Structural score-scale mismatch is documented in the frozen manifest. Requires market-specific calibration before comparing scores.",
              "4. **MODERATE — CLV DATA QUALITY.** 0/116 timestamp-qualified closes means market-process quality cannot be evaluated; this blocks formal PASS. "
              "Requires historical quote custody, not a model coefficient change.",
              "5. **MODERATE — FEATURE/CONTEXT QUALITY.** All governed ATS Top-5 rows had unverified QB/injury context and sample warnings. "
              "The evidence does not identify which missing context caused any specific loss. Improve verified pregame data custody and test its OOS value; do not invent adjustments.", "",
              "Line locking showed no defect: every grade uses the unchanged SplashSports snapshot. Home/road and spread-bucket splits are noisy at these sample sizes. "
              "Pure variance plausibly explains Jacksonville State's narrow loss but not the demonstrable Top-5 row-order governance and cross-market scale faults.", "",
              "## Lessons Learned", "",
              "- Keep the frozen governed ATS five, mixed shadow five, and human review five separate in every performance claim.",
              "- Do not promote a shadow probability score to wagering confidence before OOS calibration and cross-market comparison.",
              "- Persist timestamped book, market, quote, and capture metadata at close if CLV is an acceptance criterion.",
              "- Preserve point-in-time data warnings; a missing QB fact cannot be inferred from an outcome.",
              "- Use prior-week replay and predefined thresholds before any v2.9 cutover; no Week 6 result alone licenses a new rule.", "",
              "## Potential v2.9 research plan — no implementation", "",
              "| Priority | Current rule | Proposed research rule | Numeric delta | Evidence / expected benefit | Overfit risk | Required backtest |",
              "|---|---|---|---|---|---|---|",
              "| MUST FIX | Governed ATS Top 5 uses first five lock rows | Design a predeclared strength-rank policy with preserved fallback and compare to current policy | No justified numeric threshold yet | 0–5 Week 6 and 7–13 prior; may align Top 5 with calibrated reliability | HIGH | Replay all available sealed weeks; compare Top 5 versus remaining card and margin error |",
              "| MUST FIX | Mixed shadow compares ATS conservative and totals normal scores directly | Fit market-specific OOS calibration before a unified rank; retain shadow status until validated | No justified shrink factor yet | 25 totals above top ATS and 1–4 mixed five; makes scores comparable | HIGH | Walk-forward Brier, log loss, calibration, ROI after vig, rank monotonicity |",
              "| MUST FIX | Closing quote has no timestamp custody | Capture auditable last pre-kickoff real-book quote per market | Timestamp strictly before kickoff; no price threshold change | Enables qualified CLV and process review | LOW | Provider replay, timestamp cutoff and provenance tests |",
              "| SHOULD TEST | Totals use uncalibrated normal probability | Test calibrated totals reliability or shrinkage learned on prior weeks | 60% cap and 50% excess shrink are diagnostics only, not recommended numeric changes | High-score totals underperformed in Weeks 5 and 6 | HIGH | Multi-season walk-forward calibration, held-out weeks, baseline comparison |",
              "| SHOULD TEST | QB/injury context incomplete, no manual adjustment | Test verified point-in-time availability and incremental predictive value | No numeric adjustment justified | Warnings on official five; causal effect unknown | HIGH | Ablation with timestamped features and predeclared acceptance criteria |",
              "| DO NOT CHANGE | Immutable locked lines, ATS/totals grading, v2.8 model coefficients | Preserve | 0 | No identified defect; data custody reconciles 58/58 | LOW | Existing immutability/grading checks |", "",
              "Do not change spreads/totals, backfill outcome-aware projections, impose arbitrary 3–2 market balance, retune road-favorite rules, "
              "claim a profitable edge from hypothetical -110 accounting, or issue v2.9 before the baseline policy and OOS evidence are available.", "",
              "## WHAT ACTUALLY CAUSED WEEK 6?", "",
              "The governed ATS Top 5 was selected by locked-card order, not by estimated strength, and all five lost. "
              "The full ATS card was 28–30, so the worst outcome was concentrated in the unranked five. "
              "The mixed shadow board put totals in all five slots because its uncalibrated totals scores were systematically higher than the ATS scores; that five went 1–4. "
              "Totals overall were 33–25, but their 60%+ score bucket was 11–12, matching a Week 5 warning that high totals scores overstate reliability. "
              "Incomplete QB/injury context may matter but cannot be assigned causal credit from these records. "
              "The locked lines and grades reconciled; they did not cause the loss. "
              "Football variance explains at least the narrow Jacksonville State loss, but it does not explain deterministic Top-5 selection or unvalidated cross-market scoring. "
              "Without timestamped closes, we cannot say whether the market validated the picks before kickoff.", "",
              "**WEEK 6 AUDIT STATUS: FAIL**", "",
              "Every 58+58 selection is graded, Top-5 selection order reconstructed, calibration/ranking/history evaluated, and no production model changed. "
              "The required true CLV test cannot be completed with the available untimestamped `close` payload, and per-game raw EPA component attribution was not frozen, so the explicit PASS gate is not met.", ""]
    return "\n".join(lines)


def make_top5_analysis(rows: list[dict]) -> str:
    lines = ["# Week 6 governed ATS Top-5 loss analysis", "",
             "These are the frozen governed ATS picks, not the mixed shadow or human review list. "
             "Their Top-5 order is exactly the first five locked games, not a strength ranking. "
             "ESPN DraftKings postgame 'close' fields have no quote timestamp; the shown movement is an indicative proxy only. "
             "The frozen cards contain aggregate EPA-only margin projection and edge but do not preserve team-level EPA contribution rows, so raw component attribution is unavailable.", ""]
    for index, row in enumerate(rows):
        one_point_five = index == 1
        failure = "G — football variance / reasonable narrow loss" if one_point_five else "D — ranking/selection failure"
        edge = float(row["model_selected_edge_points"])
        probability = float(row["selected_probability"])
        home_margin = int(row["home_score"]) - int(row["away_score"])
        home_error = home_margin - float(row["projected_home_margin"])
        close_proxy = row["indicative_unqualified_clv_points"]
        market = ("toward the locked pick" if float(close_proxy) > 0 else
                  "away from the locked pick" if float(close_proxy) < 0 else "flat") if close_proxy != "" else "unavailable"
        data_warning = row["sample_quality_warning"].replace(";", ", ")
        context = "QB starter unverified; ESPN injury coverage incomplete"
        loss_size = -float(row["ats_margin_vs_locked"])
        lines += [f"## {index+1}. {row['selection']} {row['selected_spread']:+g} — {row['game']}", "",
                  f"**Result:** {row['away_score']}–{row['home_score']} (away–home), ATS LOSS by {loss_size:g} points against the immutable lock. "
                  f"Frozen home-margin projection {float(row['projected_home_margin']):+.2f}; actual {home_margin:+d}; projection error {home_error:+.2f} home-margin points. "
                  f"Aggregate selected edge {edge:.2f} points, shadow probability {probability*100:.2f}%, shadow rank {row['shadow_pool_rank']}/116, "
                  f"governed Confidence {row['confidence']}; stored official rank label {row['official_rank']}. "
                  f"Pregame current home spread {row['pregame_current_home_spread']}; frozen selected-side lock advantage {float(row['pregame_lock_advantage_points']):+.1f} points. "
                  f"Provider-labeled close home spread {row['provider_labeled_close_home_spread']}; indicative, unqualified CLV {float(close_proxy):+g} points; market proxy moved {market}. "
                  f"Late-score taxonomy: {row['late_score_classification']}.", "",
                  f"**Positive pregame signals:** aggregate EPA-only edge {edge:.2f} and recorded lock advantage {float(row['pregame_lock_advantage_points']):+.1f}; no adjustment was made. "
                  f"**Negative signals:** {data_warning}; {context}; stated probability {probability*100:.2f}% on a shadow mapping. "
                  "Per-team EPA offense/defense component contributions were not frozen and cannot be attributed from this CSV.", "",
                  f"1. **Handicap wrong?** The realized margin missed the frozen projection by {abs(home_error):.2f} points. "
                  + ("The selected side still lost ATS by only 1.5, so this game is too close to diagnose a structural handicap error." if one_point_five else
                     "That is a material realized miss, but one game cannot identify a coefficient or missing feature."),
                  f"2. **Probability too aggressive?** The frozen score was {probability*100:.2f}%. A single binary loss cannot calibrate it; "
                  + ("this was near a coin flip." if probability < 0.53 else "it remains an unvalidated shadow estimate."),
                  f"3. **Ranked too highly?** Yes for the governed Top 5: it was selected by row order despite combined shadow rank {row['shadow_pool_rank']}/116. "
                  "The rank label is not strength evidence.",
                  "4. **Important information missing?** QB starter confirmation and complete injury data were unavailable at lock; there is no proof either changed this outcome.",
                  "5. **Present but weighted incorrectly?** Sample warnings were present but did not remove the game from deterministic Top-5 order. "
                  "The stored evidence cannot isolate model coefficient weighting.",
                  "6. **Football variance?** " + ("A plausible primary explanation for a 1.5-point ATS loss at about 51% stated probability." if one_point_five else
                     "Possible on any game, but insufficient to explain the predictable selection-governance fault."),
                  "7. **Reasonable lock-time bet?** A mandatory contest side was required; the evidence did not warrant presenting it as one of five strongest sportsbook wagers. "
                  "Actual offered odds and stake decision were not frozen, and this audit makes no bet claim.", "",
                  f"**Primary loss category: {failure}.** " + ("The narrow realized shortfall with near-even probability supports G; its Top-5 placement still exposed a separate ranking-policy weakness." if one_point_five else
                     "The specific, verifiable failure is its promotion into the official five by lock order. The game result alone does not prove a model-specification or late-information defect."), ""]
    return "\n".join(lines)


if __name__ == "__main__":
    result = grade()
    print("Week 6 ATS", result["ats"]["overall"], "totals", result["totals"]["overall"])
