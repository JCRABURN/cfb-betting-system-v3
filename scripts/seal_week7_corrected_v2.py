"""Seal the append-only screenshot-corrected Week 7 prospective execution."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "outputs/2026-week7-prospective"
OUT = ROOT / "outputs/2026-week7-prospective-corrected-v2"
SOURCE = ROOT / "production-weeks/2026-week7-splashsports-corrected-v2.csv"
META = ROOT / "production-weeks/2026-week7-splashsports-corrected-v2-lock-metadata.json"
ORIGINAL_SOURCE = ROOT / "production-weeks/2026-week7-splashsports.csv"
OLD_APPROVAL = ROOT / "outputs/2026-week7-owner-review/OWNER-APPROVED-WEEK-7-CONTEST-FIVE.json"
SEAL = OUT / "week7_corrected_v2_seal_manifest.json"
REPORT = OUT / "week7_corrected_v2_custody_report.md"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def json_file(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def main() -> None:
    if SEAL.exists() or REPORT.exists():
        raise ValueError("corrected seal already exists; never overwrite")
    now = datetime.now(timezone.utc)
    old_seal = json_file(OLD / "week7_initial_seal_manifest.json")
    old_bad = [name for name, expected in old_seal["files"].items() if sha(OLD / name) != expected]
    if old_bad or len(old_seal["files"]) != 89:
        raise ValueError(f"original 89-file seal is not intact: {old_bad}")
    if sha(OLD_APPROVAL) != "335d7753d6482025aeda6e72948f182c22c93cb65d6226fc401c88c5da63bfe7":
        raise ValueError("original owner approval artifact changed")
    meta = json_file(META)
    if (meta["game_count"] != 59 or meta["original_lock_hash"] != sha(ORIGINAL_SOURCE)
            or meta["corrected_lock_hash"] != sha(SOURCE)
            or meta["raw_file_sha256"] != sha(SOURCE)
            or meta["canonical_csv_sha256"] != hashlib.sha256(SOURCE.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
            or len(meta["row_screenshot_provenance"]) != 59
            or len(meta["corrections"]) != 6):
        raise ValueError("corrected source custody mismatch")
    for item in meta["row_screenshot_provenance"]:
        image = ROOT / "production-weeks/week7-screenshot-source-v2" / item["screenshot"]
        if sha(image) != item["screenshot_sha256"]:
            raise ValueError(f"screenshot changed: {image}")
    original = csv_rows(ORIGINAL_SOURCE)
    corrected = csv_rows(SOURCE)
    if len(original) != 59 or len(corrected) != 59:
        raise ValueError("bad Week 7 source row count")
    spread_changes = sum(a["Spread"] != b["Spread"] for a, b in zip(original, corrected))
    total_changes = sum(a["Total"] != b["Total"] for a, b in zip(original, corrected))
    other_changes = sum(any(a[k] != b[k] for k in ("Away Team", "Home Team", "Game Date", "Game Time")) for a, b in zip(original, corrected))
    if (spread_changes, total_changes, other_changes) != (0, 6, 0):
        raise ValueError(f"unexpected source corrections: {spread_changes},{total_changes},{other_changes}")
    ingestion = json_file(OUT / "week7_ingestion_manifest.json")
    locked = json_file(OUT / "week7_locked_line_snapshot.json")
    model = json_file(OUT / "week7_model_manifest.json")
    card = json_file(OUT / "week7_card_manifest.json")
    comparison = json_file(OUT / "week7_correction_comparison_summary.json")
    decision = json_file(OUT / "week7_corrected_recommended_five_pending_owner_approval.json")
    if (ingestion["locked_games"], ingestion["ats_predictions"], ingestion["totals_predictions"], ingestion["explicit_missing_locked_totals"]) != (59, 59, 59, 0):
        raise ValueError("corrected execution incomplete")
    if (ingestion["integrity"] != "ok" or ingestion["foreign_key_violations"] != 0
            or model["source_database_sha256"] != sha(ROOT / "data/cfb.db")
            or model["source_database_sha256"] != "09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842"):
        raise ValueError("corrected disposable DB/source DB custody failed")
    if (model["locked_source_csv_sha256"] != meta["canonical_csv_sha256"]
            or model["locked_line_snapshot_sha256"] != locked["locked_line_snapshot_sha256"]
            or model["locked_line_snapshot_sha256"] != decision["corrected_locked_card_sha256"]
            or comparison["ats_reproduction"] != "PASS"
            or len(decision["selections"]) != 5 or decision["status"] != "PENDING_OWNER_APPROVAL"
            or decision["owner_approval_timestamp_utc"] is not None):
        raise ValueError("corrected model/decision identity failed")
    for name in ("week7_ats_full_card.csv", "week7_totals_full_card.csv", "week7_ats_research_full_board.csv", "week7_totals_research_full_board.csv", "week7_totals_old_vs_corrected_full_board.csv"):
        if len(csv_rows(OUT / name)) != 59:
            raise ValueError(f"incomplete {name}")
    if len(csv_rows(OUT / "week7_corrected_human_decision_board.csv")) != 12:
        raise ValueError("corrected human candidate board incomplete")
    if len({r["game_id"] for r in decision["selections"]}) != 5:
        raise ValueError("duplicate corrected recommendation")
    capture = json_file(OUT / "provider-evidence/core-initial/cfbd-2026-games.json")
    if any(game.get("completed") or game.get("homePoints") is not None or game.get("awayPoints") is not None for game in capture if game.get("week") == 7):
        raise ValueError("Week 7 result in pregame source")
    first_kickoff = min(instant(r["source_kickoff_utc"]) for r in locked["lines"])
    for label, value in (("screenshot source", meta["source_received_at_utc"]), ("correction", meta["correction_timestamp_utc"]), ("model", model["generated_at_utc"]), ("human decision", decision["generated_at_utc"]), ("seal", now.isoformat())):
        if instant(value) >= first_kickoff:
            raise ValueError(f"{label} reached first kickoff; cannot mark full card prospective")
    if any(instant(decision["generated_at_utc"]) >= instant(r["kickoff_utc"]) for r in decision["selections"]):
        raise ValueError("corrected selection created after its kickoff")
    if card["governed_ranking_discrimination"] != "INSUFFICIENT_DISCRIMINATION_NULL_UNCERTAINTY_AND_EQUAL_CONFIDENCE":
        raise ValueError("unexpected governed ranking behavior")
    output_files = {str(p.relative_to(OUT)).replace("\\", "/"): sha(p) for p in sorted(OUT.rglob("*")) if p.is_file() and p not in (SEAL, REPORT)}
    source_files = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in [ORIGINAL_SOURCE, SOURCE, META, ROOT / "production-weeks/2026-week7-screenshot-transcription-v2.csv", OLD / "week7_initial_seal_manifest.json", OLD_APPROVAL, *sorted((ROOT / "production-weeks/week7-screenshot-source-v2").glob("*.png"))]}
    report = ["# Week 7 corrected-v2 source and execution custody", "", f'Sealed at {now.isoformat()}, strictly before first Week 7 locked kickoff {first_kickoff.isoformat()}.', "", "Original 89/89 seal: hash-intact. Original lock and owner-approved Under 72.5: historically preserved, INVALIDATED FOR SOURCE ACCURACY — SPLASHSPORTS TRANSCRIPTION ERRORS DISCOVERED. Hashes establish that the first execution did not change; they do not prove screenshot transcription was accurate.", "", "Corrected source: 59 screenshots-matched games; 0 spread corrections; 6 total corrections; 59 ATS and 59 totals model outputs; 0 skips; no Week 7 game results in pregame capture. ATS reproduced exactly. New human decision is PENDING OWNER APPROVAL. Governed v2.8 remains unchanged and has insufficient discrimination for a meaningful Top 5.", "", f'Original source SHA-256: `{sha(ORIGINAL_SOURCE)}`. Corrected raw source SHA-256: `{sha(SOURCE)}`. Corrected canonical source SHA-256: `{meta["canonical_csv_sha256"]}`. Corrected locked-card SHA-256: `{locked["locked_line_snapshot_sha256"]}`. Source database SHA-256: `{sha(ROOT / "data/cfb.db")}`.', "", f'Model/research commit: `{model["code_commit_sha"]}`. Source-correction evidence commit: `{meta["correction_commit_sha"]}`. Corrected decision time: `{decision["generated_at_utc"]}`.', "", "All screenshot hashes, row provenance, old/new boards, raw model components, copied pregame provider evidence, and this custody report are included in the corrected-v2 seal. Copied prior context evidence remains tied to the original lock hash and is treated as independent pregame weather/injury context, not a newly generated corrected-lock capture.", ""]
    REPORT.write_text("\n".join(report), encoding="utf-8", newline="\n")
    output_files[str(REPORT.relative_to(OUT)).replace("\\", "/")] = sha(REPORT)
    result = {"title": "WEEK 7 SCREENSHOT-CORRECTED V2 CUSTODY SEAL", "status": "READY_FOR_OWNER_APPROVAL", "sealed_at_utc": now.isoformat(), "first_lined_kickoff_utc": first_kickoff.isoformat(), "original_seal_status": "HASH_INTACT_89_OF_89_SOURCE_ACCURACY_INVALIDATED", "original_approved_status": "SUPERSEDED_SOURCE_LINE_ERROR_ARTIFACT_PRESERVED", "corrected_seal_status": "SEALED_BEFORE_FIRST_KICKOFF", "owner_reapproval_required": True, "games": 59, "ats_candidates": 59, "ats_skips": 0, "totals_candidates": 59, "totals_skips": 0, "spread_corrections": spread_changes, "total_corrections": total_changes, "source_database_sha256": sha(ROOT / "data/cfb.db"), "corrected_locked_card_sha256": locked["locked_line_snapshot_sha256"], "model_research_code_commit_sha": model["code_commit_sha"], "source_correction_evidence_commit_sha": meta["correction_commit_sha"], "source_files": source_files, "output_files": output_files, "output_file_count": len(output_files), "model_versions": {"ats": model["ats"], "totals": model["totals"], "ats_selection_policy": model["ats_selection_policy"], "totals_reliability_policy": model["totals_reliability_policy"], "governed_ranking_discrimination": card["governed_ranking_discrimination"]}, "prior_seal_path": str((OLD / "week7_initial_seal_manifest.json").relative_to(ROOT)).replace("\\", "/"), "relationship": "ORIGINAL SEAL -> SOURCE ERROR DISCOVERED -> CORRECTED V2 SEAL"}
    SEAL.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"status": result["status"], "output_files": result["output_file_count"], "source_files": len(source_files), "corrected_locked_card_sha256": result["corrected_locked_card_sha256"]}))


if __name__ == "__main__":
    main()
