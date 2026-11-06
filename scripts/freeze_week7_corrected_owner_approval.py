"""Freeze a separately approved, screenshot-corrected Week 7 contest five."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORRECTED = ROOT / "outputs/2026-week7-prospective-corrected-v2"
REVIEW = ROOT / "outputs/2026-week7-owner-review"
SOURCE = ROOT / "production-weeks/2026-week7-splashsports-corrected-v2.csv"
META = ROOT / "production-weeks/2026-week7-splashsports-corrected-v2-lock-metadata.json"
ORIGINAL_APPROVAL = REVIEW / "OWNER-APPROVED-WEEK-7-CONTEST-FIVE.json"
APPROVAL = REVIEW / "OWNER-APPROVED-WEEK-7-CONTEST-FIVE-CORRECTED-V2.json"
VERIFICATION = REVIEW / "OWNER-APPROVED-WEEK-7-CORRECTED-V2-CUSTODY-VERIFICATION.json"
SEAL = CORRECTED / "week7_corrected_v2_seal_manifest.json"
SOURCE_COMMIT = "d3ffcc24316af7deee7f9f0aebce9b46cb3fac80"
APPROVAL_TIMESTAMP = "2026-10-13T19:37:43Z"
EXPECTED = (
    ("ATS", 401864524, "Air Force", 1.5, 4, 3),
    ("ATS", 401858488, "Indiana", 3.5, 5, 3),
    ("ATS", 401869957, "Georgia State", 12.5, 8, 3),
    ("ATS", 401858492, "Nebraska", 7.5, 2, 2),
    ("TOTAL", 401860923, "UNDER", 69.5, 1, 2),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    if APPROVAL.exists() or VERIFICATION.exists():
        raise ValueError("corrected owner approval already frozen; never overwrite")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if head != SOURCE_COMMIT or subprocess.call(["git", "diff", "--quiet", "HEAD", "--"], cwd=ROOT) != 0:
        raise ValueError("approval-source commit is not the unchanged corrected source head")
    at = datetime.fromisoformat(APPROVAL_TIMESTAMP.replace("Z", "+00:00"))
    if at > datetime.now(timezone.utc):
        raise ValueError("approval observation timestamp is in the future")
    seal = json.loads(SEAL.read_text(encoding="utf-8"))
    prior = json.loads(ORIGINAL_APPROVAL.read_text(encoding="utf-8"))
    pending_path = CORRECTED / "week7_corrected_recommended_five_pending_owner_approval.json"
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    metadata = json.loads(META.read_text(encoding="utf-8"))
    snapshot = json.loads((CORRECTED / "week7_locked_line_snapshot.json").read_text(encoding="utf-8"))
    model_manifest = json.loads((CORRECTED / "week7_model_manifest.json").read_text(encoding="utf-8"))
    ats = {int(r["game_id"]): r for r in rows(CORRECTED / "week7_ats_research_full_board.csv")}
    totals = {int(r["game_id"]): r for r in rows(CORRECTED / "week7_totals_research_full_board.csv")}
    source = rows(SOURCE)
    by_game = {int(item["game_id"]): item for item in snapshot["lines"]}
    by_row = {int(item["csv_row"]): item for item in metadata["row_screenshot_provenance"]}
    if len(source) != 59 or len(by_game) != 59:
        raise ValueError("corrected source/locked-game count mismatch")
    seal_mismatches = [name for name, digest in seal["output_files"].items() if sha(CORRECTED / name) != digest]
    seal_mismatches += [name for name, digest in seal["source_files"].items() if sha(ROOT / name) != digest]
    if seal_mismatches or seal["status"] != "READY_FOR_OWNER_APPROVAL":
        raise ValueError(f"corrected seal mismatch: {seal_mismatches}")
    old_seal_path = ROOT / "outputs/2026-week7-prospective/week7_initial_seal_manifest.json"
    old_seal = json.loads(old_seal_path.read_text(encoding="utf-8"))
    old_mismatches = [name for name, digest in old_seal["files"].items() if sha(ROOT / "outputs/2026-week7-prospective" / name) != digest]
    if len(old_seal["files"]) != 89 or old_mismatches:
        raise ValueError(f"original seal mismatch: {old_mismatches}")
    if sha(ORIGINAL_APPROVAL) != "335d7753d6482025aeda6e72948f182c22c93cb65d6226fc401c88c5da63bfe7" or prior["selections"][-1]["splashsports_locked_line"] != 72.5:
        raise ValueError("original approved Under 72.5 changed")
    if (pending["status"] != "PENDING_OWNER_APPROVAL" or len(pending["selections"]) != 5
            or pending["corrected_locked_card_sha256"] != seal["corrected_locked_card_sha256"]
            or sha(SOURCE) != metadata["raw_file_sha256"]
            or hashlib.sha256(SOURCE.read_bytes().replace(b"\r\n", b"\n")).hexdigest() != metadata["canonical_csv_sha256"]
            or model_manifest["code_commit_sha"] != pending["model_research_commit_sha"]):
        raise ValueError("corrected pending/source/model identities do not match")
    if sha(ROOT / "data/cfb.db") != seal["source_database_sha256"]:
        raise ValueError("source database hash changed")
    game_capture = json.loads((CORRECTED / "provider-evidence/core-initial/cfbd-2026-games.json").read_text(encoding="utf-8"))
    if any(g.get("completed") or g.get("homePoints") is not None or g.get("awayPoints") is not None for g in game_capture if g.get("week") == 7):
        raise ValueError("game result found in corrected pregame capture")
    if datetime.fromisoformat(pending["generated_at_utc"]) >= datetime.fromisoformat(seal["first_lined_kickoff_utc"]):
        raise ValueError("corrected selection was not made before first kickoff")
    selected = []
    for rank, ((market, game_id, selection, line, research_rank, confidence), candidate) in enumerate(zip(EXPECTED, pending["selections"], strict=True), 1):
        if (candidate["rank"], candidate["market"], candidate["game_id"], candidate["selection"], candidate["correct_splashsports_line"], candidate["within_market_research_rank"], candidate["human_confidence_1_to_5"]) != (rank, market, game_id, selection, line, research_rank, confidence):
            raise ValueError(f"owner approval differs from corrected pending candidate at rank {rank}")
        locked = by_game[game_id]
        original_row = source[int(locked["csv_row"]) - 1]
        screenshot = by_row[int(locked["csv_row"])]
        image_path = ROOT / "production-weeks/week7-screenshot-source-v2" / screenshot["screenshot"]
        if sha(image_path) != screenshot["screenshot_sha256"]:
            raise ValueError(f"screenshot bytes changed for game {game_id}")
        if market == "ATS":
            board = ats[game_id]
            selected_line = float(board["pick_spread"])
            screenshot_line = float(original_row["Spread"]) if board["selected_side"] == "home" else -float(original_row["Spread"])
            score = float(board["ats_shadow_score_not_calibrated"])
            board_rank = int(board["ats_research_rank"])
            model = {"selected_edge_points": float(board["ats_shadow_selected_edge_points"]), "projected_home_margin": float(board["projected_home_margin"])}
        else:
            board = totals[game_id]
            selected_line = float(board["locked_total"])
            screenshot_line = float(original_row["Total"])
            score = float(board["raw_selected_probability"])
            board_rank = int(board["totals_research_rank"])
            model = {"projected_total": float(board["projected_total"]), "selected_total_gap_points": abs(float(board["raw_point_edge"]))}
        if (selected_line != line or screenshot_line != line or board_rank != research_rank
                or score != candidate["research_score_not_calibrated"]
                or model["selected_edge_points" if market == "ATS" else "selected_total_gap_points"] != candidate["model_edge_or_total_gap_points"]):
            raise ValueError(f"line/rank/score/edge differs from corrected board for game {game_id}")
        if at >= datetime.fromisoformat(candidate["kickoff_utc"]):
            raise ValueError(f"approval reached kickoff for game {game_id}")
        selected.append({"rank": rank, "game_id": game_id, "game": candidate["game"], "selection": selection, "correct_splashsports_locked_line": line, "market": market, "within_market_research_rank": research_rank, "research_score_not_calibrated": score, "model": model, "human_confidence_1_to_5": confidence, "owner_approval_timestamp_utc": APPROVAL_TIMESTAMP, "corrected_locked_card_sha256": seal["corrected_locked_card_sha256"], "corrected_source_csv_sha256_raw": metadata["raw_file_sha256"], "corrected_source_csv_sha256_canonical": metadata["canonical_csv_sha256"], "screenshot_source": {"path": str(image_path.relative_to(ROOT)).replace("\\", "/"), "sha256": screenshot["screenshot_sha256"], "screenshot_row": screenshot["screenshot_row"]}, "corrected_model_research_commit_sha": model_manifest["code_commit_sha"], "approval_source_commit_sha": SOURCE_COMMIT})
    if len(selected) != 5 or len({r["game_id"] for r in selected}) != 5:
        raise ValueError("corrected approval cardinality/uniqueness failed")
    artifact = {"title": "OWNER-APPROVED-WEEK-7-CONTEST-FIVE-CORRECTED-V2", "status": "OWNER APPROVED — CORRECTED SOURCE V2", "approval_source": "Owner's explicit approval message in this Codex task; timestamp is earliest verifiable UTC receipt/observation, not a claimed earlier send time.", "owner_approval_timestamp_utc": APPROVAL_TIMESTAMP, "corrected_locked_card_sha256": seal["corrected_locked_card_sha256"], "corrected_source_csv_sha256_raw": metadata["raw_file_sha256"], "corrected_source_csv_sha256_canonical": metadata["canonical_csv_sha256"], "corrected_v2_seal_sha256": sha(SEAL), "corrected_model_research_commit_sha": model_manifest["code_commit_sha"], "approval_source_commit_sha": SOURCE_COMMIT, "original_approval_status": "SUPERSEDED — SOURCE LINE ERROR", "original_owner_approved_artifact_sha256": sha(ORIGINAL_APPROVAL), "prior_pending_candidate_sha256": sha(pending_path), "selections": selected}
    write_json(APPROVAL, artifact)
    checks = {"exactly_five_selections": True, "no_duplicate_selections_or_games": True, "all_five_lines_match_corrected_screenshot_source": True, "all_four_ats_lines_match_original_correct_spreads": True, "texas_state_total_is_69_5_not_72_5": True, "research_ranks_match_corrected_boards": True, "research_scores_match_corrected_boards": True, "model_edges_or_projection_match_corrected_boards": True, "corrected_locked_card_hash_unchanged": True, "corrected_source_hashes_unchanged": True, "corrected_seal_unchanged": True, "original_89_file_seal_preserved": True, "original_erroneous_approved_artifact_preserved": True, "source_database_hash_unchanged": True, "pregame_selection_without_results": True, "approval_before_all_selected_kickoffs": True}
    write_json(VERIFICATION, {"title": "WEEK 7 CORRECTED V2 OWNER APPROVAL CUSTODY VERIFICATION", "status": "PASS", "owner_approval_timestamp_utc": APPROVAL_TIMESTAMP, "owner_approved_artifact_sha256": sha(APPROVAL), "checks": checks, "corrected_seal_sha256": sha(SEAL), "corrected_locked_card_sha256": seal["corrected_locked_card_sha256"], "corrected_source_csv_sha256_raw": metadata["raw_file_sha256"], "original_seal_verified_files": 89, "corrected_seal_verified_output_files": len(seal["output_files"]), "corrected_seal_verified_source_files": len(seal["source_files"]), "original_approval_sha256": sha(ORIGINAL_APPROVAL), "source_database_sha256": sha(ROOT / "data/cfb.db"), "approval_source_commit_sha": SOURCE_COMMIT, "model_research_commit_sha": model_manifest["code_commit_sha"], "note": "Original Under 72.5 approval is preserved but superseded for source accuracy. New Under 69.5 approval is separate. No model, policy, schema, migration, or calibration changed."})
    print(json.dumps({"status": "PASS", "approval_timestamp_utc": APPROVAL_TIMESTAMP, "selected_games": len(selected), "corrected_locked_card_sha256": seal["corrected_locked_card_sha256"], "artifact_sha256": sha(APPROVAL)}))


if __name__ == "__main__":
    main()
