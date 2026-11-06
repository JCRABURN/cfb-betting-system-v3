"""Lock owner-supplied Week 8 lines and run unchanged v2.8 ATS/shadow totals.

The source DB is read only. Any missing/late/ambiguous lock or point-in-time
model input prevents a completed prospective card; no line is substituted.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sqlite3
import subprocess
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from business_entities.full_card import locked_line_snapshot_sha256
from business_entities.totals_weekly_model import run_component_totals_shadow_model
from business_entities.weekly_controller import run_epa_only_model
from contest_lines import create_contest, list_effective_locked_lines, lock_contest_line
from ingestion import CanonicalTeamResolver
from migrations.runner import apply_migrations, table_row_counts
from operations.providers import CfbdGamesParser, CfbdTeamStatsParser, _write_games, _write_team_stats
from scripts.run_week6_execution import ingest, iso, read_capture, sha, write_json


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "data/cfb.db"
WEEK5_CORE = ROOT / "outputs/2026-week5-execution-20260930-v4/provider-evidence"
WEEK6_CORE = ROOT / "outputs/2026-week6-execution-20261006T2133Z/provider-evidence/core"
CONTEST_KEY = "splashsports-cfb-2026-w08"
CHICAGO = timezone(timedelta(hours=-5), "CDT")
REQUIRED_COLUMNS = ("Away Team", "Home Team", "Spread", "Game Date", "Game Time", "Total")


def canonical_sha(path: Path) -> str:
    return sha(path.read_bytes().replace(b"\r\n", b"\n"))


def read_source(source: Path, metadata: Path) -> tuple[list[dict[str, str]], dict, str]:
    details = json.loads(metadata.read_text(encoding="utf-8"))
    if (details.get("season"), details.get("week"), details.get("contest_key")) != (2026, 8, CONTEST_KEY):
        raise ValueError("Week 8 metadata identity mismatch")
    if details.get("source") != "SplashSports" or not details.get("source_received_at_utc"):
        raise ValueError("source and actual receipt timestamp are mandatory")
    if details.get("spread_convention") != "home_team_spread":
        raise ValueError("unverified home-team spread convention")
    if details.get("total_convention") != "contest_over_under":
        raise ValueError("unverified contest-total convention")
    if details.get("game_time_zone") != "America/Chicago":
        raise ValueError("source game-time zone must be verified as America/Chicago")
    if details.get("source_timestamp_kind") not in ("owner_capture", "chat_received", "file_received"):
        raise ValueError("source timestamp provenance is mandatory")
    if not details.get("authoritative_locked_lines"):
        raise ValueError("owner has not identified the authoritative locked lines")
    digest = canonical_sha(source)
    if digest != details.get("canonical_csv_sha256"):
        raise ValueError("source line checksum mismatch")
    if sha(source.read_bytes()) != details.get("raw_file_sha256"):
        raise ValueError("raw owner-source artifact checksum mismatch")
    with source.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if reader.fieldnames is None or not set(REQUIRED_COLUMNS).issubset(reader.fieldnames):
            raise ValueError("Week 8 line CSV missing required columns")
        rows = list(reader)
    if not rows or len(rows) != details.get("game_count"):
        raise ValueError("Week 8 line count differs from source metadata")
    if len({(r["Away Team"], r["Home Team"]) for r in rows}) != len(rows):
        raise ValueError("duplicate locked matchup in owner source")
    return rows, details, digest


def reconcile(conn: sqlite3.Connection, games: list[dict], rows: list[dict],
              *, generation_time: datetime) -> list[dict]:
    resolver = CanonicalTeamResolver.from_connection(conn)
    week_games = [game for game in games if game.get("week") == 8
                  and game.get("homeClassification") == game.get("awayClassification") == "fbs"]
    mapped = {}
    for game in week_games:
        home = resolver.resolve("collegefootballdata", game["homeTeam"])
        away = resolver.resolve("collegefootballdata", game["awayTeam"])
        if home.status != "resolved" or away.status != "resolved":
            raise ValueError(f"unresolved FBS schedule team: {game['id']}")
        key = (away.canonical_name, home.canonical_name)
        if key in mapped:
            raise ValueError(f"duplicate provider schedule matchup: {key}")
        mapped[key] = game
    seen = set()
    reconciled = []
    for ordinal, row in enumerate(rows, 1):
        away = resolver.resolve("SplashSports", row["Away Team"])
        home = resolver.resolve("SplashSports", row["Home Team"])
        if away.status != "resolved" or home.status != "resolved":
            raise ValueError(f"row {ordinal}: unresolved SplashSports team identity")
        game = mapped.get((away.canonical_name, home.canonical_name))
        if game is None:
            raise ValueError(f"row {ordinal}: no matching Week 8 FBS game: {away.canonical_name} @ {home.canonical_name}")
        if game["id"] in seen:
            raise ValueError(f"row {ordinal}: duplicate provider game ID")
        seen.add(game["id"])
        source_kickoff = datetime.strptime(
            row["Game Date"] + " " + row["Game Time"], "%Y-%m-%d %I:%M %p"
        ).replace(tzinfo=CHICAGO).astimezone(timezone.utc)
        provider_kickoff = iso(game["startDate"])
        if source_kickoff != provider_kickoff:
            raise ValueError(f"row {ordinal}: kickoff conflict for game {game['id']}: source={source_kickoff}, provider={provider_kickoff}")
        if generation_time >= source_kickoff:
            raise ValueError(f"row {ordinal}: kickoff elapsed before prospective lock: game {game['id']}")
        if game.get("completed") or game.get("homePoints") is not None or game.get("awayPoints") is not None:
            raise ValueError(f"row {ordinal}: target outcome contamination")
        if not row["Spread"].strip():
            raise ValueError(f"row {ordinal}: missing ATS lock")
        spread = float(row["Spread"])
        total = float(row["Total"]) if row["Total"].strip() else None
        if not math.isfinite(spread) or (total is not None and (not math.isfinite(total) or total <= 0)):
            raise ValueError(f"row {ordinal}: nonfinite spread or total")
        reconciled.append({"csv_row": ordinal, "game_id": game["id"],
                           "raw_away": row["Away Team"], "raw_home": row["Home Team"],
                           "away": away.canonical_name, "home": home.canonical_name,
                           "home_spread": spread, "locked_total": total,
                           "source_kickoff_utc": source_kickoff.isoformat(),
                           "provider_kickoff_utc": provider_kickoff.isoformat(),
                           "total_status": "LOCKED" if total is not None else "SOURCE_TOTAL_UNAVAILABLE",
                           "source_note": row.get("Notes", "")})
    return reconciled


def run(*, source: Path, metadata: Path, capture: Path, database: Path, output: Path) -> dict:
    source, metadata, capture, database, output = (
        item.resolve() for item in (source, metadata, capture, database, output))
    if any(not item.is_relative_to(ROOT) for item in (source, metadata, capture, database, output)):
        raise ValueError("all paths must stay inside isolated Week 8 worktree")
    if database == SOURCE_DB or database.exists() or not output.is_dir():
        raise ValueError("database must be a new disposable copy and output must exist")
    if any((output / name).exists() for name in (
        "week8_ingestion_manifest.json", "week8_locked_line_snapshot.json",
        "week8_initial_seal_manifest.json",
    )):
        raise ValueError("Week 8 lock evidence already exists; never overwrite")
    derived_dir = output / "provider-evidence"
    if derived_dir.exists() and any(derived_dir.iterdir()):
        raise FileExistsError("derived ingestion evidence already exists; create a new output version")
    derived_dir.mkdir(exist_ok=True)
    rows, details, source_hash = read_source(source, metadata)
    capture_manifest = json.loads((capture / "capture-manifest.json").read_text(encoding="utf-8"))
    if capture_manifest.get("status") != "COMPLETE":
        raise ValueError("Week 8 provider core capture is incomplete")
    current_items = {item["name"]: {**item, "requested_at": item["requested_at_utc"]}
                     for item in capture_manifest["requests"]}
    # read_capture verifies each raw payload before any disposable DB mutation.
    current = {"requests": list(current_items.values())}
    games, games_item = read_capture(capture, current, "cfbd-2026-games")
    teams, _ = read_capture(capture, current, "cfbd-2026-fbs-teams")
    stats7, stats7_item = read_capture(capture, current, "cfbd-week7-advanced")
    prior6 = ROOT / "outputs/2026-week7-prospective/provider-evidence/core-initial"
    prior6_manifest = json.loads((prior6 / "capture-manifest.json").read_text())
    prior6_manifest["requests"] = [{**item, "requested_at": item["requested_at_utc"]} for item in prior6_manifest["requests"]]
    stats6, stats6_item = read_capture(prior6, prior6_manifest, "cfbd-week6-advanced")
    prior5_manifest = json.loads((WEEK6_CORE / "capture-manifest.json").read_text())
    prior4_manifest = json.loads((WEEK5_CORE / "capture-manifest.json").read_text())
    stats5, stats5_item = read_capture(WEEK6_CORE, prior5_manifest, "cfbd-week5-advanced")
    stats4, stats4_item = read_capture(WEEK5_CORE, prior4_manifest, "cfbd-week4-advanced")
    now = datetime.now(timezone.utc)
    for name, item in current_items.items():
        if not iso(item["requested_at_utc"]) <= iso(item["received_at_utc"]) <= now:
            raise ValueError("provider timestamp ordering invalid")
    if current_items["cfbd-week7-advanced"]["parameters"] != {"year": 2026, "endWeek": 7, "excludeGarbageTime": "true"}:
        raise ValueError("Week 8 forecast requires statistics strictly through Week 7")
    received = iso(details["source_received_at_utc"])
    if received > now:
        raise ValueError("source receipt timestamp is in the future")
    source_db_sha = sha(SOURCE_DB.read_bytes())
    database.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE_DB, database)
    if sha(database.read_bytes()) != source_db_sha:
        raise ValueError("disposable source DB copy hash mismatch")
    conn = sqlite3.connect(database)
    conn.execute("PRAGMA foreign_keys=ON")
    before = table_row_counts(conn)
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("source copy failed integrity gate")
    migrations = apply_migrations(conn)
    for team in teams:
        if team.get("classification") != "fbs":
            raise ValueError("non-FBS team in identities capture")
        if not conn.execute("SELECT 1 FROM teams WHERE school=?", (team["school"],)).fetchone():
            conn.execute("INSERT INTO teams(team_id,school,conference,division) VALUES(?,?,?,?)",
                         (team["id"], team["school"], team.get("conference"), team.get("division")))
    conn.commit()
    locked = reconcile(conn, games, rows, generation_time=now)
    scheduled_ids = {game["id"] for game in games if game.get("week") == 8
                     and game.get("homeClassification") == game.get("awayClassification") == "fbs"}
    excluded = details.get("excluded_completed_games", [])
    completed_ids = {g["id"] for g in games if g.get("week") == 8 and (g.get("completed") or iso(g["startDate"]) <= now)}
    if {g["game_id"] for g in excluded} != completed_ids:
        raise ValueError("completed-game exclusions differ from captured schedule")
    unlined_ids = sorted(scheduled_ids - completed_ids - {item["game_id"] for item in locked})
    documented_unlined = details.get("unlined_fbs_games", [])
    if unlined_ids != sorted(item.get("game_id") for item in documented_unlined):
        raise ValueError(f"unexplained unlined FBS schedule games: {unlined_ids}")
    if any(not item.get("reason") or not item.get("source") for item in documented_unlined):
        raise ValueError("unlined FBS game lacks source/reason")
    if received >= min(iso(item["source_kickoff_utc"]) for item in locked):
        raise ValueError("owner line source received after first lined kickoff")
    ingestions = []
    for week in range(2, 9):
        week_games = [game for game in games if game.get("week") == week
                      and game.get("homeClassification") == game.get("awayClassification") == "fbs"]
        if week < 8 and any(not game.get("completed") for game in week_games):
            raise ValueError(f"prior Week {week} results incomplete")
        if week == 8:
            week_games = [game for game in week_games if game["id"] in {item["game_id"] for item in locked}]
        if week == 8 and any(game.get("completed") or game.get("homePoints") is not None or game.get("awayPoints") is not None for game in week_games):
            raise ValueError("Week 8 result information entered pregame provider capture")
        ingestions.append(ingest(conn, output, week_games, name=f"cfbd-week{week}-games",
                                 item=games_item, parameters={"year": 2026, "week": week, "classification": "fbs"},
                                 parser=CfbdGamesParser(), writer=_write_games))
    for week, stats, item in ((4, stats4, stats4_item), (5, stats5, stats5_item), (6, stats6, stats6_item), (7, stats7, stats7_item)):
        ingestions.append(ingest(conn, output, stats, name=f"cfbd-week{week}-advanced",
                                 item=item, parameters={"year": 2026, "endWeek": week, "excludeGarbageTime": "true"},
                                 parser=CfbdTeamStatsParser(), writer=_write_team_stats))
    contest = create_contest(conn, contest_key=CONTEST_KEY, name="SplashSports 2026 Week 8",
                             season=2026, week=8, source="SplashSports", source_contest_id=CONTEST_KEY,
                             created_at=now, provenance="owner-supplied prospective Week 8 lock; disposable execution copy")
    metadata_sha = sha(metadata.read_bytes())
    for item in locked:
        record = lock_contest_line(conn, contest_id=contest.id, game_id=item["game_id"],
                                   raw_home_team=item["raw_home"], raw_away_team=item["raw_away"],
                                   normalized_home_team=item["home"], normalized_away_team=item["away"],
                                   home_spread=item["home_spread"], total=item["locked_total"],
                                   source="SplashSports", source_line_id=f"csv-row:{item['csv_row']}",
                                   payload_sha256=source_hash, locked_at=now,
                                   provenance=f"week8 owner lock;csv_sha256={source_hash};metadata_sha256={metadata_sha};disposable-copy")
        item["locked_line_id"] = record.line.id
    conn.commit()
    lines = list_effective_locked_lines(conn, contest.id, as_of=now)
    if len(lines) != len(rows):
        raise ValueError("locked-line row count mismatch")
    lock_sha = locked_line_snapshot_sha256(lines)
    with (output / "week8_ingestion_reconciliation.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(locked[0]))
        writer.writeheader()
        writer.writerows(locked)
    write_json(output / "week8_locked_line_snapshot.json", {
        "contest_key": CONTEST_KEY, "source_csv_sha256": source_hash,
        "metadata_sha256": metadata_sha, "locked_at_utc": now.isoformat(),
        "locked_line_snapshot_sha256": lock_sha, "lines": locked})
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    ats_run = run_epa_only_model(conn, contest_id=contest.id,
                                 model_run_key="week8-20261021:epa", code_commit_sha=commit,
                                 generated_at=now, provenance="owner-request://2026-week8-prospective")
    total_run = run_component_totals_shadow_model(conn, contest_id=contest.id,
                                                   model_run_key="week8-20261021:component-totals",
                                                   code_commit_sha=commit, generated_at=now,
                                                   provenance="owner-request://2026-week8-prospective")
    conn.commit()
    ats_predictions = conn.execute("SELECT COUNT(*) FROM model_predictions WHERE model_run_id=?", (ats_run.id,)).fetchone()[0]
    total_predictions = conn.execute("SELECT COUNT(*) FROM total_model_predictions WHERE total_model_run_id=?", (total_run.id,)).fetchone()[0]
    expected_totals = sum(item["locked_total"] is not None for item in locked)
    if ats_predictions != len(lines) or total_predictions != expected_totals:
        raise ValueError(f"point-in-time model coverage failed: ATS {ats_predictions}/{len(lines)}; totals {total_predictions}/{expected_totals}")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    if integrity != "ok" or foreign_keys or sha(SOURCE_DB.read_bytes()) != source_db_sha:
        raise ValueError("post-model integrity or source DB hash changed")
    if datetime.now(timezone.utc) >= min(iso(item["source_kickoff_utc"]) for item in locked):
        raise ValueError("execution completed at or after the first lined kickoff")
    result = {"generated_at_utc": now.isoformat(), "code_commit_sha": commit,
              "source_database_sha256": source_db_sha, "source_csv_sha256": source_hash,
              "metadata_sha256": metadata_sha, "locked_line_snapshot_sha256": lock_sha,
              "provider_capture": capture_manifest, "provider_ingestion": ingestions,
              "migration_versions": [item.version for item in migrations],
              "before_counts": before, "after_counts": table_row_counts(conn),
              "locked_games": len(lines), "ats_predictions": ats_predictions,
              "scheduled_fbs_games": len(scheduled_ids),
              "documented_unlined_fbs_games": documented_unlined, "excluded_completed_games": excluded,
              "totals_predictions": total_predictions,
              "explicit_missing_locked_totals": len(lines)-expected_totals,
              "ats_run": asdict(ats_run), "totals_run": asdict(total_run),
              "integrity": integrity, "foreign_key_violations": foreign_keys}
    write_json(output / "week8_ingestion_manifest.json", result)
    conn.close()
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-lines", type=Path, required=True)
    parser.add_argument("--source-metadata", type=Path, required=True)
    parser.add_argument("--capture-dir", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(source=args.source_lines, metadata=args.source_metadata,
                 capture=args.capture_dir, database=args.database, output=args.output)
    print(json.dumps({key: result[key] for key in
                      ("locked_games", "ats_predictions", "totals_predictions", "explicit_missing_locked_totals")}))


if __name__ == "__main__":
    main()
