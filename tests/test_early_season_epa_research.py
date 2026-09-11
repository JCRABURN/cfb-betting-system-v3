import sqlite3
from pathlib import Path

from models.early_season_epa_research import (
    build_early_season_rows,
    grouped_summaries,
    paired_ats_comparisons,
)


ROOT = Path(__file__).resolve().parents[1]


def test_predefined_early_season_candidates_use_only_rolling_origin_inputs():
    database = (ROOT / "data" / "cfb.db").resolve()
    conn = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    try:
        rows = build_early_season_rows(conn, seasons=(2025,))
    finally:
        conn.close()

    assert {row["candidate"] for row in rows} == {
        "current_production",
        "fixed_prior_25_75",
        "fixed_prior_50_50",
        "fixed_prior_75_25",
    }
    assert {row["week"] for row in rows} == {2, 3, 4}
    assert all(row["season"] == 2025 for row in rows)
    assert all(row["home_offensive_plays"] is None for row in rows)
    assert all(row["away_defensive_plays"] is None for row in rows)
    assert all(row["training_feature_sd"] > 0 for row in rows)
    assert all(row["actual_home_margin"] is not None for row in rows)
    assert all(row["opening_home_spread"] is not None for row in rows)
    for row in rows:
        assert row["home_prior_fallback"] in {
            "current_production",
            "fixed_prior_blend",
            "current_only_missing_prior",
        }
        assert row["away_prior_fallback"] in {
            "current_production",
            "fixed_prior_blend",
            "current_only_missing_prior",
        }

    summaries = grouped_summaries(rows)
    assert summaries["current_production"]["combined_weeks_2_4"]["n"] == 147
    comparisons = paired_ats_comparisons(rows)
    assert set(comparisons) == {
        "fixed_prior_25_75",
        "fixed_prior_50_50",
        "fixed_prior_75_25",
    }
    assert all(item["mcnemar_p_value"] >= 0 for item in comparisons.values())
