"""Create an append-only screenshot-corrected Week 7 line file and metadata."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from scripts.reconcile_week7_screenshots import IMAGES, OLD, ROOT, SCREEN


DEST = ROOT / "production-weeks/2026-week7-splashsports-corrected-v2.csv"
META = ROOT / "production-weeks/2026-week7-splashsports-corrected-v2-lock-metadata.json"
ORIGINAL_META = ROOT / "production-weeks/2026-week7-splashsports-lock-metadata.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if DEST.exists() or META.exists():
        raise ValueError("corrected v2 lock already exists; never overwrite")
    original = list(csv.DictReader(OLD.open(encoding="utf-8-sig", newline="")))
    screenshot = list(csv.DictReader(SCREEN.open(encoding="utf-8-sig", newline="")))
    if len(original) != len(screenshot) or len(original) != 59:
        raise ValueError("missing screenshot rows")
    by_game = {(row["Away Team"], row["Home Team"]): row for row in screenshot}
    if len(by_game) != 59 or set(by_game) != {(row["Away Team"], row["Home Team"]) for row in original}:
        raise ValueError("screenshot matching failure")
    corrected = []
    changes = []
    row_provenance = []
    for index, old in enumerate(original, 1):
        shot = by_game[(old["Away Team"], old["Home Team"])]
        image = IMAGES / shot["Screenshot"]
        if not image.is_file():
            raise ValueError(f"missing screenshot {image}")
        if (float(old["Spread"]) != float(shot["Home Spread"])
                or -float(old["Spread"]) != float(shot["Away Spread"])
                or old["Game Date"] != shot["Game Date"] or old["Game Time"] != shot["Game Time"]):
            raise ValueError(f"unanticipated non-total correction at row {index}")
        updated = dict(old)
        updated["Total"] = shot["Total"]
        if updated["Total"] != old["Total"]:
            changes.append({"csv_row": index, "game": f'{old["Away Team"]} @ {old["Home Team"]}', "field": "Total", "old": old["Total"], "corrected": updated["Total"], "screenshot": shot["Screenshot"], "screenshot_row": int(shot["Screen Row"])})
        corrected.append(updated)
        row_provenance.append({"csv_row": index, "game": f'{old["Away Team"]} @ {old["Home Team"]}', "screenshot": shot["Screenshot"], "screenshot_sha256": sha(image), "screenshot_row": int(shot["Screen Row"]), "source_image_file_last_modified_utc": datetime.fromtimestamp(image.stat().st_mtime, tz=timezone.utc).isoformat()})
    if len(changes) != 6:
        raise ValueError(f"expected six total corrections; found {len(changes)}")
    with DEST.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(original[0]))
        writer.writeheader()
        writer.writerows(corrected)
    original_meta = json.loads(ORIGINAL_META.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).isoformat()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    result = {**original_meta,
              "source": "SplashSports", "source_medium": "owner-supplied SplashSports screenshots",
              "source_received_at_utc": now, "source_timestamp_kind": "file_received",
              "source_timestamp_provenance": "Earliest verified local reconciliation/metadata creation observation; screenshot filesystem modification times are recorded separately and are not asserted as owner receipt times.",
              "source_commit_sha": commit, "correction_commit_sha": commit,
              "authoritative_locked_lines": True, "correction_reason": "transcription_error",
              "correction_status": "SOURCE_CORRECTED_V2_PENDING_OWNER_CARD_APPROVAL",
              "original_lock_reference": str(OLD.relative_to(ROOT)).replace("\\", "/"),
              "original_lock_hash": sha(OLD), "corrected_lock_hash": sha(DEST),
              "raw_file_sha256": sha(DEST),
              "canonical_csv_sha256": hashlib.sha256(DEST.read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
              "screenshot_transcription_sha256": sha(SCREEN),
              "screenshot_sources": {name: sha(IMAGES / name) for name in sorted({r["Screenshot"] for r in screenshot})},
              "row_screenshot_provenance": row_provenance,
              "corrections": changes, "correction_timestamp_utc": now,
              "source_accuracy_status_of_original": "INVALIDATED FOR SOURCE ACCURACY — SPLASHSPORTS TRANSCRIPTION ERRORS DISCOVERED"}
    META.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"games": len(corrected), "spread_corrections": 0, "total_corrections": len(changes), "raw_corrected_sha256": sha(DEST), "canonical_corrected_sha256": result["canonical_csv_sha256"], "correction_commit_sha": commit}, indent=2))


if __name__ == "__main__":
    main()
