"""Reconcile recovered Week 10 screenshots without rewriting PR49 source artifacts."""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ingestion import CanonicalTeamResolver
from ingestion.custody import DEFAULT_TEAM_ALIASES
from scripts.run_week6_execution import iso, read_capture

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/2026-week10-prospective"
SOURCE = ROOT / "data/ingest/2026-week10-splashsports-screen-capture.csv"
REVIEW = ROOT / "data/ingest/2026-week10-independent-screenshot-review.csv"
ALIASES = ROOT / "data/ingest/2026-week10-team-aliases.json"
CST = timezone(timedelta(hours=-6), "CST")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def resolver_for(schools: list[str]) -> CanonicalTeamResolver:
    aliases = {provider: dict(values) for provider, values in DEFAULT_TEAM_ALIASES.items()}
    additions = json.loads(ALIASES.read_bytes())
    if additions["aliases"] != {"SplashSports": {"Miami OH": "Miami (OH)"}}:
        raise ValueError("unexpected Week 10 source identity correction")
    aliases["SplashSports"].update(additions["aliases"]["SplashSports"])
    return CanonicalTeamResolver(schools, aliases)


def reconcile(source: list[dict], review: list[dict], games: list[dict],
              resolver: CanonicalTeamResolver, now: datetime) -> tuple[list, list, list]:
    def key(away: str, home: str, provider: str = "SplashSports") -> tuple:
        pair = [resolver.resolve(provider, name) for name in (away, home)]
        if any(p.status != "resolved" for p in pair):
            raise ValueError("unresolved source or schedule identity")
        return tuple(p.canonical_name for p in pair)

    images = {}
    for row in review:
        k = key(row["away_team"], row["home_team"])
        if k in images:
            raise ValueError("duplicate screenshot matchup")
        images[k] = row
    schedule = {}
    for game in games:
        if game.get("week") == 10 and game.get("homeClassification") == game.get("awayClassification") == "fbs":
            k = key(game["awayTeam"], game["homeTeam"], "collegefootballdata")
            if k in schedule:
                raise ValueError("duplicate official schedule matchup")
            schedule[k] = game
    seen, upcoming, excluded, records = set(), [], [], []
    for index, row in enumerate(source, 2):
        k = key(row["away_team"], row["home_team"])
        if k in seen or k not in images or k not in schedule:
            raise ValueError("duplicate or missing source/screenshot/schedule matchup")
        seen.add(k)
        image, game = images[k], schedule[k]
        if (float(row["away_spread"]) != float(image["away_spread"])
                or float(row["home_spread"]) != -float(image["away_spread"])
                or float(row["total"]) != float(image["total"])):
            raise ValueError("screenshot line differs from original PR49 transcription")
        kickoff = iso(game["startDate"])
        if kickoff.astimezone(CST).date().isoformat() != row["date"]:
            raise ValueError("source date differs from official schedule")
        reference = f"splashsports-{int(image['image']):02}.png:row-{image['row']}"
        if row["status"] == "FINAL":
            if kickoff >= now or not game.get("completed"):
                raise ValueError("source final contradicts schedule")
            if (row["final_away"] != image["final_away"] or row["final_home"] != image["final_home"]
                    or int(row["final_away"]) != game["awayPoints"] or int(row["final_home"]) != game["homePoints"]):
                raise ValueError("completed exclusion score mismatch")
            reason = "FINAL_AT_SCREENSHOT_RECEIPT_NOT_PROSPECTIVE"
        elif row["status"] == "PREGAME":
            if kickoff.astimezone(CST).strftime("%I:%M %p") != image["local_time"]:
                raise ValueError("displayed kickoff conflicts with official CST schedule")
            reason = "KICKOFF_ELAPSED_BEFORE_GENERATION" if kickoff <= now else ""
            if not reason and (game.get("completed") or game.get("homePoints") is not None or game.get("awayPoints") is not None):
                raise ValueError("upcoming target outcome contamination")
        else:
            raise ValueError("unknown source status")
        if reason:
            excluded.append({"game_id": game["id"], "reason": reason, "source_csv_row": index,
                             "kickoff_utc": kickoff.isoformat()})
        else:
            upcoming.append({"Away Team": row["away_team"], "Home Team": row["home_team"],
                             "Spread": row["home_spread"], "Game Date": row["date"],
                             "Game Time": image["local_time"], "Total": row["total"],
                             "Notes": reference + f";PR49-csv-row={index}"})
        records.append({"game_id": game["id"], "source_csv_row": index,
                        "original_reference": row["source"], "verified_reference": reference,
                        "canonical_away": k[0], "canonical_home": k[1],
                        "line_values_match": True, "status": reason or "UPCOMING"})
    if seen != set(images) or seen != set(schedule):
        raise ValueError("incomplete 62-game source/screenshot/official FBS coverage")
    return upcoming, excluded, records


def main() -> dict:
    targets = [ROOT / "production-weeks/2026-week10-splashsports.csv",
               ROOT / "production-weeks/2026-week10-splashsports-lock-metadata.json",
               OUT / "screenshot-reconciliation.json"]
    if any(p.exists() for p in targets):
        raise FileExistsError("Week 10 source evidence exists; use a new version")
    custody = json.loads((OUT / "source-evidence/screenshot-custody.json").read_bytes())
    if digest(SOURCE) != custody["source_csv_sha256"] or digest(REVIEW) != custody["independent_review_sha256"]:
        raise ValueError("original transcription or screenshot review changed")
    if len(custody["images"]) != 9:
        raise ValueError("nine original images required")
    for image in custody["images"]:
        if digest(OUT / "source-evidence" / image["path"]) != image["sha256"]:
            raise ValueError("original screenshot bytes changed")
    core = OUT / "core-initial"
    capture = json.loads((core / "capture-manifest.json").read_bytes())
    games, _ = read_capture(core, capture, "cfbd-2026-games")
    teams, _ = read_capture(core, capture, "cfbd-2026-fbs-teams")
    with sqlite3.connect(f"file:{(ROOT / 'data/cfb.db').as_posix()}?mode=ro&immutable=1", uri=True) as conn:
        schools = [r[0] for r in conn.execute("SELECT school FROM teams")]
    now = datetime.now(timezone.utc)
    upcoming, excluded, records = reconcile(read_csv(SOURCE), read_csv(REVIEW), games,
                                           resolver_for(schools + [t["school"] for t in teams]), now)
    if len(upcoming) != 57 or len(excluded) != 5:
        raise ValueError("current version requires 57 upcoming and five elapsed games")
    with targets[0].open("x", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(upcoming[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(upcoming)
    metadata = {"season": 2026, "week": 10, "contest_key": "splashsports-cfb-2026-w10",
                "source": "SplashSports", "authoritative_locked_lines": True,
                "source_received_at_utc": datetime.fromtimestamp(custody["chat_received_unix_seconds"], timezone.utc).isoformat(),
                "source_timestamp_kind": "chat_received", "source_capture_time": None,
                "original_posting_time": None, "spread_convention": "home_team_spread",
                "total_convention": "contest_over_under", "game_time_zone": "America/Chicago",
                "timezone_verification": "All displayed pregame times match captured UTC schedule at CST UTC-06; image itself omits timezone",
                "game_count": len(upcoming), "raw_file_sha256": digest(targets[0]),
                "canonical_csv_sha256": digest(targets[0]), "original_pr49_csv_sha256": digest(SOURCE),
                "screenshot_custody_sha256": digest(OUT / "source-evidence/screenshot-custody.json"),
                "excluded_completed_games": excluded, "unlined_fbs_games": [],
                "prepared_at_utc": now.isoformat(), "owner_selection_approval": "PENDING",
                "source_authorization": "Owner designated PR49 screenshot lines for Week10 execution; no market replacement"}
    for path, data in zip(targets[1:], (metadata, {"unique_games": 62, "upcoming": 57,
            "excluded_elapsed_games": excluded, "line_discrepancies": [], "rows": records,
            "provenance_correction": custody["provenance_supersession"]})):
        with path.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(data, indent=2) + "\n")
    return {"unique_games": 62, "upcoming": 57, "excluded": 5, "line_discrepancies": 0}


if __name__ == "__main__":
    print(json.dumps(main(), indent=2))
