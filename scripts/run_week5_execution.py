"""Execute Week 5 in a disposable V3 database from checksummed owner/provider inputs.

This is a local rehearsal, not a cloud production cutover or a model promotion.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sqlite3
import subprocess
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from business_entities.weekly_controller import run_epa_only_model
from business_entities.totals_weekly_model import run_component_totals_shadow_model
from contest_lines import create_contest, list_effective_locked_lines, lock_contest_line
from ingestion import CanonicalTeamResolver, IngestionRequest, ProviderIngestionService
from migrations.runner import apply_migrations, table_row_counts
from operations.providers import CfbdGamesParser, CfbdTeamStatsParser, _write_games, _write_team_stats


ROOT = Path(__file__).resolve().parents[1]
CONTEST_KEY = "splashsports-cfb-2026-w05"
SOURCE = ROOT / "production-weeks" / "2026-week5-splashsports.csv"
METADATA = ROOT / "production-weeks" / "2026-week5-splashsports-lock-metadata.json"
EVIDENCE = ROOT / "outputs" / "2026-week5-execution-20260930-v3" / "provider-evidence"
SOURCE_DB = ROOT / "data" / "cfb.db"
# All supplied October 1–3, 2026 local times precede the November DST change.
CHICAGO = timezone(timedelta(hours=-5), "CDT")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def load_evidence() -> tuple[dict, dict[str, list[dict]], dict[str, dict]]:
    manifest = json.loads((EVIDENCE / "capture-manifest.json").read_text(encoding="utf-8"))
    specs = {item["name"]: item for item in manifest["requests"]}
    payloads: dict[str, list[dict]] = {}
    for name, item in specs.items():
        if item["status"] != "captured":
            raise ValueError(f"provider capture failed: {name}")
        raw = (EVIDENCE / item["path"]).read_bytes()
        if sha(raw) != item["sha256"]:
            raise ValueError(f"provider evidence checksum mismatch: {name}")
        payloads[name] = json.loads(raw)
    return manifest, payloads, specs


def ingest(conn: sqlite3.Connection, records: list[dict], *, name: str,
           spec: dict, parameters: dict, parser: object, writer: object) -> dict:
    raw = json.dumps(records, sort_keys=True, separators=(",", ":")).encode()
    derived = EVIDENCE / f"{name}.derived.json"
    if derived.exists() and derived.read_bytes() != raw:
        raise ValueError(f"derived replay payload conflicts: {name}")
    derived.write_bytes(raw)
    result = ProviderIngestionService().ingest_payload(
        conn,
        IngestionRequest(
            provider="collegefootballdata", endpoint=spec["endpoint"],
            request_parameters=parameters,
            requested_at=iso(spec["requested_at"]), parser_version=parser.version,
            raw_payload_reference=str(derived.relative_to(ROOT)),
            data_type="game_status" if isinstance(parser, CfbdGamesParser) else "contextual",
            expected_payload_sha256=sha(raw),
        ), raw, parser, accepted_writer=writer,
    )
    summary = asdict(result)
    if summary["rows_rejected"]:
        raise ValueError(f"provider custody rejected {name}: {summary['rows_rejected']}")
    return {"name": name, "source_sha256": spec["sha256"], "derived_sha256": sha(raw), **summary}


def reconcile(conn: sqlite3.Connection, games: list[dict], rows: list[dict]) -> list[dict]:
    if len(rows) != 56 or Counter(row["Game Date"] for row in rows) != {
        "2026-10-01": 2, "2026-10-02": 3, "2026-10-03": 51,
    }:
        raise ValueError("Week 5 CSV inventory must be 2/3/51 = 56")
    resolver = CanonicalTeamResolver.from_connection(conn)
    week_games = [game for game in games if game["week"] == 5]
    seen: set[int] = set()
    result: list[dict] = []
    for index, row in enumerate(rows, 1):
        home_res = resolver.resolve("SplashSports", row["Home Team"])
        away_res = resolver.resolve("SplashSports", row["Away Team"])
        if home_res.status != "resolved" or away_res.status != "resolved":
            raise ValueError(f"row {index}: unresolved/ambiguous team names: {home_res}, {away_res}")
        home, away = home_res.canonical_name, away_res.canonical_name
        matches = [game for game in week_games if game["homeTeam"] == home and game["awayTeam"] == away]
        reversed_matches = [game for game in week_games if game["homeTeam"] == away and game["awayTeam"] == home]
        if len(matches) != 1 or reversed_matches:
            raise ValueError(f"row {index}: missing/ambiguous/reversed schedule identity")
        game = matches[0]
        if game["id"] in seen:
            raise ValueError(f"row {index}: duplicate game ID")
        seen.add(game["id"])
        home_spread, total = float(row["Spread"]), float(row["Total"])
        if not math.isfinite(home_spread) or not math.isfinite(total) or total <= 0:
            raise ValueError(f"row {index}: invalid home spread or total")
        source_time = datetime.strptime(row["Game Date"] + " " + row["Game Time"], "%Y-%m-%d %I:%M %p").replace(tzinfo=CHICAGO).astimezone(timezone.utc)
        provider_time = iso(game["startDate"])
        difference_minutes = int((source_time - provider_time).total_seconds() / 60)
        if difference_minutes not in (0, 1) or (difference_minutes == 1 and game["id"] != 401864513):
            raise ValueError(f"row {index}: unexplained kickoff difference {difference_minutes} minutes")
        result.append({
            "csv_row": index, "game_id": game["id"], "raw_away": row["Away Team"],
            "raw_home": row["Home Team"], "away": away, "home": home,
            "away_resolution": away_res.method, "home_resolution": home_res.method,
            "home_spread": home_spread, "locked_total": total,
            "source_kickoff_utc": source_time.isoformat(), "provider_kickoff_utc": provider_time.isoformat(),
            "kickoff_discrepancy_minutes": difference_minutes,
            "home_classification": game.get("homeClassification"),
            "away_classification": game.get("awayClassification"),
            "source_note": row.get("Notes", ""), "status": "MATCHED" if difference_minutes == 0 else "MATCHED_ONE_MINUTE_SOURCE_DIFFERENCE",
        })
    expected = {game["id"] for game in week_games if game.get("homeClassification") == game.get("awayClassification") == "fbs"}
    if seen != expected:
        raise ValueError(f"source/schedule FBS inventory mismatch: missing={sorted(expected-seen)}, extra={sorted(seen-expected)}")
    return result


def correct_existing_schedule(conn: sqlite3.Connection, games: list[dict]) -> list[dict]:
    """Record and correct the one provider-confirmed legacy kickoff conflict."""
    corrections = []
    for game in games:
        if game["week"] > 5 or game.get("homeClassification") != "fbs" or game.get("awayClassification") != "fbs":
            continue
        stored = conn.execute(
            "SELECT season,week,home_team,away_team,start_date FROM games WHERE game_id=?",
            (game["id"],),
        ).fetchone()
        if stored is None:
            continue
        if stored[:4] != (game["season"], game["week"], game["homeTeam"], game["awayTeam"]):
            raise ValueError(f"existing matchup identity conflicts with CFBD: {game['id']}")
        if iso(stored[4]) == iso(game["startDate"]):
            continue
        if game["id"] != 401858207 or game["week"] != 1:
            raise ValueError(f"unreviewed existing kickoff conflict: {game['id']}")
        corrections.append({
            "game_id": game["id"], "old_start_date": stored[4],
            "new_start_date": game["startDate"], "source": "CFBD 2026 games capture",
            "reason": "Provider schedule moved kickoff by 30 minutes; execution-copy correction only",
        })
        conn.execute("UPDATE games SET start_date=? WHERE game_id=?", (game["startDate"], game["id"]))
    return corrections


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    target, output = args.database.resolve(), args.output.resolve()
    if not target.is_relative_to(ROOT) or target == SOURCE_DB or not output.is_relative_to(ROOT):
        parser.error("target and output must be isolated paths inside the Week 5 worktree")
    if output.exists() and (
        any(path.name not in ("provider-evidence", "prior-evidence") for path in output.iterdir())
        or not EVIDENCE.is_relative_to(output)
    ):
        parser.error("output directory already contains execution results")
    if sha(SOURCE_DB.read_bytes()) != "09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842":
        raise ValueError("authoritative source database changed")
    meta = json.loads(METADATA.read_text(encoding="utf-8"))
    raw_csv = SOURCE.read_bytes()
    canonical_csv_hash = sha(raw_csv.replace(b"\r\n", b"\n"))
    if canonical_csv_hash != meta["canonical_csv_sha256"]:
        raise ValueError("canonical Week 5 CSV checksum mismatch")
    manifest, payloads, specs = load_evidence()
    with SOURCE.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    output.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target)
    conn.execute("PRAGMA foreign_keys=ON")
    before = table_row_counts(conn)
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("pre-import database integrity failed")
    migrations = apply_migrations(conn)
    additions = []
    for team in payloads["cfbd-2026-fbs-teams"]:
        if team.get("classification") != "fbs":
            raise ValueError("non-FBS identity in FBS team feed")
        if conn.execute("SELECT 1 FROM teams WHERE school=?", (team["school"],)).fetchone():
            continue
        conn.execute("INSERT INTO teams(team_id,school,conference,division) VALUES(?,?,?,?)",
                     (team["id"], team["school"], team.get("conference"), team.get("division")))
        additions.append({"id": team["id"], "school": team["school"]})
    reconciliation = reconcile(conn, payloads["cfbd-2026-games"], rows)
    schedule_corrections = correct_existing_schedule(conn, payloads["cfbd-2026-games"])
    conn.commit()
    games = payloads["cfbd-2026-games"]
    ingestions = []
    for week in range(1, 6):
        week_games = [game for game in games if game["week"] == week and game.get("homeClassification") == game.get("awayClassification") == "fbs"]
        if week < 5 and any(not game.get("completed") for game in week_games):
            raise ValueError(f"incomplete week {week} result feed")
        if week == 5 and any(game.get("completed") for game in week_games):
            raise ValueError("Week 5 feed already contains final scores; refuse retroactive execution")
        ingestions.append(ingest(conn, week_games, name=f"cfbd-week{week}-games", spec=specs["cfbd-2026-games"],
                                 parameters={"year": 2026, "week": week, "classification": "fbs"},
                                 parser=CfbdGamesParser(), writer=_write_games))
    ingestions.append(ingest(conn, payloads["cfbd-week4-advanced"], name="cfbd-week4-advanced", spec=specs["cfbd-week4-advanced"],
                             parameters={"year": 2026, "endWeek": 4, "excludeGarbageTime": "true"},
                             parser=CfbdTeamStatsParser(), writer=_write_team_stats))
    generated_at = datetime.now(timezone.utc)
    if any(iso(row["provider_kickoff_utc"]) <= generated_at for row in reconciliation):
        raise ValueError("one or more Week 5 kickoffs elapsed before locking")
    contest = create_contest(conn, contest_key=CONTEST_KEY, name="SplashSports 2026 Week 5",
                             season=2026, week=5, source="SplashSports", source_contest_id=CONTEST_KEY,
                             created_at=generated_at, provenance="owner-supplied Week 5 screenshot transcription; local execution copy")
    metadata_hash = sha(METADATA.read_bytes())
    for row in reconciliation:
        locked = lock_contest_line(conn, contest_id=contest.id, game_id=row["game_id"],
                                   raw_home_team=row["raw_home"], raw_away_team=row["raw_away"],
                                   normalized_home_team=row["home"], normalized_away_team=row["away"],
                                   home_spread=row["home_spread"], total=row["locked_total"],
                                   source="SplashSports", source_line_id=f"csv-row:{row['csv_row']}",
                                   payload_sha256=canonical_csv_hash, locked_at=generated_at,
                                   provenance=f"week5 owner input;csv_sha256={canonical_csv_hash};metadata_sha256={metadata_hash};screenshot={row['source_note']};local-execution-copy")
        row["locked_line_id"] = locked.line.id
        row["lock_status"] = "CREATED" if locked.created else "IDENTICAL_REPLAY"
    conn.commit()
    lines = list_effective_locked_lines(conn, contest.id, as_of=generated_at)
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    ats_run = run_epa_only_model(conn, contest_id=contest.id, model_run_key="week5-20260930:epa",
                                 code_commit_sha=commit, generated_at=generated_at, provenance="owner-request://2026-week5-execution")
    totals_run = run_component_totals_shadow_model(conn, contest_id=contest.id, model_run_key="week5-20260930:component-totals",
                                                     code_commit_sha=commit, generated_at=generated_at, provenance="owner-request://2026-week5-execution")
    conn.commit()
    after = table_row_counts(conn)
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    if integrity != "ok" or foreign_keys:
        raise ValueError("post-model database integrity failed")
    dump(output / "week5_ingestion_manifest.json", {
        "status": "LOCAL_REHEARSAL", "execution_code_commit_sha": commit, "generated_at": generated_at.isoformat(),
        "source_database_sha256": sha(SOURCE_DB.read_bytes()), "source_csv_checkout_sha256": sha(raw_csv),
        "source_csv_canonical_sha256": canonical_csv_hash, "metadata_sha256": metadata_hash,
        "provider_capture": manifest, "provider_ingestion": ingestions, "migration_versions": [item.version for item in migrations],
        "before_counts": before, "after_counts": after, "added_fbs_teams": additions,
        "schedule_corrections": schedule_corrections,
        "locked_count": len(lines), "ats_run": asdict(ats_run), "totals_run": asdict(totals_run),
        "integrity": integrity, "foreign_key_violations": foreign_keys,
    })
    with (output / "week5_ingestion_reconciliation.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(reconciliation[0])); writer.writeheader(); writer.writerows(reconciliation)
    print(json.dumps({"output": str(output), "locked": len(lines), "ats_run_id": ats_run.id,
                      "totals_run_id": totals_run.id, "integrity": integrity, "fk": foreign_keys}))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
