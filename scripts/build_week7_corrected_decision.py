"""Append a new, explicitly pending human decision from corrected Week 7 inputs."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/2026-week7-prospective-corrected-v2"
OLD = ROOT / "outputs/2026-week7-prospective"
SOURCE = ROOT / "production-weeks/2026-week7-splashsports-corrected-v2.csv"
ASSESSMENTS = [
    ("ATS", 401864524, "STRONG", "KEEP", "Medders made first start after Szarka season-ending absence; small QB sample.", "Option rushing and possession at home; UNLV is traveling to a fifth time zone.", "UNLV defense has been strong in league play; no completed Air Force pass in prior game.", "QB replacement sample; ATS score uncalibrated.", "https://goairforcefalcons.com/news/2026/10/12/football-game-6-air-force-vs-unlv"),
    ("ATS", 401858488, "STRONG", "KEEP", "No newly confirmed major QB absence; availability remains unverified.", "Unbeaten home side with productive Hoover and strong defense.", "Ohio State is a top-five opponent; explosive plays and turnover risk.", "ATS score uncalibrated; no confirmed full injury clearance.", "https://iuhoosiers.com/news/2026/10/12/football-football-gameday-ohio-state-week-7"),
    ("ATS", 401869957, "STRONG", "KEEP", "No confirmed new starter absence; not proof of full health.", "Georgia State arrives off bye with strong rushing and protection profile.", "James Madison is unbeaten; first GSU league road game; gusts could disrupt passing.", "ATS score uncalibrated; weather-sensitive passing.", "https://georgiastatesports.com/news/2026/10/12/football-panthers-continue-conference-play-at-james-madison.aspx"),
    ("ATS", 401858492, "MODERATE", "BORDERLINE", "Oregon Dante Moore availability for Nebraska remains UNRESOLVED.", "Nebraska has balanced offense, strong defense, and a full touchdown cushion.", "Oregon home field and possible QB upgrade may shrink the model gap.", "QB status may make Week 6 EPA projection stale.", "https://huskers.com/news/2026/10/12/huskers-look-to-bounce-back-at-oregon"),
    ("TOTAL", 401860923, "MODERATE", "BORDERLINE", "CSU quarterback rotation and Texas State game-day starter status not fully verified.", "Corrected 69.5 total still exceeds the frozen 59.34 projection by 10.16 points, largest within totals.", "Texas State produced 565 yards on 102 plays against San Diego State; both offenses/defenses can produce a fast, high-scoring game.", "Totals shadow score is uncalibrated; pace is not modeled; local kickoff weather capture unavailable.", "https://txst.com/news/2026/10/4/football-game-recap-bobcats-fall-at-san-diego-state.aspx"),
    ("ATS", 401866442, "WEAK", "REPLACE", "UMass starter Pop Watson missed Week 6; replacement Aedan McCarthy left injured; Week 7 starter UNRESOLVED.", "Largest ATS model edge and solid defense.", "Two-deep QB uncertainty directly threatens scoring and cover path.", "Injury uncertainty dominates uncalibrated score.", "https://umassathletics.com/news/2026/10/13/massachusetts-football-prepares-for-flagship-cup-matchup-at-buffalo"),
    ("ATS", 401858265, "WEAK", "REPLACE", "Syracuse QB Malachi Nelson left Week 6 injured; Week 7 starter UNRESOLVED.", "Large home underdog cushion against Louisville.", "Multiple injured QB possibilities and weaker team case.", "QB uncertainty dominates raw model edge.", "https://cuse.com/news/2026/10/10/football-syracuse-at-virginia"),
    ("ATS", 401856809, "MODERATE", "REPLACE", "BYU RB LJ Martin and OT Andrew Gentry reported unavailable; Bachmeier played last game.", "Undefeated home dog gets double-digit points.", "Two key offensive absences and unbeaten Notre Dame opponent.", "Personnel losses not in raw ATS model.", "https://byucougars.com/news/2026/10/12/byu-football-game-week-2026-notre-dame"),
    ("ATS", 401856723, "WEAK", "REPLACE", "Tennessee starting QB decision UNRESOLVED this week.", "Home rivalry setting and 8.5-point cushion.", "Alabama strength and unsettled quarterback create a fragile cover thesis.", "QB uncertainty not in raw model.", "https://utsports.com/news/2026/10/12/football-14-14-vols-preparing-for-major-test-against-6-7-alabama"),
    ("TOTAL", 401856831, "WEAK", "REPLACE", "No verified game-day QB/injury clearance for either team.", "Second-highest totals shadow score and 8.76-point Under gap.", "Oklahoma State's official preview says it scored over 40 points in three straight games.", "Uncalibrated totals score; offense trend contradicts Under thesis.", "https://okstate.com/news/2026/10/13/cowboy-football-oklahoma-state-visits-houston-for-ap-top-25-matchup"),
    ("TOTAL", 401869934, "WEAK", "REPLACE", "No verified starter/injury clearance for either offense.", "Third-highest totals shadow score and 8.63-point Under gap.", "Southern Miss coach reports Arkansas State QB can throw and defensive problems could raise scoring.", "Uncalibrated totals score; weak independent Under case.", "https://southernmiss.com/news/2026/10/12/football-blake-anderson-weekly-news-conference-the-arkansas-state-game"),
    ("TOTAL", 401864522, "WEAK", "REPLACE", "No verified starter/injury clearance for either team.", "Over model gap is 8.25 points on a low 40.5 total.", "Captured Wyoming wind gusts 26.6 mph and altitude create passing/finishing risk.", "Uncalibrated totals score; weather is a material Over risk.", "outputs/2026-week7-prospective/provider-evidence/context-initial/weather-kickoff.json"),
]
RECOMMENDED = [("ATS", 401864524, 3), ("ATS", 401858488, 3), ("ATS", 401869957, 3), ("ATS", 401858492, 2), ("TOTAL", 401860923, 2)]


def load_rows(name: str) -> list[dict[str, str]]:
    with (OUT / name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def main() -> None:
    board_file = OUT / "week7_corrected_human_decision_board.csv"
    recommendation_file = OUT / "week7_corrected_recommended_five_pending_owner_approval.json"
    review_file = OUT / "week7_corrected_human_review.md"
    if any(path.exists() for path in (board_file, recommendation_file, review_file)):
        raise ValueError("corrected human decision already recorded; append another version instead")
    comparison = json.loads((OUT / "week7_correction_comparison_summary.json").read_text(encoding="utf-8"))
    if comparison["ats_reproduction"] != "PASS" or comparison["total_line_changes"] != 6:
        raise ValueError("corrected board has not passed source/model custody gates")
    ats = {int(r["game_id"]): r for r in load_rows("week7_ats_research_full_board.csv")}
    totals = {int(r["game_id"]): r for r in load_rows("week7_totals_research_full_board.csv")}
    old_weather = {int(r["game_id"]): r for r in json.loads((OLD / "provider-evidence/context-initial/weather-kickoff.json").read_text(encoding="utf-8"))}
    raw = {int(r["game_id"]): r for r in json.loads((OUT / "week7_raw_model_components.json").read_text(encoding="utf-8"))["games"]}
    core = json.loads((OUT / "provider-evidence/core-initial/cfbd-2026-games.json").read_text(encoding="utf-8"))
    if any(game.get("completed") or game.get("homePoints") is not None or game.get("awayPoints") is not None for game in core if game.get("week") == 7):
        raise ValueError("Week 7 results present in decision source")
    now = datetime.now(timezone.utc)
    decision = []
    for market, game_id, assessment, verdict, qb, for_case, against, concern, source in ASSESSMENTS:
        row = ats[game_id] if market == "ATS" else totals[game_id]
        raw_row = raw[game_id]
        kickoff = datetime.fromisoformat(raw_row["kickoff_utc"])
        if now >= kickoff:
            raise ValueError(f"human decision is not prospective for game {game_id}")
        weather = old_weather[game_id]
        weather_label = (f'{weather["temperature_f"]} F; wind {weather["wind_mph"]} mph; gust {weather["gust_mph"]} mph' if weather["status"] == "CAPTURED" else weather["status"])
        decision.append({"market": market, "game_id": game_id, "game": f'{row["away"]} @ {row["home"]}', "selection": row["pick"] if market == "ATS" else row["pick"].upper(), "correct_splashsports_line": row["pick_spread"] if market == "ATS" else row["locked_total"], "within_market_rank": row["ats_research_rank"] if market == "ATS" else row["totals_research_rank"], "research_score_not_calibrated": row["ats_shadow_score_not_calibrated"] if market == "ATS" else row["raw_selected_probability"], "model_edge_or_total_gap_points": row["ats_shadow_selected_edge_points"] if market == "ATS" else abs(float(row["raw_point_edge"])), "current_qb_injury_status": qb, "weather": weather_label, "travel_rest": f'away rest {raw_row["raw_point_in_time_package"]["away_days_rest"]} days; home rest {raw_row["raw_point_in_time_package"]["home_days_rest"]} days', "football_case_for": for_case, "football_case_against": against, "data_quality_concern": concern, "qualitative_assessment": assessment, "red_team_verdict": verdict, "context_source": source, "context_evidence_accessed_at_utc": now.isoformat(), "kickoff_utc": kickoff.isoformat()})
    with board_file.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(decision[0]))
        writer.writeheader()
        writer.writerows(decision)
    by_key = {(r["market"], r["game_id"]): r for r in decision}
    selected = []
    for rank, (market, game_id, confidence) in enumerate(RECOMMENDED, 1):
        item = by_key[(market, game_id)]
        selected.append({"rank": rank, "market": market, "game_id": game_id, "game": item["game"], "selection": item["selection"], "correct_splashsports_line": float(item["correct_splashsports_line"]), "within_market_research_rank": int(item["within_market_rank"]), "research_score_not_calibrated": float(item["research_score_not_calibrated"]), "model_edge_or_total_gap_points": float(item["model_edge_or_total_gap_points"]), "human_confidence_1_to_5": confidence, "red_team_verdict": item["red_team_verdict"], "kickoff_utc": item["kickoff_utc"]})
    if len(selected) != 5 or len({r["game_id"] for r in selected}) != 5 or selected[-1]["correct_splashsports_line"] != 69.5:
        raise ValueError("corrected recommended five are invalid")
    model = json.loads((OUT / "week7_model_manifest.json").read_text(encoding="utf-8"))
    recommendation = {"title": "CORRECTED WEEK 7 RECOMMENDED FIVE — PENDING OWNER APPROVAL", "status": "PENDING_OWNER_APPROVAL", "generated_at_utc": now.isoformat(), "owner_approval_timestamp_utc": None, "corrected_locked_card_sha256": model["locked_line_snapshot_sha256"], "corrected_source_csv_sha256": hashlib.sha256(SOURCE.read_bytes()).hexdigest(), "model_research_commit_sha": model["code_commit_sha"], "old_approved_card_status": "SUPERSEDED — SOURCE LINE ERROR; HISTORICAL ARTIFACT PRESERVED", "under_69_5_would_have_been_selected_from_start": "YES", "selection_reason": "Corrected Under 69.5 remains totals rank 1 with a 10.16-point model gap; all 59 totals were rerun. The pace and calibration risks are material, so it remains BORDERLINE at 2/5. Other fifth-place ATS and totals alternatives have stronger unresolved quarterback, injury, offense-trend, or weather concerns. This is a new recommendation, not retroactive approval of 69.5.", "selections": selected}
    recommendation_file.write_text(json.dumps(recommendation, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    lines = ["# Corrected Week 7 human decision — pending owner approval", "", f'Generated {now.isoformat()}; before all selected kickoffs. No Week 7 game result was present in the frozen pregame capture.', "", "The original owner-approved Under 72.5 is preserved but SUPERSEDED — SOURCE LINE ERROR. Under 69.5 is a distinct prospective candidate and is not owner approved.", "", "## Corrected recommended five", "", "| Rank | Pick | Line | Market | Within-market rank | Confidence | Verdict |", "|---:|---|---:|---|---:|---:|---|"]
    for r in selected:
        lines.append(f'| {r["rank"]} | {r["selection"]} | {r["correct_splashsports_line"]:+g} | {r["market"]} | {r["within_market_research_rank"]} | {r["human_confidence_1_to_5"]}/5 | {r["red_team_verdict"]} |' if r["market"] == "ATS" else f'| {r["rank"]} | {r["game"]} {r["selection"]} | {r["correct_splashsports_line"]:g} | TOTAL | {r["within_market_research_rank"]} | {r["human_confidence_1_to_5"]}/5 | {r["red_team_verdict"]} |')
    lines += ["", "## Would Under 69.5 have been selected from the start?", "", "YES, provisionally. The full corrected totals run still ranks it first (projection 59.34, gap 10.16, uncalibrated score 0.7281). Texas State's documented 102-play, 565-yard previous game, offensive explosiveness, unresolved QB details and absent local weather capture weaken the case, so this is a BORDERLINE 2/5 selection, not a calibrated betting recommendation. The alternatives are weaker on independent football/context review. The three-point correction materially reduces the Under cushion; owner reapproval is required.", "", "## Red-team findings", "", "| Selection | Source line | Model-input risk | QB/injury | Weather | Matchup case / stronger alternative | Verdict |", "|---|---|---|---|---|---|---|"]
    for r in selected:
        item = by_key[(r["market"], r["game_id"])]
        lines.append(f'| {r["selection"]} {r["correct_splashsports_line"]:+g} | screenshot row verified | {item["data_quality_concern"]} | {item["current_qb_injury_status"]} | {item["weather"]} | {item["football_case_for"]} Against: {item["football_case_against"]} | {r["red_team_verdict"]} |')
    lines += ["", "## Candidate comparison", "", "The 12-row machine-readable board records source, rank, score, model gap, QB/injury, weather, rest/travel, cases for/against, and data-quality concerns. ATS and totals scores are uncalibrated and are not compared numerically across markets. The old pregame weather capture is reused as timestamped context evidence; it is not a new corrected-lock capture. This human assessment uses source publications available before first kickoff.", "", "## New context source checked after correction", "", "Texas State's official [October 4 recap](https://txst.com/news/2026/10/4/football-game-recap-bobcats-fall-at-san-diego-state.aspx) reports 102 plays and 565 yards against San Diego State. Oklahoma State's [October 13 preview](https://okstate.com/news/2026/10/13/cowboy-football-oklahoma-state-visits-houston-for-ap-top-25-matchup) reports three straight games above 40 points. Southern Miss's [October 12 coach availability](https://southernmiss.com/news/2026/10/12/football-blake-anderson-weekly-news-conference-the-arkansas-state-game) describes Arkansas State passing strength and defensive concerns. All precede this decision.", ""]
    review_file.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps({"status": recommendation["status"], "candidates": len(decision), "recommended": len(selected), "under_69_5": recommendation["under_69_5_would_have_been_selected_from_start"], "generated_at_utc": now.isoformat()}))


if __name__ == "__main__":
    main()
