"""Adversarial acceptance checks for the frozen Week 5 source and generated card."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.run_week5_execution import reconcile
from contest_lines import create_contest, lock_contest_line
from business_entities.weekly_controller import run_epa_only_model


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "production-weeks/2026-week5-splashsports.csv"
META = ROOT / "production-weeks/2026-week5-splashsports-lock-metadata.json"
OUTPUT = ROOT / "outputs/2026-week5-execution-20260930-v4"
GAMES = OUTPUT / "provider-evidence/cfbd-2026-games.json"


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


@pytest.fixture
def schedule_and_conn():
    games = json.loads(GAMES.read_text(encoding="utf-8"))
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE teams (school TEXT NOT NULL)")
    conn.execute("CREATE TABLE provider_team_aliases (id INTEGER PRIMARY KEY, provider TEXT, raw_team_name TEXT, canonical_team TEXT)")
    teams = sorted({game[side] for game in games if game["week"] == 5 for side in ("homeTeam", "awayTeam")})
    conn.executemany("INSERT INTO teams(school) VALUES(?)", ((team,) for team in teams))
    yield games, conn
    conn.close()


def test_authoritative_source_reconciles_all_56_and_preserves_one_minute_discrepancy(schedule_and_conn):
    games, conn = schedule_and_conn
    source_bytes = SOURCE.read_bytes()
    declared = json.loads(META.read_text(encoding="utf-8"))["canonical_csv_sha256"]
    assert hashlib.sha256(source_bytes.replace(b"\r\n", b"\n")).hexdigest() == declared
    result = reconcile(conn, games, rows(SOURCE))
    assert len(result) == len({row["game_id"] for row in result}) == 56
    assert Counter(row["status"] for row in result) == {
        "MATCHED": 55, "MATCHED_ONE_MINUTE_SOURCE_DIFFERENCE": 1,
    }
    assert {row["game_id"] for row in result if row["kickoff_discrepancy_minutes"]} == {401864513}
    assert all(row["home_classification"] == row["away_classification"] == "fbs" for row in result)


@pytest.mark.parametrize("corruption", ("duplicate", "reversed", "bad_total", "wrong_kickoff"))
def test_bad_source_never_silently_locks(schedule_and_conn, corruption):
    games, conn = schedule_and_conn
    source = [dict(row) for row in rows(SOURCE)]
    if corruption == "duplicate":
        source[1] = dict(source[0])
    elif corruption == "reversed":
        source[0]["Away Team"], source[0]["Home Team"] = source[0]["Home Team"], source[0]["Away Team"]
    elif corruption == "bad_total":
        source[0]["Total"] = "0"
    else:
        source[0]["Game Time"] = "7:30 PM"
    with pytest.raises(ValueError):
        reconcile(conn, games, source)


def test_generated_cards_use_locked_lines_and_correct_ats_sign():
    ats = rows(OUTPUT / "week5_ats_full_card.csv")
    totals = rows(OUTPUT / "week5_totals_full_card.csv")
    reconciliation = rows(OUTPUT / "week5_ingestion_reconciliation.csv")
    source = rows(SOURCE)
    assert len(ats) == len(totals) == len(reconciliation) == len(source) == 56
    assert len({row["game_id"] for row in ats}) == 56
    source_by_game = {row["game_id"]: source[int(row["csv_row"])-1] for row in reconciliation}
    totals_by_game = {row["game_id"]: row for row in totals}
    for row in ats:
        line = source_by_game[row["game_id"]]
        assert float(row["locked_home_spread"]) == float(line["Spread"])
        assert float(totals_by_game[row["game_id"]]["locked_total"]) == float(line["Total"])
        edge = float(row["projected_home_margin"]) + float(row["locked_home_spread"])
        assert float(row["home_ats_edge"]) == pytest.approx(edge)
        assert row["selected_side"] == ("home" if edge > 0 else "away" if edge < 0 else "")
        assert row["fallback_code"] == ""
        assert 1 <= int(row["confidence"]) <= 5


def test_three_top_fives_are_complete_deterministic_and_pregame():
    ats = rows(OUTPUT / "week5_ats_full_card.csv")
    ats_top = rows(OUTPUT / "week5_official_ats_top5.csv")
    shadow_ats_top = rows(OUTPUT / "week5_shadow_ats_top5.csv")
    total_top = rows(OUTPUT / "week5_shadow_totals_top5.csv")
    combined = rows(OUTPUT / "week5_combined_top5.csv")
    assert len(ats_top) == len(shadow_ats_top) == len(total_top) == len(combined) == 5
    assert all(row["uncertainty_points"] == "" and row["confidence"] == "1" for row in ats)
    assert [int(row["locked_line_id"]) for row in ats_top] == sorted(int(row["locked_line_id"]) for row in ats)[:5]
    assert [float(row["shadow_uncertainty_points"]) for row in shadow_ats_top] == sorted(float(row["shadow_uncertainty_points"]) for row in shadow_ats_top)
    assert {row["game_id"] for row in ats_top} == {row["game_id"] for row in ats if row["top_five"] == "True"}
    assert [int(row["rank"]) for row in ats_top] == [5, 4, 3, 2, 1]
    assert len({row["game_id"] for row in combined}) == 5
    assert [int(row["rank"]) for row in combined] == [1, 2, 3, 4, 5]
    assert all(row["probability_status"] == "NOT_EMPIRICALLY_VALIDATED" for row in combined)
    run_time = datetime.fromisoformat(json.loads((OUTPUT / "week5_card_manifest.json").read_text())["generated_at"])
    assert all(run_time < datetime.fromisoformat(row["provider_kickoff_utc"]) for row in rows(OUTPUT / "week5_ingestion_reconciliation.csv"))


@pytest.mark.parametrize(
    ("offset", "kickoff_value", "expected_feature_calls", "expected_skip_reason"),
    (
        (-1, None, 1, "missing_point_in_time_epa"),
        (0, None, 0, "kickoff_elapsed"),
        (1, None, 0, "kickoff_elapsed"),
        (-1, "invalid-kickoff", 0, "kickoff_elapsed"),
    ),
)
def test_ats_model_blocks_feature_access_at_and_after_exact_kickoff(
    temp_db, monkeypatch, offset, kickoff_value, expected_feature_calls, expected_skip_reason
):
    from models import backtest_harness as harness

    conn = temp_db.get_connection()
    kickoff = datetime(2026, 9, 30, 17, tzinfo=timezone.utc)
    locked_at = kickoff - timedelta(days=1)
    contest = create_contest(
        conn,
        contest_key="exact-kickoff-ats-guard",
        name="Exact kickoff ATS guard",
        season=2026,
        week=5,
        source="fixture",
        provenance="fixture://exact-kickoff-ats-guard",
        created_at=locked_at,
    )
    conn.execute(
        "INSERT INTO games (game_id, season, week, home_team, away_team, start_date) "
        "VALUES (9001, 2026, 5, 'Home', 'Away', ?)",
        (kickoff_value or kickoff.isoformat(),),
    )
    lock_contest_line(
        conn,
        contest_id=contest.id,
        game_id=9001,
        raw_home_team="Home",
        raw_away_team="Away",
        normalized_home_team="Home",
        normalized_away_team="Away",
        home_spread=-3.5,
        source="fixture",
        source_line_id="exact-kickoff-line",
        provenance="fixture://exact-kickoff-line",
        payload_sha256="a" * 64,
        locked_at=locked_at,
    )
    monkeypatch.setattr(harness, "available_seasons_before", lambda *args: [])
    monkeypatch.setattr(harness, "build_training_set", lambda *args: ([], []))
    feature_calls = []

    def spy_get_pregame_stats(*args):
        feature_calls.append(args)
        return None

    monkeypatch.setattr(harness, "get_pregame_stats", spy_get_pregame_stats)
    run = run_epa_only_model(
        conn,
        contest_id=contest.id,
        model_run_key=f"exact-kickoff-ats-guard-{offset}",
        code_commit_sha="b" * 40,
        generated_at=kickoff + timedelta(seconds=offset),
        provenance="fixture://exact-kickoff-ats-guard",
    )
    assert len(feature_calls) == expected_feature_calls
    assert f"9001:{expected_skip_reason}" in run.provenance
