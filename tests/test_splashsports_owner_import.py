import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingestion import CanonicalTeamResolver, IngestionRequest
from operations.providers import CfbdTeamStatsParser
from operations.splashsports import (
    OWNER_MODEL_IMPORT_FORMAT,
    OWNER_MODEL_IMPORT_VERSION,
    SplashSportsImportError,
    SplashSportsImportRequest,
    build_splashsports_manifest,
    ingest_owner_reviewed_schedule,
)


CAPTURED_AT = datetime(2026, 9, 9, 13, 39, tzinfo=timezone.utc)
IMPORTED_AT = datetime(2026, 9, 10, 1, 0, tzinfo=timezone.utc)
HEADER = (
    "game_id,season,week,game_date,start_time,away_team,home_team,"
    "away_spread,home_spread,locked_total,favorite,favorite_line,underdog,"
    "source,locked_at,source_image,lock_status"
)
WEEK_2_INPUT = (
    Path(__file__).resolve().parents[1]
    / "production-weeks"
    / "CFB_2026_Week2_Model_Import.csv"
)
WEEK_2_INPUT_SHA256 = (
    "1b2fed8f991dbdde2bb709d106d2c36aae2cbace9e937effbbb712bc50ce7432"
)
WEEK_1_EVIDENCE = (
    Path(__file__).resolve().parents[1]
    / "production-weeks"
    / "evidence"
    / "2026-week2"
)
WEEK_1_EPA_RAW_SHA256 = (
    "0247baa317f1bfdf44790f87cb0010245fffc0c5ba93c44c6d7aa7bf2ca279e4"
)


def _request(path, expected=2):
    return SplashSportsImportRequest(
        source_path=path,
        input_format=OWNER_MODEL_IMPORT_FORMAT,
        season=2026,
        week=2,
        contest_key="splashsports-2026-week-2",
        contest_name="SplashSports 2026 Week 2",
        source_contest_id="splashsports-2026-week-2",
        expected_lined_game_count=expected,
        captured_at=CAPTURED_AT,
        imported_by="repository-owner",
        provenance="owner-reviewed-week-2-model-import",
    )


def _seed_identity_universe(conn):
    conn.executemany(
        "INSERT INTO teams (team_id, school) VALUES (?, ?)",
        ((1, "App State"), (2, "Air Force")),
    )
    conn.execute(
        "INSERT INTO games "
        "(game_id, season, week, start_date, home_team, away_team, completed) "
        "VALUES (99, 2025, 1, '2025-08-30T17:00:00+00:00', "
        "'Sacramento State', 'North Dakota State', 1)"
    )
    conn.commit()


def _write_valid(path):
    path.write_text(
        HEADER
        + "\n"
        + "2026_W02_01,2026,2,2026-09-12,11:00 AM,Appalachian State,"
        "Air Force,3.5,-3.5,51.5,Air Force,-3.5,Appalachian State,"
        "SplashSports,2026-09-09 08:39 CDT,Screenshot 1,LOCKED\n"
        + "2026_W02_02,2026,2,2026-09-12,6:00 PM,North Dakota State,"
        "Sacramento State,-2.5,2.5,47.5,North Dakota State,-2.5,"
        "Sacramento State,SplashSports,2026-09-09 08:39 CDT,"
        "Screenshot 1,LOCKED\n",
        encoding="utf-8",
    )


def test_owner_reviewed_import_resolves_aliases_and_existing_fcs_identities(
    temp_db, tmp_path
):
    conn = temp_db.get_connection()
    _seed_identity_universe(conn)
    path = tmp_path / "week2.csv"
    _write_valid(path)
    team_count = conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0]

    first = ingest_owner_reviewed_schedule(
        conn, _request(path), imported_at=IMPORTED_AT
    )
    second = ingest_owner_reviewed_schedule(
        conn, _request(path), imported_at=IMPORTED_AT
    )
    manifest = build_splashsports_manifest(conn, _request(path))

    assert first.requested_count == first.inserted_count == 2
    assert first.existing_count == 0
    assert second.inserted_count == 0
    assert second.existing_count == 2
    assert len(set(first.game_ids)) == 2
    assert conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0] == team_count
    assert conn.execute(
        "SELECT start_date FROM games WHERE game_id = ?", (first.game_ids[0],)
    ).fetchone()[0] == "2026-09-12T16:00:00+00:00"
    lines = manifest.payload["lines"]
    assert len(lines) == 2
    assert lines[0]["raw_away_team"] == "Appalachian State"
    assert lines[0]["normalized_away_team"] == "App State"
    assert lines[1]["normalized_away_team"] == "North Dakota State"
    assert lines[0]["owner_reviewed_custody"]["source_image"] == "Screenshot 1"
    ingestion_source = (
        f"{OWNER_MODEL_IMPORT_VERSION}:"
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}"
    )
    assert conn.execute(
        "SELECT COUNT(*) FROM ingestion_runs WHERE source = ?",
        (ingestion_source,),
    ).fetchone()[0] == 1
    conn.close()


def test_owner_import_reuses_existing_game_identity_without_duplicate_team(
    temp_db, tmp_path
):
    conn = temp_db.get_connection()
    _seed_identity_universe(conn)
    path = tmp_path / "week2.csv"
    _write_valid(path)

    result = ingest_owner_reviewed_schedule(
        conn, _request(path), imported_at=IMPORTED_AT
    )

    assert result.inserted_count == 2
    assert conn.execute(
        "SELECT COUNT(*) FROM teams WHERE school = 'North Dakota State'"
    ).fetchone()[0] == 0
    conn.close()


def test_cfbd_stats_reuse_exact_historical_fcs_identity_without_team_row(temp_db):
    conn = temp_db.get_connection()
    _seed_identity_universe(conn)
    parsed = CfbdTeamStatsParser().parse(
        conn,
        CanonicalTeamResolver.from_connection(conn),
        "collegefootballdata",
        IngestionRequest(
            provider="collegefootballdata",
            endpoint="https://api.collegefootballdata.com/stats/season/advanced",
            request_parameters={"year": 2026, "endWeek": 1},
            requested_at=CAPTURED_AT,
            parser_version="cfbd_team_stats_v1",
            raw_payload_reference="fixture://cfbd-fcs-stats",
            data_type="contextual",
        ),
        0,
        {
            "team": "North Dakota State",
            "offense": {"ppa": 0.25, "successRate": 0.5},
            "defense": {
                "ppa": -0.10,
                "successRate": 0.4,
                "havoc": {"total": 0.2},
            },
        },
    )

    assert parsed.team == "North Dakota State"
    assert conn.execute(
        "SELECT COUNT(*) FROM teams WHERE school = 'North Dakota State'"
    ).fetchone()[0] == 0
    conn.close()


def test_week_2_cfbd_replay_bundle_binds_the_exact_archived_payload():
    raw_path = WEEK_1_EVIDENCE / "cfbd-week1-stats.raw.json"
    bundle_path = WEEK_1_EVIDENCE / "cfbd-week1-stats-replay-bundle.json"
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))

    assert hashlib.sha256(raw_path.read_bytes()).hexdigest() == WEEK_1_EPA_RAW_SHA256
    assert bundle["capture_scope"] == "pregame"
    assert bundle["context_capture"] is False
    assert bundle["season"] == 2026
    assert bundle["week"] == 2
    assert bundle["payloads"] == [
        {
            "data_type": "contextual",
            "endpoint": "https://api.collegefootballdata.com/stats/season/advanced",
            "parser_version": "cfbd_team_stats_v1",
            "payload_path": "cfbd-week1-stats.raw.json",
            "payload_sha256": WEEK_1_EPA_RAW_SHA256,
            "provider": "collegefootballdata",
            "raw_payload_reference": (
                "repo://production-weeks/evidence/2026-week2/"
                "cfbd-week1-stats.raw.json"
            ),
            "request_parameters": {
                "endWeek": 1,
                "excludeGarbageTime": True,
                "year": 2026,
            },
            "requested_at": "2026-09-09T13:38:46.896384+00:00",
        }
    ]


def test_owner_reviewed_import_rejects_asymmetric_spreads(temp_db, tmp_path):
    conn = temp_db.get_connection()
    _seed_identity_universe(conn)
    path = tmp_path / "bad-spread.csv"
    _write_valid(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace("3.5,-3.5", "3.5,-4.5", 1),
        encoding="utf-8",
    )

    with pytest.raises(SplashSportsImportError, match="do not sum to zero"):
        ingest_owner_reviewed_schedule(conn, _request(path), imported_at=IMPORTED_AT)
    assert conn.execute(
        "SELECT COUNT(*) FROM games WHERE season = 2026 AND week = 2"
    ).fetchone()[0] == 0
    conn.close()


def test_owner_reviewed_import_rejects_lock_timestamp_mismatch(temp_db, tmp_path):
    conn = temp_db.get_connection()
    _seed_identity_universe(conn)
    path = tmp_path / "bad-time.csv"
    _write_valid(path)
    request = _request(path)
    request = SplashSportsImportRequest(
        **{**request.__dict__, "captured_at": datetime(2026, 9, 9, 14, tzinfo=timezone.utc)}
    )

    with pytest.raises(SplashSportsImportError, match="disagrees with captured_at"):
        ingest_owner_reviewed_schedule(conn, request, imported_at=IMPORTED_AT)
    conn.close()


def test_owner_reviewed_import_rejects_noncontiguous_source_ids(temp_db, tmp_path):
    conn = temp_db.get_connection()
    _seed_identity_universe(conn)
    path = tmp_path / "bad-id.csv"
    _write_valid(path)
    path.write_text(
        path.read_text(encoding="utf-8").replace("2026_W02_02", "2026_W02_99"),
        encoding="utf-8",
    )

    with pytest.raises(SplashSportsImportError, match="sequence"):
        ingest_owner_reviewed_schedule(conn, _request(path), imported_at=IMPORTED_AT)
    conn.close()


def test_week_2_owner_input_is_the_exact_complete_immutable_slate():
    assert hashlib.sha256(WEEK_2_INPUT.read_bytes()).hexdigest() == WEEK_2_INPUT_SHA256
    with WEEK_2_INPUT.open(newline="", encoding="utf-8-sig") as source:
        rows = list(csv.DictReader(source))
    assert len(rows) == 49
    assert [row["game_id"] for row in rows] == [
        f"2026_W02_{sequence:02d}" for sequence in range(1, 50)
    ]
    assert all(row["source"] == "SplashSports" for row in rows)
    assert all(row["lock_status"] == "LOCKED" for row in rows)
    assert all(row["locked_at"] == "2026-09-09 08:39 CDT" for row in rows)
    assert all(row["locked_total"].strip() for row in rows)
    assert all(
        abs(float(row["away_spread"]) + float(row["home_spread"])) < 1e-9
        for row in rows
    )
