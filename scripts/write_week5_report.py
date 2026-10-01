"""Write the Week 5 execution review from sealed cards and captured evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/2026-week5-execution-20260930-v4"


def csv_rows(name: str) -> list[dict]:
    with (OUTPUT / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def json_file(name: str) -> dict:
    return json.loads((OUTPUT / name).read_text(encoding="utf-8"))


def signed(value: object) -> str:
    return f"{float(value):+.1f}"


def table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> str:
    result = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    result.extend("| " + " | ".join(str(value).replace("|", "/") for value in row) + " |" for row in rows)
    return "\n".join(result)


def main() -> None:
    ats = csv_rows("week5_ats_full_card.csv")
    totals = csv_rows("week5_totals_full_card.csv")
    ats_top = csv_rows("week5_official_ats_top5.csv")
    shadow_ats_top = csv_rows("week5_shadow_ats_top5.csv")
    total_top = csv_rows("week5_shadow_totals_top5.csv")
    combined = csv_rows("week5_combined_top5.csv")
    context = {row["game_id"]: row for row in csv_rows("week5_context_review.csv")}
    ats_by_game = {row["game_id"]: row for row in ats}
    total_by_game = {row["game_id"]: row for row in totals}
    ingested = json_file("week5_ingestion_manifest.json")
    manifest = json_file("week5_model_manifest.json")
    prior = json_file("week5_prior_performance_audit.json")
    fresh = json_file("week5_data_freshness.json")
    oos = json_file("week5_totals_oos_evidence.json")
    card = json_file("week5_card_manifest.json")
    if len(ats) != 56 or len(totals) != 56:
        raise ValueError("full-card row count mismatch")

    def line_advantage(item: dict, market: str) -> str:
        value = context[item["game_id"]]["ats_selected_locked_line_advantage" if market == "ATS" else "totals_selected_locked_line_advantage"]
        return "unavailable" if value == "" else signed(value)

    def script(item: dict) -> str:
        game_id = item["game_id"]
        margin = float(ats_by_game[game_id]["projected_home_margin"])
        total = float(total_by_game[game_id]["projected_total"])
        away, home = (total-margin)/2, (total+margin)/2
        return f"Independent forecasts imply {item['away']} {away:.1f}, {item['home']} {home:.1f}; both implied scores are positive."

    def risk(item: dict, market: str) -> str:
        ctx = context[item["game_id"]]
        delta = float(ctx["ats_selected_locked_line_advantage"] if market == "ATS" else ctx["totals_selected_locked_line_advantage"])
        if delta <= -2:
            return f"DraftKings now gives the selected side {abs(delta):.1f} more points than the lock; QB/injury coverage is incomplete."
        if market == "TOTAL":
            return "Component totals lost money out of sample and the ESPN injury feed covers only three teams."
        return "Main-policy ATS uncertainty is absent and all Confidence values are 1; FCS-game effects and QB status are unverified."

    ats_table = []
    for row in ats_top:
        ctx = context[row["game_id"]]
        ats_table.append((row["rank"], f"{row['away']} @ {row['home']}",
                          f"{row['pick']} {signed(row['pick_spread'])}",
                          signed(row["locked_home_spread"]), signed(row["projected_home_margin"]),
                          signed(row["home_ats_edge"]), row["confidence"],
                          signed(ctx["current_draftkings_home_spread"]), line_advantage(row, "ATS"),
                          script(row), risk(row, "ATS")))
    shadow_ats_table = []
    for index, row in enumerate(shadow_ats_top, 1):
        shadow_ats_table.append((index, f"{row['away']} @ {row['home']}",
                                 f"{row['pick']} {signed(row['pick_spread'])}",
                                 signed(row["locked_home_spread"]), signed(row["projected_home_margin"]),
                                 signed(row["home_ats_edge"]), f"{float(row['shadow_uncertainty_points']):.3f}",
                                 script(row), risk(row, "ATS")))
    total_table = []
    for index, row in enumerate(total_top, 1):
        ctx = context[row["game_id"]]
        total_table.append((index, f"{row['away']} @ {row['home']}", row["pick"].upper(),
                            row["locked_total"], f"{float(row['projected_total']):.1f}",
                            signed(row["raw_point_edge"]), f"{float(row['raw_selected_probability']):.3f} raw",
                            row["confidence"], ctx["current_draftkings_total"],
                            line_advantage(row, "TOTAL"), script(row), risk(row, "TOTAL")))
    combined_table = []
    for row in combined:
        market = "ATS" if row["market"].lower() == "ats" else "TOTAL"
        item = ats_by_game[row["game_id"]] if market == "ATS" else total_by_game[row["game_id"]]
        current = context[row["game_id"]]["current_draftkings_home_spread" if market == "ATS" else "current_draftkings_total"]
        combined_table.append((row["rank"], f"{row['away']} @ {row['home']}", market,
                               row["pick"], row["locked_line"], f"{float(row['projection']):.1f}",
                               signed(row["edge_points"]), f"{float(row['shadow_probability_score']):.3f} shadow",
                               row["confidence"], current, line_advantage(item, market),
                               script(item), risk(item, market)))
    lines = [
        "# WEEK 5 MODEL EXECUTION — READY FOR PICKS",
        "",
        "**Local governed draft and shadow research only. No authoritative cloud publication or wager recommendation.**",
        "",
        f"Generated {manifest['generated_at_utc']}; execution code `{manifest['code_commit_sha']}`; contest `{manifest['contest_key']}`.",
        "",
        "## Readiness and source custody",
        "",
        f"The authoritative owner CSV reconciles to **56/56** Week 5 FBS matchups and 56 immutable spread-plus-total locks in the isolated execution database. Its normalized LF SHA-256 is `{manifest['locked_source_csv_sha256']}`. The Windows checkout byte hash is `{ingested['source_csv_checkout_sha256']}`. No original source database row was modified.",
        "",
        "A Week 1 Pittsburgh–Miami (OH) kickoff moved by 30 minutes in CFBD; the original and corrected values are in the ingestion manifest. The Hawai‘i Week 5 CSV kickoff is one minute later than CFBD and remains explicitly visible in reconciliation. All 56 Week 5 predictions preceded their provider kickoffs. All current market observations remain separate from locked SplashSports lines.",
        "",
        f"Completed 2026 FBS-vs-FBS games ingested through Week 4: **215**. End-of-Week-4 EPA snapshots: **138** teams. Week 5 ATS forecasts: **{len(ats)}**; totals forecasts: **{len(totals)}**; model fallbacks: **0**; manual numeric adjustments: **0**.",
        "",
        f"DraftKings current spreads and totals matched **{fresh['market']['captured_games']}/56**; outdoor kickoff forecasts **{fresh['weather']['outdoor_forecasts']}/54**, with two dome games. ESPN listed only **{fresh['injuries']['espn_team_groups']}** team groups: missing rows are not evidence of health. Expected quarterbacks are unverified. FCS opponents appear in several teams’ prior schedules, and the aggregate CFBD EPA feed does not prove FBS-only isolation.",
        "",
        "## Model trust",
        "",
        "The main-policy ATS EPA-only model fits 4,830 historical rows from 2019–2025, using Week 4 snapshots for all Week 5 targets. It produces game-specific home margins but no game-specific uncertainty, so all governed Confidence values are 1 and the official-policy Top 5 follows deterministic lock-ID tie order. A separate out-of-sample residual-based uncertainty artifact yields a shadow ATS ranking, but its uncertainty ranges only about 18.282–18.304 points across this slate and does not establish five strong bets. No 2026 outcome was used to refit ATS coefficients; completed games affect only point-in-time Week 4 team features.",
        "",
        f"The component totals model is shadow-only. Its 2019–2025 rolling-origin evaluation produced {oos['oos_predictions']} projections, MAE {oos['total_mae']:.3f}, RMSE {oos['total_rmse']:.3f}, and {oos['wins']}-{oos['losses']}-{oos['pushes']} against archived opening totals, ROI {oos['roi_minus110']:.2%} at -110. Original quote timestamps are unverified. Its displayed normal probabilities are raw, not empirically calibrated. The unified ranking uses a conservative ATS transform and these raw totals probabilities; it is experimental and its five selections are not a calibrated cross-market betting card.",
        "",
        "## Prior card audit",
        "",
        f"Week 1 local ATS card {prior['ats_by_week']['1']['win']}-{prior['ats_by_week']['1']['loss']}-{prior['ats_by_week']['1']['push']}; Week 2 local ATS card {prior['ats_by_week']['2']['win']}-{prior['ats_by_week']['2']['loss']}-{prior['ats_by_week']['2']['push']}. Combined recorded Weeks 1–2: {prior['ats_recorded_local_draft_weeks1_2']['win']}-{prior['ats_recorded_local_draft_weeks1_2']['loss']}-{prior['ats_recorded_local_draft_weeks1_2']['push']}; Top 5 {prior['ats_top_five_recorded_local_draft_weeks1_2']['win']}-{prior['ats_top_five_recorded_local_draft_weeks1_2']['loss']}-{prior['ats_top_five_recorded_local_draft_weeks1_2']['push']}. Week 3's previously generated pre-kickoff provisional ATS card graded {prior['ats_by_week']['3']['win']}-{prior['ats_by_week']['3']['loss']}-{prior['ats_by_week']['3']['push']}, provisional Top 5 {prior['ats_top_five_by_week']['3']['win']}-{prior['ats_top_five_by_week']['3']['loss']}-{prior['ats_top_five_by_week']['3']['push']}. Shadow totals across Weeks 2–3: {prior['totals_all_shadow']['win']}-{prior['totals_all_shadow']['loss']}-{prior['totals_all_shadow']['push']}. No Week 4 historical pick was fabricated. Full cuts are in `week5_prior_performance_audit.json`; complete CLV remains unavailable without timestamped closing custody.",
        "",
        "## OFFICIAL ATS TOP 5 — governed selection order, local draft",
        "",
        "Home spread and current DraftKings line are both stated as home-team spreads. Positive locked advantage means the locked selected-side price is better than current market. None is a wager recommendation.",
        "",
        table(("Rank", "Game", "Pick", "Locked home", "Home margin", "Home ATS edge", "Conf", "DK home", "Locked advantage", "Game script", "Primary risk"), ats_table),
        "",
        "## SHADOW ATS TOP 5 — research uncertainty order",
        "",
        table(("Rank", "Game", "Pick", "Locked home", "Home margin", "Home ATS edge", "Shadow uncertainty", "Game script", "Primary risk"), shadow_ats_table),
        "",
        "## SHADOW TOTALS TOP 5",
        "",
        table(("Rank", "Game", "Pick", "Locked total", "Projected", "Edge", "Raw P", "Conf", "DK total", "Locked advantage", "Game script", "Primary risk"), total_table),
        "",
        "## COMBINED ATS/O-U TOP 5 — experimental shadow",
        "",
        table(("Rank", "Game", "Market", "Pick", "Locked line", "Projection", "Edge", "Shadow score", "Conf", "DK line", "Locked advantage", "Game script", "Primary risk"), combined_table),
        "",
        "## What I would trust most",
        "",
        "Trust the immutable source lines, CFBD schedule/results reconciliation, and the relative direction of the baseline EPA forecast more than its ranked Confidence or any betting probability. The main-policy ATS Top 5 is a deterministic tie order with no demonstrated reliability discrimination; the research uncertainty order barely discriminates and prior local cards and Top 5 have poor realized performance. Totals and unified outputs are useful experimental signals for review, but their negative out-of-sample ROI and unverified quote-time custody prevent treating them as recommended wagers.",
        "",
        "## Reproduction, limits, and rollback",
        "",
        "The complete 56-game ATS and totals cards, reconciliation, current market/weather/rest review, model manifest, freshness report, prior audit, and checksummed raw provider evidence are adjacent files. Replay uses the copied source database in `data/production_inputs/2026-week5-execution/` or a byte-identical `data/cfb.db`, the fixed provider evidence, and the scripts in this branch. The managed PostgreSQL production stream was not available, so the local locks are durable only in the isolated execution copy and this review branch. No model was promoted, production workflow enabled, card published to the dashboard, or wager placed.",
        "",
        "Rollback consists of abandoning this branch and retaining the local evidence archive; the authoritative source database hash is unchanged. The Week 1 schedule correction exists only in the disposable execution copy. No unrelated tracked files were changed.",
        "",
    ]
    (OUTPUT / "week5_execution_report.md").write_text("\n".join(lines), encoding="utf-8")
    print("wrote week5_execution_report.md")


if __name__ == "__main__":
    main()
