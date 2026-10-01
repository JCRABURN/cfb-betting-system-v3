"""Adversarial acceptance checks for the frozen Week 5 source and generated card."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

import pytest

from scripts.run_week5_execution import reconcile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "production-weeks/2026-week5-splashsports.csv"
META = ROOT / "production-weeks/2026-week5-splashsports-lock-metadata.json"
OUTPUT = ROOT / "outputs/2026-week5-execution-20260930-v3"
GAMES = OUTPUT / "provider-evidence/cfbd-2026-games.json"


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


@pytest.fixture
def schedule_and_conn():
    games = json.loads(GAMES.read_text(encoding="utf-8"))
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE teams (school TEXT NOT NULL)")
    conn.execute("CREATE TABLE provider_team_aliases (provider TEXT, raw_team_name TEXT, canonical_team TEXT)")
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
    total_top = rows(OUTPUT / "week5_shadow_totals_top5.csv")
    combined = rows(OUTPUT / "week5_combined_top5.csv")
    assert len(ats_top) == len(total_top) == len(combined) == 5
    assert {row["game_id"] for row in ats_top} == {row["game_id"] for row in ats if row["top_five"] == "True"}
    assert [int(row["rank"]) for row in ats_top] == [5, 4, 3, 2, 1]
    assert len({row["game_id"] for row in combined}) == 5
    assert [int(row["rank"]) for row in combined] == [1, 2, 3, 4, 5]
    assert all(row["probability_status"] == "NOT_EMPIRICALLY_VALIDATED" for row in combined)
    run_time = datetime.fromisoformat(json.loads((OUTPUT / "week5_card_manifest.json").read_text())["generated_at"])
    assert all(run_time < datetime.fromisoformat(row["provider_kickoff_utc"]) for row in rows(OUTPUT / "week5_ingestion_reconciliation.csv"))
