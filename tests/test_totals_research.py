import sqlite3

import pytest

from models.totals_research import (
    FEATURE_SCHEMA_VERSION,
    MODEL_NAME,
    MODEL_VERSION,
    TARGET_VERSION,
    TotalsResearchError,
    TotalsResearchObservation,
    TotalsResearchPolicy,
    build_totals_research_dataset,
    run_totals_rolling_origin,
    totals_dataset_from_observations,
)


def _observation(game_id, season, week, actual_total, opening_total=50.0):
    return TotalsResearchObservation(
        game_id=game_id,
        season=season,
        week=week,
        kickoff_at=f"{season}-09-{min(week, 28):02d}T17:00:00+00:00",
        features=(0.0, 0.0, 0.0, 0.0),
        home_stats_as_of_season=season - 1,
        home_stats_as_of_week=15,
        away_stats_as_of_season=season - 1,
        away_stats_as_of_week=15,
        actual_total=float(actual_total),
        opening_total=opening_total,
        opening_book=None if opening_total is None else "fixturebook",
    )


def test_totals_research_is_independent_target_and_strict_rolling_origin():
    actuals = (49.0, 51.0, 49.0, 51.0, 50.0, 50.0, 50.0, 50.0, 50.0, 50.0)
    observations = tuple(
        _observation(index, 2024, index, actual)
        for index, actual in enumerate(actuals, start=1)
    )
    dataset = totals_dataset_from_observations(observations)
    result = run_totals_rolling_origin(
        dataset,
        policy=TotalsResearchPolicy(minimum_training_examples=5),
    )

    assert result.model_name == MODEL_NAME == "pit_epa_total_linear"
    assert result.model_version == MODEL_VERSION == "pit-epa-total-linear-v1"
    assert result.feature_schema_version == FEATURE_SCHEMA_VERSION == "pit-epa-levels-v1"
    assert result.target_version == TARGET_VERSION == "actual-game-total-v1"
    assert all(
        audit.latest_training_fold < (audit.season, audit.week)
        for audit in result.fold_audits
    )
    assert result.metrics.forecast_count == 5
    assert result.metrics.mae == pytest.approx(0.0)
    assert result.metrics.rmse == pytest.approx(0.0)
    assert all(item.selected_direction == "under" for item in result.predictions)
    assert all(item.selected_probability == pytest.approx(0.5) for item in result.predictions)
    assert all(item.result == "push" for item in result.predictions)
    assert result.production_eligible is False
    assert result.governance_status == "research_shadow_only"
    assert "TOTALS PRODUCTION ELIGIBLE: NO" in result.recommendation


def test_totals_research_reports_ou_roi_probability_and_replay_determinism():
    training = tuple(
        _observation(index, 2024, index, 48 + index % 5, opening_total=50)
        for index in range(1, 9)
    )
    testing = (
        _observation(101, 2024, 9, 60, opening_total=45),
        _observation(102, 2024, 10, 35, opening_total=55),
        _observation(103, 2024, 11, 50, opening_total=50),
        _observation(104, 2024, 12, 58, opening_total=None),
    )
    dataset = totals_dataset_from_observations(training + testing)
    policy = TotalsResearchPolicy(minimum_training_examples=5)
    first = run_totals_rolling_origin(dataset, policy=policy)
    second = run_totals_rolling_origin(dataset, policy=policy)

    assert first.ledger_sha256 == second.ledger_sha256
    assert first.predictions == second.predictions
    assert first.metrics.mae >= 0
    assert first.metrics.rmse >= first.metrics.mae
    assert first.metrics.ou_decision_count > 0
    assert first.metrics.ou_win_rate is not None
    assert first.metrics.roi_at_minus_110 is not None
    assert first.metrics.brier_score is not None
    assert first.metrics.log_loss is not None
    assert first.metrics.expected_calibration_error is not None
    assert any(item.opening_total is None and item.result is None for item in first.predictions)


def test_future_feature_snapshot_is_rejected_adversarially():
    with pytest.raises(TotalsResearchError, match="home feature snapshot"):
        TotalsResearchObservation(
            game_id=1,
            season=2026,
            week=3,
            kickoff_at="2026-09-12T17:00:00+00:00",
            features=(0.2, 0.1, 0.3, 0.2),
            home_stats_as_of_season=2026,
            home_stats_as_of_week=3,
            away_stats_as_of_season=2026,
            away_stats_as_of_week=2,
            actual_total=52,
            opening_total=50,
            opening_book="fixture",
        )


def test_dataset_builder_uses_pit_stats_and_actual_points_total(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE games (game_id INTEGER PRIMARY KEY, season INTEGER, week INTEGER, "
        "home_team TEXT, away_team TEXT, home_points INTEGER, away_points INTEGER, "
        "start_date TEXT, completed INTEGER)"
    )
    conn.execute(
        "INSERT INTO games VALUES "
        "(1, 2026, 2, 'H', 'A', 31, 24, '2026-09-05T17:00:00+00:00', 1)"
    )

    from models import totals_research

    monkeypatch.setattr(totals_research.bh, "list_weeks", lambda connection, season: [2])
    monkeypatch.setattr(
        totals_research.bh,
        "list_games",
        lambda connection, season, week: [
            (1, "H", "A", 31, 24, "2026-09-05T17:00:00+00:00")
        ],
    )
    monkeypatch.setattr(
        totals_research.bh,
        "get_pregame_stats",
        lambda *args: {
            "home_stats": {
                "offense_epa_play": 0.3,
                "defense_epa_play": 0.1,
                "as_of_season": 2026,
                "as_of_week": 1,
            },
            "away_stats": {
                "offense_epa_play": 0.2,
                "defense_epa_play": 0.15,
                "as_of_season": 2026,
                "as_of_week": 1,
            },
        },
    )
    monkeypatch.setattr(
        totals_research.bh,
        "get_opening_line",
        lambda connection, game_id: {"home_spread": -3, "total": 52.5, "book": "fixture"},
    )

    dataset = build_totals_research_dataset(conn, seasons=(2026,))

    assert len(dataset.observations) == 1
    observation = dataset.observations[0]
    assert observation.actual_total == 55
    assert observation.opening_total == 52.5
    assert observation.features == (0.3, 0.1, 0.2, 0.15)
    assert observation.home_stats_as_of_week == 1 < observation.week
    conn.close()
