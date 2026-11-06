"""Strict, read-only Week 7 acceptance gate (integrity-v2).

The v1 replay implementation is itself sealed evidence and remains byte-identical.
Use this entry point for acceptance; v1 alone is only a historical replay.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts import build_week7_postgame_audit as replay
from scripts import research_week7_acceptance as research

ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "tests/fixtures/audit_integrity/week7_expected_manifest.json"
STATUS_FIELDS = ("audit_version", "grading_status", "formal_audit_status", "qualified_clv_rows")


def validate_manifest(manifest: dict, expected: dict) -> None:
    """Require the fixed original inventory, never an inventory derived from a suspect manifest."""
    for key in ("output_sha256", "audit_code_sha256"):
        if not isinstance(manifest.get(key), dict) or set(manifest[key]) != set(expected[key]):
            raise ValueError(f"exact checksum coverage required: {key}")
        if manifest[key] != expected[key]:
            raise ValueError(f"original checksum values changed: {key}")
    for key in (*STATUS_FIELDS, "audit_code_hash_encoding"):
        if type(manifest.get(key)) is not type(expected[key]) or manifest[key] != expected[key]:
            raise ValueError(f"contradictory audit status/identity: {key}")
    if set(manifest) != set(expected):
        raise ValueError("unexpected manifest declarations")


def verify() -> dict:
    expected = json.loads(EXPECTED.read_text(encoding="utf-8"))
    manifest = replay.read_json(replay.OUTPUT / "week7_postgame_manifest.json")
    validate_manifest(manifest, expected)
    actual = {p.relative_to(replay.OUTPUT).as_posix() for p in replay.OUTPUT.rglob("*")
              if p.is_file() and p.name != "week7_postgame_manifest.json"}
    if actual != set(expected["output_sha256"]):
        raise ValueError("audit file inventory differs from fixed expected coverage")
    data = replay.main(verify=True)
    for key in STATUS_FIELDS:
        if type(data.get(key)) is not type(manifest[key]) or data[key] != manifest[key]:
            raise ValueError(f"replayed audit status contradicts manifest: {key}")
    return data


def verify_research() -> dict:
    """Replay numerical evidence while separately checking historical/current checkout custody.

    PR40 recorded an LF checkout's EOL failure, which remains historical evidence.
    Its numeric output must reproduce exactly after the real checkout repair.
    """
    manifest = research.read(research.OUT / "research_manifest.json")
    for name, digest in manifest["outputs"].items():
        if research.sha((research.OUT / name).read_bytes().replace(b"\r\n", b"\n")) != digest:
            raise ValueError(f"historical research output changed: {name}")
    for name, digest in manifest["inputs"].items():
        if research.sha((ROOT / name).read_bytes().replace(b"\r\n", b"\n")) != digest:
            raise ValueError(f"research input changed: {name}")
    if research.sha((ROOT / "scripts/research_week7_acceptance.py").read_bytes().replace(b"\r\n", b"\n")) != manifest["script_sha256"]:
        raise ValueError("historical research code changed")
    current = research.custody()
    if len(current["checks"]) != 419 or any(r["status"] != "EXACT" for r in current["checks"]):
        raise ValueError("current checkout must satisfy every original exact-byte hash")
    historical = research.read(research.OUT / "custody_checks.json")
    identity = lambda r: (r["group"], r["path"], r["expected_sha256"], r["canonical_lf_sha256"])
    if [identity(r) for r in current["checks"]] != [identity(r) for r in historical["checks"]]:
        raise ValueError("historical/current custody content identity mismatch")
    rows = research.load_earlier() + [r for week in (5, 6, 7) for r in research.load_modern(week)]
    result = research.analysis(rows)
    from dataclasses import asdict
    files = {
        "diagnostics.json": research.serialize(result),
        "week7_custody_details.json": research.serialize(research.week7_custody_details()),
        "diagnostic_tables.md": research.markdown_tables(result),
        "selection_ledger.csv": research.csv_bytes([dict(**asdict(r), error_actual_minus_prediction=r.error) for r in rows]),
        "weekly_metrics.csv": research.csv_bytes(result["weekly"]),
        "segments_week5_7.csv": research.csv_bytes(result["segments"]),
        "earlier_week_segments.csv": research.csv_bytes(result["earlier_segments"]),
        "rank_nonoverlap.csv": research.csv_bytes(result["rank_nonoverlap"]),
        "correlations.csv": research.csv_bytes(result["correlations"]),
        "time_split_replay.csv": research.csv_bytes(result["retrospective_time_split_replay"]),
    }
    if set(files) | {"custody_checks.json"} != set(manifest["outputs"]):
        raise ValueError("research replay coverage differs")
    for name, payload in files.items():
        if payload != (research.OUT / name).read_bytes():
            raise ValueError(f"research deterministic replay mismatch: {name}")
    return {"exact_custody_checks": len(current["checks"]), "replayed_research_outputs": len(files),
            "historical_checkout_diagnosis_preserved": True}


if __name__ == "__main__":
    data = verify()
    print(json.dumps({"grading_status": data["grading_status"],
                      "formal_audit_status": data["formal_audit_status"],
                      "research": verify_research()}, indent=2))
