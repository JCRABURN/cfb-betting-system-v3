"""Governed point-in-time rolling-origin research for game totals.

The target is ``actual_home_points + actual_away_points``.  This is not the
EPA margin model under another label: it fits an independent linear total
baseline from four pregame EPA level features obtained only through the
sanctioned ``backtest_harness.get_pregame_stats`` access path.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime

from models import backtest_harness as bh


FEATURE_NAMES = (
    "home_offense_epa_play",
    "home_defense_epa_play",
    "away_offense_epa_play",
    "away_defense_epa_play",
)
MODEL_NAME = "pit_epa_total_linear"
MODEL_VERSION = "pit-epa-total-linear-v1"
FEATURE_SCHEMA_VERSION = "pit-epa-levels-v1"
TARGET_VERSION = "actual-game-total-v1"
PROBABILITY_MODEL_VERSION = "normal-total-residual-v1"
CONFIGURATION_VERSION = "weekly-rolling-origin-ridge-v1"


class TotalsResearchError(ValueError):
    """Raised when totals research inputs are incomplete or unsafe."""


@dataclass(frozen=True)
class TotalsResearchObservation:
    game_id: int
    season: int
    week: int
    kickoff_at: str
    features: tuple[float, float, float, float]
    home_stats_as_of_season: int
    home_stats_as_of_week: int
    away_stats_as_of_season: int
    away_stats_as_of_week: int
    actual_total: float
    opening_total: float | None
    opening_book: str | None

    def __post_init__(self) -> None:
        if self.game_id < 1 or self.season < 1869 or self.week < 0:
            raise TotalsResearchError("game identity is invalid")
        if len(self.features) != len(FEATURE_NAMES) or not all(
            math.isfinite(value) for value in self.features
        ):
            raise TotalsResearchError("totals features must be four finite values")
        try:
            kickoff = datetime.fromisoformat(
                self.kickoff_at.replace("Z", "+00:00")
            )
        except (TypeError, ValueError) as exc:
            raise TotalsResearchError("kickoff_at must be an ISO-8601 timestamp") from exc
        if kickoff.utcoffset() is None or kickoff.utcoffset().total_seconds() != 0:
            raise TotalsResearchError("kickoff_at must be UTC")
        target = (self.season, self.week)
        if (self.home_stats_as_of_season, self.home_stats_as_of_week) >= target:
            raise TotalsResearchError("home feature snapshot must precede target week")
        if (self.away_stats_as_of_season, self.away_stats_as_of_week) >= target:
            raise TotalsResearchError("away feature snapshot must precede target week")
        if not math.isfinite(self.actual_total) or self.actual_total < 0:
            raise TotalsResearchError("actual_total must be finite and nonnegative")
        if (self.opening_total is None) != (self.opening_book is None):
            raise TotalsResearchError(
                "opening_total and opening_book must both be present or absent"
            )
        if self.opening_book is not None and not self.opening_book.strip():
            raise TotalsResearchError("opening_book must be non-empty")
        if self.opening_total is not None and (
            not math.isfinite(self.opening_total) or self.opening_total < 0
        ):
            raise TotalsResearchError("opening_total must be finite and nonnegative")

    @property
    def fold_key(self) -> tuple[int, int]:
        return self.season, self.week


@dataclass(frozen=True)
class TotalsResearchSkip:
    game_id: int
    season: int
    week: int
    reason: str


@dataclass(frozen=True)
class TotalsResearchDataset:
    observations: tuple[TotalsResearchObservation, ...]
    skips: tuple[TotalsResearchSkip, ...]
    dataset_sha256: str

    def __post_init__(self) -> None:
        ordered = tuple(
            sorted(
                self.observations,
                key=lambda item: (
                    item.season,
                    item.week,
                    item.kickoff_at,
                    item.game_id,
                ),
            )
        )
        if ordered != self.observations:
            raise TotalsResearchError("totals observations must be chronological")
        ids = [item.game_id for item in self.observations]
        if len(ids) != len(set(ids)):
            raise TotalsResearchError("totals observations require unique game IDs")
        if self.dataset_sha256 != _dataset_hash(self.observations, self.skips):
            raise TotalsResearchError("totals dataset checksum does not match contents")


@dataclass(frozen=True)
class TotalsResearchPolicy:
    policy_version: str = "totals-research-policy-v1"
    minimum_training_examples: int = 100
    ridge_alpha: float = 0.001
    calibration_slope: float = 1.0
    forecast_tie_direction: str = "under"
    american_price: int = -110
    calibration_bin_count: int = 10

    def __post_init__(self) -> None:
        if self.minimum_training_examples < 5:
            raise TotalsResearchError("minimum_training_examples must be at least 5")
        if not math.isfinite(self.ridge_alpha) or self.ridge_alpha < 0:
            raise TotalsResearchError("ridge_alpha must be finite and nonnegative")
        if not math.isfinite(self.calibration_slope) or self.calibration_slope <= 0:
            raise TotalsResearchError("calibration_slope must be positive")
        if self.forecast_tie_direction not in ("over", "under"):
            raise TotalsResearchError("forecast_tie_direction must be over or under")
        if self.american_price != -110:
            raise TotalsResearchError("v1 totals research is pre-registered at -110")
        if self.calibration_bin_count < 2:
            raise TotalsResearchError("calibration_bin_count must be at least 2")


@dataclass(frozen=True)
class TotalsFoldAudit:
    season: int
    week: int
    training_count: int
    test_count: int
    latest_training_fold: tuple[int, int]
    uncertainty_points: float


@dataclass(frozen=True)
class TotalsSkippedFold:
    season: int
    week: int
    available_training_examples: int
    reason: str


@dataclass(frozen=True)
class TotalsOutOfSamplePrediction:
    game_id: int
    season: int
    week: int
    actual_total: float
    projected_total: float
    uncertainty_points: float
    opening_total: float | None
    selected_direction: str | None
    selected_probability: float | None
    result: str | None
    unit_profit: float | None
    error: float


@dataclass(frozen=True)
class TotalsResearchMetrics:
    forecast_count: int
    mae: float
    rmse: float
    ou_decision_count: int
    wins: int
    losses: int
    pushes: int
    ou_win_rate: float | None
    roi_at_minus_110: float | None
    brier_score: float | None
    log_loss: float | None
    expected_calibration_error: float | None


@dataclass(frozen=True)
class TotalsResearchResult:
    model_name: str
    model_version: str
    feature_schema_version: str
    target_version: str
    probability_model_version: str
    configuration_version: str
    policy: TotalsResearchPolicy
    dataset_sha256: str
    fold_audits: tuple[TotalsFoldAudit, ...]
    skipped_folds: tuple[TotalsSkippedFold, ...]
    predictions: tuple[TotalsOutOfSamplePrediction, ...]
    metrics: TotalsResearchMetrics
    ledger_sha256: str
    governance_status: str
    production_eligible: bool
    recommendation: str


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _dataset_hash(
    observations: tuple[TotalsResearchObservation, ...],
    skips: tuple[TotalsResearchSkip, ...],
) -> str:
    return _canonical_sha256(
        {
            "feature_names": FEATURE_NAMES,
            "target": TARGET_VERSION,
            "observations": [asdict(item) for item in observations],
            "skips": [asdict(item) for item in skips],
        }
    )


def totals_dataset_from_observations(
    observations: tuple[TotalsResearchObservation, ...],
    skips: tuple[TotalsResearchSkip, ...] = (),
) -> TotalsResearchDataset:
    ordered = tuple(
        sorted(
            observations,
            key=lambda item: (
                item.season,
                item.week,
                item.kickoff_at,
                item.game_id,
            ),
        )
    )
    return TotalsResearchDataset(ordered, skips, _dataset_hash(ordered, skips))


def build_totals_research_dataset(
    conn: sqlite3.Connection, *, seasons: tuple[int, ...]
) -> TotalsResearchDataset:
    """Build totals targets and PIT features through the sanctioned accessor."""
    if not seasons or tuple(sorted(set(seasons))) != seasons:
        raise TotalsResearchError("seasons must be unique and increasing")
    observations: list[TotalsResearchObservation] = []
    skips: list[TotalsResearchSkip] = []
    for season in seasons:
        for week in bh.list_weeks(conn, season):
            for game in bh.list_games(conn, season, week):
                game_id, home, away, home_points, away_points, kickoff = game
                package = bh.get_pregame_stats(
                    conn, home, away, season, week, kickoff
                )
                if package is None:
                    skips.append(
                        TotalsResearchSkip(
                            game_id, season, week, "missing_pregame_stats"
                        )
                    )
                    continue
                home_stats = package["home_stats"]
                away_stats = package["away_stats"]
                values = (
                    home_stats["offense_epa_play"],
                    home_stats["defense_epa_play"],
                    away_stats["offense_epa_play"],
                    away_stats["defense_epa_play"],
                )
                if any(value is None for value in values):
                    skips.append(
                        TotalsResearchSkip(game_id, season, week, "missing_epa_level")
                    )
                    continue
                opening = bh.get_opening_line(conn, game_id)
                opening_total = None
                opening_book = None
                if opening is not None and opening["total"] is not None:
                    opening_total = float(opening["total"])
                    opening_book = str(opening["book"])
                observations.append(
                    TotalsResearchObservation(
                        game_id=game_id,
                        season=season,
                        week=week,
                        kickoff_at=kickoff,
                        features=tuple(float(value) for value in values),
                        home_stats_as_of_season=home_stats["as_of_season"],
                        home_stats_as_of_week=home_stats["as_of_week"],
                        away_stats_as_of_season=away_stats["as_of_season"],
                        away_stats_as_of_week=away_stats["as_of_week"],
                        actual_total=float(home_points + away_points),
                        opening_total=opening_total,
                        opening_book=opening_book,
                    )
                )
    return totals_dataset_from_observations(tuple(observations), tuple(skips))


def _solve(matrix: list[list[float]], target: list[float]) -> list[float]:
    size = len(target)
    augmented = [matrix[row][:] + [target[row]] for row in range(size)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise TotalsResearchError("totals linear system is singular")
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
    observations: tuple[TotalsResearchObservation, ...], ridge_alpha: float
) -> tuple[float, tuple[float, float, float, float]]:
    rows = [(1.0, *item.features) for item in observations]
    dimension = len(rows[0])
    gram = [[0.0] * dimension for _ in range(dimension)]
    rhs = [0.0] * dimension
    for row, observation in zip(rows, observations):
        for i in range(dimension):
            rhs[i] += row[i] * observation.actual_total
            for j in range(dimension):
                gram[i][j] += row[i] * row[j]
    for index in range(1, dimension):
        gram[index][index] += ridge_alpha
    fitted = _solve(gram, rhs)
    return fitted[0], tuple(fitted[1:])


def _forecast(
    sealed_features: tuple[float, float, float, float],
    intercept: float,
    coefficients: tuple[float, float, float, float],
) -> float:
    """Predict from sealed PIT features only; no target or connection is passed."""
    return intercept + sum(
        coefficient * feature
        for coefficient, feature in zip(coefficients, sealed_features)
    )


def _normal_cdf(value: float) -> float:
    return 0.5 * (1 + math.erf(value / math.sqrt(2)))


def _symmetric_calibration(probability: float, slope: float) -> float:
    bounded = min(max(probability, 1e-12), 1 - 1e-12)
    logit = math.log(bounded / (1 - bounded))
    scaled = min(max(slope * logit, -700.0), 700.0)
    return 1 / (1 + math.exp(-scaled))


def _metrics(
    predictions: tuple[TotalsOutOfSamplePrediction, ...], bin_count: int
) -> TotalsResearchMetrics:
    if not predictions:
        raise TotalsResearchError("no out-of-sample totals predictions were produced")
    mae = sum(abs(item.error) for item in predictions) / len(predictions)
    rmse = math.sqrt(
        sum(item.error * item.error for item in predictions) / len(predictions)
    )
    graded = tuple(item for item in predictions if item.result is not None)
    wins = sum(item.result == "win" for item in graded)
    losses = sum(item.result == "loss" for item in graded)
    pushes = sum(item.result == "push" for item in graded)
    decisions = wins + losses
    win_rate = wins / decisions if decisions else None
    roi = (
        sum(item.unit_profit or 0.0 for item in graded) / len(graded)
        if graded
        else None
    )
    probability_rows = tuple(item for item in graded if item.result != "push")
    if probability_rows:
        outcomes = [1.0 if item.result == "win" else 0.0 for item in probability_rows]
        probabilities = [float(item.selected_probability) for item in probability_rows]
        brier = sum(
            (probability - outcome) ** 2
            for probability, outcome in zip(probabilities, outcomes)
        ) / len(probability_rows)
        log_loss = -sum(
            outcome * math.log(min(max(probability, 1e-12), 1 - 1e-12))
            + (1 - outcome)
            * math.log(min(max(1 - probability, 1e-12), 1 - 1e-12))
            for probability, outcome in zip(probabilities, outcomes)
        ) / len(probability_rows)
        bins: list[list[tuple[float, float]]] = [[] for _ in range(bin_count)]
        for probability, outcome in zip(probabilities, outcomes):
            index = min(int(probability * bin_count), bin_count - 1)
            bins[index].append((probability, outcome))
        calibration_error = sum(
            len(items)
            / len(probability_rows)
            * abs(
                sum(item[0] for item in items) / len(items)
                - sum(item[1] for item in items) / len(items)
            )
            for items in bins
            if items
        )
    else:
        brier = log_loss = calibration_error = None
    return TotalsResearchMetrics(
        forecast_count=len(predictions),
        mae=mae,
        rmse=rmse,
        ou_decision_count=len(graded),
        wins=wins,
        losses=losses,
        pushes=pushes,
        ou_win_rate=win_rate,
        roi_at_minus_110=roi,
        brier_score=brier,
        log_loss=log_loss,
        expected_calibration_error=calibration_error,
    )


def run_totals_rolling_origin(
    dataset: TotalsResearchDataset,
    *,
    policy: TotalsResearchPolicy = TotalsResearchPolicy(),
) -> TotalsResearchResult:
    """Fit each weekly fold only on observations from strictly earlier folds."""
    if not isinstance(dataset, TotalsResearchDataset):
        raise TotalsResearchError("dataset must be a TotalsResearchDataset")
    folds = sorted({item.fold_key for item in dataset.observations})
    fold_audits: list[TotalsFoldAudit] = []
    skipped_folds: list[TotalsSkippedFold] = []
    predictions: list[TotalsOutOfSamplePrediction] = []
    for fold in folds:
        training = tuple(
            item for item in dataset.observations if item.fold_key < fold
        )
        testing = tuple(
            item for item in dataset.observations if item.fold_key == fold
        )
        if len(training) < policy.minimum_training_examples:
            skipped_folds.append(
                TotalsSkippedFold(
                    fold[0],
                    fold[1],
                    len(training),
                    "insufficient_prior_training_examples",
                )
            )
            continue
        intercept, coefficients = _fit(training, policy.ridge_alpha)
        training_errors = [
            item.actual_total - _forecast(item.features, intercept, coefficients)
            for item in training
        ]
        uncertainty = math.sqrt(
            sum(error * error for error in training_errors) / len(training_errors)
        )
        if not math.isfinite(uncertainty) or uncertainty <= 0:
            raise TotalsResearchError("training residual uncertainty is invalid")
        fold_audits.append(
            TotalsFoldAudit(
                season=fold[0],
                week=fold[1],
                training_count=len(training),
                test_count=len(testing),
                latest_training_fold=max(item.fold_key for item in training),
                uncertainty_points=uncertainty,
            )
        )
        for item in testing:
            projected = _forecast(item.features, intercept, coefficients)
            direction = None
            selected_probability = None
            result = None
            unit_profit = None
            if item.opening_total is not None:
                raw_over = _normal_cdf(
                    (projected - item.opening_total) / uncertainty
                )
                calibrated_over = _symmetric_calibration(
                    raw_over, policy.calibration_slope
                )
                if projected > item.opening_total:
                    direction = "over"
                elif projected < item.opening_total:
                    direction = "under"
                else:
                    direction = policy.forecast_tie_direction
                selected_probability = (
                    calibrated_over if direction == "over" else 1 - calibrated_over
                )
                if item.actual_total == item.opening_total:
                    result = "push"
                    unit_profit = 0.0
                else:
                    actual_direction = (
                        "over" if item.actual_total > item.opening_total else "under"
                    )
                    result = "win" if direction == actual_direction else "loss"
                    unit_profit = 100 / 110 if result == "win" else -1.0
            predictions.append(
                TotalsOutOfSamplePrediction(
                    game_id=item.game_id,
                    season=item.season,
                    week=item.week,
                    actual_total=item.actual_total,
                    projected_total=projected,
                    uncertainty_points=uncertainty,
                    opening_total=item.opening_total,
                    selected_direction=direction,
                    selected_probability=selected_probability,
                    result=result,
                    unit_profit=unit_profit,
                    error=projected - item.actual_total,
                )
            )
    prediction_tuple = tuple(predictions)
    metrics = _metrics(prediction_tuple, policy.calibration_bin_count)
    ledger_hash = _canonical_sha256(
        {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "target_version": TARGET_VERSION,
            "probability_model_version": PROBABILITY_MODEL_VERSION,
            "configuration_version": CONFIGURATION_VERSION,
            "policy": asdict(policy),
            "dataset_sha256": dataset.dataset_sha256,
            "fold_audits": [asdict(item) for item in fold_audits],
            "skipped_folds": [asdict(item) for item in skipped_folds],
            "predictions": [asdict(item) for item in prediction_tuple],
            "metrics": asdict(metrics),
        }
    )
    return TotalsResearchResult(
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        target_version=TARGET_VERSION,
        probability_model_version=PROBABILITY_MODEL_VERSION,
        configuration_version=CONFIGURATION_VERSION,
        policy=policy,
        dataset_sha256=dataset.dataset_sha256,
        fold_audits=tuple(fold_audits),
        skipped_folds=tuple(skipped_folds),
        predictions=prediction_tuple,
        metrics=metrics,
        ledger_sha256=ledger_hash,
        governance_status="research_shadow_only",
        production_eligible=False,
        recommendation=(
            "TOTALS PRODUCTION ELIGIBLE: NO. This first independent baseline has "
            "no pre-registered promoted comparator and remains research/shadow only."
        ),
    )
