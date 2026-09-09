import sqlite3
from datetime import datetime, timezone

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
from models.totals_component_research import (
    MODEL_VERSION as COMPONENT_MODEL_VERSION,
    TotalsComponentObservation,
    run_totals_component_rolling_origin,
)
from models.cross_market_correlation import (
    CrossMarketCorrelationError,
    CrossMarketOutOfSampleOutcome,
    estimate_cross_market_correlations,
)
from business_entities.totals_weekly_model import run_component_totals_shadow_model
from contest_lines import create_contest, lock_contest_line
from models.totals_evaluation import evaluate_totals_research


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
    comparison = evaluate_totals_research(dataset, result)
    assert comparison.market_total_baseline.sample_n == 5
    assert comparison.proposed_minimum_oos_decisions > 0
    assert comparison.totals_production_eligible is False


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


def test_component_score_model_fits_separate_targets_and_replays_deterministically():
    base = tuple(
        _observation(index, 2024, index, 40 + index)
        for index in range(1, 11)
    )
    dataset = totals_dataset_from_observations(base)
    components = tuple(
        TotalsComponentObservation(
            item,
            actual_home_points=20 + item.week,
            actual_away_points=20,
        )
        for item in base
    )
    policy = TotalsResearchPolicy(minimum_training_examples=5)
    first = run_totals_component_rolling_origin(dataset, components, policy=policy)
    second = run_totals_component_rolling_origin(dataset, components, policy=policy)

    assert first.model_version == COMPONENT_MODEL_VERSION
    assert first.ledger_sha256 == second.ledger_sha256
    assert first.predictions == second.predictions
    assert len(first.predictions) == 5
    assert all(
        item.projected_total
        == pytest.approx(item.projected_home_points + item.projected_away_points)
        for item in first.predictions
    )
    assert first.production_eligible is False


def test_cross_market_correlation_uses_oos_outcomes_and_positive_ci_only():
    rows = tuple(
        CrossMarketOutOfSampleOutcome(
            game_id=index,
            season=2024,
            week=index,
            ats_selected_market_status="favorite",
            ats_result="win" if index % 2 else "loss",
            total_selected_direction="over",
            total_result="win" if index % 2 else "loss",
        )
        for index in range(1, 101)
    )
    result = estimate_cross_market_correlations(rows)
    favorite_over = next(
        item for item in result.estimates if item.relation_code == "favorite_over"
    )
    assert favorite_over.sample_n == 100
    assert favorite_over.positive_penalty_weight > 0
    assert favorite_over.positive_penalty_weight == pytest.approx(
        max(favorite_over.fisher_lower_95, 0)
    )
    assert all(
        item.positive_penalty_weight == 0
        for item in result.estimates
        if item.relation_code != "favorite_over"
    )
    with pytest.raises(CrossMarketCorrelationError, match="unique"):
        estimate_cross_market_correlations((rows[0], rows[0]))


def test_weekly_component_runner_is_shadow_only_and_records_components(temp_db, monkeypatch):
    conn = temp_db.get_connection()
    generated = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    kickoff = datetime(2026, 8, 29, 17, tzinfo=timezone.utc)
    contest = create_contest(
        conn,
        contest_key="component-weekly-contest",
        name="Component Weekly Contest",
        season=2026,
        week=1,
        source="fixture",
        provenance="fixture://component-weekly-contest",
        created_at=generated,
    )
    conn.execute(
        "INSERT INTO games (game_id, season, week, home_team, away_team, "
        "start_date, completed) VALUES (9001, 2026, 1, 'Home', 'Away', ?, 0)",
        (kickoff.isoformat(),),
    )
    lock_contest_line(
        conn,
        contest_id=contest.id,
        game_id=9001,
        raw_home_team="Home",
        raw_away_team="Away",
        normalized_home_team="Home",
        normalized_away_team="Away",
        home_spread=-3,
        total=52.5,
        source="fixture",
        source_line_id="component-line",
        provenance="fixture://component-line",
        payload_sha256="a" * 64,
        locked_at=generated,
    )
    base = tuple(
        _observation(index, 2024, index, 40 + index)
        for index in range(1, 7)
    )
    dataset = totals_dataset_from_observations(base)
    components = tuple(
        TotalsComponentObservation(item, 20 + item.week, 20) for item in base
    )
    from business_entities import totals_weekly_model

    monkeypatch.setattr(
        totals_weekly_model,
        "build_totals_component_dataset",
        lambda connection, seasons: (dataset, components),
    )
    monkeypatch.setattr(
        totals_weekly_model.harness,
        "available_seasons_before",
        lambda connection, season: [2024],
    )
    monkeypatch.setattr(
        totals_weekly_model.harness,
        "get_pregame_stats",
        lambda *args: {
            "home_stats": {
                "offense_epa_play": 0.3,
                "defense_epa_play": 0.1,
                "as_of_season": 2025,
                "as_of_week": 15,
            },
            "away_stats": {
                "offense_epa_play": 0.2,
                "defense_epa_play": 0.15,
                "as_of_season": 2025,
                "as_of_week": 15,
            },
        },
    )
    run = run_component_totals_shadow_model(
        conn,
        contest_id=contest.id,
        model_run_key="component-weekly-run",
        code_commit_sha="b" * 40,
        generated_at=generated,
        provenance="fixture://component-weekly-run",
        policy=TotalsResearchPolicy(minimum_training_examples=5),
    )
    prediction = conn.execute(
        "SELECT id, projected_total FROM total_model_predictions "
        "WHERE total_model_run_id = ?",
        (run.id,),
    ).fetchone()
    component = conn.execute(
        "SELECT projected_home_points, projected_away_points, projected_total "
        "FROM total_score_component_predictions "
        "WHERE total_model_prediction_id = ?",
        (prediction[0],),
    ).fetchone()
    assert run.lifecycle_stage == "shadow"
    assert prediction[1] == pytest.approx(component[0] + component[1])
    assert component[2] == pytest.approx(prediction[1])
    assert conn.execute("SELECT COUNT(*) FROM contest_picks").fetchone()[0] == 0
