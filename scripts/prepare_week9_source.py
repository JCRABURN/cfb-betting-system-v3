"""Reconcile original screenshots/PR43 and capture schedule; freeze upcoming source rows."""
from __future__ import annotations
import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ingestion import CanonicalTeamResolver
from scripts.run_week6_execution import iso, read_capture

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/2026-week9-prospective"
SOURCE = ROOT / "data/ingest/2026-week9-splashsports-screen-capture.csv"
REVIEW = ROOT / "data/ingest/2026-week9-independent-screenshot-review.csv"
CDT = timezone(timedelta(hours=-5))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def reconcile(source: list[dict], review: list[dict], games: list[dict], resolver: CanonicalTeamResolver,
              now: datetime, *, exclude_elapsed: bool = False) -> tuple[list[dict], list[dict], list[dict]]:
    def key(away, home, provider="SplashSports"):
        pair = [resolver.resolve(provider, name) for name in (away, home)]
        if any(p.status != "resolved" for p in pair):
            raise ValueError(f"unresolved identity: {away} @ {home}")
        return tuple(p.canonical_name for p in pair)
    image_rows = {}
    for row in review:
        k = key(row["away_team"], row["home_team"])
        if k in image_rows:
            previous = image_rows[k][0]
            if any(previous[f] != row[f] for f in ("away_spread", "total", "local_time", "final_away", "final_home")):
                raise ValueError("overlapping screenshots disagree")
        image_rows.setdefault(k, []).append(row)
    schedule = {}
    for game in games:
        if game.get("week") != 9 or game.get("homeClassification") != "fbs" or game.get("awayClassification") != "fbs":
            continue
        k = key(game["awayTeam"], game["homeTeam"], "collegefootballdata")
        if k in schedule: raise ValueError("duplicate schedule matchup")
        schedule[k] = game
    seen, prospective, excluded, reconciliation = set(), [], [], []
    for index, row in enumerate(source, 2):
        k = key(row["away_team"], row["home_team"])
        if k in seen: raise ValueError("duplicate source matchup")
        seen.add(k)
        if k not in image_rows or k not in schedule: raise ValueError("missing screenshot/schedule matchup")
        image = image_rows[k][0]; game = schedule[k]
        if float(row["away_spread"]) != float(image["away_spread"]) or float(row["home_spread"]) != -float(image["away_spread"]) or float(row["total"]) != float(image["total"]):
            raise ValueError("source line differs from screenshot")
        kickoff = iso(game["startDate"])
        if kickoff.astimezone(CDT).date().isoformat() != row["date"]:
            raise ValueError("source date differs from schedule")
        references = [f"splashsports-{int(x['image']):02}.png:row-{x['row']}" for x in image_rows[k]]
        if row["status"] == "FINAL":
            if not game.get("completed") or kickoff >= now: raise ValueError("final exclusion contradicts schedule")
            if any(row[f] != image[f] for f in ("final_away", "final_home")) or int(row["final_away"]) != game["awayPoints"] or int(row["final_home"]) != game["homePoints"]:
                raise ValueError("final score mismatch")
            excluded.append({"game_id": game["id"], "reason": "FINAL_BEFORE_SOURCE_RECEIPT_NOT_PROSPECTIVE", "source_csv_row": index})
        elif row["status"] == "LIVE_AT_SCREENSHOT":
            if kickoff >= now or row["final_away"] or row["final_home"]:
                raise ValueError("live exclusion contradicts source timing/status")
            excluded.append({"game_id": game["id"], "reason": "LIVE_AT_SOURCE_RECEIPT_NOT_PROSPECTIVE", "source_csv_row": index})
        elif row["status"] == "PREGAME":
            if kickoff <= now and exclude_elapsed:
                excluded.append({"game_id": game["id"], "reason": "KICKOFF_ELAPSED_SINCE_SOURCE_RECEIPT_NO_PROSPECTIVE_PREDICTION", "source_csv_row": index})
                reconciliation.append({"game_id": game["id"], "source_csv_row": index, "screenshots": references,
                    "canonical_away": k[0], "canonical_home": k[1], "status": "ELAPSED_EXCLUDED", "spread_total_match": True})
                continue
            if kickoff <= now or game.get("completed") or game.get("homePoints") is not None or game.get("awayPoints") is not None:
                raise ValueError("kickoff elapsed or target outcome contamination")
            if kickoff.astimezone(CDT).strftime("%I:%M %p") != image["local_time"]:
                raise ValueError("screenshot time differs from schedule in Chicago timezone")
            prospective.append({"Away Team": row["away_team"], "Home Team": row["home_team"],
                "Spread": row["home_spread"], "Game Date": row["date"], "Game Time": image["local_time"],
                "Total": row["total"], "Notes": ";".join(references) + f";PR43-csv-row={index}"})
        else: raise ValueError("unknown source status")
        reconciliation.append({"game_id": game["id"], "source_csv_row": index, "screenshots": references,
            "canonical_away": k[0], "canonical_home": k[1], "status": row["status"], "spread_total_match": True})
    if seen != set(image_rows) or seen != set(schedule):
        raise ValueError("incomplete source/screenshot/scheduled FBS coverage")
    return prospective, excluded, reconciliation


def main(version: str = "") -> dict:
    if version and (not version.isalnum() or version == "v1"):
        raise ValueError("version must be a new alphanumeric suffix")
    suffix = "-" + version if version else ""
    output = ROOT / ("outputs/2026-week9-prospective" + suffix)
    targets = [ROOT / f"production-weeks/2026-week9-splashsports{suffix}.csv",
               ROOT / f"production-weeks/2026-week9-splashsports{suffix}-lock-metadata.json",
               output / "screenshot-reconciliation.json"]
    if any(p.exists() for p in targets): raise FileExistsError("Week 9 source lock already exists")
    custody = json.loads((OUT / "source-evidence/screenshot-custody.json").read_text())
    if digest(SOURCE) != custody["source_csv_sha256"]: raise ValueError("original PR43 bytes changed")
    for item in custody["images"]:
        if digest(OUT / "source-evidence" / item["path"]) != item["sha256"]: raise ValueError("original screenshot changed")
    capture_dir = output / "core-initial"
    capture = json.loads((capture_dir / "capture-manifest.json").read_text())
    games, _ = read_capture(capture_dir, capture, "cfbd-2026-games")
    teams, _ = read_capture(capture_dir, capture, "cfbd-2026-fbs-teams")
    with sqlite3.connect(f"file:{(ROOT / 'data/cfb.db').as_posix()}?mode=ro", uri=True) as conn:
        schools = [r[0] for r in conn.execute("SELECT school FROM teams")]
    resolver = CanonicalTeamResolver(schools + [team["school"] for team in teams])
    now = datetime.now(timezone.utc)
    upcoming, excluded, rows = reconcile(read_csv(SOURCE), read_csv(REVIEW), games, resolver, now, exclude_elapsed=bool(version))
    if not upcoming: raise ValueError("no eligible upcoming games")
    with targets[0].open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(upcoming[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(upcoming)
    metadata = {"season": 2026, "week": 9, "contest_key": "splashsports-cfb-2026-w09", "source": "SplashSports",
        "authoritative_locked_lines": True, "source_received_at_utc": datetime.fromtimestamp(custody["chat_received_unix_seconds"], timezone.utc).isoformat(),
        "source_timestamp_kind": "chat_received", "source_capture_time": None, "original_posting_time": None,
        "spread_convention": "home_team_spread", "total_convention": "contest_over_under", "game_time_zone": "America/Chicago",
        "timezone_verification": f"All {len(upcoming)} eligible displayed times reconcile to captured UTC schedule using Chicago CDT; timezone not printed on image",
        "game_count": len(upcoming), "raw_file_sha256": digest(targets[0]), "canonical_csv_sha256": digest(targets[0]),
        "original_pr43_csv_sha256": digest(SOURCE), "independent_review_sha256": digest(REVIEW),
        "screenshot_custody_sha256": digest(OUT / "source-evidence/screenshot-custody.json"),
        "excluded_completed_games": excluded, "unlined_fbs_games": [], "prepared_at_utc": now.isoformat(),
        "source_authorization": "Owner supplied card in Review PR 38 Audit and requested Week 9 execution; Tuesday elapsed games excluded"}
    reconciliation = {"unique_games": len(rows), "image_observations": len(read_csv(REVIEW)), "upcoming": len(upcoming),
        "completed_exclusions": excluded, "discrepancies": [], "rows": rows}
    for path, data in zip(targets[1:], (metadata, reconciliation)):
        with path.open("x", encoding="utf-8", newline="\n") as stream: stream.write(json.dumps(data, indent=2) + "\n")
    return {"unique_games": len(rows), "upcoming": len(upcoming), "excluded": len(excluded), "discrepancies": 0}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", default="")
    print(json.dumps(main(parser.parse_args().version), indent=2))
