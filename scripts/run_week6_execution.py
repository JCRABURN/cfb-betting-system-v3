"""Reconcile and lock Week 6, then run unchanged ATS and shadow totals models."""

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
from ingestion import CanonicalTeamResolver, IngestionRequest, ProviderIngestionService
from migrations.runner import apply_migrations, table_row_counts
from operations.providers import CfbdGamesParser, CfbdTeamStatsParser, _write_games, _write_team_stats


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DB = ROOT / "data/cfb.db"
SOURCE = ROOT / "production-weeks/2026-week6-splashsports.csv"
METADATA = ROOT / "production-weeks/2026-week6-splashsports-lock-metadata.json"
PRIOR = ROOT / "outputs/2026-week5-execution-20260930-v4/provider-evidence"
CONTEST_KEY = "splashsports-cfb-2026-w06"
CHICAGO = timezone(timedelta(hours=-5), "CDT")
HAWAII_ASU_KICKOFF = {
    "game_id": 401856808,
    "cfbd_utc": "2026-10-11T01:30:00+00:00",
    "official_utc": "2026-10-11T02:30:00+00:00",
    "source": "https://sundevils.com/event/sun-devil-football-arizona-state-vs-hawaii",
    "corroboration": "https://hawaiiathletics.com/news/2026/10/5/football-rainbow-warriors-hit-the-road-for-contest-at-arizona-state.aspx",
    "reason": "ASU and Hawai'i athletics specify 7:30 p.m. MST; CFBD lists one hour earlier",
}


def sha(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")


def read_capture(directory: Path, manifest: dict, name: str) -> tuple[list[dict], dict]:
    item = next(entry for entry in manifest["requests"] if entry["name"] == name)
    raw = (directory / item["path"]).read_bytes()
    if sha(raw) != item["sha256"] or item["status"] != "captured":
        raise ValueError(f"provider evidence failed checksum/status: {name}")
    records = json.loads(raw)
    if not isinstance(records, list) or len(records) != item["records"]:
        raise ValueError(f"provider evidence failed count: {name}")
    return records, item


def ingest(
    conn: sqlite3.Connection, output: Path, records: list[dict], *, name: str,
    item: dict, parameters: dict, parser: object, writer: object,
) -> dict:
    raw = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    derived = output / "provider-evidence" / f"{name}.derived.json"
    derived.write_bytes(raw)
    result = ProviderIngestionService().ingest_payload(
        conn,
        IngestionRequest(
            provider="collegefootballdata", endpoint=item["endpoint"],
            request_parameters=parameters, requested_at=iso(item["requested_at"]),
            parser_version=parser.version,
            raw_payload_reference=str(derived.relative_to(ROOT)),
            data_type="game_status" if isinstance(parser, CfbdGamesParser) else "contextual",
            expected_payload_sha256=sha(raw),
        ), raw, parser, accepted_writer=writer,
    )
    summary = asdict(result)
    if summary["rows_rejected"]:
        raise ValueError(f"provider custody rejected {name}: {summary['rows_rejected']}")
    return {"name": name, "source_sha256": item["sha256"], "derived_sha256": sha(raw), **summary}


def reconcile(conn: sqlite3.Connection, games: list[dict], rows: list[dict]) -> list[dict]:
    dates = Counter(row["Game Date"] for row in rows)
    expected_dates = {"2026-10-06": 1, "2026-10-07": 2, "2026-10-08": 4,
                      "2026-10-09": 5, "2026-10-10": 46}
    if len(rows) != 58 or dict(dates) != expected_dates:
        raise ValueError(f"Week 6 lock inventory mismatch: rows={len(rows)}, dates={dict(dates)}")
    resolver = CanonicalTeamResolver.from_connection(conn)
    week_games = [game for game in games if game["week"] == 6 and
                  game.get("homeClassification") == game.get("awayClassification") == "fbs"]
    if len(week_games) != 58:
        raise ValueError(f"CFBD Week 6 FBS inventory is {len(week_games)}, expected 58")
    mapped = {}
    for game in week_games:
        home = resolver.resolve("collegefootballdata", game["homeTeam"])
        away = resolver.resolve("collegefootballdata", game["awayTeam"])
        if home.status != "resolved" or away.status != "resolved":
            raise ValueError(f"unresolved provider game identity: {game['id']}")
        key = (away.canonical_name, home.canonical_name)
        if key in mapped:
            raise ValueError(f"duplicate provider matchup: {key}")
        mapped[key] = game
    seen: set[int] = set()
    result: list[dict] = []
    for index, row in enumerate(rows, 1):
        away_res = resolver.resolve("SplashSports", row["Away Team"])
        home_res = resolver.resolve("SplashSports", row["Home Team"])
        if away_res.status != "resolved" or home_res.status != "resolved":
            raise ValueError(f"row {index}: unresolved lock identity: {away_res}, {home_res}")
        away, home = away_res.canonical_name, home_res.canonical_name
        game = mapped.get((away, home))
        if game is None:
            reverse = mapped.get((home, away))
            raise ValueError(f"row {index}: {'reversed' if reverse else 'missing'} provider matchup: {away} @ {home}")
        if game["id"] in seen:
            raise ValueError(f"row {index}: duplicate game ID {game['id']}")
        seen.add(game["id"])
        spread, total = float(row["Spread"]), float(row["Total"])
        if not math.isfinite(spread) or not math.isfinite(total) or total <= 0:
            raise ValueError(f"row {index}: invalid locked spread or total")
        source_time = datetime.strptime(
            row["Game Date"] + " " + row["Game Time"], "%Y-%m-%d %I:%M %p"
        ).replace(tzinfo=CHICAGO).astimezone(timezone.utc)
        provider_time = iso(game["startDate"])
        correction = (
            game["id"] == HAWAII_ASU_KICKOFF["game_id"]
            and provider_time == iso(HAWAII_ASU_KICKOFF["cfbd_utc"])
            and source_time == iso(HAWAII_ASU_KICKOFF["official_utc"])
        )
        if source_time != provider_time and not correction:
            raise ValueError(f"row {index}: kickoff conflict {source_time} vs {provider_time}: {away} @ {home}")
        away_id = conn.execute("SELECT team_id FROM teams WHERE school=?", (away,)).fetchone()
        home_id = conn.execute("SELECT team_id FROM teams WHERE school=?", (home,)).fetchone()
        if away_id is None or home_id is None:
            raise ValueError(f"row {index}: missing provider team ID: {away} @ {home}")
        result.append({
            "csv_row": index, "game_id": game["id"],
            "raw_away": row["Away Team"], "raw_home": row["Home Team"],
            "away": away, "home": home,
            "away_provider_team_id": away_id[0], "home_provider_team_id": home_id[0],
            "away_resolution": away_res.method, "home_resolution": home_res.method,
            "home_spread": spread, "locked_total": total,
            "source_kickoff_utc": source_time.isoformat(),
            "provider_kickoff_utc": provider_time.isoformat(),
            "source_note": row["Notes"],
            "status": "OFFICIAL_TEAM_SCHEDULE_KICKOFF_CORRECTION" if correction else "MATCHED",
        })
    if seen != {game["id"] for game in week_games}:
        raise ValueError("locked game IDs differ from the full CFBD Week 6 FBS inventory")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    target, output = args.database.resolve(), args.output.resolve()
    if not target.is_relative_to(ROOT) or target == SOURCE_DB or target.exists():
        parser.error("database must be a new isolated path inside this worktree")
    if not output.is_relative_to(ROOT) or not output.is_dir():
        parser.error("output must be an existing isolated Week 6 directory")
    metadata = json.loads(METADATA.read_text(encoding="utf-8"))
    raw_csv = SOURCE.read_bytes()
    canonical_sha = sha(raw_csv.replace(b"\r\n", b"\n"))
    if canonical_sha != metadata["canonical_csv_sha256"] or metadata["game_count"] != 58:
        raise ValueError("Week 6 source lock checksum/count mismatch")
    with SOURCE.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    if len({(row["Away Team"], row["Home Team"]) for row in rows}) != 58:
        raise ValueError("duplicate locked matchups")
    if any(not row["Spread"] or not row["Total"] for row in rows):
        raise ValueError("missing locked spread or total")
    evidence = output / "provider-evidence"
    core = evidence / "core"
    current = json.loads((core / "capture-manifest.json").read_text(encoding="utf-8"))
    prior = json.loads((PRIOR / "capture-manifest.json").read_text(encoding="utf-8"))
    games, games_item = read_capture(core, current, "cfbd-2026-games")
    teams, _ = read_capture(core, current, "cfbd-2026-fbs-teams")
    stats5, stats5_item = read_capture(core, current, "cfbd-week5-advanced")
    stats4, stats4_item = read_capture(PRIOR, prior, "cfbd-week4-advanced")
    source_hash = sha(SOURCE_DB.read_bytes())
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE_DB, target)
    if sha(target.read_bytes()) != source_hash:
        raise ValueError("isolated database copy checksum mismatch")
    conn = sqlite3.connect(target)
    conn.execute("PRAGMA foreign_keys=ON")
    before = table_row_counts(conn)
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("pre-migration isolated database integrity failed")
    migrations = apply_migrations(conn)
    added_teams = []
    for team in teams:
        if team.get("classification") != "fbs":
            raise ValueError("non-FBS identity in CFBD FBS team feed")
        if conn.execute("SELECT 1 FROM teams WHERE school=?", (team["school"],)).fetchone():
            continue
        conn.execute("INSERT INTO teams(team_id,school,conference,division) VALUES(?,?,?,?)",
                     (team["id"], team["school"], team.get("conference"), team.get("division")))
        added_teams.append({"id": team["id"], "school": team["school"]})
    reconciliation = reconcile(conn, games, rows)
    conn.commit()
    ingestions = []
    for week in range(2, 7):
        week_games = [game for game in games if game["week"] == week and
                      game.get("homeClassification") == game.get("awayClassification") == "fbs"]
        if week < 6 and any(not game.get("completed") for game in week_games):
            raise ValueError(f"Week {week} game results are incomplete")
        if week == 6 and any(game.get("completed") for game in week_games):
            raise ValueError("Week 6 already contains final scores")
        ingestions.append(ingest(
            conn, output, week_games, name=f"cfbd-week{week}-games",
            item=games_item, parameters={"year": 2026, "week": week, "classification": "fbs"},
            parser=CfbdGamesParser(), writer=_write_games,
        ))
    kickoff_corrections = []
    for row in reconciliation:
        if row["status"] != "OFFICIAL_TEAM_SCHEDULE_KICKOFF_CORRECTION":
            continue
        stored = conn.execute("SELECT start_date FROM games WHERE game_id=?", (row["game_id"],)).fetchone()
        if stored is None or iso(stored[0]) != iso(row["provider_kickoff_utc"]):
            raise ValueError(f"kickoff correction does not match ingested provider schedule: {row['game_id']}")
        conn.execute("UPDATE games SET start_date=? WHERE game_id=?",
                     (row["source_kickoff_utc"], row["game_id"]))
        kickoff_corrections.append({**HAWAII_ASU_KICKOFF, "old_start_date": stored[0],
                                    "new_start_date": row["source_kickoff_utc"]})
    conn.commit()
    for week, records, item in ((4, stats4, stats4_item), (5, stats5, stats5_item)):
        ingestions.append(ingest(
            conn, output, records, name=f"cfbd-week{week}-advanced",
            item=item, parameters={"year": 2026, "endWeek": week, "excludeGarbageTime": "true"},
            parser=CfbdTeamStatsParser(), writer=_write_team_stats,
        ))
    now = datetime.now(timezone.utc)
    contest = create_contest(
        conn, contest_key=CONTEST_KEY, name="SplashSports 2026 Week 6",
        season=2026, week=6, source="SplashSports", source_contest_id=CONTEST_KEY,
        created_at=now, provenance="owner-supplied Week 6 screenshot transcription; isolated execution copy",
    )
    metadata_hash = sha(METADATA.read_bytes())
    for row in reconciliation:
        locked = lock_contest_line(
            conn, contest_id=contest.id, game_id=row["game_id"],
            raw_home_team=row["raw_home"], raw_away_team=row["raw_away"],
            normalized_home_team=row["home"], normalized_away_team=row["away"],
            home_spread=row["home_spread"], total=row["locked_total"],
            source="SplashSports", source_line_id=f"csv-row:{row['csv_row']}",
            payload_sha256=canonical_sha, locked_at=now,
            provenance=(f"week6 owner lock;csv_sha256={canonical_sha};metadata_sha256={metadata_hash};"
                        f"screenshot={row['source_note']};isolated-execution-copy"),
        )
        row["locked_line_id"] = locked.line.id
    conn.commit()
    lines = list_effective_locked_lines(conn, contest.id, as_of=now)
    if len(lines) != 58 or any(line.total is None for line in lines):
        raise ValueError("lock custody failed 58-spread/58-total gate")
    lock_hash = locked_line_snapshot_sha256(lines)
    with (output / "week6_ingestion_reconciliation.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(reconciliation[0]))
        writer.writeheader()
        writer.writerows(reconciliation)
    write_json(output / "week6_locked_line_snapshot.json", {
        "contest_key": CONTEST_KEY, "source_csv_sha256": canonical_sha,
        "metadata_sha256": metadata_hash, "locked_at_utc": now.isoformat(),
        "locked_line_snapshot_sha256": lock_hash,
        "lines": reconciliation,
    })
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    ats_run = run_epa_only_model(
        conn, contest_id=contest.id, model_run_key="week6-20261006:epa",
        code_commit_sha=commit, generated_at=now,
        provenance="owner-request://2026-week6-execution",
    )
    total_run = run_component_totals_shadow_model(
        conn, contest_id=contest.id, model_run_key="week6-20261006:component-totals",
        code_commit_sha=commit, generated_at=now,
        provenance="owner-request://2026-week6-execution",
    )
    conn.commit()
    after = table_row_counts(conn)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    if integrity != "ok" or fk:
        raise ValueError("post-model isolated database integrity failed")
    ats_count = conn.execute("SELECT COUNT(*) FROM model_predictions WHERE model_run_id=?", (ats_run.id,)).fetchone()[0]
    total_count = conn.execute("SELECT COUNT(*) FROM total_model_predictions WHERE total_model_run_id=?", (total_run.id,)).fetchone()[0]
    write_json(output / "week6_ingestion_manifest.json", {
        "generated_at_utc": now.isoformat(), "code_commit_sha": commit,
        "source_database_sha256": source_hash,
        "source_csv_sha256": canonical_sha, "metadata_sha256": metadata_hash,
        "lock_snapshot_sha256": lock_hash,
        "provider_capture": current, "provider_ingestion": ingestions,
        "prior_week4_stats_capture": stats4_item,
        "migration_versions": [item.version for item in migrations],
        "before_counts": before, "after_counts": after,
        "added_fbs_teams": added_teams,
        "kickoff_corrections": kickoff_corrections,
        "locked_count": len(lines), "ats_run": asdict(ats_run),
        "totals_run": asdict(total_run), "ats_predictions": ats_count,
        "totals_predictions": total_count,
        "integrity": integrity, "foreign_key_violations": fk,
    })
    print(json.dumps({"locked": len(lines), "ats_predictions": ats_count,
                      "totals_predictions": total_count, "earliest_kickoff_utc":
                      min(row["provider_kickoff_utc"] for row in reconciliation),
                      "generated_at_utc": now.isoformat(), "integrity": integrity,
                      "foreign_keys": fk}))
    conn.close()


if __name__ == "__main__":
    main()
