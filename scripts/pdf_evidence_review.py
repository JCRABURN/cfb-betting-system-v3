"""Create separate reading copies without rewriting immutable PDF evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("outputs/2026-week9-context/20261028T2310Z-thursday-gate/supplement")
OUTPUT = Path("outputs/2026-ci-merge-gates/20261029-investigation/pdf-review-views")
PINS = {
    "fau": (
        "6d5109d09086ab49700be6c2bf3a4dfe1405a092543d6e54bc81e08ac69b5f82",
        "778770ce550e783411d0fc130e26b37f43f95c299d6706f094c986b6ea16ff09",
    ),
    "jmu": (
        "e1ec568fd79da741dd7bb1cb3f12a1f6ff43b44f69de12ccd599c9d2daa7d2e7",
        "c84fbd1f4944438ab64e5950c8b485b1379b0e25171c49fbafdc0b08ea83a2aa",
    ),
    "unt": (
        "cea10a8ddaec7db5bbc042321d5aca6990b3e9fb75b1087f1da0c3da0a28ad9f",
        "7ec2239a25dcda5aaccd23125934ed2689d2bb2d5f26145808f7bcca46bcb075",
    ),
}


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def reading_copy(raw: bytes) -> bytes:
    """Strip ASCII line-end spaces/tabs, use LF and one final newline only."""
    lines = [line.removesuffix(b"\r").rstrip(b" \t") for line in raw.split(b"\n")]
    return b"\n".join(lines).rstrip(b"\n") + b"\n"


def payloads(root: Path) -> dict[str, bytes]:
    files = {}
    records = []
    for school, (text_hash, pdf_hash) in PINS.items():
        text_path = SOURCE / f"{school}-notes-plain.txt"
        pdf_path = SOURCE / f"{school}-notes.pdf"
        raw = (root / text_path).read_bytes()
        if sha(raw) != text_hash or sha((root / pdf_path).read_bytes()) != pdf_hash:
            raise ValueError(f"immutable evidence changed: {school}")
        name = f"{school}-notes-review.txt"
        files[name] = reading_copy(raw)
        records.append({
            "source_text": text_path.as_posix(), "source_text_sha256": text_hash,
            "source_pdf": pdf_path.as_posix(), "source_pdf_sha256": pdf_hash,
            "reading_copy": name, "reading_copy_sha256": sha(files[name]),
            "lines_with_trailing_horizontal_whitespace": sum(
                line.removesuffix(b"\r").endswith((b" ", b"\t"))
                for line in raw.split(b"\n")
            ),
        })
    manifest = {
        "purpose": "READING_COPIES_ONLY_NOT_REPLACEMENT_SOURCE_EVIDENCE",
        "normalization": "ASCII line-end spaces/tabs removed; LF; one final newline",
        "raw_git_diff_check_suppressed": False,
        "records": records,
    }
    files["manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    return files


def run(root: Path = ROOT, *, verify: bool = True) -> dict[str, object]:
    target = root / OUTPUT
    if not verify and target.exists():
        raise FileExistsError("reading-copy version already exists; never overwrite")
    files = payloads(root)
    if verify:
        if not target.is_dir() or {p.name for p in target.iterdir()} != set(files):
            raise ValueError("exact reading-copy inventory required")
        for name, raw in files.items():
            if not (target / name).is_file() or (target / name).read_bytes() != raw:
                raise ValueError("reading-copy replay mismatch: " + name)
    else:
        target.mkdir(parents=True, exist_ok=False)
        for name, raw in files.items():
            with (target / name).open("xb") as stream:
                stream.write(raw)
    return {"verified_reading_copies": len(PINS), "source_bytes_unchanged": True,
            "original_whitespace_findings_remain_visible": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true", help="Create a new, separate version")
    args = parser.parse_args()
    print(json.dumps(run(verify=not args.create), indent=2))
