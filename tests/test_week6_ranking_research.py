"""Guard the research replay against accidental loss of sealed candidate coverage."""

import math

from scripts.research_week6_ranking import calibration, frozen_mixed_top5, load_week, rank


def test_week6_ranking_replay_uses_complete_frozen_cards_and_original_tie_break():
    ats, totals = load_week(6)
    assert len(ats) == len(totals) == 58
    assert len({row["game_id"] for row in ats}) == 58
    assert len({row["game_id"] for row in totals}) == 58
    assert {row["confidence"] for row in ats} == {1}
    assert {row["governed_uncertainty"] for row in ats} == {None}
    governed = rank(ats, "governed")
    assert [row["locked_line_id"] for row in governed] == sorted(row["locked_line_id"] for row in ats)
    assert [row["official_rank"] for row in governed[:5]] == [5, 4, 3, 2, 1]
    assert all(row["official_rank"] is None for row in governed[5:])
    assert len(frozen_mixed_top5(6, ats, totals)) == 5


def test_shadow_scores_are_transform_replay_not_independent_probability_evidence():
    for week in (5, 6):
        ats, totals = load_week(week)
        assert len(ats) == len(totals) == (56 if week == 5 else 58)
        assert all(math.isclose(row["score"], min(.60, .50 + .005*row["edge_points"]), abs_tol=1e-12)
                   for row in ats)
        assert len(frozen_mixed_top5(week, ats, totals)) == 5
    ats5, _ = load_week(5)
    assert all(row["score_source"] == "RECONSTRUCTED_PREEXISTING_POLICY_FROM_FROZEN_EDGE" for row in ats5)


def test_calibration_keeps_ranking_and_probability_diagnostics_distinct():
    rows = [{"score": .60, "result": "LOSS"}, {"score": .50, "result": "WIN"}]
    result = calibration(rows)
    assert result["pairwise_auc"] == 0
    assert result["brier_shadow_diagnostic"] > .25
    assert result["buckets"][-1]["wins"] == 0
