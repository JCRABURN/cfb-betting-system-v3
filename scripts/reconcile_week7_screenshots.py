"""Compare a human transcription of owner screenshots with the original Week 7 CSV.

The transcription is stored separately from both the screenshots and the old
lock. This script never edits either source; disagreements remain visible.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "production-weeks/2026-week7-splashsports.csv"
SCREEN = ROOT / "production-weeks/2026-week7-screenshot-transcription-v2.csv"
IMAGES = ROOT / "production-weeks/week7-screenshot-source-v2"
OUTPUT = ROOT / "outputs/2026-week7-prospective-corrected-v2"
FIELDS = ("Away Team", "Home Team", "Away Spread", "Home Spread", "Total", "Game Date", "Game Time", "Matchup Orientation")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    old = list(csv.DictReader(OLD.open(encoding="utf-8-sig", newline="")))
    screen = list(csv.DictReader(SCREEN.open(encoding="utf-8-sig", newline="")))
    if len(old) != 59 or len(screen) != 59:
        raise ValueError(f"expected 59 old and screenshot rows, found {len(old)} and {len(screen)}")
    screen_by_game = {(r["Away Team"], r["Home Team"]): r for r in screen}
    if len(screen_by_game) != 59:
        raise ValueError("duplicate screenshot matchup")
    if set(screen_by_game) != {(r["Away Team"], r["Home Team"]) for r in old}:
        raise ValueError("screenshot and old CSV matchup sets differ")
    images = {}
    for filename in sorted({r["Screenshot"] for r in screen}):
        path = IMAGES / filename
        if not path.is_file():
            raise ValueError(f"missing screenshot: {filename}")
        images[filename] = {"sha256": digest(path), "rows_supported": [i + 1 for i, r in enumerate(old) if screen_by_game[(r["Away Team"], r["Home Team"])]["Screenshot"] == filename]}
    report = []
    discrepant_games = set()
    counts = Counter()
    for ordinal, row in enumerate(old, 1):
        shot = screen_by_game[(row["Away Team"], row["Home Team"])]
        if float(shot["Away Spread"]) != -float(shot["Home Spread"]):
            raise ValueError(f"screenshot spread asymmetry: row {ordinal}")
        values = {
            "Away Team": (row["Away Team"], shot["Away Team"]),
            "Home Team": (row["Home Team"], shot["Home Team"]),
            "Away Spread": (-float(row["Spread"]), float(shot["Away Spread"])),
            "Home Spread": (float(row["Spread"]), float(shot["Home Spread"])),
            "Total": (float(row["Total"]), float(shot["Total"])),
            "Game Date": (row["Game Date"], shot["Game Date"]),
            "Game Time": (row["Game Time"], shot["Game Time"]),
            "Matchup Orientation": (f'{row["Away Team"]} @ {row["Home Team"]}', f'{shot["Away Team"]} @ {shot["Home Team"]}'),
        }
        for field in FIELDS:
            previous, actual = values[field]
            match = previous == actual
            if not match:
                counts[field] += 1
                discrepant_games.add(ordinal)
            report.append({
                "Game": f'{row["Away Team"]} @ {row["Home Team"]}',
                "Field": field,
                "Existing CSV Value": previous,
                "Screenshot Value": actual,
                "Match / Mismatch": "MATCH" if match else "MISMATCH",
                "Correction Required": "YES" if not match else "NO",
                "Screenshot Source": shot["Screenshot"],
                "Notes": f'screenshot row {shot["Screen Row"]}; original CSV row {ordinal}',
            })
    summary = {"games_checked": 59, "exact_games": 59 - len(discrepant_games), "games_with_discrepancies": len(discrepant_games), "field_discrepancies": dict(counts), "screenshot_count": len(images), "original_csv_sha256": digest(OLD), "screenshot_transcription_sha256": digest(SCREEN), "screenshot_sources": images, "reconciled_at_utc": datetime.now(timezone.utc).isoformat()}
    if summary["exact_games"] != 53 or summary["games_with_discrepancies"] != 6 or counts != {"Total": 6}:
        raise ValueError(f"independent reconciliation differs from manual audit: {summary}")
    OUTPUT.mkdir(exist_ok=True)
    with (OUTPUT / "screenshot-discrepancy-report.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(report[0]))
        writer.writeheader()
        writer.writerows(report)
    (OUTPUT / "screenshot-discrepancy-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    lines = ["# Week 7 screenshot-to-lock reconciliation", "", "All 59 source games were checked against the eight owner screenshots, including away/home identity, both spread signs, total, date, time, and orientation.", "", f'Exact games: {summary["exact_games"]}; discrepant games: {summary["games_with_discrepancies"]}; spread discrepancies: 0; total discrepancies: 6.', "", "| Game | Field | Existing CSV | Screenshot | Source |", "|---|---|---:|---:|---|"]
    for item in report:
        if item["Correction Required"] == "YES":
            lines.append(f'| {item["Game"]} | {item["Field"]} | {item["Existing CSV Value"]} | {item["Screenshot Value"]} | {item["Screenshot Source"]} |')
    lines += ["", "The original CSV and 89-file seal remain byte-valid evidence of the first execution. Hash integrity established immutability, not transcription accuracy. The original custody chain and owner-approved card are INVALIDATED FOR SOURCE ACCURACY — SPLASHSPORTS TRANSCRIPTION ERRORS DISCOVERED. The original approval remains preserved as historical evidence; a corrected selection needs new owner approval.", ""]
    (OUTPUT / "screenshot-discrepancy-report.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(json.dumps({k: summary[k] for k in ("games_checked", "exact_games", "games_with_discrepancies", "field_discrepancies", "screenshot_count")}, indent=2))


if __name__ == "__main__":
    main()
