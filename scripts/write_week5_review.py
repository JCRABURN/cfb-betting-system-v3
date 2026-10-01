"""Publish a review-only Week 5 decision packet from frozen v4 and fresh context.

No model runs, locks, database rows, or official cards are changed here.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "outputs/2026-week5-execution-20260930-v4"
OUT = ROOT / "outputs/2026-week5-review-20261001"
OLD_WORKTREE = ROOT.parents[1] / "week5" / ROOT.name
OLD_HEAD = "417b77e7ffbc0ae8e8bda793a9ee3822a2ca8f79"
ATS_PRIOR = "Recorded Weeks 1-2: 42-50 ATS; Top 5: 3-7. Week 3 provisional Top 5: 1-4. No calibrated cover probability."
TOTALS_PRIOR = "2019-25 rolling-origin: 4,687 projections; 1,897-1,784-38 on archived opening totals; -1.62% ROI at -110; quote times unverified; raw P uncalibrated."


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, records: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signed(value: str | float) -> str:
    return f"{float(value):+g}"


# Human adjudication of the three v4 Top-5 lists. This is neither model policy nor a wager signal.
# Each case is assessed independently; a large raw edge never overrides the data-quality checks.
CASE_NOTES = [
    (401871049, "WKU @ New Mexico State ATS", "RETAIN_GOVERNED_ONLY", "Both teams used multiple QBs recently; Week 4 FCS/blowout effects and turnover swings contaminate a 12.7-point raw edge. No QB certainty or market confirmation."),
    (401862786, "North Texas @ Tulsa ATS", "DOWNGRADE", "Tulsa used Williams after Hayes, whose knee status remains unconfirmed. DraftKings shifted 3 points against the locked Tulsa side; its 1.4-point raw edge is overwhelmed by that diagnostic."),
    (401871050, "Liberty @ Delaware ATS", "CONDITIONAL_SHORTLIST", "Delaware Minicucci is probable; Liberty used Purdie and Vasko. Raw 7.4-point edge and +7.5 lock survive, but both teams had FCS opponents and large blowouts."),
    (401858245, "Pittsburgh @ Virginia Tech ATS", "DECISION_SHORTLIST", "Pitt Heintschel and VT Grunkemeyer probable; +3.5 lock is half a point better than current +3.0. Modest 4.5-point raw edge avoids oversized-edge trap."),
    (401858476, "Penn State @ Northwestern ATS", "DECISION_SHORTLIST", "Both QBs probable; Northwestern's six-point loss at Indiana supports competitiveness. Locked +2.5 is half a point worse than current +3.0."),
    (401856820, "Cincinnati @ Arizona ATS", "DECISION_SHORTLIST", "Both current quarterbacks are probable from official previews; +7.5 lock is 1 point better than current +6.5. Raw 3.8-point edge is modest and uncalibrated."),
    (401866434, "Ohio @ Kent State ATS", "DOWNGRADE", "Ohio's Vezza was reported injured earlier and Week 5 availability is unresolved. Kent's 57- and 56-point losses distort a four-game EPA sample; 7.1-point edge is fragile."),
    (401858247, "California @ UNLV ATS", "SECONDARY", "UNLV Arnold probable, Cal starter less verified; 3.0-point raw edge and unchanged spread survive, but the small edge has no calibration support."),
    (401869942, "Georgia Southern @ Coastal Carolina ATS", "DOWNGRADE", "Both QB statuses uncertain, both prior schedules include FCS opponents, and Coastal's Week 4 Liberty loss challenges the 8.4-point raw edge."),
    (401856710, "Auburn @ Tennessee total", "RESEARCH_SIGNAL", "Under has 9.9 raw points and no line erosion, but both offensive injuries remain unverified and Tennessee's explosive offense can invalidate the low projection."),
    (401858246, "Boston College @ SMU total", "REJECT", "Under 55.5 conflicts with SMU's explosive Jennings passing ceiling; its 464-yard Week 4 passing came against FCS Missouri State, so pace/opponent mix is uncertain."),
    (401858247, "California @ UNLV total", "REJECT", "The locked Under 52.5 is a full point worse than current 53.5; indoors, weather offers no scoring suppression and QB/injury status is incomplete."),
    (401862791, "Navy @ Air Force total", "WEAK_SIGNAL", "Over projection is 7.4 points high, but locked 46.5 is 1 point worse than current 45.5; service-academy run-game pace and low possessions threaten the Over."),
    (401858476, "Penn State @ Northwestern total", "WEAK_SIGNAL", "Both QBs probable and Northwestern passed effectively against Indiana; 13.6-mph wind and a historically losing totals model limit the Over case."),
    (401856707, "Alabama @ Mississippi State ATS", "DECISION_SHORTLIST", "Only >=7-point edge with no prior FCS opponent on either side. Both QBs probable, current +5.5 unchanged. Strong Alabama opponent and prior blowouts remain major hazards."),
]

ATS_CANDIDATES = [
    (401858245, "Pittsburgh", "Probable/probable QBs, favorable half-point lock, no material market move; directional edge survives."),
    (401856707, "Mississippi State", "No prior FCS opponents for either side; QBs probable and current line unchanged; a conditional large edge."),
    (401856820, "Cincinnati", "Probable/probable QBs and +7.5 locked versus +6.5 current; directional model support."),
    (401858476, "Northwestern", "Probable/probable QBs and a competitive road performance at Indiana; current +3 is better than lock."),
    (401871050, "Delaware", "Model near pick'em versus +7.5 lock, Delaware QB probable; Liberty QB and FCS/blowout mix keep it conditional."),
    (401858247, "UNLV", "Small 3.0-point edge and no line erosion; opponent QB/injury uncertainty keeps it below the decision five."),
    (401869942, "Coastal Carolina", "Raw 8.4-point edge remains a research case; dual QB uncertainty and FCS mix prevent elevation."),
]

DECISION_RISKS = {
    401858245: "Pitt's first road game at Virginia Tech and unverified line/defensive injuries could overwhelm a 4.5-point raw edge.",
    401856707: "Alabama can outperform an early-season EPA estimate; both sides' large prior margins and unverified injuries weaken the 7.3-point edge.",
    401856820: "Arizona's Fifita and home offense may justify the market; model ATS edge is only 3.8 points and uncalibrated.",
    401858476: "The locked +2.5 misses current +3 and Northwestern's 13.6-mph wind/Friday travel context may differ from model assumptions.",
    401871050: "Liberty's unresolved QB split and each team's FCS/blowout sample could make the 7.4-point edge spurious.",
}

TOTAL_CLASS = {
    401856710: ("RESEARCH SIGNAL", "Large 9.9-point raw Under edge, neutral market movement, light wind; Tennessee explosive-play ceiling and missing injuries remain open."),
    401858246: ("REJECT", "SMU's passing ceiling and 61% rain probability create opposing scripts; no injury validation for either offense."),
    401858247: ("REJECT", "Locked Under is 1 point worse than current and the indoor venue offers no weather support."),
    401862791: ("WEAK SIGNAL", "Light wind helps the Over, but service-academy pace can suppress possessions and the lock is 1 point worse than current."),
    401858476: ("WEAK SIGNAL", "Northwestern's recent passing output supports a higher total, but 13.6-mph wind and missing injuries remain."),
}


def source_checksums() -> dict[str, object]:
    files = sorted(path for path in V4.rglob("*") if path.is_file())
    entries = [{"path": path.relative_to(ROOT).as_posix(), "sha256": digest(path), "bytes": path.stat().st_size}
               for path in files]
    old_db = OLD_WORKTREE / "data/production_inputs/2026-week5-execution/execution-v4.db"
    if digest(ROOT / "data/cfb.db") != "09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842":
        raise ValueError("source database hash changed")
    expected_db_sha = "e5d00e33e68a7ed2f20160fdb62fd808bf735ac0ee9009b6e643cfb74f197baa"
    if old_db.is_file() and digest(old_db) != expected_db_sha:
        raise ValueError("archived execution database hash changed")
    if digest(V4 / "week5_execution_report.md") != "6ecfc40b5b88fd10e44a714ed2b023fdec2d96470bff111f854dd33041f15f16":
        raise ValueError("v4 report hash changed")
    return {"v4_pr_head": OLD_HEAD, "source_database_sha256": digest(ROOT / "data/cfb.db"),
            "archived_execution_database_path": Path(os.path.relpath(old_db, ROOT)).as_posix(),
            "archived_execution_database_sha256": expected_db_sha,
            "archived_execution_database_verified_locally": old_db.is_file(),
            "v4_files": entries, "file_count": len(entries),
            "locked_line_snapshot_sha256": "0e9705b44349587bb3d54ff7a22e6b0159a6fbd9a04fe1f7862759cc143543aa"}


def main() -> None:
    ats = {int(row["game_id"]): row for row in read_csv(V4 / "week5_ats_full_card.csv")}
    totals = {int(row["game_id"]): row for row in read_csv(V4 / "week5_totals_full_card.csv")}
    context = {int(row["game_id"]): row for row in read_csv(OUT / "week5_market_weather_review.csv")}
    qb = {int(row["game_id"]): row for row in read_csv(OUT / "week5_qb_injury_review.csv")}
    audit = read_csv(OUT / "week5_large_ats_edge_audit.csv")
    if len(ats) != len(totals) or len(ats) != len(context) or len(ats) != len(qb) or len(ats) != 56:
        raise ValueError("review coverage is not exactly 56 unique games")
    if len(audit) != 23:
        raise ValueError("large ATS edge review count changed")
    if any(row["confidence"] != "1" for row in ats.values()):
        raise ValueError("governed ATS confidence changed")
    custody = source_checksums()
    (OUT / "v4-custody-manifest.json").write_text(json.dumps(custody, indent=2) + "\n", encoding="utf-8")

    shortlist: list[dict[str, object]] = []
    for rank, (game_id, pick, why) in enumerate(ATS_CANDIDATES, start=1):
        a, m, q = ats[game_id], context[game_id], qb[game_id]
        if a["pick"] != pick:
            raise ValueError(f"expected pick differs: {game_id}")
        edge = abs(float(a["home_ats_edge"]))
        shortlist.append({
            "rank": rank, "game_id": game_id, "game": f"{a['away']} @ {a['home']}",
            "market": "ATS", "pick": pick, "locked_splash_line": a["pick_spread"],
            "model_projected_home_margin": round(float(a["projected_home_margin"]), 1),
            "raw_ats_edge_points": round(edge, 1),
            "current_dk_home_spread": m["current_dk_home_spread"],
            "selected_locked_advantage_points": m["ats_selected_locked_advantage"],
            "qb_status": f"{q['expected_away_qb']} ({q['away_qb_status']}); {q['expected_home_qb']} ({q['home_qb_status']})",
            "material_injuries": f"Away: {q['material_away_injuries']}; Home: {q['material_home_injuries']}",
            "weather_issue": f"{m['weather_status']}; wind {m['wind_mph'] or 'indoor'} mph; precip {m['precip_probability_pct'] or 'indoor'}%",
            "sample_quality_warning": ("FCS and/or blowout in Week 1-4 EPA aggregates; " if game_id in {401871050, 401869942} else "Week 1-4 EPA sample only; ") + "opponent mix not adjusted",
            "shadow_uncertainty_points": round(float(a["shadow_uncertainty_points"]), 3),
            "shadow_uncertainty_interpretation": "EFFECTIVELY_FLAT_NOT_USED_FOR_RANKING",
            "historical_model_evidence": ATS_PRIOR,
            "why_survives_review": why,
            "primary_reason_it_could_fail": DECISION_RISKS.get(game_id, "QB/injury uncertainty and early-season EPA noise."),
            "selection_status": "WEEK_5_DECISION_SHORTLIST" if rank <= 5 else "ANALYTICAL_ATS_SECONDARY",
        })
    write_csv(OUT / "week5_analytical_ats_shortlist.csv", shortlist)
    write_csv(OUT / "week5_decision_shortlist.csv", shortlist[:5])

    watchlist: list[dict[str, object]] = []
    for game_id in (401856710, 401858246, 401858247, 401862791, 401858476):
        t, m, q = totals[game_id], context[game_id], qb[game_id]
        classification, sanity = TOTAL_CLASS[game_id]
        watchlist.append({
            "game_id": game_id, "game": f"{t['away']} @ {t['home']}", "pick": t["pick"].upper(),
            "locked_total": t["locked_total"], "current_dk_total": m["current_dk_total"],
            "selected_locked_advantage_points": m["total_selected_locked_advantage"],
            "model_projected_total": round(float(t["projected_total"]), 1),
            "raw_edge_points": round(float(t["raw_point_edge"]), 1),
            "raw_uncalibrated_probability": round(float(t["raw_selected_probability"]), 3),
            "historical_model_status": TOTALS_PRIOR,
            "current_injuries": f"Away: {q['material_away_injuries']}; Home: {q['material_home_injuries']}",
            "weather": f"{m['weather_status']}; wind {m['wind_mph'] or 'indoor'} mph; precip {m['precip_probability_pct'] or 'indoor'}%",
            "pace_and_game_script_sanity_check": sanity,
            "classification": classification,
        })
    write_csv(OUT / "week5_shadow_totals_watchlist.csv", watchlist)

    adversarial = []
    for game_id, label, assessment, reason in CASE_NOTES:
        if game_id not in ats:
            raise ValueError(f"adversarial case unmatched: {label}")
        adversarial.append({"game_id": game_id, "case": label, "assessment": assessment, "reason": reason})
    write_csv(OUT / "week5_top5_adversarial_review.csv", adversarial)

    # Every large edge has a recorded, case-specific structural classification.
    large_adjudication = []
    for row in audit:
        gid = int(row["game_id"])
        fcs = int(row["away_fcs_games"]) + int(row["home_fcs_games"])
        max_blowout = max(int(row["away_max_prior_margin"]), int(row["home_max_prior_margin"]))
        if gid == 401856707:
            verdict = "CONDITIONAL_BEST_RELATIVE_SAMPLE"
            reason = "No FCS opponents; both QBs probable, but prior 38/49-point margins and Alabama opponent strength remain; no calibrated edge."
        elif gid == 401871050:
            verdict = "CONDITIONAL_WITH_QB_AND_FCS_RISK"
            reason = "Delaware QB probable; Liberty two-QB role unresolved; one FCS game each and large prior margins."
        elif gid == 401871049:
            verdict = "HIGHLY_FRAGILE_QB_AND_SAMPLE"
            reason = "Both QB rooms rotated after Week 4; one FCS game each and 50/37-point prior margins; NM State turnover swing."
        elif gid == 401866434:
            verdict = "HIGHLY_FRAGILE_INJURY_AND_BLOWOUT"
            reason = "Ohio QB injury unresolved; Kent State lost by 57 and 56 points and both teams played FCS opponents."
        elif gid == 401869942:
            verdict = "FRAGILE_QB_AND_FCS_MIX"
            reason = "Both QBs uncertain, both prior schedules include FCS; Coastal's Liberty loss challenges the raw margin."
        else:
            verdict = "FRAGILE_UNVERIFIED_CONTEXT" if fcs or max_blowout >= 35 else "CONDITIONAL_UNVERIFIED_CONTEXT"
            reason = f"{fcs} combined prior FCS games; largest prior final margin {max_blowout}; QB status {row['qb_change_status']}. Opponent strength, garbage-time filtering and turnover effects remain unverified."
        large_adjudication.append({**row, "structural_credibility": verdict, "human_review_reason": reason})
    write_csv(OUT / "week5_large_ats_edge_adjudication.csv", large_adjudication)

    # Concise reviewer-facing output; detailed columns and source URLs are in adjacent CSVs.
    lines = [
        "# WEEK 5 FINAL REVIEW — DECISION PACKET",
        "",
        f"Generated {datetime.now(timezone.utc).isoformat()} from immutable v4 artifacts and October 1 review captures.",
        "Review-only analysis. No official policy ranking, model change, numeric adjustment, sportsbook recommendation, or wager.",
        "",
        "## Data and custody",
        "",
        "56/56 immutable SplashSports spread/total locks, 56/56 ATS picks, 56/56 shadow totals, 56/56 market/QB/weather review rows. No lock changed; see `v4-custody-manifest.json` for every v4 SHA-256 and the archived execution DB hash.",
        "The refreshed ESPN injury feed contains only three stale team groups (2020/2022), so 2026 material injuries remain UNVERIFIED for almost all teams. ESPN passing leaders are candidate QBs, never confirmed Week 5 starters. Official team previews refine several to PROBABLE, not CONFIRMED. No numeric manual adjustment was justified.",
        "DraftKings matched 56 games; two spreads moved at least 1.5, no totals moved at least 2.5. Outdoor weather was refreshed for 54 games; two are domes. Market observations are diagnostic and do not replace locks.",
        "",
        "## DETERMINISTIC POLICY TOP 5 — NOT STRENGTH RANKED",
        "",
        "All 56 governed ATS picks have Confidence 1. Rank is lock-ID tiebreak, not estimated reliability.",
        "",
        "| Governed rank | Game | Pick | Raw edge | Current DK home spread | Review |",
        "| --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in sorted((r for r in ats.values() if r["top_five"] == "True"), key=lambda r: -int(r["rank"])):
        gid = int(row["game_id"])
        note = next(item for item in adversarial if item["game_id"] == gid and item["case"].endswith("ATS"))
        lines.append(f"| {row['rank']} | {row['away']} @ {row['home']} | {row['pick']} {signed(row['pick_spread'])} | {abs(float(row['home_ats_edge'])):.1f} | {signed(context[gid]['current_dk_home_spread'])} | {note['assessment']} |")
    lines += ["", "## Analytical ATS shortlist", "",
              "This is an evidence-ordered review list, not an official rank or calibrated probability. Shadow uncertainty is effectively flat (about 18.282-18.304 points) and was not used to order candidates.", "",
              "| Review order | Game | Pick | Edge | Locked advantage vs DK | QB evidence | Key concern |",
              "| --- | --- | --- | ---: | ---: | --- | --- |"]
    for row in shortlist:
        lines.append(f"| {row['rank']} | {row['game']} | {row['pick']} {signed(row['locked_splash_line'])} | {row['raw_ats_edge_points']} | {signed(row['selected_locked_advantage_points'])} | {row['qb_status']} | {row['primary_reason_it_could_fail']} |")
    lines += ["", "## Shadow totals watchlist", "",
              "Raw probabilities below are uncalibrated and are not bet probabilities. Historical totals ROI is negative; no total enters the decision five.", "",
              "| Game | Pick | Lock / DK | Projection | Raw edge | Raw P | Classification |",
              "| --- | --- | --- | ---: | ---: | ---: | --- |"]
    for row in watchlist:
        lines.append(f"| {row['game']} | {row['pick']} | {row['locked_total']} / {row['current_dk_total']} | {row['model_projected_total']} | {row['raw_edge_points']} | {row['raw_uncalibrated_probability']} | {row['classification']} |")
    lines += ["", "## WEEK 5 DECISION SHORTLIST", "",
              "Five ATS contest options for human evaluation, one per game. This table is not an official model ranking and does not imply a profitable wager.", "",
              "| Rank | Game | Market / pick / lock | Model home margin | Raw edge | DK home / lock advantage | QB status | Injuries / weather | Why it survives | Main failure mode |",
              "| --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- |"]
    for row in shortlist[:5]:
        lines.append(f"| {row['rank']} | {row['game']} | {row['market']} {row['pick']} {signed(row['locked_splash_line'])} | {signed(row['model_projected_home_margin'])} | {row['raw_ats_edge_points']} | {signed(row['current_dk_home_spread'])} / {signed(row['selected_locked_advantage_points'])} | {row['qb_status']} | Injuries UNVERIFIED; {row['weather_issue']} | {row['why_survives_review']} | {row['primary_reason_it_could_fail']} |")
    lines += ["", "## Large-edge and adversarial review", "",
              "All 23 ATS games with absolute raw edge >=7 are classified in `week5_large_ats_edge_adjudication.csv`. The review records game counts, FCS exposure, blowouts, play counts, QB evidence, and unverified opponent strength, garbage-time and turnover effects. Only Alabama @ Mississippi State has no prior FCS opponent on either side. This does not validate any raw edge.",
              "The 15 original governed/shadow Top-5 entries are assessed independently in `week5_top5_adversarial_review.csv`. Tulsa's adverse three-point market move and QB uncertainty are particularly material; the governed card itself is unchanged.",
              "", "## Five biggest risks", "",
              "1. All governed ATS Confidence values are 1, and the tie-ordered Top 5 has no reliability meaning.",
              "2. Injury coverage is unusable for 2026; most QB starters and position-group injuries remain unverified.",
              "3. Week 4 EPA aggregates may include FCS opponents and blowouts, and do not control opponent strength.",
              "4. ATS recent local cards and Top 5 underperformed; large raw edges are not calibrated probabilities.",
              "5. Shadow totals lost 1.62% out of sample with incomplete opening-quote custody; market/forecast context can move before kickoff.",
              "", "## Changes, verification and PR boundary", "",
              "Objective: make the Week 5 review decision-ready without changing v4, immutable contest locks, model coefficients or policy. New files: context capture/build/review scripts, source evidence, 56-game QB/injury and market/weather tables, 23-game edge audit, 15-case adversarial review, ATS/totals/decision shortlists, custody manifest, and focused tests. No existing v4 file or source DB row changed; no schema change or migration applied during remediation; no unrelated files changed.",
              "Data-quality checks: 56/56 normalized locks, ATS picks, totals projections, market matches and context rows; duplicate/missing game IDs 0; governed Confidence 1 for all; five governed Top-5 rows; v4 fallbacks 0; 54 outdoor forecasts plus two domes; two material spread moves, zero material total moves; 23 large edges classified; 15 original Top-5 cases attacked. Injury completeness is the major known limitation.",
              "Executed in this Windows worktree: `C:/Users/jraburn/Documents/GitHub/cfb-betting-system-v3/.venv/Scripts/python.exe -m pytest -q` (591 passed, 39 existing deprecation warnings); `... -m pytest -q tests/test_week5_review.py tests/test_week5_execution.py` (11 passed); `git diff --check` (passed). The updated artifact-only review code was rerun after the full suite, then the focused 11 tests passed again.",
              "Dependency chain: main -> draft PR #30 (`codex/week5-totals-dependency`, research schema/migrations 21-22) -> draft PR #29 (`codex/2026-week5-execution`, Week 5 code/evidence only). Migration 21 supplies the shadow contest entities; migration 22 is research audit infrastructure and not required to select the five Week 5 options. Migration 23 and the unapproved ATS publication gate are absent. Both PRs require review before merge; neither is merged.",
              "The old v4 head is retained at `codex/2026-week5-v4-preserved`. Rollback: reset PR #29 to archived v4 head or close it; discard this review-only layer and retain the archived v4 DB. No deployment, cloud publication, secret rotation, or wager occurred.",
              ""]
    (OUT / "week5_final_review.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"v4_files_hashed": custody["file_count"], "decision_selections": 5,
                      "totals_watchlist": len(watchlist), "top5_adversarial_cases": len(adversarial),
                      "large_edges_adjudicated": len(large_adjudication)}))


if __name__ == "__main__":
    main()
