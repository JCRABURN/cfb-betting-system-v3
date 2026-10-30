"""Screenshot reconciliation and prospective anti-lookahead regression tests."""
import copy
import json
import sqlite3
from datetime import timedelta

import pytest

from ingestion import CanonicalTeamResolver
from scripts import prepare_week9_source as source
from scripts import run_week9_execution as execution


def inputs():
    capture = source.OUT / "core-initial"
    games = json.loads((capture / "cfbd-2026-games.json").read_text())
    teams = json.loads((capture / "cfbd-2026-fbs-teams.json").read_text())
    with sqlite3.connect(f"file:{(source.ROOT / 'data/cfb.db').as_posix()}?mode=ro", uri=True) as conn:
        schools = [r[0] for r in conn.execute("SELECT school FROM teams")]
    resolver = CanonicalTeamResolver(schools + [r["school"] for r in teams])
    now = source.iso(json.loads((capture / "capture-manifest.json").read_text())["captured_at_utc"])
    return source.read_csv(source.SOURCE), source.read_csv(source.REVIEW), games, resolver, now


def test_all_screenshot_lines_and_schedule_reconcile_with_no_market_substitution():
    upcoming, excluded, rows = source.reconcile(*inputs())
    assert (len(upcoming), len(excluded), len(rows)) == (54, 2, 56)
    assert len({r["game_id"] for r in rows}) == 56
    assert sum(len(r["screenshots"]) for r in rows) == 56
    metadata = source.ROOT / "production-weeks/2026-week9-splashsports-lock-metadata.json"
    actual, details, _ = execution.read_source(source.ROOT / "production-weeks/2026-week9-splashsports.csv", metadata)
    assert actual == upcoming and len(details["excluded_completed_games"]) == 2


@pytest.mark.parametrize("field,value", [("away_spread", "99.5"), ("home_spread", "99.5"), ("total", "99.5")])
def test_changed_line_or_orientation_is_rejected(field, value):
    args = list(inputs()); args[0][3][field] = value
    with pytest.raises(ValueError, match="line differs"):
        source.reconcile(*args)


def test_overlapping_screenshots_cannot_contradict():
    args = list(inputs()); args[1].append(copy.deepcopy(args[1][-1])); args[1][-1]["total"] = "99.5"
    with pytest.raises(ValueError, match="overlapping"):
        source.reconcile(*args)


@pytest.mark.parametrize("kind", ["missing", "duplicate", "unknown", "late", "outcome"])
def test_source_coverage_and_pregame_fail_closed(kind):
    args = list(inputs())
    if kind == "missing": args[0].pop()
    if kind == "duplicate": args[0].append(copy.deepcopy(args[0][3]))
    if kind == "unknown": args[0][3]["home_team"] = "Unknown club"
    if kind == "late": args[4] += timedelta(days=7)
    if kind == "outcome":
        next(g for g in args[2] if g["week"] == 9 and g["awayTeam"] == "Jacksonville State")["homePoints"] = 7
    with pytest.raises(ValueError): source.reconcile(*args)


def test_final_scores_and_screenshot_times_are_checked():
    args = list(inputs()); args[0][0]["final_home"] = "999"
    with pytest.raises(ValueError, match="score mismatch"): source.reconcile(*args)
    args = list(inputs()); args[1][3]["local_time"] = "08:00 PM"
    with pytest.raises(ValueError, match="time differs"): source.reconcile(*args)


def test_connecticut_alias_is_at_canonical_boundary():
    resolver = CanonicalTeamResolver(["UConn", "Massachusetts"])
    assert resolver.resolve("SplashSports", "Connecticut").canonical_name == "UConn"
    assert resolver.resolve("unregistered-provider", "Connecticut").status == "unknown"


def test_source_preparation_never_overwrites_existing_lock():
    before = source.digest(source.ROOT / "production-weeks/2026-week9-splashsports.csv")
    with pytest.raises(FileExistsError): source.main()
    assert source.digest(source.ROOT / "production-weeks/2026-week9-splashsports.csv") == before


def test_live_source_cannot_be_reclassified_as_pregame():
    args = list(inputs()); args[0][1]["status"] = "PREGAME"
    with pytest.raises(ValueError, match="kickoff elapsed"):
        source.reconcile(*args)


def test_screenshot_live_score_is_not_recorded_as_final():
    args = list(inputs()); args[0][1]["final_home"] = "10"
    with pytest.raises(ValueError, match="live exclusion"):
        source.reconcile(*args)
