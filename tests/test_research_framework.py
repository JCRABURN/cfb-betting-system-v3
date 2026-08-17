from dataclasses import replace

import sqlite3
from pathlib import Path

import pytest

from models import research_framework as rf
from models import run_research


FEATURES = ("epa_differential", "success_rate_differential")


def _input(game_id, season, week, *, epa, signal, home="Home", away="Away"):
    return rf.ModelInput(
        game_id=game_id,
        season=season,
        week=week,
        kickoff_at=f"{season}-09-{week + 1:02d}T17:00:00+00:00",
        home_team=f"{home} {game_id}",
        away_team=f"{away} {game_id}",
        features=(
            ("epa_differential", float(epa)),
            ("success_rate_differential", float(signal)),
        ),
        opening_spread=0.0,
        opening_book="fixturebook",
    )


def _observation(game_id, season, week, *, epa, signal, residual):
    return rf.ResearchObservation(
        model_input=_input(game_id, season, week, epa=epa, signal=signal),
        actual_home_margin=float(residual),
        closing_spread=(-1.0 if residual > 0 else 1.0),
        closing_book="fixturebook",
        home_stats_as_of_season=season,
        home_stats_as_of_week=week - 1,
        away_stats_as_of_season=season,
        away_stats_as_of_week=week - 1,
    )


def _synthetic_dataset(*, through_week=6):
    observations = []
    game_id = 1
    residuals = (-4.0, -2.0, 2.0, 4.0)
    for week in range(2, through_week + 1):
        for offset, residual in enumerate(residuals):
            observations.append(
                _observation(
                    game_id,
                    2022,
                    week,
                    epa=(-1.5, 0.5, -0.5, 1.5)[offset],
                    signal=residual / 4,
                    residual=residual,
                )
            )
            game_id += 1
    return rf.research_dataset_from_observations(
        feature_names=FEATURES,
        observations=tuple(observations),
    )


def _policy(**changes):
    values = dict(
        policy_version="research-policy-v1",
        minimum_training_observations=8,
        minimum_fit_observations=4,
        minimum_calibration_observations=4,
        calibration_fraction=0.25,
        minimum_uncertainty_points=0.25,
        probability_clip=0.001,
        calibration_bin_count=5,
        minimum_oos_predictions=4,
        minimum_oos_seasons=1,
        minimum_mae_improvement=0.0,
        minimum_rmse_improvement=0.0,
        minimum_brier_improvement=0.0,
        minimum_log_loss_improvement=0.0,
        maximum_calibration_error_increase=0.0,
        minimum_ats_improvement=0.0,
        minimum_roi_improvement=0.0,
        minimum_clv_improvement=0.0,
        maximum_drawdown_increase=0.0,
        minimum_confidence_monotonicity=0.0,
        confidence_probability_thresholds=(0.55, 0.60, 0.65, 0.70),
    )
    values.update(changes)
    return rf.ResearchPolicy(**values)


METADATA = rf.ResearchMetadata(
    code_commit_sha="a" * 40,
    data_snapshot_sha256="b" * 64,
    feature_schema_version="research-features-v1",
    configuration_version="research-config-v1",
    generated_at="2026-08-17T20:00:00+00:00",
)


def _ridge():
    return rf.ridge_candidate(
        model_key="ridge_epa_success",
        model_version="ridge-epa-success-v1",
        feature_names=FEATURES,
        l2_penalty=0.1,
    )


def _run(dataset):
    return rf.run_weekly_rolling_origin(
        dataset=dataset,
        baseline=rf.epa_only_baseline(),
        candidates=(_ridge(),),
        policy=_policy(),
        metadata=METADATA,
    )


def test_observation_rejects_same_week_or_future_feature_snapshot():
    safe = _observation(1, 2022, 3, epa=0.1, signal=0.2, residual=3)
    with pytest.raises(rf.ResearchError, match="strictly before"):
        replace(safe, home_stats_as_of_week=3)
    with pytest.raises(rf.ResearchError, match="strictly before"):
        replace(safe, away_stats_as_of_season=2023, away_stats_as_of_week=1)


def _insert_game(conn, game_id, *, week=3, opening=True):
    conn.execute(
        "INSERT INTO games "
        "(game_id, season, week, home_team, away_team, home_points, "
        "away_points, completed, start_date) "
        "VALUES (?, 2023, ?, 'H', 'A', 24, 17, 1, "
        "'2023-09-16T17:00:00+00:00')",
        (game_id, week),
    )
    if opening:
        conn.execute(
            "INSERT INTO betting_lines "
            "(game_id, season, week, home_team, away_team, book, home_spread, "
            "line_type, source, fetched_at) VALUES (?, 2023, ?, 'H', 'A', "
            "'fixturebook', -3, 'opening', 'fixture', 'now')",
            (game_id, week),
        )
    conn.execute(
        "INSERT INTO betting_lines "
        "(game_id, season, week, home_team, away_team, book, home_spread, "
        "line_type, source, fetched_at) VALUES (?, 2023, ?, 'H', 'A', "
        "'fixturebook', -4, 'closing', 'fixture', 'now')",
        (game_id, week),
    )


def _insert_stats(conn, team, week, off_epa):
    conn.execute(
        "INSERT INTO team_game_stats "
        "(season, week, team, offense_epa_play, defense_epa_play, "
        "offense_success_rate, defense_success_rate, havoc_rate, source, "
        "fetched_at) VALUES (2023, ?, ?, ?, 0.05, 0.50, 0.40, 0.12, "
        "'cfbd_point_in_time', 'now')",
        (week, team, off_epa),
    )


def test_dataset_builder_uses_sanctioned_as_of_stats_and_never_substitutes_close(temp_db):
    conn = temp_db.get_connection()
    _insert_game(conn, 1, opening=True)
    _insert_stats(conn, "H", 1, 0.20)
    _insert_stats(conn, "A", 1, 0.10)
    _insert_stats(conn, "H", 3, 999.0)
    _insert_game(conn, 2, opening=False)
    conn.commit()

    dataset = rf.build_research_dataset(
        conn,
        seasons=(2023,),
        feature_names=("epa_differential",),
    )
    conn.close()

    assert len(dataset.observations) == 1
    observation = dataset.observations[0]
    assert observation.model_input.game_id == 1
    assert observation.model_input.feature("epa_differential") == pytest.approx(0.10)
    assert observation.home_stats_as_of_week == 1
    assert observation.closing_spread == -4.0
    assert dataset.skips == (
        rf.ResearchBuildSkip(2, 2023, 3, "missing_opening_line"),
    )
    assert len(dataset.dataset_sha256) == 64


def test_dataset_hash_detects_tampering():
    dataset = _synthetic_dataset(through_week=3)
    with pytest.raises(rf.ResearchError, match="does not match"):
        replace(dataset, dataset_sha256="0" * 64)


def test_epa_baseline_is_fixed_to_one_epa_feature():
    baseline = rf.epa_only_baseline()
    assert baseline.spec.family == "epa_only_baseline"
    assert baseline.spec.feature_names == ("epa_differential",)
    assert baseline.spec.target == "market_residual_v1"


def test_regularized_linear_model_fits_market_residual_without_test_fields():
    model = rf.ridge_candidate(
        model_key="ridge",
        model_version="ridge-v1",
        feature_names=("success_rate_differential",),
        l2_penalty=0.01,
    )
    examples = tuple(
        rf.TrainingExample(
            _input(index, 2022, 2, epa=index % 2, signal=value),
            2 * value,
        )
        for index, value in enumerate((-2, -1, -0.5, 0.5, 1, 2), 1)
    )
    fitted = model.fit(examples)
    prediction = fitted.predict_market_residual(
        _input(99, 2022, 3, epa=0, signal=1.5)
    )
    assert prediction == pytest.approx(3.0, abs=0.02)


def test_gradient_boosted_stumps_learn_a_nonlinear_split():
    model = rf.gradient_boosted_candidate(
        model_key="boosted",
        model_version="boosted-v1",
        feature_names=("success_rate_differential",),
        estimator_count=8,
        learning_rate=0.5,
        minimum_leaf_size=2,
    )
    values = (-3, -2, -1, -0.5, 0.5, 1, 2, 3)
    examples = tuple(
        rf.TrainingExample(
            _input(index, 2022, 2, epa=index % 2, signal=value),
            -4.0 if value < 0 else 4.0,
        )
        for index, value in enumerate(values, 1)
    )
    fitted = model.fit(examples)
    assert fitted.predict_market_residual(
        _input(90, 2022, 3, epa=0, signal=-2)
    ) < 0
    assert fitted.predict_market_residual(
        _input(91, 2022, 3, epa=0, signal=2)
    ) > 0


def test_dynamic_team_rating_learns_only_from_supplied_training_history():
    model = rf.dynamic_rating_candidate(
        model_key="ratings",
        model_version="ratings-v1",
        update_rate=0.5,
        carry_decay=0.2,
    )
    examples = tuple(
        rf.TrainingExample(
            rf.ModelInput(
                game_id=index,
                season=2022,
                week=index + 1,
                kickoff_at=f"2022-09-{index + 2:02d}T17:00:00+00:00",
                home_team="A",
                away_team="B",
                features=(),
                opening_spread=0,
                opening_book="fixturebook",
            ),
            6.0,
        )
        for index in range(1, 5)
    )
    fitted = model.fit(examples)
    prediction = fitted.predict_market_residual(examples[-1].model_input)
    assert prediction > 0


def test_weekly_rolling_origin_uses_identical_strictly_prior_games_for_all_models():
    dataset = _synthetic_dataset()
    result = _run(dataset)
    assert result.model_specs[0].family == "epa_only_baseline"
    assert result.dataset_sha256 == dataset.dataset_sha256
    assert result.dataset_feature_names == FEATURES
    assert result.dataset_observation_count == len(dataset.observations)
    assert result.dataset_skips == ()
    assert len(result.ledger_sha256) == 64
    assert result.predictions
    by_fold = {}
    for fold in result.folds:
        by_fold.setdefault((fold.season, fold.week), []).append(fold)
        assert set(fold.training_game_ids).isdisjoint(fold.test_game_ids)
        assert set(fold.fit_game_ids).isdisjoint(fold.calibration_game_ids)
        assert set(fold.fit_game_ids) | set(fold.calibration_game_ids) == set(
            fold.training_game_ids
        )
        assert fold.uncertainty_points > 0
    assert all(len(folds) == 2 for folds in by_fold.values())
    assert all(
        len({fold.test_game_ids for fold in folds}) == 1
        for folds in by_fold.values()
    )
    assert all(0 < item.home_cover_probability < 1 for item in result.predictions)
    assert all(1 <= item.research_confidence <= 5 for item in result.predictions)


def test_future_fold_cannot_change_already_emitted_predictions():
    earlier = _run(_synthetic_dataset(through_week=5))
    with_future = _run(_synthetic_dataset(through_week=6))
    earlier_values = {
        (item.model_key, item.game_id): (
            item.predicted_market_residual,
            item.home_cover_probability,
            item.uncertainty_points,
        )
        for item in earlier.predictions
    }
    future_values = {
        (item.model_key, item.game_id): (
            item.predicted_market_residual,
            item.home_cover_probability,
            item.uncertainty_points,
        )
        for item in with_future.predictions
        if (item.model_key, item.game_id) in earlier_values
    }
    assert future_values == earlier_values


def _metrics(model_key, **changes):
    values = dict(
        model_key=model_key,
        prediction_count=100,
        season_count=5,
        margin_mae=10.0,
        margin_rmse=13.0,
        brier_score=0.24,
        log_loss=0.68,
        calibration_error=0.05,
        ats_percentage=0.52,
        roi_after_vig=-0.01,
        average_clv=0.10,
        maximum_drawdown=8.0,
        confidence_rank_monotonicity=1.0,
        confidence_tier_rates=((1, 20, 0.45), (2, 20, 0.50), (3, 20, 0.55),
                               (4, 20, 0.60), (5, 20, 0.65)),
        average_uncertainty_points=12.0,
    )
    values.update(changes)
    return rf.ResearchMetrics(**values)


def test_promotion_requires_every_preregistered_metric_and_never_auto_promotes():
    baseline = _metrics("epa_only_baseline")
    better = _metrics(
        "ridge_epa_success",
        margin_mae=9.5,
        margin_rmse=12.5,
        brier_score=0.23,
        log_loss=0.66,
        calibration_error=0.04,
        ats_percentage=0.54,
        roi_after_vig=0.02,
        average_clv=0.20,
        maximum_drawdown=7.0,
    )
    policy = _policy(
        minimum_mae_improvement=0.1,
        minimum_rmse_improvement=0.1,
        minimum_brier_improvement=0.005,
        minimum_log_loss_improvement=0.005,
        minimum_ats_improvement=0.01,
        minimum_roi_improvement=0.01,
        minimum_clv_improvement=0.05,
        minimum_confidence_monotonicity=1.0,
    )
    accepted = rf.evaluate_promotion(
        baseline=baseline,
        candidate=better,
        candidate_spec=_ridge().spec,
        policy=policy,
    )
    assert accepted.status == "candidate_pending_owner_approval"
    assert accepted.owner_approval_required is True
    assert accepted.automatic_promotion is False
    assert all(item.passed for item in accepted.criteria)

    failed = rf.evaluate_promotion(
        baseline=baseline,
        candidate=replace(better, brier_score=0.30),
        candidate_spec=_ridge().spec,
        policy=policy,
    )
    assert failed.status == "rejected"
    assert failed.owner_approval_required is False
    assert failed.automatic_promotion is False
    assert next(
        item for item in failed.criteria if item.criterion_code == "brier_improvement"
    ).passed is False


def test_research_cli_connection_is_read_only(temp_db):
    connection = temp_db.get_connection()
    connection.close()
    read_only = run_research._read_only_connection(Path(temp_db.DB_PATH))
    assert read_only.execute("PRAGMA query_only").fetchone()[0] == 1
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        read_only.execute("INSERT INTO teams (school) VALUES ('Forbidden')")
    read_only.close()


def test_default_policy_is_versioned_and_predefines_every_promotion_gate():
    policy = rf.default_research_policy()
    assert policy.policy_version == "weekly-market-residual-research-v1"
    assert policy.minimum_oos_predictions == 1000
    assert policy.minimum_oos_seasons == 4
    assert policy.minimum_mae_improvement > 0
    assert policy.minimum_brier_improvement > 0
    assert policy.minimum_clv_improvement > 0
    assert policy.minimum_confidence_monotonicity == 1.0
