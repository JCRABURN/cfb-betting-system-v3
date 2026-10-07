"""Acceptance and adversarial checks for Week 6 locked-line execution."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from business_entities.totals_weekly_model import run_component_totals_shadow_model
from contest_lines import create_contest, lock_contest_line
from scripts.finalize_week6_card import require_complete_market_coverage
from scripts.run_week6_execution import reconcile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "production-weeks/2026-week6-splashsports.csv"
META = ROOT / "production-weeks/2026-week6-splashsports-lock-metadata.json"
OUT = ROOT / "outputs/2026-week6-execution-20261006T2133Z"
SCHEDULE = OUT / "provider-evidence/core/cfbd-2026-games.json"


def csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


@pytest.fixture
def schedule_and_conn():
    games = json.loads(SCHEDULE.read_text(encoding="utf-8"))
    teams = json.loads((OUT / "provider-evidence/core/cfbd-2026-fbs-teams.json").read_text())
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE teams (team_id INTEGER PRIMARY KEY, school TEXT NOT NULL)")
    conn.execute("CREATE TABLE provider_team_aliases (id INTEGER PRIMARY KEY, provider TEXT, raw_team_name TEXT, canonical_team TEXT)")
    conn.executemany("INSERT INTO teams(team_id,school) VALUES(?,?)",
                     ((item["id"], item["school"]) for item in teams))
    yield games, conn
    conn.close()


def test_all_58_authoritative_locks_reconcile_without_repricing(schedule_and_conn):
    games, conn = schedule_and_conn
    source = csv_rows(SOURCE)
    declared = json.loads(META.read_text())
    assert hashlib.sha256(SOURCE.read_bytes().replace(b"\r\n", b"\n")).hexdigest() == declared["canonical_csv_sha256"]
    resolved = reconcile(conn, games, source)
    assert len(source) == len(resolved) == len({item["game_id"] for item in resolved}) == 58
    assert all(item["locked_total"] > 0 for item in resolved)
    for item in resolved:
        original = source[item["csv_row"] - 1]
        assert item["home_spread"] == float(original["Spread"])
        assert item["locked_total"] == float(original["Total"])
    first = resolved[0]
    assert (first["away"], first["home"], first["home_spread"], first["locked_total"]) == (
        "Southern Miss", "Troy", -10.5, 50.5)
    assert {item["status"] for item in resolved} == {
        "MATCHED", "OFFICIAL_TEAM_SCHEDULE_KICKOFF_CORRECTION"}


@pytest.mark.parametrize("corruption", ("duplicate", "reversed", "missing_total", "zero_total", "wrong_kickoff"))
def test_bad_week6_source_fails_visible_reconciliation(schedule_and_conn, corruption):
    games, conn = schedule_and_conn
    source = [dict(row) for row in csv_rows(SOURCE)]
    if corruption == "duplicate":
        source[1] = dict(source[0])
    elif corruption == "reversed":
        source[0]["Away Team"], source[0]["Home Team"] = source[0]["Home Team"], source[0]["Away Team"]
    elif corruption == "missing_total":
        source[0]["Total"] = ""
    elif corruption == "zero_total":
        source[0]["Total"] = "0"
    else:
        source[0]["Game Time"] = "7:30 PM"
    with pytest.raises(ValueError):
        reconcile(conn, games, source)


def test_full_market_coverage_gate_rejects_a_single_total_skip(capsys):
    require_complete_market_coverage(58, 58, 58, [])
    assert "Combined market selections: 116" in capsys.readouterr().out
    with pytest.raises(ValueError, match="TOTALS_COMPLETENESS_BLOCKER.*missing_point_in_time_epa"):
        require_complete_market_coverage(58, 58, 57, [(7, "missing_point_in_time_epa")])


def test_generated_116_selection_pool_uses_stored_comparable_scores():
    ats = csv_rows(OUT / "week6_ats_full_card.csv")
    totals = csv_rows(OUT / "week6_totals_full_card.csv")
    pool = csv_rows(OUT / "week6_combined_candidate_pool.csv")
    official = csv_rows(OUT / "week6_official_ats_top5.csv")
    mixed = csv_rows(OUT / "week6_mixed_market_shadow_top5.csv")
    assert len(ats) == len(totals) == 58
    assert len(pool) == len({(row["game_id"], row["market_type"]) for row in pool}) == 116
    assert {row["game_id"] for row in ats} == {row["game_id"] for row in totals}
    assert all(row["pick"] in ("over", "under") for row in totals)
    assert len(official) == len(mixed) == 5
    assert [float(row["candidate_score"]) for row in pool] == sorted(
        (float(row["candidate_score"]) for row in pool), reverse=True)
    assert [int(row["combined_top5_rank"]) for row in mixed] == [1, 2, 3, 4, 5]
    assert len({row["game_id"] for row in mixed}) == 5
    assert all(row["score_status"] == "CROSS_MARKET_SHADOW_NOT_EMPIRICALLY_VALIDATED" for row in pool)
    assert len(csv_rows(OUT / "week6_ats_shadow_calibration.csv")) == 58
    assert len(csv_rows(OUT / "week6_context_status.csv")) == 58
    assert len(csv_rows(OUT / "week6_qb_injury_review.csv")) == 58
    assert len(csv_rows(OUT / "week6_market_weather_review.csv")) == 58
    assert len(csv_rows(OUT / "week6_decision_shortlist.csv")) == 5


def test_run_and_card_timestamps_precede_every_kickoff_and_source_db_is_unchanged():
    ingestion = json.loads((OUT / "week6_ingestion_manifest.json").read_text())
    card = json.loads((OUT / "week6_card_manifest.json").read_text())
    model = json.loads((OUT / "week6_model_manifest.json").read_text())
    locks = json.loads((OUT / "week6_locked_line_snapshot.json").read_text())["lines"]
    run = datetime.fromisoformat(ingestion["generated_at_utc"])
    sealed = datetime.fromisoformat(card["generated_at"])
    assert all(run < datetime.fromisoformat(item["source_kickoff_utc"]) and
               sealed < datetime.fromisoformat(item["source_kickoff_utc"]) for item in locks)
    assert model["week"] == 6
    assert ingestion["lock_snapshot_sha256"] == model["locked_line_snapshot_sha256"]
    assert card["coverage"]["combined_market_selections"] == 116
    assert hashlib.sha256((ROOT / "data/cfb.db").read_bytes()).hexdigest() == ingestion["source_database_sha256"]


def test_all_sealed_week6_artifact_bytes_match_portable_checksums():
    sealed = json.loads((OUT / "week6_artifact_checksums.json").read_text())
    assert len(sealed["files"]) == 41  # original 40 plus review-only scale diagnostic
    for name, expected in sealed["files"].items():
        assert hashlib.sha256((OUT / name).read_bytes()).hexdigest() == expected
    card = json.loads((OUT / "week6_card_manifest.json").read_text())
    assert hashlib.sha256((OUT / "provider-evidence/context/capture-manifest.json").read_bytes()).hexdigest() == card["context_capture_manifest_sha256"]


def test_frozen_week6_execution_and_independent_human_review_are_distinct():
    from scripts.review_week6_decision import FROZEN_HASHES, LOCK_SHA, MIXED_LABEL, REVIEW_LABEL

    sealed = json.loads((OUT / "week6_artifact_checksums.json").read_text())
    for name, expected in FROZEN_HASHES.items():
        assert sealed["files"][name] == expected
        assert hashlib.sha256((OUT / name).read_bytes()).hexdigest() == expected
    ats = csv_rows(OUT / "week6_ats_full_card.csv")
    totals = csv_rows(OUT / "week6_totals_full_card.csv")
    pool = csv_rows(OUT / "week6_combined_candidate_pool.csv")
    official = csv_rows(OUT / "week6_official_ats_top5.csv")
    mixed = csv_rows(OUT / "week6_mixed_market_shadow_top5.csv")
    decisions = csv_rows(OUT / "week6_decision_shortlist.csv")
    assert (len(ats), len(totals), len(pool), len(official), len(mixed), len(decisions)) == (
        58, 58, 116, 5, 5, 5)
    assert [(row["away"], row["home"], row["selection"], row["locked_line"])
            for row in mixed] == [
        ("UCF", "Oklahoma State", "under", "53.5"),
        ("Tulane", "Army", "over", "47.5"),
        ("UCLA", "Oregon", "under", "59.5"),
        ("Arizona", "West Virginia", "under", "61.5"),
        ("Central Michigan", "Ohio", "over", "46.5"),
    ]
    assert {(row["market_type"], row["game_id"]) for row in decisions} != {
        (row["market_type"], row["game_id"]) for row in mixed}
    assert [int(row["decision_rank"]) for row in decisions] == [1, 2, 3, 4, 5]
    assert all(row["review_label"] == REVIEW_LABEL and row["why_survived_human_review"]
               and row["primary_failure_mode"] and row["cross_market_score_limitation"]
               for row in decisions)
    assert all(row["review_status"] == "HUMAN_REVIEW_OPTION_NOT_SPORTSBOOK_RECOMMENDATION"
               for row in decisions)
    report = (OUT / "week6_execution_report.md").read_text(encoding="utf-8")
    assert "## OFFICIAL GOVERNED ATS TOP 5" in report
    assert f"## {MIXED_LABEL}" in report
    assert f"## {REVIEW_LABEL}" in report
    assert LOCK_SHA in report
    locks = json.loads((OUT / "week6_locked_line_snapshot.json").read_text())
    card = json.loads((OUT / "week6_card_manifest.json").read_text())
    model = json.loads((OUT / "week6_model_manifest.json").read_text())
    ingestion = json.loads((OUT / "week6_ingestion_manifest.json").read_text())
    assert {LOCK_SHA} == {locks["locked_line_snapshot_sha256"],
                          card["ats_card"]["locked_line_snapshot_sha256"],
                          card["totals_card"]["locked_line_snapshot_sha256"],
                          model["locked_line_snapshot_sha256"], ingestion["lock_snapshot_sha256"]}


def test_frozen_cross_market_score_scale_is_reported_without_calibration_claim():
    from scripts.review_week6_decision import SCALE_LABEL, score_diagnostic

    pool = csv_rows(OUT / "week6_combined_candidate_pool.csv")
    computed = score_diagnostic(pool)
    reported = json.loads((OUT / "week6_cross_market_scale_diagnostic.json").read_text())
    assert reported == computed
    assert reported["score_interpretation"] == SCALE_LABEL
    assert reported["cross_market_common_scale_validated"] is False
    assert reported["ats_policy_maximum_selected_probability"] == 0.60
    assert reported["total_score_method"] == "UNCALIBRATED_NORMAL_SHADOW"
    assert reported["total_candidates_above_best_ats_score"] == 25
    assert reported["markets"]["ATS"]["count"] == 58
    assert reported["markets"]["TOTAL"]["count"] == 58
    assert reported["markets"]["ATS"]["minimum"] == pytest.approx(0.5007, abs=0.0001)
    assert reported["markets"]["ATS"]["median"] == pytest.approx(0.5197, abs=0.0001)
    assert reported["markets"]["ATS"]["maximum"] == pytest.approx(0.5896, abs=0.0001)
    assert reported["markets"]["TOTAL"]["minimum"] == pytest.approx(0.5040, abs=0.0001)
    assert reported["markets"]["TOTAL"]["median"] == pytest.approx(0.5749, abs=0.0001)
    assert reported["markets"]["TOTAL"]["maximum"] == pytest.approx(0.7197, abs=0.0001)


@pytest.mark.parametrize("offset,feature_calls", ((-1, 1), (0, 0), (1, 0)))
def test_totals_model_never_accesses_features_at_or_after_kickoff(
    temp_db, monkeypatch, offset, feature_calls,
):
    from business_entities import totals_weekly_model as runner
    from models import backtest_harness as harness

    conn = temp_db.get_connection()
    kickoff = datetime(2026, 10, 7, tzinfo=timezone.utc)
    locked_at = kickoff - timedelta(days=1)
    contest = create_contest(conn, contest_key="week6-totals-kickoff-guard",
        name="Week 6 totals kickoff guard", season=2026, week=6, source="fixture",
        provenance="fixture://week6-total-timing", created_at=locked_at)
    conn.execute("INSERT INTO games(game_id,season,week,home_team,away_team,start_date) "
                 "VALUES(9006,2026,6,'Home','Away',?)", (kickoff.isoformat(),))
    lock_contest_line(conn, contest_id=contest.id, game_id=9006,
        raw_home_team="Home", raw_away_team="Away",
        normalized_home_team="Home", normalized_away_team="Away",
        home_spread=-3.5, total=50.5, source="fixture", source_line_id="week6-total-timing",
        provenance="fixture://week6-total-timing", payload_sha256="a" * 64, locked_at=locked_at)
    monkeypatch.setattr(harness, "available_seasons_before", lambda *args: [])
    monkeypatch.setattr(runner, "build_totals_component_dataset",
                        lambda *args, **kwargs: (SimpleNamespace(dataset_sha256="b" * 64), ()))
    monkeypatch.setattr(runner, "fit_totals_component_model",
                        lambda *args, **kwargs: SimpleNamespace(uncertainty_points=10.0))
    calls = []

    def spy(*args):
        calls.append(args)
        return None

    monkeypatch.setattr(harness, "get_pregame_stats", spy)
    run_component_totals_shadow_model(conn, contest_id=contest.id,
        model_run_key=f"week6-totals-cutoff-{offset}", code_commit_sha="c" * 40,
        generated_at=kickoff + timedelta(seconds=offset), provenance="fixture://week6-total-timing")
    assert len(calls) == feature_calls
