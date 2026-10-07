"""Seal Week 6 text bytes for portable SHA-256 custody across Git checkouts."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/2026-week6-execution-20261006T2133Z"
CHECKSUMS = OUT / "week6_artifact_checksums.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    if not OUT.is_dir():
        raise RuntimeError("Week 6 execution output is missing")
    if CHECKSUMS.is_file():
        previous = json.loads(CHECKSUMS.read_text())
        if all(sha(OUT / name) == expected for name, expected in previous["files"].items()):
            print(json.dumps({"files": len(previous["files"]), "status": "VERIFIED_REPLAY"}))
            return
        raise ValueError("sealed Week 6 artifact bytes changed")
    core = json.loads((OUT / "provider-evidence/core/capture-manifest.json").read_text())
    context = json.loads((OUT / "provider-evidence/context/capture-manifest.json").read_text())
    ingestion = json.loads((OUT / "week6_ingestion_manifest.json").read_text())
    raw: dict[Path, str] = {}
    for item in core["requests"]:
        raw[OUT / "provider-evidence/core" / item["path"]] = item["sha256"]
    for item in context["requests"]:
        if "path" in item:
            raw[OUT / "provider-evidence/context" / item["path"]] = item["sha256"]
        if "raw_path" in item:
            raw[OUT / "provider-evidence/context" / item["raw_path"]] = item["raw_sha256"]
    for item in ingestion["provider_ingestion"]:
        raw[OUT / "provider-evidence" / f"{item['name']}.derived.json"] = item["derived_sha256"]
    for path, expected in raw.items():
        if sha(path) != expected:
            raise ValueError(f"raw provider evidence hash mismatch: {path.relative_to(OUT)}")
    normalized = []
    for path in sorted(OUT.rglob("*")):
        if not path.is_file() or path in raw or path == CHECKSUMS:
            continue
        if path.suffix not in (".csv", ".json", ".md"):
            continue
        payload = path.read_bytes()
        if b"\r\n" in payload:
            path.write_bytes(payload.replace(b"\r\n", b"\n"))
            normalized.append(str(path.relative_to(OUT)).replace("\\", "/"))
    card_path = OUT / "week6_card_manifest.json"
    card = json.loads(card_path.read_text())
    card["context_capture_manifest_sha256"] = sha(OUT / "provider-evidence/context/capture-manifest.json")
    card_path.write_bytes((json.dumps(card, indent=2, sort_keys=True) + "\n").encode())
    for path, expected in raw.items():
        if sha(path) != expected:
            raise ValueError(f"packaging altered raw provider evidence: {path.relative_to(OUT)}")
    files = {str(path.relative_to(OUT)).replace("\\", "/"): sha(path)
             for path in sorted(OUT.rglob("*")) if path.is_file() and path != CHECKSUMS}
    CHECKSUMS.write_bytes((json.dumps({"files": files, "normalized_text_files": normalized,
        "raw_provider_files_preserved": len(raw)}, indent=2, sort_keys=True) + "\n").encode())
    print(json.dumps({"files": len(files), "normalized": len(normalized),
                      "raw_provider_files_preserved": len(raw)}))


if __name__ == "__main__":
    main()
