"""Replay sealed forecasts, source custody, rankings and adversarial failure modes."""
import copy

import pytest

from scripts import seal_week9_board as board


def test_all_108_selections_and_board_replay_from_the_exact_seal():
    assert board.sha(board.SEAL) == "77aea6d0eefecc6dce014524610294da617d7dab2b6e903a59f8664f664e5460"
    result = board.main(verify=True)
    assert (result["eligible_games"], result["ats_selections"], result["total_selections"], result["excluded_elapsed_games"]) == (54, 54, 54, 2)


@pytest.mark.parametrize("kind", ["feature_lookahead", "target_score", "ats_projection", "total_projection", "production_promotion"])
def test_mutated_evidence_is_rejected_without_touching_files(monkeypatch, kind):
    original = board.read
    def corrupt(path):
        value = copy.deepcopy(original(path))
        if path.name == "week9_raw_model_components.json":
            if kind == "feature_lookahead": value["games"][0]["raw_point_in_time_package"]["home_stats"]["as_of_week"] = 9
            if kind == "ats_projection": value["games"][0]["ats"]["projected_home_margin"] += 1
            if kind == "total_projection": value["games"][0]["totals"]["projected_home_points"] += 1
        if path.name == "cfbd-week9-games.derived.json" and kind == "target_score": value[0]["homePoints"] = 7
        if path.name == "week9_card_manifest.json" and kind == "production_promotion": value["legacy_mixed_production_eligible"] = True
        return value
    monkeypatch.setattr(board, "read", corrupt)
    with pytest.raises(ValueError): board.validate(sealed_at=original(board.SEAL)["sealed_at_utc"])


@pytest.mark.parametrize("kind", ["side", "confidence", "line", "rank"])
def test_mutated_card_is_rejected(monkeypatch, kind):
    original = board.csv_rows
    def corrupt(name):
        rows = original(name)
        if name == "week9_ats_full_card.csv":
            if kind == "side": rows[0]["selected_side"] = "home" if rows[0]["selected_side"] == "away" else "away"
            if kind == "line": rows[0]["locked_home_spread"] = "99.5"
        if name == "week9_totals_full_card.csv" and kind == "confidence": rows[0]["confidence"] = "5"
        if name == "week9_legacy_mixed_research_top5.csv" and kind == "rank": rows.reverse()
        return rows
    monkeypatch.setattr(board, "csv_rows", corrupt)
    with pytest.raises(ValueError): board.validate(sealed_at=board.read(board.SEAL)["sealed_at_utc"])


def test_seal_cannot_be_replaced_or_created_after_kickoff():
    before = board.sha(board.SEAL)
    with pytest.raises(ValueError, match="already exists"): board.main()
    with pytest.raises(ValueError, match="timestamp"):
        board.validate(sealed_at="2026-10-28T23:00:00+00:00")
    assert board.sha(board.SEAL) == before


def test_partial_ingestion_cannot_be_overwritten(tmp_path):
    from scripts import run_week9_execution as execution
    output = execution.ROOT / "outputs/2026-week9-prospective"
    with pytest.raises(ValueError, match="already exists"):
        execution.run(source=board.SOURCE, metadata=board.METADATA,
                      capture=output/"core-initial", database=execution.ROOT/"data/week9-never-created-test.db", output=output)
