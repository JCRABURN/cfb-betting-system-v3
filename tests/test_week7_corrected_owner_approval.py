"""The corrected owner approval is separate from both sealed research and the old approval."""

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "outputs/2026-week7-owner-review"
CORRECTED = ROOT / "outputs/2026-week7-prospective-corrected-v2"
APPROVAL = REVIEW / "OWNER-APPROVED-WEEK-7-CONTEST-FIVE-CORRECTED-V2.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def board(path: Path) -> dict[int, dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {int(row["game_id"]): row for row in csv.DictReader(stream)}


def test_corrected_owner_approval_is_distinct_and_pre_kickoff() -> None:
    approved = read(APPROVAL)
    pending = read(CORRECTED / "week7_corrected_recommended_five_pending_owner_approval.json")
    old_path = REVIEW / "OWNER-APPROVED-WEEK-7-CONTEST-FIVE.json"
    old = read(old_path)
    selections = approved["selections"]
    assert approved["status"] == "OWNER APPROVED — CORRECTED SOURCE V2"
    assert approved["original_approval_status"] == "SUPERSEDED — SOURCE LINE ERROR"
    assert approved["original_owner_approved_artifact_sha256"] == sha(old_path)
    assert old["selections"][-1]["splashsports_locked_line"] == 72.5
    assert len(selections) == len({item["game_id"] for item in selections}) == 5
    assert [(item["market"], item["selection"], item["correct_splashsports_locked_line"], item["human_confidence_1_to_5"]) for item in selections] == [
        ("ATS", "Air Force", 1.5, 3),
        ("ATS", "Indiana", 3.5, 3),
        ("ATS", "Georgia State", 12.5, 3),
        ("ATS", "Nebraska", 7.5, 2),
        ("TOTAL", "UNDER", 69.5, 2),
    ]
    assert all(datetime.fromisoformat(item["owner_approval_timestamp_utc"].replace("Z", "+00:00")) < datetime.fromisoformat(pending["selections"][index]["kickoff_utc"]) for index, item in enumerate(selections))
    assert all(item["corrected_locked_card_sha256"] == approved["corrected_locked_card_sha256"] for item in selections)


def test_corrected_approval_matches_sealed_board_and_source() -> None:
    approved = read(APPROVAL)
    seal_path = CORRECTED / "week7_corrected_v2_seal_manifest.json"
    seal = read(seal_path)
    ats = board(CORRECTED / "week7_ats_research_full_board.csv")
    totals = board(CORRECTED / "week7_totals_research_full_board.csv")
    assert approved["corrected_v2_seal_sha256"] == sha(seal_path)
    assert approved["corrected_locked_card_sha256"] == seal["corrected_locked_card_sha256"]
    assert approved["corrected_source_csv_sha256_raw"] == sha(ROOT / "production-weeks/2026-week7-splashsports-corrected-v2.csv")
    for item in approved["selections"]:
        assert sha(ROOT / item["screenshot_source"]["path"]) == item["screenshot_source"]["sha256"]
        if item["market"] == "ATS":
            row = ats[item["game_id"]]
            assert item["correct_splashsports_locked_line"] == float(row["pick_spread"])
            assert item["within_market_research_rank"] == int(row["ats_research_rank"])
            assert item["research_score_not_calibrated"] == float(row["ats_shadow_score_not_calibrated"])
            assert item["model"]["selected_edge_points"] == float(row["ats_shadow_selected_edge_points"])
        else:
            row = totals[item["game_id"]]
            assert item["correct_splashsports_locked_line"] == float(row["locked_total"])
            assert item["within_market_research_rank"] == int(row["totals_research_rank"])
            assert item["research_score_not_calibrated"] == float(row["raw_selected_probability"])
            assert item["model"]["projected_total"] == float(row["projected_total"])


def test_custody_verification_matches_frozen_bytes() -> None:
    verified = read(REVIEW / "OWNER-APPROVED-WEEK-7-CORRECTED-V2-CUSTODY-VERIFICATION.json")
    assert verified["status"] == "PASS" and all(verified["checks"].values())
    assert verified["owner_approved_artifact_sha256"] == sha(APPROVAL)
    assert verified["source_database_sha256"] == sha(ROOT / "data/cfb.db")
    assert verified["original_seal_verified_files"] == 89
    assert verified["corrected_seal_verified_output_files"] == 96
