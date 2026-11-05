"""Adversarial gates for the separately versioned Week 10 source and adapters."""
from __future__ import annotations
import copy
import json
from datetime import datetime, timezone
import pytest
from scripts import prepare_week10_source as source
from scripts import run_week10_execution as execution
from scripts.finalize_week10_card import CARD_OUTPUTS, require_new_card_outputs


@pytest.fixture
def captured():
    core = source.OUT / "core-initial"
    games = json.loads((core / "games.raw.json").read_bytes())
    teams = json.loads((core / "teams.raw.json").read_bytes())
    resolver = source.resolver_for([t["school"] for t in teams])
    return source.read_csv(source.SOURCE), source.read_csv(source.REVIEW), games, resolver


def replay(captured):
    return source.reconcile(*captured, datetime(2026, 11, 5, 1, tzinfo=timezone.utc))


def test_complete_source_and_five_elapsed_exclusions(captured):
    upcoming, excluded, rows = replay(captured)
    assert (len(upcoming), len(excluded), len(rows)) == (57, 5, 62)
    assert all(r["line_values_match"] for r in rows)
    assert len({r["game_id"] for r in rows}) == 62


@pytest.mark.parametrize("field", ["away_spread", "home_spread", "total"])
def test_reject_source_line_replacement(captured, field):
    captured[0][7][field] = str(float(captured[0][7][field]) + 1)
    with pytest.raises(ValueError, match="screenshot line"):
        replay(captured)


def test_reject_duplicate_source_game(captured):
    captured[0].append(copy.deepcopy(captured[0][7]))
    with pytest.raises(ValueError, match="duplicate"):
        replay(captured)


def test_reject_missing_screenshot_row(captured):
    captured[1].pop()
    with pytest.raises(ValueError, match="missing"):
        replay(captured)


def test_reject_screenshot_clock_error(captured):
    captured[1][7]["local_time"] = "01:00 AM"
    with pytest.raises(ValueError, match="kickoff"):
        replay(captured)


def test_reject_completed_score_contradiction(captured):
    captured[0][0]["final_away"] = "99"
    with pytest.raises(ValueError, match="score mismatch"):
        replay(captured)


def test_reject_upcoming_target_result(captured):
    game = next(g for g in captured[2] if g.get("week") == 10 and g["awayTeam"] == "Virginia Tech")
    game["homePoints"] = 0
    with pytest.raises(ValueError, match="outcome contamination"):
        replay(captured)


def test_reject_unknown_source_status(captured):
    captured[0][7]["status"] = "APPROVED"
    with pytest.raises(ValueError, match="unknown source status"):
        replay(captured)


def test_canonical_alias_correction_stays_at_resolver_boundary(captured):
    resolver = captured[3]
    assert resolver.resolve("SplashSports", "Miami OH").canonical_name == "Miami (OH)"
    assert resolver.resolve("SplashSports", "Miami (FL)").canonical_name == "Miami"
    assert captured[0][1]["home_team"] == "Miami OH"


def test_recovered_image_row_provenance_supersedes_without_rewrite(captured):
    _, _, rows = replay(captured)
    jmu = next(r for r in rows if r["canonical_away"] == "James Madison")
    assert jmu["original_reference"].endswith("image 1 row 7")
    assert jmu["verified_reference"] == "splashsports-02.png:row-1"


def test_source_preparation_refuses_overwrite():
    with pytest.raises(FileExistsError):
        source.main()


def test_execution_rejects_altered_csv_before_database_mutation(tmp_path):
    original = source.ROOT / "production-weeks/2026-week10-splashsports.csv"
    altered = tmp_path / "altered.csv"
    altered.write_bytes(original.read_bytes().replace(b"73.5", b"74.5", 1))
    with pytest.raises(ValueError, match="checksum"):
        execution.read_source(altered, source.ROOT / "production-weeks/2026-week10-splashsports-lock-metadata.json")


def test_week10_schedule_uses_cst_not_previous_week_cdt():
    assert source.CST.utcoffset(None).total_seconds() == -21600
    assert execution.CHICAGO.utcoffset(None).total_seconds() == -21600


@pytest.mark.parametrize("filename", CARD_OUTPUTS)
def test_partial_card_always_blocks_overwrite(tmp_path, filename):
    original = tmp_path / filename
    original.write_bytes(b"immutable original")
    with pytest.raises(FileExistsError):
        require_new_card_outputs(tmp_path)
    assert original.read_bytes() == b"immutable original"
