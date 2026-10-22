"""Fail-closed, append-only Week 7 pre-kickoff artifact custody manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs/2026-week7-prospective"
REQUIRED = (
    "week7_ingestion_manifest.json", "week7_ingestion_reconciliation.csv",
    "week7_locked_line_snapshot.json", "week7_card_manifest.json",
    "week7_model_manifest.json", "week7_raw_model_components.json",
    "week7_ats_full_card.csv", "week7_v28_governed_top5.csv",
    "week7_ats_research_full_board.csv", "week7_ats_research_top5.csv",
    "week7_totals_full_card.csv", "week7_totals_research_full_board.csv",
    "week7_totals_research_top5.csv", "week7_legacy_mixed_research_top5.csv",
    "week7_human_review_shortlist.csv",
    "provider-evidence/core-initial/capture-manifest.json",
    "provider-evidence/context-initial/capture-manifest.json",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def require_strictly_before(label: str, instant: datetime, kickoff: datetime) -> None:
    if instant >= kickoff:
        raise ValueError(f"{label} timestamp is not strictly before first lined kickoff")


def validate(output: Path, *, now: datetime | None = None) -> dict:
    output = output.resolve()
    if output != DEFAULT_OUTPUT.resolve() or not output.is_dir():
        raise ValueError("snapshot must be sealed in the isolated Week 7 output directory")
    missing = [name for name in REQUIRED if not (output / name).is_file()]
    if missing:
        raise ValueError(f"Week 7 prospective artifact(s) missing: {missing}")
    now = now or datetime.now(timezone.utc)
    ingestion = json.loads((output / "week7_ingestion_manifest.json").read_text())
    locked = json.loads((output / "week7_locked_line_snapshot.json").read_text())
    card = json.loads((output / "week7_card_manifest.json").read_text())
    model = json.loads((output / "week7_model_manifest.json").read_text())
    context = json.loads((output / "provider-evidence/context-initial/capture-manifest.json").read_text())
    core = json.loads((output / "provider-evidence/core-initial/capture-manifest.json").read_text())
    raw_path = output / "week7_raw_model_components.json"
    raw = json.loads(raw_path.read_text())
    line_count = len(locked["lines"])
    earliest = min(timestamp(row["source_kickoff_utc"]) for row in locked["lines"])
    for label, instant in (("seal", now), ("line lock", timestamp(locked["locked_at_utc"])),
                           ("card", timestamp(card["generated_at"])),
                           ("model", timestamp(model["generated_at_utc"])),
                           ("context", timestamp(context["completed_at"]))):
        require_strictly_before(label, instant, earliest)
    if (ingestion["locked_games"] != line_count
            or model["locked_line_snapshot_sha256"] != locked["locked_line_snapshot_sha256"]
            or context["locked_line_snapshot_sha256"] != locked["locked_line_snapshot_sha256"]
            or ingestion["locked_line_snapshot_sha256"] != locked["locked_line_snapshot_sha256"]):
        raise ValueError("locked line identities/hashes disagree")
    if core.get("status") != "COMPLETE" or len(core.get("requests", [])) != 3:
        raise ValueError("core pregame provider evidence is incomplete")
    for item in core["requests"]:
        require_strictly_before(f"core {item['name']}", timestamp(item["requested_at_utc"]), earliest)
        if sha(output / "provider-evidence/core-initial" / item["path"]) != item["sha256"]:
            raise ValueError(f"core provider payload changed: {item['name']}")
    schedule = json.loads((output / "provider-evidence/core-initial/cfbd-2026-games.json").read_text())
    if any(game.get("completed") for game in schedule if game.get("week") == 7
           and game.get("homeClassification") == game.get("awayClassification") == "fbs"):
        raise ValueError("Week 7 result information present in pregame schedule capture")
    for item in context.get("requests", []):
        if sha(output / "provider-evidence/context-initial" / item["path"]) != item["sha256"]:
            raise ValueError(f"context provider payload changed: {item['name']}")
    if (sha(raw_path) != card["raw_model_components_sha256"]
            or len(raw["games"]) != line_count
            or raw["status"] != "PREGAME_COMPONENT_REPLAY_VERIFIED"):
        raise ValueError("raw model components incomplete or changed")
    if (model["code_commit_sha"] != ingestion["code_commit_sha"]
            or raw["code_commit_sha"] != model["code_commit_sha"]
            or context["code_commit_sha"] != model["code_commit_sha"]):
        raise ValueError("Week 7 model/context code commit identities disagree")
    active_commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if active_commit != model["code_commit_sha"]:
        raise ValueError("active code changed since Week 7 pregame execution")
    ats = csv_rows(output / "week7_ats_full_card.csv")
    totals = csv_rows(output / "week7_totals_full_card.csv")
    ats_research = csv_rows(output / "week7_ats_research_full_board.csv")
    totals_research = csv_rows(output / "week7_totals_research_full_board.csv")
    available_totals = line_count - ingestion["explicit_missing_locked_totals"]
    if not (len(ats) == len(totals) == len(ats_research) == line_count
            and len(totals_research) == available_totals):
        raise ValueError("full-card market coverage failed")
    if len({row["game_id"] for row in ats}) != line_count or len({row["game_id"] for row in totals}) != line_count:
        raise ValueError("duplicate/missing Week 7 game identity")
    for filename in ("week7_v28_governed_top5.csv", "week7_ats_research_top5.csv",
                     "week7_totals_research_top5.csv", "week7_legacy_mixed_research_top5.csv"):
        if len(csv_rows(output / filename)) != 5:
            raise ValueError(f"Top 5 cardinality failure: {filename}")
    if not 8 <= len(csv_rows(output / "week7_human_review_shortlist.csv")) <= 12:
        raise ValueError("human-review shortlist is not approximately 8–12")
    source = ROOT / "production-weeks/2026-week7-splashsports.csv"
    metadata = ROOT / "production-weeks/2026-week7-splashsports-lock-metadata.json"
    meta = json.loads(metadata.read_text())
    if (sha(source) != meta["raw_file_sha256"] or sha(ROOT / "data/cfb.db") != model["source_database_sha256"]
            or sha(metadata) != locked["metadata_sha256"]):
        raise ValueError("source lines/database/metadata changed")
    return {"status": "READY_FOR_PROSPECTIVE_TRACKING",
            "sealed_at_utc": now.isoformat(), "code_commit_sha": active_commit,
            "earliest_lined_kickoff_utc": earliest.isoformat(),
            "locked_games": line_count, "ats_candidates": len(ats_research),
            "totals_candidates": len(totals_research),
            "explicit_missing_locked_totals": ingestion["explicit_missing_locked_totals"],
            "governed_ranking_discrimination": card["governed_ranking_discrimination"],
            "locked_line_snapshot_sha256": locked["locked_line_snapshot_sha256"],
            "source_database_sha256": model["source_database_sha256"],
            "source_csv_sha256": meta["raw_file_sha256"]}


def seal(output: Path, *, now: datetime | None = None) -> dict:
    output = output.resolve()
    target = output / "week7_initial_seal_manifest.json"
    if target.exists():
        raise ValueError("initial Week 7 seal already exists; never overwrite")
    result = validate(output, now=now)
    files = {str(path.relative_to(output)).replace("\\", "/"): sha(path)
             for path in sorted(output.rglob("*")) if path.is_file() and path != target}
    result["files"] = files
    result["file_count"] = len(files)
    target.write_bytes((json.dumps(result, indent=2, sort_keys=True) + "\n").encode())
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = seal(args.output)
    print(json.dumps({key: result[key] for key in
                      ("status", "locked_games", "ats_candidates", "totals_candidates", "file_count")}))


if __name__ == "__main__":
    main()
