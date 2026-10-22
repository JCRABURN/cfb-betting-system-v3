"""Week 7 market completeness and governed-rank warning cannot silently relax."""

import pytest

from scripts.finalize_week7_card import governed_ranking_status, require_complete_market_coverage


def test_all_lined_markets_complete_or_source_total_explicitly_missing():
    require_complete_market_coverage(59, 59, 59, 59, [])
    require_complete_market_coverage(59, 58, 59, 58, [(17, "missing_locked_total")])


def test_model_total_skip_and_ats_omission_are_blockers():
    with pytest.raises(ValueError, match="POINT_IN_TIME_TOTALS_BLOCKER"):
        require_complete_market_coverage(59, 59, 59, 58, [(17, "missing_total_prediction")])
    with pytest.raises(ValueError, match="COMPLETENESS_BLOCKER"):
        require_complete_market_coverage(59, 59, 58, 59, [])


def test_equal_confidence_and_missing_uncertainty_are_disclosed():
    rows = [{"confidence": 1, "uncertainty_points": None} for _ in range(59)]
    assert governed_ranking_status(rows).startswith("INSUFFICIENT_DISCRIMINATION")
    rows[0]["uncertainty_points"] = 5.0
    assert governed_ranking_status(rows) == "POLICY_RANKING_INPUTS_RECORDED"
