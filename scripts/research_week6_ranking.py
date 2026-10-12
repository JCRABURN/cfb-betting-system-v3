"""Read-only, reproducible Week 5-6 ranking diagnostics from sealed CSV artifacts.

This research script never queries or changes the source database or card generators.
Its output is descriptive and must not be used as a production selection policy.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "2026-week6-ranking-calibration-research"
EXECUTION = {
    5: ROOT / "outputs" / "2026-week5-execution-20260930-v4",
    6: ROOT / "outputs" / "2026-week6-execution-20261006T2133Z",
}
AUDIT = {
    5: ROOT / "outputs" / "2026-week5-postgame-audit",
    6: ROOT / "outputs" / "2026-week6-postgame-audit",
}


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        return list(csv.DictReader(stream))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"refusing empty output {path}")
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def number(value: str | float) -> float:
    return float(value)


def quantile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low = math.floor(index)
    high = math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


def wilson(wins: int, n: int) -> list[float] | None:
    if n == 0:
        return None
    z = 1.959963984540054
    center = (wins / n + z * z / (2 * n)) / (1 + z * z / n)
    radius = z * math.sqrt((wins / n) * (1 - wins / n) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [center - radius, center + radius]


def record(rows: list[dict]) -> dict:
    counts = Counter(row["result"] for row in rows)
    decided = counts["WIN"] + counts["LOSS"]
    return {
        "n": len(rows), "wins": counts["WIN"], "losses": counts["LOSS"],
        "pushes": counts["PUSH"], "win_rate_ex_push": counts["WIN"] / decided if decided else None,
        "wilson_95_ex_push": wilson(counts["WIN"], decided),
        "mean_shadow_score": sum(row["score"] for row in rows) / len(rows) if rows else None,
        "expected_wins_shadow": sum(row["score"] for row in rows),
    }


def calibration(rows: list[dict]) -> dict:
    decided = [row for row in rows if row["result"] in ("WIN", "LOSS")]
    if not decided:
        return {"n": 0}
    n = len(decided)
    buckets = []
    for low, high in ((.50, .52), (.52, .54), (.54, .56), (.56, .58), (.58, .60), (.60, 1.01)):
        group = [row for row in decided if low <= row["score"] < high]
        wins = sum(row["result"] == "WIN" for row in group)
        mean = sum(row["score"] for row in group) / len(group) if group else None
        observed = wins / len(group) if group else None
        buckets.append({"bucket": f"{low:.2f}-{high:.2f}" if high < 1 else "0.60+",
                        "n": len(group), "mean_score": mean, "win_rate": observed,
                        "gap_observed_minus_score": observed - mean if group else None,
                        "expected_wins": sum(row["score"] for row in group),
                        "wins": wins, "wilson_95": wilson(wins, len(group))})
    brier = sum((row["score"] - (row["result"] == "WIN")) ** 2 for row in decided) / n
    logloss = -sum(math.log(row["score"] if row["result"] == "WIN" else 1-row["score"])
                   for row in decided) / n
    ece = sum(item["n"] * abs(item["gap_observed_minus_score"])
              for item in buckets if item["n"]) / n
    # Pairwise concordance is a ranking statistic, distinct from calibration.
    wins = [row["score"] for row in decided if row["result"] == "WIN"]
    losses = [row["score"] for row in decided if row["result"] == "LOSS"]
    auc = (sum((a > b) + .5 * (a == b) for a in wins for b in losses) /
           (len(wins) * len(losses))) if wins and losses else None
    return {"n": n, "brier_shadow_diagnostic": brier,
            "log_loss_shadow_diagnostic": logloss, "ece_shadow_diagnostic": ece,
            "pairwise_auc": auc, "buckets": buckets}


def load_week(week: int) -> tuple[list[dict], list[dict]]:
    pre = EXECUTION[week]
    audit = AUDIT[week]
    card = read_csv(pre / f"week{week}_ats_full_card.csv")
    ats_grades = {r["game_id"]: r for r in read_csv(audit / f"week{week}_ats_audit.csv")}
    totals_card = read_csv(pre / f"week{week}_totals_full_card.csv")
    totals_grades = {r["game_id"]: r for r in read_csv(audit / f"week{week}_totals_audit.csv")}
    frozen_ats = ({r["game_id"]: r for r in read_csv(pre / "week6_ats_shadow_calibration.csv")}
                  if week == 6 else {})
    if len(card) != len(ats_grades) or len(totals_card) != len(totals_grades):
        raise ValueError(f"Week {week} candidate/grade coverage differs")
    ats = []
    for item in card:
        game = item["game_id"]
        grade = ats_grades[game]
        if week == 5:
            edge = abs(number(item["home_ats_edge"]))
            # Exact pre-existing conservative transform in finalize_week5_card.py.
            score = min(.60, .50 + .005 * edge)
            score_source = "RECONSTRUCTED_PREEXISTING_POLICY_FROM_FROZEN_EDGE"
        else:
            shadow = frozen_ats[game]
            edge = number(shadow["selected_margin_advantage_points"])
            score = number(shadow["candidate_score"])
            if not math.isclose(score, min(.60, .50 + .005 * edge), abs_tol=1e-12):
                raise ValueError(f"ATS score transform mismatch: {game}")
            score_source = "SEALED_PREGAME_CANDIDATE_SCORE"
        if grade["ats_result"] not in ("WIN", "LOSS", "PUSH"):
            raise ValueError(f"ungraded ATS game: {game}")
        ats.append({"week": week, "game_id": game, "game": f"{item['away']} @ {item['home']}",
                    "pick": item["pick"], "opponent": item["home"] if item["selected_side"] == "away" else item["away"],
                    "locked_spread": number(item["pick_spread"]), "locked_line_id": int(item["locked_line_id"]),
                    "official_rank": int(item["rank"]) if item["rank"] else None,
                    "confidence": int(item["confidence"]),
                    "governed_uncertainty": number(item["uncertainty_points"]) if item["uncertainty_points"] else None,
                    "shadow_uncertainty": number(item["shadow_uncertainty_points"]),
                    "edge_points": edge, "score": score, "score_source": score_source,
                    "result": grade["ats_result"]})
    totals = []
    for item in totals_card:
        game = item["game_id"]
        grade = totals_grades[game]
        if not item["pick"] or grade["total_result"] not in ("WIN", "LOSS", "PUSH"):
            raise ValueError(f"incomplete total: Week {week} game {game}")
        score = number(item["raw_selected_probability"])
        totals.append({"week": week, "game_id": game, "game": f"{item['away']} @ {item['home']}",
                       "pick": item["pick"].upper(), "locked_total": number(item["locked_total"]),
                       "score": score, "confidence": int(item["confidence"]),
                       "edge_points": abs(number(item["raw_point_edge"])),
                       "result": grade["total_result"]})
    return ats, totals


def rank(rows: list[dict], method: str) -> list[dict]:
    if method == "governed":
        return sorted(rows, key=lambda r: (-r["confidence"], r["governed_uncertainty"] is None,
                                           r["governed_uncertainty"] if r["governed_uncertainty"] is not None else math.inf,
                                           r["locked_line_id"]))
    if method == "shadow_score":
        return sorted(rows, key=lambda r: (-r["score"], r["locked_line_id"]))
    if method == "confidence":
        return sorted(rows, key=lambda r: (-r["confidence"], r["locked_line_id"]))
    if method == "edge":
        return sorted(rows, key=lambda r: (-r["edge_points"], r["locked_line_id"]))
    if method == "shadow_uncertainty":
        return sorted(rows, key=lambda r: (r["shadow_uncertainty"], r["locked_line_id"]))
    raise ValueError(method)


def frozen_mixed_top5(week: int, ats: list[dict], totals: list[dict]) -> list[dict]:
    path = EXECUTION[week] / f"week{week}_combined_top5.csv"
    by_market_game = {(market, row["game_id"]): row
                      for market, rows in (("ATS", ats), ("TOTAL", totals)) for row in rows}
    picks = []
    for frozen in sorted(read_csv(path), key=lambda row: int(row["rank"])):
        source = by_market_game[(frozen["market"].upper(), frozen["game_id"])]
        if not math.isclose(number(frozen["shadow_probability_score"]), source["score"], abs_tol=1e-12):
            raise ValueError(f"frozen combined score mismatch: Week {week}, {source['game_id']}")
        picks.append({**source, "market": frozen["market"].upper()})
    if len(picks) != 5 or len({row["game_id"] for row in picks}) != 5:
        raise ValueError(f"incomplete/duplicated frozen mixed Top 5: Week {week}")
    return picks


def replay_summary(by_week: dict[int, tuple[list[dict], list[dict]]],
                   rankings: dict[int, dict[str, list[dict]]]) -> dict:
    strategies = ("governed_ats", "ats_shadow_score", "totals_shadow_score", "frozen_mixed_shadow")
    result = {}
    for strategy in strategies:
        weekly = []
        cumulative_wins = cumulative_losses = 0
        balance = peak = 0
        max_drawdown = 0
        losing_week_streak = max_losing_week_streak = 0
        for week in (5, 6):
            ats, totals = by_week[week]
            if strategy == "governed_ats":
                picks = [{**row, "market": "ATS"} for row in rankings[week]["governed"][:5]]
            elif strategy == "ats_shadow_score":
                picks = [{**row, "market": "ATS"} for row in rankings[week]["shadow_score"][:5]]
            elif strategy == "totals_shadow_score":
                picks = [{**row, "market": "TOTAL"} for row in
                         sorted(totals, key=lambda row: (-row["score"], row["game_id"]))[:5]]
            else:
                picks = frozen_mixed_top5(week, ats, totals)
            for row in picks:
                if row["result"] == "WIN":
                    cumulative_wins += 1
                elif row["result"] == "LOSS":
                    cumulative_losses += 1
            weekly_wins = sum(row["result"] == "WIN" for row in picks)
            weekly_losses = sum(row["result"] == "LOSS" for row in picks)
            balance += weekly_wins - weekly_losses
            peak = max(peak, balance)
            max_drawdown = max(max_drawdown, peak - balance)
            losing_week_streak = losing_week_streak + 1 if weekly_losses > weekly_wins else 0
            max_losing_week_streak = max(max_losing_week_streak, losing_week_streak)
            weekly.append({"week": week, **record(picks),
                           "ats_count": sum(row["market"] == "ATS" for row in picks),
                           "totals_count": sum(row["market"] == "TOTAL" for row in picks),
                           "cumulative_wins": cumulative_wins, "cumulative_losses": cumulative_losses})
        result[strategy] = {"weekly": weekly,
                            "cumulative_wins": cumulative_wins, "cumulative_losses": cumulative_losses,
                            "max_week_end_drawdown_even_money_units": max_drawdown,
                            "longest_losing_week_streak": max_losing_week_streak,
                            "status": "FROZEN_OR_FIXED_RULE_REPLAY_ONLY_NOT_VALIDATED_WALK_FORWARD"}
    return result


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    by_week = {week: load_week(week) for week in (5, 6)}
    if any(len(ats) != expected or len(totals) != expected
           for (ats, totals), expected in ((by_week[5], 56), (by_week[6], 58))):
        raise ValueError("Week 5/6 full-card coverage mismatch")
    all_ats = [r for week in (5, 6) for r in by_week[week][0]]
    all_totals = [r for week in (5, 6) for r in by_week[week][1]]
    methods = ("governed", "shadow_score", "confidence", "edge", "shadow_uncertainty")
    rankings = {week: {method: rank(by_week[week][0], method) for method in methods} for week in (5, 6)}
    reconstructed = []
    for item in sorted(by_week[6][0], key=lambda r: r["locked_line_id"]):
        reconstructed.append({"governed_order": rankings[6]["governed"].index(item)+1,
                              "official_top5_rank": item["official_rank"] or "",
                              "game": item["game"], "team": item["pick"], "opponent": item["opponent"],
                              "locked_spread": item["locked_spread"], "ats_shadow_score_not_validated_probability": item["score"],
                              "confidence": item["confidence"], "governed_uncertainty": item["governed_uncertainty"] or "",
                              "shadow_uncertainty": item["shadow_uncertainty"],
                              "selected_edge_points_not_ev": item["edge_points"],
                              "actual_result": item["result"],
                              **{f"{method}_ordinal": rankings[6][method].index(item)+1 for method in methods if method != "governed"}})
    write_csv(OUTPUT / "week6_ats_58_reconstructed.csv", reconstructed)
    ranking_results = {}
    top_rows = []
    for method in methods:
        ranked_by_week = [rankings[week][method] for week in (5, 6)]
        bands = {}
        for label, start, stop in (("1-5", 0, 5), ("6-10", 5, 10), ("11-20", 10, 20), ("remaining", 20, None)):
            bands[label] = record([r for ranked in ranked_by_week for r in ranked[start:stop]])
        ranking_results[method] = {"weeks": 2, "selections": 114, "bands": bands,
                                   "top5_by_week": {str(week): record(rankings[week][method][:5]) for week in (5, 6)}}
        for week in (5, 6):
            for ordinal, row in enumerate(rankings[week][method][:5], 1):
                top_rows.append({"method": method, "week": week, "ordinal": ordinal,
                                 "game": row["game"], "pick": row["pick"], "spread": row["locked_spread"],
                                 "shadow_score": row["score"], "confidence": row["confidence"],
                                 "edge_points": row["edge_points"], "result": row["result"]})
    write_csv(OUTPUT / "ats_counterfactual_top5_in_sample.csv", top_rows)
    total_bands = {}
    for label, start, stop in (("1-5", 0, 5), ("6-10", 5, 10), ("11-20", 10, 20), ("remaining", 20, None)):
        total_bands[label] = record([r for week in (5, 6)
                                      for r in sorted(by_week[week][1], key=lambda x: (-x["score"], x["game_id"]))[start:stop]])
    distributions = {}
    for market, rows in (("ATS", by_week[6][0]), ("TOTAL", by_week[6][1])):
        values = [r["score"] for r in rows]
        distributions[market] = {label: quantile(values, q) for label, q in
                                 (("min", 0), ("p10", .1), ("p25", .25), ("median", .5),
                                  ("p75", .75), ("p90", .9), ("max", 1))}
    diagnostics = {
        "scope": "RESEARCH_ONLY_IN_SAMPLE_NOT_VALIDATION",
        "weeks_included": [5, 6],
        "weeks_excluded": {"1": "archived audit is not an independently sealed full pregame candidate ledger",
                           "2": "audit lacks full frozen per-candidate edge/score/probability ledger",
                           "3": "provisional card has kickoff-passed skips and incomplete frozen grading join",
                           "4": "no complete frozen pregame candidate ledger"},
        "ats": {"n": len(all_ats), "ranking": ranking_results,
                "calibration_all": calibration(all_ats),
                "calibration_by_week": {str(w): calibration(by_week[w][0]) for w in (5, 6)}},
        "totals": {"n": len(all_totals), "score_rank_bands": total_bands,
                   "calibration_all": calibration(all_totals),
                   "neutral_half_shrink_posthoc_diagnostic": calibration(
                       [{**row, "score": .5 + .5*(row["score"]-.5)} for row in all_totals]),
                   "calibration_by_week": {str(w): calibration(by_week[w][1]) for w in (5, 6)},
                   "top5_by_week": {str(w): record(sorted(by_week[w][1], key=lambda x: -x["score"])[:5]) for w in (5, 6)}},
        "week6_score_distribution": distributions,
        "week6_totals_above_best_ats": sum(r["score"] > distributions["ATS"]["max"] for r in by_week[6][1]),
        "random_baseline_expected_wins_per_week": {str(w): {market: 5*sum(r["result"] == "WIN" for r in rows)/len(rows)
                                                                for market, rows in (("ATS", by_week[w][0]), ("TOTAL", by_week[w][1]))}
                                                   for w in (5, 6)},
        "fixed_rule_replay": replay_summary(by_week, rankings),
        "walk_forward_calibration": "NOT_ESTIMABLE: only two complete frozen dual-market weeks; no prior training period for Week 5, and one prior week is insufficient for a credible Week 6 fit",
    }
    (OUTPUT / "diagnostics.json").write_text(json.dumps(diagnostics, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"ats": len(all_ats), "totals": len(all_totals),
                      "w6_totals_above_ats": diagnostics["week6_totals_above_best_ats"],
                      "w6_top5": {m: ranking_results[m]["top5_by_week"]["6"] for m in methods}}, indent=2))


if __name__ == "__main__":
    main()
