"""Strict rolling-origin component-score research for the totals shadow model.

Home and away points are fitted as separate targets from the same sealed,
opponent-adjusted pregame EPA features used by the independent totals baseline.
Their sum is the projected game total.  This module is additive and does not
alter the version-1 combined-target research ledger.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass

from models.totals_research import (
    FEATURE_NAMES,
    TotalsResearchDataset,
    TotalsResearchError,
    TotalsResearchObservation,
    TotalsResearchPolicy,
    build_totals_research_dataset,
)


MODEL_NAME = "pit_epa_component_total_linear"
MODEL_VERSION = "pit-epa-component-total-linear-v1"
TARGET_VERSION = "actual-home-away-points-v1"
CONFIGURATION_VERSION = "weekly-rolling-origin-component-ridge-v1"


@dataclass(frozen=True)
class TotalsComponentObservation:
    base: TotalsResearchObservation
    actual_home_points: float
    actual_away_points: float

    def __post_init__(self) -> None:
        if self.actual_home_points < 0 or self.actual_away_points < 0:
            raise TotalsResearchError("component targets must be nonnegative")
        if abs(
            self.actual_home_points
            + self.actual_away_points
            - self.base.actual_total
        ) >= 1e-9:
            raise TotalsResearchError("component targets must sum to actual_total")


@dataclass(frozen=True)
class TotalsComponentPrediction:
    game_id: int
    season: int
    week: int
    projected_home_points: float
    projected_away_points: float
    projected_total: float
    actual_home_points: float
    actual_away_points: float
    actual_total: float
    home_error: float
    away_error: float
    total_error: float


@dataclass(frozen=True)
class TotalsComponentResearchResult:
    model_name: str
    model_version: str
    target_version: str
    feature_names: tuple[str, ...]
    configuration_version: str
    dataset_sha256: str
    predictions: tuple[TotalsComponentPrediction, ...]
    home_mae: float
    away_mae: float
    total_mae: float
    total_rmse: float
    ledger_sha256: str
    governance_status: str
    production_eligible: bool


@dataclass(frozen=True)
class FittedTotalsComponentModel:
    home_intercept: float
    home_coefficients: tuple[float, ...]
    away_intercept: float
    away_coefficients: tuple[float, ...]
    uncertainty_points: float
    training_count: int


def fit_totals_component_model(
    observations: tuple[TotalsComponentObservation, ...],
    *,
    policy: TotalsResearchPolicy = TotalsResearchPolicy(),
) -> FittedTotalsComponentModel:
    if len(observations) < policy.minimum_training_examples:
        raise TotalsResearchError(
            "insufficient strictly prior component-score training examples"
        )
    home_intercept, home_coefficients = _fit(
        observations, target="home", ridge_alpha=policy.ridge_alpha
    )
    away_intercept, away_coefficients = _fit(
        observations, target="away", ridge_alpha=policy.ridge_alpha
    )
    errors = []
    for item in observations:
        home, away = predict_totals_component_score(
            item.base.features,
            FittedTotalsComponentModel(
                home_intercept,
                home_coefficients,
                away_intercept,
                away_coefficients,
                1.0,
                len(observations),
            ),
        )
        errors.append(home + away - item.base.actual_total)
    uncertainty = math.sqrt(sum(error**2 for error in errors) / len(errors))
    if not math.isfinite(uncertainty) or uncertainty <= 0:
        raise TotalsResearchError("component model residual uncertainty is invalid")
    return FittedTotalsComponentModel(
        home_intercept,
        home_coefficients,
        away_intercept,
        away_coefficients,
        uncertainty,
        len(observations),
    )


def predict_totals_component_score(
    features: tuple[float, ...], fitted: FittedTotalsComponentModel
) -> tuple[float, float]:
    if len(features) != len(FEATURE_NAMES) or not all(
        math.isfinite(value) for value in features
    ):
        raise TotalsResearchError("component features must be finite and complete")
    return (
        max(0.0, _forecast(features, fitted.home_intercept, fitted.home_coefficients)),
        max(0.0, _forecast(features, fitted.away_intercept, fitted.away_coefficients)),
    )


def _sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def build_totals_component_dataset(
    conn: sqlite3.Connection, *, seasons: tuple[int, ...]
) -> tuple[TotalsResearchDataset, tuple[TotalsComponentObservation, ...]]:
    dataset = build_totals_research_dataset(conn, seasons=seasons)
    points = {
        int(row[0]): (float(row[1]), float(row[2]))
        for row in conn.execute(
            "SELECT game_id, home_points, away_points FROM games "
            "WHERE completed = 1 AND home_points IS NOT NULL AND away_points IS NOT NULL"
        )
    }
    observations = tuple(
        TotalsComponentObservation(item, *points[item.game_id])
        for item in dataset.observations
    )
    return dataset, observations


def _solve(matrix: list[list[float]], target: list[float]) -> list[float]:
    size = len(target)
    augmented = [matrix[row][:] + [target[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise TotalsResearchError("component linear system is singular")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        divisor = augmented[column][column]
        augmented[column] = [value / divisor for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            multiplier = augmented[row][column]
            augmented[row] = [
                value - multiplier * pivot_value
                for value, pivot_value in zip(augmented[row], augmented[column])
            ]
    return [augmented[row][-1] for row in range(size)]


def _fit(
    observations: tuple[TotalsComponentObservation, ...],
    *,
    target: str,
    ridge_alpha: float,
) -> tuple[float, tuple[float, ...]]:
    rows = [(1.0, *item.base.features) for item in observations]
    dimension = len(rows[0])
    gram = [[0.0] * dimension for _ in range(dimension)]
    rhs = [0.0] * dimension
    for row, observation in zip(rows, observations):
        value = (
            observation.actual_home_points
            if target == "home"
            else observation.actual_away_points
        )
        for i in range(dimension):
            rhs[i] += row[i] * value
            for j in range(dimension):
                gram[i][j] += row[i] * row[j]
    for index in range(1, dimension):
        gram[index][index] += ridge_alpha
    fitted = _solve(gram, rhs)
    return fitted[0], tuple(fitted[1:])


def _forecast(
    features: tuple[float, ...], intercept: float, coefficients: tuple[float, ...]
) -> float:
    return intercept + sum(
        coefficient * feature
        for coefficient, feature in zip(coefficients, features)
    )


def run_totals_component_rolling_origin(
    dataset: TotalsResearchDataset,
    observations: tuple[TotalsComponentObservation, ...],
    *,
    policy: TotalsResearchPolicy = TotalsResearchPolicy(),
) -> TotalsComponentResearchResult:
    if {item.base.game_id for item in observations} != {
        item.game_id for item in dataset.observations
    }:
        raise TotalsResearchError("component observations do not match base dataset")
    folds = sorted({item.base.fold_key for item in observations})
    predictions: list[TotalsComponentPrediction] = []
    for fold in folds:
        training = tuple(item for item in observations if item.base.fold_key < fold)
        testing = tuple(item for item in observations if item.base.fold_key == fold)
        if len(training) < policy.minimum_training_examples:
            continue
        fitted = fit_totals_component_model(training, policy=policy)
        for item in testing:
            home, away = predict_totals_component_score(item.base.features, fitted)
            total = home + away
            predictions.append(
                TotalsComponentPrediction(
                    game_id=item.base.game_id,
                    season=item.base.season,
                    week=item.base.week,
                    projected_home_points=home,
                    projected_away_points=away,
                    projected_total=total,
                    actual_home_points=item.actual_home_points,
                    actual_away_points=item.actual_away_points,
                    actual_total=item.base.actual_total,
                    home_error=home - item.actual_home_points,
                    away_error=away - item.actual_away_points,
                    total_error=total - item.base.actual_total,
                )
            )
    if not predictions:
        raise TotalsResearchError("no component-score predictions were produced")
    result = tuple(predictions)
    home_mae = sum(abs(item.home_error) for item in result) / len(result)
    away_mae = sum(abs(item.away_error) for item in result) / len(result)
    total_mae = sum(abs(item.total_error) for item in result) / len(result)
    total_rmse = math.sqrt(
        sum(item.total_error * item.total_error for item in result) / len(result)
    )
    ledger = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "target_version": TARGET_VERSION,
        "feature_names": FEATURE_NAMES,
        "configuration_version": CONFIGURATION_VERSION,
        "dataset_sha256": dataset.dataset_sha256,
        "policy": asdict(policy),
        "predictions": [asdict(item) for item in result],
        "metrics": {
            "home_mae": home_mae,
            "away_mae": away_mae,
            "total_mae": total_mae,
            "total_rmse": total_rmse,
        },
    }
    return TotalsComponentResearchResult(
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        target_version=TARGET_VERSION,
        feature_names=FEATURE_NAMES,
        configuration_version=CONFIGURATION_VERSION,
        dataset_sha256=dataset.dataset_sha256,
        predictions=result,
        home_mae=home_mae,
        away_mae=away_mae,
        total_mae=total_mae,
        total_rmse=total_rmse,
        ledger_sha256=_sha256(ledger),
        governance_status="research_shadow_only",
        production_eligible=False,
    )
