"""Fail-closed comparison of immutable original and screenshot-corrected Week 7 runs."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "outputs/2026-week7-prospective"
NEW = ROOT / "outputs/2026-week7-prospective-corrected-v2"


def rows(directory: Path, filename: str) -> list[dict[str, str]]:
    with (directory / filename).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def dump(filename: str, payload: object) -> None:
    (NEW / filename).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    old_ats = rows(OLD, "week7_ats_research_full_board.csv")
    new_ats = rows(NEW, "week7_ats_research_full_board.csv")
    old_total = rows(OLD, "week7_totals_research_full_board.csv")
    new_total = rows(NEW, "week7_totals_research_full_board.csv")
    if not all(len(x) == 59 for x in (old_ats, new_ats, old_total, new_total)):
        raise ValueError("incomplete original or corrected research board")
    old_ats_by_game = {r["game_id"]: r for r in old_ats}
    new_ats_by_game = {r["game_id"]: r for r in new_ats}
    if set(old_ats_by_game) != set(new_ats_by_game):
        raise ValueError("ATS game set changed")
    ats_fields = ("pick", "pick_spread", "locked_home_spread", "projected_home_margin", "home_ats_edge", "ats_shadow_score_not_calibrated", "ats_shadow_selected_edge_points", "ats_research_rank", "selected_side", "shadow_uncertainty_points", "confidence")
    ats_mismatches = [{"game_id": game, "field": key, "old": old_ats_by_game[game][key], "corrected": new_ats_by_game[game][key]} for game in old_ats_by_game for key in ats_fields if old_ats_by_game[game][key] != new_ats_by_game[game][key]]
    old_raw = json.loads((OLD / "week7_raw_model_components.json").read_text(encoding="utf-8"))
    new_raw = json.loads((NEW / "week7_raw_model_components.json").read_text(encoding="utf-8"))
    original_components = {str(game["game_id"]): game for game in old_raw["games"]}
    new_components = {str(game["game_id"]): game for game in new_raw["games"]}
    raw_mismatches = []
    for game_id in original_components:
        a, b = original_components[game_id], new_components[game_id]
        for key in ("epa_differential", "coefficients", "intercept", "projected_home_margin", "selected_margin_advantage_points", "shadow_score_not_empirically_calibrated", "governed_selected_side", "governed_uncertainty_points"):
            if a["ats"][key] != b["ats"][key]:
                raw_mismatches.append({"game_id": game_id, "field": key})
        if a["raw_point_in_time_package"] != b["raw_point_in_time_package"]:
            raw_mismatches.append({"game_id": game_id, "field": "raw_point_in_time_package"})
    ats = {"status": "PASS" if not ats_mismatches and not raw_mismatches else "FAIL", "games_compared": 59, "selection_spread_edge_score_rank_mismatches": ats_mismatches, "raw_component_mismatches": raw_mismatches}
    dump("week7_ats_reproduction.json", ats)
    if ats["status"] != "PASS":
        raise ValueError(f"ATS changed unexpectedly: {ats}")
    old_by_game = {r["game_id"]: r for r in old_total}
    new_by_game = {r["game_id"]: r for r in new_total}
    if set(old_by_game) != set(new_by_game):
        raise ValueError("totals game set changed")
    differences = []
    total_line_changes = 0
    for new_ranked in new_total:
        game = new_ranked["game_id"]
        old, new = old_by_game[game], new_by_game[game]
        if old["projected_total"] != new["projected_total"]:
            raise ValueError(f"input-only correction altered total model projection for {game}")
        if old["locked_total"] != new["locked_total"]:
            total_line_changes += 1
        differences.append({"game_id": game, "game": f'{new["away"]} @ {new["home"]}', "old_selection": old["pick"], "corrected_selection": new["pick"], "old_locked_total": old["locked_total"], "corrected_locked_total": new["locked_total"], "model_total": new["projected_total"], "old_gap": old["raw_point_edge"], "corrected_gap": new["raw_point_edge"], "old_score_not_calibrated": old["raw_selected_probability"], "corrected_score_not_calibrated": new["raw_selected_probability"], "old_rank": int(old["totals_research_rank"]), "new_rank": int(new["totals_research_rank"]), "rank_change_old_minus_new": int(old["totals_research_rank"]) - int(new["totals_research_rank"])})
    if total_line_changes != 6:
        raise ValueError(f"corrected totals did not change exactly six locks: {total_line_changes}")
    with (NEW / "week7_totals_old_vs_corrected_full_board.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(differences[0]))
        writer.writeheader()
        writer.writerows(differences)
    old_mixed = rows(OLD, "week7_legacy_mixed_research_top5.csv")
    new_mixed = rows(NEW, "week7_legacy_mixed_research_top5.csv")
    texas = next(item for item in differences if item["game"] == "Colorado State @ Texas State")
    dump("week7_texas_state_correction.json", texas)
    dump("week7_legacy_mixed_comparison.json", {"warning": "RESEARCH ONLY — ATS AND TOTALS SCORES ARE NOT CALIBRATED TO A COMMON SCALE.", "old_top_five": old_mixed, "corrected_top_five": new_mixed})
    old_seal = json.loads((OLD / "week7_initial_seal_manifest.json").read_text(encoding="utf-8"))
    old_seal_mismatches = [name for name, expected in old_seal["files"].items() if hashlib.sha256((OLD / name).read_bytes()).hexdigest() != expected]
    if old_seal_mismatches:
        raise ValueError(f"original seal files changed: {old_seal_mismatches}")
    summary = {"ats_reproduction": "PASS", "ats_games_compared": 59, "totals_candidates": 59, "total_line_changes": total_line_changes, "total_rank_changes": sum(item["old_rank"] != item["new_rank"] for item in differences), "total_selection_changes": [item for item in differences if item["old_selection"] != item["corrected_selection"]], "original_seal_files_unchanged": len(old_seal["files"]), "governed_ranking_discrimination": json.loads((NEW / "week7_card_manifest.json").read_text(encoding="utf-8"))["governed_ranking_discrimination"], "texas_state": texas}
    dump("week7_correction_comparison_summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
