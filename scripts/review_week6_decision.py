"""Revise only the frozen Week 6 human review and score-scale reporting.

This script reads sealed pre-kickoff evidence. It never opens the execution DB,
reruns a model, captures a provider, or changes a selection in the 116-row pool.
"""

from __future__ import annotations

import csv
import hashlib
import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/2026-week6-execution-20261006T2133Z"
CHECKSUMS = OUT / "week6_artifact_checksums.json"
LOCK_SHA = "f2723f75d94c2c3e4edaadf618cbb71866f3cf2d8b59c62fe48ab84bad6c2c75"
SCALE_LABEL = "SHADOW SCORE ORDERING WITH CROSS-MARKET SCALE LIMITATION"
REVIEW_LABEL = "WEEK 6 DECISION SHORTLIST — ADVERSARIAL HUMAN REVIEW"
MIXED_LABEL = "MIXED-MARKET SHADOW TOP 5 — SCALE-LIMITED RESEARCH ORDERING"
EDITABLE = {
    "week6_decision_shortlist.csv",
    "week6_execution_report.md",
    "week6_cross_market_scale_diagnostic.json",
}
FROZEN_HASHES = {
    "week6_ats_full_card.csv": "24cafb1c900a6906d29f7c71728aa529cfdc98103ccc2aba41344823735e2a34",
    "week6_totals_full_card.csv": "4cec853791cbf7946d45473bacfac5b44df486f53fc200d2678cbd3d67712e29",
    "week6_combined_candidate_pool.csv": "73b8ad05d1efa10dc2ea870d7ad7342fda41355d48e425ea0ae22dfc77530111",
    "week6_official_ats_top5.csv": "e1c7743e075a4b39adad27f44b11eba17464d366692e80ec6fffea99c9e7255f",
    "week6_mixed_market_shadow_top5.csv": "e1f03be16f8759da4613a9cb0fe83ca0b5d201b6ae991124d3a4f2a16b9d9ccb",
    "week6_locked_line_snapshot.json": "e724966c31211770dff61901195ec3ed36c18d57cc166757553c66b5bf092450",
    "week6_card_manifest.json": "428d3ea4ab31a7ef9180c7c9798d69fd414520fd5d48ae1cba9b71427e4d2ce6",
    "week6_model_manifest.json": "03dee2bd4cdf1fd90947010b6c599ca2c1f1738af2776989b3aa5b676ab7dccc",
    "week6_ingestion_manifest.json": "5afead896dc731f7c251a34ad94a9442d0a2cf84feed98ad40809919df348595",
}

# Deliberate owner-review options, chosen from the frozen analytical shortlists.
# These notes are qualitative review judgments, not a scoring formula or policy.
REVIEW = (
    ("ATS", "401856718",
     "Four prior FBS games per team and no prior 35-point blowout make this large raw ATS edge less sample-fragile than the higher-scoring Ball State and Massachusetts ATS options. The locked Vanderbilt +10.5 is half a point better than the captured current +10.0. Week 5 ATS was 34-22. This ATS review option displaces higher-scoring totals because their uncalibrated normal scores cannot be compared as validated probabilities with ATS scores.",
     "Ole Miss offense exceeds the unadjusted margin forecast; QB and injury status remain unverified, and Vanderbilt has prior FCS exposure."),
    ("TOTAL", "401856824",
     "The frozen projection is 9.74 points below the locked 53.5, and the lock is one point better for the Under than the captured 52.5. It survives review despite Week 5 shadow totals at 23-33, unvalidated normal probability, 16.73-point uncertainty, and unverified QB starts because both the raw gap and observed lock advantage are explicit in the pre-kickoff evidence; it remains a shadow review option only.",
     "Offensive pace or unverified QB/injury conditions defeat the Under; one team has only three prior FBS games and both have prior blowout exposure."),
    ("TOTAL", "401862795",
     "The frozen projection is 9.51 points above the locked 47.5, and the lock is one point better for the Over than the captured 48.5. It survives review despite Week 5 shadow totals at 23-33, unvalidated normal probability, 16.73-point uncertainty, and unverified QB starts because the raw gap and observed lock advantage are recorded separately; no production eligibility is inferred.",
     "Army pace or unverified QB/injury conditions suppress scoring; one team has only three prior FBS games and there is prior FCS/blowout exposure."),
    ("TOTAL", "401860902",
     "The locked Under 55.5 is two points better than the captured 53.5 and both teams have four prior FBS games. This market evidence gives it a distinct review case despite a lower stored score than the mixed Top 5. Week 5 shadow totals were 23-33; the normal score is unvalidated, uncertainty is 16.73 points, and QB starts are unverified, so this is only an owner review option.",
     "The projected 5.76-point Under gap is smaller than the model's uncertainty; unverified QB/injury conditions and prior FCS/blowout exposure could erase it."),
    ("ATS", "401858257",
     "Five prior FBS games per team and no prior FCS exposure provide a more inspectable ATS sample than several higher-scoring ATS options. The frozen raw edge is 12.30 points. Week 5 ATS was 34-22. This ATS review option displaces higher-scoring totals because their uncalibrated normal scores have no validated common scale with ATS; the captured market is one point better than the lock, which limits the case.",
     "The 37.5-point spread is exposed to blowout-tail error, both teams have prior 35-point blowouts, QB/injury status is unverified, and current market movement is against the lock."),
)


def read_csv(name: str) -> list[dict[str, str]]:
    with (OUT / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def sha(name: str) -> str:
    return hashlib.sha256((OUT / name).read_bytes()).hexdigest()


def verify_custody() -> dict:
    sealed = json.loads(CHECKSUMS.read_text(encoding="utf-8"))
    for name, expected in sealed["files"].items():
        if sha(name) != expected:
            raise ValueError(f"sealed Week 6 artifact changed before review: {name}")
    for name, expected in FROZEN_HASHES.items():
        if sealed["files"].get(name) != expected:
            raise ValueError(f"frozen Week 6 execution checksum changed: {name}")
    locked = json.loads((OUT / "week6_locked_line_snapshot.json").read_text())
    card = json.loads((OUT / "week6_card_manifest.json").read_text())
    model = json.loads((OUT / "week6_model_manifest.json").read_text())
    ingestion = json.loads((OUT / "week6_ingestion_manifest.json").read_text())
    hashes = (locked["locked_line_snapshot_sha256"], card["ats_card"]["locked_line_snapshot_sha256"],
              card["totals_card"]["locked_line_snapshot_sha256"], model["locked_line_snapshot_sha256"],
              ingestion["lock_snapshot_sha256"])
    if set(hashes) != {LOCK_SHA}:
        raise ValueError("committed locked-line domain snapshot SHA is inconsistent")
    return sealed


def score_diagnostic(pool: list[dict[str, str]]) -> dict:
    grouped = {kind: [float(row["candidate_score"]) for row in pool if row["market_type"] == kind]
               for kind in ("ATS", "TOTAL")}
    if len(pool) != 116 or any(len(grouped[kind]) != 58 for kind in grouped):
        raise ValueError("frozen 58 + 58 market pool is incomplete")
    return {
        "source": "sealed week6_combined_candidate_pool.csv",
        "source_sha256": FROZEN_HASHES["week6_combined_candidate_pool.csv"],
        "locked_line_domain_snapshot_sha256": LOCK_SHA,
        "score_interpretation": SCALE_LABEL,
        "cross_market_common_scale_validated": False,
        "ats_policy_maximum_selected_probability": 0.60,
        "total_score_method": "UNCALIBRATED_NORMAL_SHADOW",
        "markets": {kind: {"count": len(values), "minimum": min(values),
                           "median": statistics.median(values), "maximum": max(values)}
                    for kind, values in grouped.items()},
        "total_candidates_above_best_ats_score": sum(
            value > max(grouped["ATS"]) for value in grouped["TOTAL"]),
    }


def decision_rows(pool: list[dict[str, str]]) -> list[dict[str, str | int]]:
    by_key = {(row["market_type"], row["game_id"]): row for row in pool}
    context = {row["game_id"]: row for row in read_csv("week6_context_status.csv")}
    weather = {row["game_id"]: row for row in read_csv("week6_market_weather_review.csv")}
    analytical = {(row["market_type"], row["game_id"])
                  for name in ("week6_analytical_ats_shortlist.csv", "week6_analytical_totals_shortlist.csv")
                  for row in read_csv(name)}
    rows = []
    for rank, (kind, game_id, reason, failure) in enumerate(REVIEW, 1):
        key = (kind, game_id)
        if key not in by_key or key not in analytical:
            raise ValueError(f"review option absent from frozen analytical pool: {key}")
        source, ctx, forecast = by_key[key], context[game_id], weather[game_id]
        current = source["current_market_line"]
        rows.append({
            "decision_rank": rank, "review_label": REVIEW_LABEL,
            **source,
            "projection_basis": "projected home margin" if kind == "ATS" else "projected game total",
            "market_specific_confidence": source["confidence"],
            "current_market_comparison": (
                f"captured current home spread {current}; selected lock advantage {source['lock_advantage']} points"
                if kind == "ATS" else
                f"captured current total {current}; selected lock advantage {source['lock_advantage']} points"),
            "qb_evidence": "Week 6 starter unverified; passing leader is not a starter confirmation",
            "injury_evidence": "ESPN injury feed incomplete; absence of record does not establish health",
            "weather_evidence": (f"{source['weather_status']}; wind {forecast['wind_mph']} mph; "
                                 f"precipitation {forecast['precip_probability_pct']}%"),
            "sample_quality_warning": (
                f"FBS samples away/home {ctx['away_fbs_games_before_week6']}/"
                f"{ctx['home_fbs_games_before_week6']}; {source['structural_warning']}"),
            "cross_market_score_limitation": SCALE_LABEL,
            "why_survived_human_review": reason,
            "primary_failure_mode": failure,
            "review_status": "HUMAN_REVIEW_OPTION_NOT_SPORTSBOOK_RECOMMENDATION",
        })
    if len(rows) != 5 or len({(row["market_type"], row["game_id"]) for row in rows}) != 5:
        raise ValueError("decision shortlist must have five distinct market/game options")
    return rows


def write_review_outputs(*, update_checksums: bool = True) -> None:
    sealed = verify_custody() if CHECKSUMS.exists() else None
    ats, totals = read_csv("week6_ats_full_card.csv"), read_csv("week6_totals_full_card.csv")
    pool = read_csv("week6_combined_candidate_pool.csv")
    official, mixed = read_csv("week6_official_ats_top5.csv"), read_csv("week6_mixed_market_shadow_top5.csv")
    if len(ats) != 58 or len(totals) != 58 or len(official) != 5 or len(mixed) != 5:
        raise ValueError("frozen Week 6 execution coverage changed")
    diagnostic = score_diagnostic(pool)
    decisions = decision_rows(pool)
    with (OUT / "week6_decision_shortlist.csv").open("w", encoding="utf-8", newline="\n") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(decisions[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(decisions)
    (OUT / "week6_cross_market_scale_diagnostic.json").write_text(
        json.dumps(diagnostic, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    report = [
        "# Week 6 initial execution — local governed draft", "",
        "**WEEK 6 MARKET COVERAGE**", "", "Locked games: 58",
        "ATS candidates: 58; ATS skips: 0", "Totals candidates: 58; Totals skips: 0",
        "Combined market selections: 116", "",
        "## Custody and timing", "",
        f"Authoritative locked-line domain snapshot SHA-256: `{LOCK_SHA}`. This is the committed execution-v9 lock custody hash; the earlier execution-v8 timestamp-specific hash is not the card's hash. The SplashSports source remains the immutable grading and selection lock. Model generation preceded every reconciled kickoff; this review used only the sealed pregame files. The one-hour Hawai'i–Arizona State CFBD schedule discrepancy was corrected only in the isolated execution database using both teams' official 7:30 p.m. MST schedules; the raw provider capture was retained and the locked spread and total were unchanged.", "",
        "## OFFICIAL GOVERNED ATS TOP 5", "",
        "The 58 governed ATS Confidence values are all 1. This Top 5 is deterministic policy order, not a strength ranking.", "",
    ]
    report.extend(f"- {i}. {row['pick']} {row['pick_spread']} — {row['away']} at {row['home']}"
                  for i, row in enumerate(official, 1))
    report.extend(["", f"## {MIXED_LABEL}", "",
        f"{SCALE_LABEL}. Research only; unchanged 0 ATS / 5 TOTAL composition. Stored scores order the 116 frozen candidates, but they are not validated cross-market probabilities or overall confidence. ATS policy caps selected probability at 0.60; TOTAL scores use UNCALIBRATED_NORMAL_SHADOW. Week 5 ATS was 34-22 and shadow totals were 23-33.", ""])
    report.extend(f"- {row['combined_top5_rank']}. {row['away']} at {row['home']}: "
                  f"{row['selection']} {row['locked_line']} (stored score {float(row['candidate_score']):.4f})"
                  for row in mixed)
    a, t = diagnostic["markets"]["ATS"], diagnostic["markets"]["TOTAL"]
    report.extend(["", "## CROSS-MARKET SCORE SCALE DIAGNOSTIC", "",
        f"ATS {a['count']}: minimum {a['minimum']:.4f}, median {a['median']:.4f}, maximum {a['maximum']:.4f}.",
        f"TOTAL {t['count']}: minimum {t['minimum']:.4f}, median {t['median']:.4f}, maximum {t['maximum']:.4f}.",
        f"TOTAL scores above the best ATS score: {diagnostic['total_candidates_above_best_ats_score']}. This distribution reflects different, unvalidated market score scales, not evidence that 25 totals are stronger than every ATS side.", "",
        f"## {REVIEW_LABEL}", "",
        "Five separate qualitative owner-review options from the frozen analytical shortlists. This is neither the mixed score order nor a sportsbook recommendation; ranks are review order, not model strength.", ""])
    report.extend(f"- {row['decision_rank']}. {row['market_type']} {row['selection']} {row['locked_line']} — "
                  f"{row['away']} at {row['home']}; {row['why_survived_human_review']} "
                  f"Primary failure mode: {row['primary_failure_mode']}"
                  for row in decisions)
    report.extend(["", "## Context limitations", "",
        "ESPN displayed DraftKings spread and total for 57/58 games; the direct Odds API endpoint was unavailable. ESPN does not supply per-line observation timestamps, so retrieval time is the only freshness bound. These observations never replace SplashSports locks. Open-Meteo kickoff-hour forecasts were captured for 56 games; the other two are domes or have explicit status. QB starters remain unverified. The ESPN injury feed returned three team groups; absent records do not establish health. Weather and market observations are the frozen Oct 6 captures. No manual, coaching, travel, injury, or weather point adjustment, model change, or policy change was made.", ""])
    (OUT / "week6_execution_report.md").write_text("\n".join(report), encoding="utf-8", newline="\n")
    if update_checksums:
        if sealed is None:
            raise ValueError("cannot update a missing Week 6 artifact checksum manifest")
        for name in EDITABLE:
            sealed["files"][name] = sha(name)
        CHECKSUMS.write_text(json.dumps(sealed, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8", newline="\n")
        verify_custody()


if __name__ == "__main__":
    write_review_outputs()
