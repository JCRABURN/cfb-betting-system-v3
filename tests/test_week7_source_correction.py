"""The screenshot-corrected lock must remain distinct from the original seal."""

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ORIGINAL = ROOT / "outputs/2026-week7-prospective"
CORRECTED = ROOT / "outputs/2026-week7-prospective-corrected-v2"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def test_all_screenshot_rows_trace_to_59_games_and_only_six_total_corrections() -> None:
    original = csv_rows(ROOT / "production-weeks/2026-week7-splashsports.csv")
    corrected = csv_rows(ROOT / "production-weeks/2026-week7-splashsports-corrected-v2.csv")
    transcription = csv_rows(ROOT / "production-weeks/2026-week7-screenshot-transcription-v2.csv")
    metadata = json.loads((ROOT / "production-weeks/2026-week7-splashsports-corrected-v2-lock-metadata.json").read_text())
    assert len(original) == len(corrected) == len(transcription) == len(metadata["row_screenshot_provenance"]) == 59
    assert len({(r["Away Team"], r["Home Team"]) for r in transcription}) == 59
    assert sum(a["Spread"] != b["Spread"] for a, b in zip(original, corrected)) == 0
    assert sum(a["Total"] != b["Total"] for a, b in zip(original, corrected)) == 6
    for old, new, shot, provenance in zip(original, corrected, transcription, metadata["row_screenshot_provenance"]):
        assert (old["Away Team"], old["Home Team"]) == (new["Away Team"], new["Home Team"]) == (shot["Away Team"], shot["Home Team"])
        assert old["Game Date"] == new["Game Date"] == shot["Game Date"]
        assert old["Game Time"] == new["Game Time"] == shot["Game Time"]
        assert float(new["Spread"]) == float(shot["Home Spread"]) == -float(shot["Away Spread"])
        assert float(new["Total"]) == float(shot["Total"])
        assert sha(ROOT / "production-weeks/week7-screenshot-source-v2" / provenance["screenshot"]) == provenance["screenshot_sha256"]


def test_corrected_execution_reproduces_ats_and_keeps_owner_approval_distinct() -> None:
    ats = json.loads((CORRECTED / "week7_ats_reproduction.json").read_text())
    comparison = json.loads((CORRECTED / "week7_correction_comparison_summary.json").read_text())
    recommendation = json.loads((CORRECTED / "week7_corrected_recommended_five_pending_owner_approval.json").read_text())
    old_approval = json.loads((ROOT / "outputs/2026-week7-owner-review/OWNER-APPROVED-WEEK-7-CONTEST-FIVE.json").read_text())
    assert ats["status"] == "PASS" and ats["games_compared"] == 59
    assert ats["selection_spread_edge_score_rank_mismatches"] == ats["raw_component_mismatches"] == []
    assert comparison["total_line_changes"] == 6
    assert recommendation["status"] == "PENDING_OWNER_APPROVAL"
    assert recommendation["owner_approval_timestamp_utc"] is None
    assert recommendation["selections"][-1]["correct_splashsports_line"] == 69.5
    assert old_approval["selections"][-1]["splashsports_locked_line"] == 72.5
    assert len(recommendation["selections"]) == len({r["game_id"] for r in recommendation["selections"]}) == 5


def test_both_seals_remain_byte_valid_without_claiming_old_source_accuracy() -> None:
    old = json.loads((ORIGINAL / "week7_initial_seal_manifest.json").read_text())
    corrected = json.loads((CORRECTED / "week7_corrected_v2_seal_manifest.json").read_text())
    assert len(old["files"]) == 89
    assert all(sha(ORIGINAL / name) == digest for name, digest in old["files"].items())
    assert corrected["original_seal_status"] == "HASH_INTACT_89_OF_89_SOURCE_ACCURACY_INVALIDATED"
    assert corrected["status"] == "READY_FOR_OWNER_APPROVAL" and corrected["owner_reapproval_required"]
    assert corrected["spread_corrections"] == 0 and corrected["total_corrections"] == 6
    assert corrected["ats_candidates"] == corrected["totals_candidates"] == 59
    assert corrected["ats_skips"] == corrected["totals_skips"] == 0
    assert all(sha(CORRECTED / name) == digest for name, digest in corrected["output_files"].items())
    assert all(sha(ROOT / name) == digest for name, digest in corrected["source_files"].items())
    assert sha(ROOT / "data/cfb.db") == corrected["source_database_sha256"]
