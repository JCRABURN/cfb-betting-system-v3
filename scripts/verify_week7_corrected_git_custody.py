"""Ensure the Git index preserves every byte recorded in corrected-v2 seal."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/2026-week7-prospective-corrected-v2"


def main() -> None:
    manifest = json.loads((OUT / "week7_corrected_v2_seal_manifest.json").read_text(encoding="utf-8"))
    entries = {f'outputs/2026-week7-prospective-corrected-v2/{name}': digest for name, digest in manifest["output_files"].items()}
    entries.update(manifest["source_files"])
    entries["outputs/2026-week7-prospective-corrected-v2/week7_corrected_v2_seal_manifest.json"] = hashlib.sha256((OUT / "week7_corrected_v2_seal_manifest.json").read_bytes()).hexdigest()
    bad = []
    for name, expected in entries.items():
        data = subprocess.check_output(["git", "show", ":" + name], cwd=ROOT, stderr=subprocess.DEVNULL)
        if hashlib.sha256(data).hexdigest() != expected:
            bad.append(name)
    if bad:
        raise ValueError(f"Git index differs from corrected seal bytes: {bad}")
    print(f"Corrected Git custody passed: {len(entries)} indexed source/output file hashes match the seal")


if __name__ == "__main__":
    main()
