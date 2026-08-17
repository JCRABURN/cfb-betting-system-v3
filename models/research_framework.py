"""Point-in-time-safe, weekly rolling-origin model research framework.

This module extends the sanctioned access path in ``backtest_harness``.  A
candidate model never receives a database connection, closing line, final
score, or test target.  It can fit only ``TrainingExample`` objects from folds
strictly earlier than the week being evaluated and can predict only sealed
``ModelInput`` objects.

The research target is market residual::

    actual_home_margin - market_implied_home_margin

where ``market_implied_home_margin == -opening_home_spread``.  Closing lines
remain evaluation-only CLV inputs.  The EPA-only linear model is the mandatory
baseline; candidates can use ridge regression, dynamic team ratings, or
deterministic gradient-boosted decision stumps.  Promotion is never automatic:
a candidate that clears every pre-registered criterion is recorded only as
``candidate_pending_owner_approval`` under its new model version.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Protocol

from models import backtest_harness as bh


SUPPORTED_FEATURES = (
    "epa_differential",
    "success_rate_differential",
    "havoc_rate_differential",
    "rest_days_differential",
    "bye_flag_differential",
)
SUPPORTED_MODEL_FAMILIES = (
    "epa_only_baseline",
    "regularized_linear",
    "dynamic_team_rating",
    "gradient_boosted_stumps",
)
BYE_THRESHOLD_DAYS = 10


class ResearchError(ValueError):
    """Raised when a research run would be incomplete or unsafe."""


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchError(f"{field} must be non-empty text")
    return value.strip()


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResearchError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ResearchError(f"{field} must be finite")
    return number


def _positive_integer(value: object, field: str, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ResearchError(f"{field} must be an integer >= {minimum}")
    return value


def _utc_datetime(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ResearchError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None:
        raise ResearchError(f"{field} must include a UTC offset")
    if parsed.utcoffset().total_seconds() != 0:
        raise ResearchError(f"{field} must be UTC")
    return parsed


def _sha(value: str, length: int, field: str) -> str:
    value = _required_text(value, field)
    if (
        value != value.lower()
        or len(value) != length
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ResearchError(f"{field} must be a {length}-character lowercase hex digest")
    return value


@dataclass(frozen=True)
class ModelInput:
    game_id: int
    season: int
    week: int
    kickoff_at: str
    home_team: str
    away_team: str
    features: tuple[tuple[str, float], ...]
    opening_spread: float
    opening_book: str

    def feature(self, name: str) -> float:
        for feature_name, value in self.features:
            if feature_name == name:
                return value
        raise ResearchError(f"sealed model input lacks required feature: {name}")


@dataclass(frozen=True)
class ResearchObservation:
    model_input: ModelInput
    actual_home_margin: float
    closing_spread: float | None
    closing_book: str | None
    home_stats_as_of_season: int
    home_stats_as_of_week: int
    away_stats_as_of_season: int
    away_stats_as_of_week: int
    opening_line_type: str = "opening"

    def __post_init__(self) -> None:
        _positive_integer(self.model_input.game_id, "game_id")
        _positive_integer(self.model_input.season, "season")
        _positive_integer(self.model_input.week, "week")
        _utc_datetime(self.model_input.kickoff_at, "kickoff_at")
        _required_text(self.model_input.home_team, "home_team")
        _required_text(self.model_input.away_team, "away_team")
        if self.model_input.home_team == self.model_input.away_team:
            raise ResearchError("home_team and away_team must differ")
        _finite(self.model_input.opening_spread, "opening_spread")
        _required_text(self.model_input.opening_book, "opening_book")
        _finite(self.actual_home_margin, "actual_home_margin")
        if self.opening_line_type != "opening":
            raise ResearchError("research observations require a genuine opening line")
        if (self.closing_spread is None) != (self.closing_book is None):
            raise ResearchError("closing_spread and closing_book must both be present or absent")
        if self.closing_spread is not None:
            _finite(self.closing_spread, "closing_spread")
            _required_text(self.closing_book, "closing_book")
        feature_names = [name for name, _ in self.model_input.features]
        if not feature_names or len(feature_names) != len(set(feature_names)):
            raise ResearchError("features must contain unique named values")
        for name, value in self.model_input.features:
            if name not in SUPPORTED_FEATURES:
                raise ResearchError(f"unsupported research feature: {name}")
            _finite(value, f"feature[{name}]")
        self._validate_as_of(
            self.home_stats_as_of_season,
            self.home_stats_as_of_week,
            "home",
        )
        self._validate_as_of(
            self.away_stats_as_of_season,
            self.away_stats_as_of_week,
            "away",
        )

    def _validate_as_of(self, season: int, week: int, side: str) -> None:
        _positive_integer(season, f"{side}_stats_as_of_season")
        _positive_integer(week, f"{side}_stats_as_of_week")
        target = (self.model_input.season, self.model_input.week)
        if (season, week) >= target:
            raise ResearchError(
                f"{side} feature snapshot must be strictly before the target week"
            )

    @property
    def fold_key(self) -> tuple[int, int]:
        return self.model_input.season, self.model_input.week

    @property
    def market_residual(self) -> float:
        return self.actual_home_margin + self.model_input.opening_spread


@dataclass(frozen=True)
class ResearchBuildSkip:
    game_id: int
    season: int
    week: int
    reason: str


@dataclass(frozen=True)
class ResearchDataset:
    feature_names: tuple[str, ...]
    observations: tuple[ResearchObservation, ...]
    skips: tuple[ResearchBuildSkip, ...]
    dataset_sha256: str

    def __post_init__(self) -> None:
        if not self.feature_names or len(set(self.feature_names)) != len(
            self.feature_names
        ):
            raise ResearchError("dataset feature names must be non-empty and unique")
        if set(self.feature_names) - set(SUPPORTED_FEATURES):
            raise ResearchError("dataset contains unsupported features")
        ordered = tuple(
            sorted(
                self.observations,
                key=lambda item: (
                    item.model_input.season,
                    item.model_input.week,
                    item.model_input.kickoff_at,
                    item.model_input.game_id,
                ),
            )
        )
        if ordered != self.observations:
            raise ResearchError("dataset observations must be chronologically ordered")
        game_ids = [item.model_input.game_id for item in self.observations]
        if len(game_ids) != len(set(game_ids)):
            raise ResearchError("dataset observations must have unique game IDs")
        for observation in self.observations:
            observation_features = tuple(
                name for name, _ in observation.model_input.features
            )
            if observation_features != self.feature_names:
                raise ResearchError(
                    "every observation must match the declared feature schema"
                )
        _sha(self.dataset_sha256, 64, "dataset_sha256")
        if self.dataset_sha256 != _dataset_hash(
            self.feature_names,
            self.observations,
            self.skips,
        ):
            raise ResearchError("dataset SHA-256 does not match its canonical contents")


def _feature_values(package: dict[str, object]) -> dict[str, float | None]:
    home = package["home_stats"]
    away = package["away_stats"]
    home_epa = home["offense_epa_play"] - home["defense_epa_play"]
    away_epa = away["offense_epa_play"] - away["defense_epa_play"]
    values: dict[str, float | None] = {
        "epa_differential": home_epa - away_epa,
    }
    success_fields = (
        home["offense_success_rate"],
        home["defense_success_rate"],
        away["offense_success_rate"],
        away["defense_success_rate"],
    )
    values["success_rate_differential"] = (
        None
        if any(value is None for value in success_fields)
        else (
            home["offense_success_rate"]
            - home["defense_success_rate"]
            - away["offense_success_rate"]
            + away["defense_success_rate"]
        )
    )
    values["havoc_rate_differential"] = (
        None
        if home["havoc_rate"] is None or away["havoc_rate"] is None
        else home["havoc_rate"] - away["havoc_rate"]
    )
    home_rest = package["home_days_rest"]
    away_rest = package["away_days_rest"]
    values["rest_days_differential"] = (
        None if home_rest is None or away_rest is None else home_rest - away_rest
    )
    values["bye_flag_differential"] = (
        None
        if home_rest is None or away_rest is None
        else int(home_rest >= BYE_THRESHOLD_DAYS)
        - int(away_rest >= BYE_THRESHOLD_DAYS)
    )
    return values


def _dataset_hash(
    feature_names: tuple[str, ...],
    observations: tuple[ResearchObservation, ...],
    skips: tuple[ResearchBuildSkip, ...],
) -> str:
    canonical = json.dumps(
        {
            "feature_names": feature_names,
            "observations": [asdict(observation) for observation in observations],
            "skips": [asdict(skip) for skip in skips],
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def research_dataset_from_observations(
    *,
    feature_names: tuple[str, ...],
    observations: tuple[ResearchObservation, ...],
    skips: tuple[ResearchBuildSkip, ...] = (),
) -> ResearchDataset:
    """Seal an already constructed fixture or recorded observation set."""
    ordered = tuple(
        sorted(
            observations,
            key=lambda item: (
                item.model_input.season,
                item.model_input.week,
                item.model_input.kickoff_at,
                item.model_input.game_id,
            ),
        )
    )
    return ResearchDataset(
        feature_names,
        ordered,
        skips,
        _dataset_hash(feature_names, ordered, skips),
    )


def build_research_dataset(
    conn: sqlite3.Connection,
    *,
    seasons: tuple[int, ...],
    feature_names: tuple[str, ...],
    require_closing_line: bool = False,
) -> ResearchDataset:
    """Build sealed observations exclusively through the sanctioned harness."""
    if not seasons or tuple(sorted(set(seasons))) != seasons:
        raise ResearchError("seasons must be unique and strictly increasing")
    if not feature_names or len(set(feature_names)) != len(feature_names):
        raise ResearchError("feature_names must be non-empty and unique")
    unknown = set(feature_names) - set(SUPPORTED_FEATURES)
    if unknown:
        raise ResearchError(f"unsupported research features: {sorted(unknown)}")

    observations: list[ResearchObservation] = []
    skips: list[ResearchBuildSkip] = []
    for season in seasons:
        for week in bh.list_weeks(conn, season):
            for game in bh.list_games(conn, season, week):
                game_id, home, away, home_points, away_points, kickoff_at = game
                package, reason = bh.build_feature_package(
                    conn,
                    game_id,
                    season,
                    week,
                    home,
                    away,
                    kickoff_at,
                )
                if package is None:
                    skips.append(ResearchBuildSkip(game_id, season, week, reason))
                    continue
                values = _feature_values(package)
                missing = next(
                    (name for name in feature_names if values[name] is None),
                    None,
                )
                if missing is not None:
                    skips.append(
                        ResearchBuildSkip(
                            game_id,
                            season,
                            week,
                            f"missing_feature:{missing}",
                        )
                    )
                    continue
                closing = bh.get_closing_line(
                    conn,
                    game_id,
                    book=package["opening_book"],
                )
                if closing is None and require_closing_line:
                    skips.append(
                        ResearchBuildSkip(game_id, season, week, "missing_closing_line")
                    )
                    continue
                model_input = ModelInput(
                    game_id=game_id,
                    season=season,
                    week=week,
                    kickoff_at=_utc_datetime(kickoff_at, "kickoff_at").isoformat(),
                    home_team=home,
                    away_team=away,
                    features=tuple(
                        (name, float(values[name])) for name in feature_names
                    ),
                    opening_spread=float(package["opening_spread"]),
                    opening_book=package["opening_book"],
                )
                observations.append(
                    ResearchObservation(
                        model_input=model_input,
                        actual_home_margin=float(home_points - away_points),
                        closing_spread=(
                            None if closing is None else float(closing["home_spread"])
                        ),
                        closing_book=(None if closing is None else closing["book"]),
                        home_stats_as_of_season=package["home_stats"]["as_of_season"],
                        home_stats_as_of_week=package["home_stats"]["as_of_week"],
                        away_stats_as_of_season=package["away_stats"]["as_of_season"],
                        away_stats_as_of_week=package["away_stats"]["as_of_week"],
                    )
                )
    ordered = tuple(
        sorted(
            observations,
            key=lambda item: (
                item.model_input.season,
                item.model_input.week,
                item.model_input.kickoff_at,
                item.model_input.game_id,
            ),
        )
    )
    skip_tuple = tuple(skips)
    return research_dataset_from_observations(
        feature_names=feature_names,
        observations=ordered,
        skips=skip_tuple,
    )


@dataclass(frozen=True)
class TrainingExample:
    model_input: ModelInput
    market_residual: float


@dataclass(frozen=True)
class ModelSpec:
    model_key: str
    model_version: str
    family: str
    feature_names: tuple[str, ...]
    hyperparameters: tuple[tuple[str, float | int | str], ...]
    target: str = "market_residual_v1"

    def __post_init__(self) -> None:
        _required_text(self.model_key, "model_key")
        _required_text(self.model_version, "model_version")
        if self.family not in SUPPORTED_MODEL_FAMILIES:
            raise ResearchError(f"unsupported model family: {self.family}")
        if self.target != "market_residual_v1":
            raise ResearchError("all research models must predict market residual")
        if len(set(self.feature_names)) != len(self.feature_names):
            raise ResearchError("model feature names must be unique")
        if set(self.feature_names) - set(SUPPORTED_FEATURES):
            raise ResearchError("model spec contains unsupported features")
        parameter_names = [name for name, _ in self.hyperparameters]
        if len(parameter_names) != len(set(parameter_names)):
            raise ResearchError("model hyperparameter names must be unique")
        for name, value in self.hyperparameters:
            _required_text(name, "hyperparameter name")
            if not isinstance(value, str):
                _finite(value, f"hyperparameter[{name}]")


class FittedResearchModel(Protocol):
    def predict_market_residual(self, model_input: ModelInput) -> float: ...


class ResearchModel(Protocol):
    spec: ModelSpec

    def fit(self, examples: tuple[TrainingExample, ...]) -> FittedResearchModel: ...


def _solve_linear_system(matrix: list[list[float]], target: list[float]) -> list[float]:
    size = len(target)
    augmented = [row[:] + [target[index]] for index, row in enumerate(matrix)]
    for column in range(size):
        pivot_row = max(
            range(column, size),
            key=lambda row: abs(augmented[row][column]),
        )
        if abs(augmented[pivot_row][column]) < 1e-12:
            raise ResearchError("training design is singular")
        augmented[column], augmented[pivot_row] = (
            augmented[pivot_row],
            augmented[column],
        )
        pivot = augmented[column][column]
        augmented[column] = [value / pivot for value in augmented[column]]
        for row in range(size):
            if row == column:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                augmented[row][index] - factor * augmented[column][index]
                for index in range(size + 1)
            ]
    return [augmented[index][size] for index in range(size)]


@dataclass(frozen=True)
class _FittedLinearModel:
    feature_names: tuple[str, ...]
    means: tuple[float, ...]
    scales: tuple[float, ...]
    intercept: float
    coefficients: tuple[float, ...]

    def predict_market_residual(self, model_input: ModelInput) -> float:
        standardized = tuple(
            (model_input.feature(name) - mean) / scale
            for name, mean, scale in zip(
                self.feature_names,
                self.means,
                self.scales,
            )
        )
        return self.intercept + sum(
            coefficient * value
            for coefficient, value in zip(self.coefficients, standardized)
        )


@dataclass(frozen=True)
class RegularizedLinearModel:
    spec: ModelSpec
    l2_penalty: float

    def __post_init__(self) -> None:
        penalty = _finite(self.l2_penalty, "l2_penalty")
        if penalty < 0:
            raise ResearchError("l2_penalty cannot be negative")
        if not self.spec.feature_names:
            raise ResearchError("linear models require at least one feature")
        expected = (
            "epa_only_baseline" if penalty == 0 else "regularized_linear"
        )
        if self.spec.family != expected:
            raise ResearchError(
                f"linear model with l2_penalty={penalty} must use family {expected}"
            )

    def fit(self, examples: tuple[TrainingExample, ...]) -> _FittedLinearModel:
        feature_count = len(self.spec.feature_names)
        if len(examples) < feature_count + 2:
            raise ResearchError("linear model has insufficient training observations")
        columns = [
            [example.model_input.feature(name) for example in examples]
            for name in self.spec.feature_names
        ]
        means = tuple(sum(column) / len(column) for column in columns)
        scales = []
        for column, mean in zip(columns, means):
            variance = sum((value - mean) ** 2 for value in column) / len(column)
            scale = math.sqrt(variance)
            if scale < 1e-12:
                raise ResearchError("linear model feature has zero variance")
            scales.append(scale)
        rows = [
            [1.0]
            + [
                (example.model_input.feature(name) - mean) / scale
                for name, mean, scale in zip(
                    self.spec.feature_names,
                    means,
                    scales,
                )
            ]
            for example in examples
        ]
        targets = [example.market_residual for example in examples]
        size = feature_count + 1
        xtx = [
            [
                sum(row[left] * row[right] for row in rows)
                for right in range(size)
            ]
            for left in range(size)
        ]
        for index in range(1, size):
            xtx[index][index] += self.l2_penalty
        xty = [
            sum(row[index] * target for row, target in zip(rows, targets))
            for index in range(size)
        ]
        beta = _solve_linear_system(xtx, xty)
        return _FittedLinearModel(
            self.spec.feature_names,
            means,
            tuple(scales),
            beta[0],
            tuple(beta[1:]),
        )


def epa_only_baseline(*, model_version: str = "epa-residual-baseline-v1") -> RegularizedLinearModel:
    return RegularizedLinearModel(
        ModelSpec(
            model_key="epa_only_baseline",
            model_version=model_version,
            family="epa_only_baseline",
            feature_names=("epa_differential",),
            hyperparameters=(("l2_penalty", 0.0),),
        ),
        l2_penalty=0.0,
    )


def ridge_candidate(
    *,
    model_key: str,
    model_version: str,
    feature_names: tuple[str, ...],
    l2_penalty: float,
) -> RegularizedLinearModel:
    penalty = _finite(l2_penalty, "l2_penalty")
    if penalty <= 0:
        raise ResearchError("ridge candidates require l2_penalty > 0")
    return RegularizedLinearModel(
        ModelSpec(
            model_key=model_key,
            model_version=model_version,
            family="regularized_linear",
            feature_names=feature_names,
            hyperparameters=(("l2_penalty", penalty),),
        ),
        l2_penalty=penalty,
    )


@dataclass(frozen=True)
class _DecisionStump:
    feature_name: str
    threshold: float
    left_value: float
    right_value: float


@dataclass(frozen=True)
class _FittedBoostedModel:
    initial_value: float
    learning_rate: float
    stumps: tuple[_DecisionStump, ...]

    def predict_market_residual(self, model_input: ModelInput) -> float:
        prediction = self.initial_value
        for stump in self.stumps:
            value = model_input.feature(stump.feature_name)
            leaf = stump.left_value if value <= stump.threshold else stump.right_value
            prediction += self.learning_rate * leaf
        return prediction


@dataclass(frozen=True)
class GradientBoostedStumpsModel:
    spec: ModelSpec
    estimator_count: int
    learning_rate: float
    minimum_leaf_size: int

    def __post_init__(self) -> None:
        if self.spec.family != "gradient_boosted_stumps":
            raise ResearchError("gradient boosted model has the wrong family")
        if not self.spec.feature_names:
            raise ResearchError("gradient boosted models require features")
        _positive_integer(self.estimator_count, "estimator_count")
        _positive_integer(self.minimum_leaf_size, "minimum_leaf_size")
        rate = _finite(self.learning_rate, "learning_rate")
        if rate <= 0 or rate > 1:
            raise ResearchError("learning_rate must be within (0, 1]")

    def fit(self, examples: tuple[TrainingExample, ...]) -> _FittedBoostedModel:
        if len(examples) < 2 * self.minimum_leaf_size:
            raise ResearchError("gradient boosting has insufficient training observations")
        targets = [example.market_residual for example in examples]
        initial = sum(targets) / len(targets)
        predictions = [initial] * len(examples)
        stumps: list[_DecisionStump] = []
        for _ in range(self.estimator_count):
            residuals = [target - prediction for target, prediction in zip(targets, predictions)]
            best: tuple[float, int, float, float, float] | None = None
            for feature_index, feature_name in enumerate(self.spec.feature_names):
                ordered = sorted(
                    (
                        example.model_input.feature(feature_name),
                        residuals[index],
                    )
                    for index, example in enumerate(examples)
                )
                total_sum = sum(residual for _, residual in ordered)
                total_square_sum = sum(
                    residual * residual for _, residual in ordered
                )
                left_sum = 0.0
                left_square_sum = 0.0
                for split_index in range(1, len(ordered)):
                    prior_residual = ordered[split_index - 1][1]
                    left_sum += prior_residual
                    left_square_sum += prior_residual * prior_residual
                    left_count = split_index
                    right_count = len(ordered) - split_index
                    if (
                        left_count < self.minimum_leaf_size
                        or right_count < self.minimum_leaf_size
                        or ordered[split_index - 1][0] == ordered[split_index][0]
                    ):
                        continue
                    right_sum = total_sum - left_sum
                    right_square_sum = total_square_sum - left_square_sum
                    left_value = left_sum / left_count
                    right_value = right_sum / right_count
                    error = (
                        left_square_sum - left_sum * left_sum / left_count
                        + right_square_sum
                        - right_sum * right_sum / right_count
                    )
                    threshold = (
                        ordered[split_index - 1][0] + ordered[split_index][0]
                    ) / 2
                    candidate = (
                        error,
                        feature_index,
                        threshold,
                        left_value,
                        right_value,
                    )
                    if best is None or candidate < best:
                        best = candidate
            if best is None:
                break
            _, feature_index, threshold, left_value, right_value = best
            stump = _DecisionStump(
                self.spec.feature_names[feature_index],
                threshold,
                left_value,
                right_value,
            )
            stumps.append(stump)
            for index, example in enumerate(examples):
                value = example.model_input.feature(stump.feature_name)
                leaf = stump.left_value if value <= stump.threshold else stump.right_value
                predictions[index] += self.learning_rate * leaf
        if not stumps:
            raise ResearchError("gradient boosting could not form a valid split")
        return _FittedBoostedModel(initial, self.learning_rate, tuple(stumps))


def gradient_boosted_candidate(
    *,
    model_key: str,
    model_version: str,
    feature_names: tuple[str, ...],
    estimator_count: int,
    learning_rate: float,
    minimum_leaf_size: int,
) -> GradientBoostedStumpsModel:
    return GradientBoostedStumpsModel(
        ModelSpec(
            model_key=model_key,
            model_version=model_version,
            family="gradient_boosted_stumps",
            feature_names=feature_names,
            hyperparameters=(
                ("estimator_count", estimator_count),
                ("learning_rate", learning_rate),
                ("minimum_leaf_size", minimum_leaf_size),
            ),
        ),
        estimator_count,
        learning_rate,
        minimum_leaf_size,
    )


@dataclass(frozen=True)
class _FittedDynamicRatings:
    ratings: tuple[tuple[str, float], ...]
    unknown_team_rating: float = 0.0

    def predict_market_residual(self, model_input: ModelInput) -> float:
        by_team = dict(self.ratings)
        return by_team.get(
            model_input.home_team,
            self.unknown_team_rating,
        ) - by_team.get(model_input.away_team, self.unknown_team_rating)


@dataclass(frozen=True)
class DynamicTeamRatingModel:
    spec: ModelSpec
    update_rate: float
    carry_decay: float

    def __post_init__(self) -> None:
        if self.spec.family != "dynamic_team_rating" or self.spec.feature_names:
            raise ResearchError("dynamic team ratings use team identity, not feature columns")
        update = _finite(self.update_rate, "update_rate")
        decay = _finite(self.carry_decay, "carry_decay")
        if update <= 0 or update > 1:
            raise ResearchError("update_rate must be within (0, 1]")
        if decay < 0 or decay >= 1:
            raise ResearchError("carry_decay must be within [0, 1)")

    def fit(self, examples: tuple[TrainingExample, ...]) -> _FittedDynamicRatings:
        if len(examples) < 2:
            raise ResearchError("dynamic ratings require at least two training games")
        ratings: dict[str, float] = {}
        prior_season: int | None = None
        ordered = sorted(
            examples,
            key=lambda item: (
                item.model_input.season,
                item.model_input.week,
                item.model_input.kickoff_at,
                item.model_input.game_id,
            ),
        )
        for example in ordered:
            if prior_season is not None and example.model_input.season != prior_season:
                ratings = {
                    team: rating * (1 - self.carry_decay)
                    for team, rating in ratings.items()
                }
            prior_season = example.model_input.season
            home = example.model_input.home_team
            away = example.model_input.away_team
            prediction = ratings.get(home, 0.0) - ratings.get(away, 0.0)
            error = example.market_residual - prediction
            change = self.update_rate * error / 2
            ratings[home] = ratings.get(home, 0.0) + change
            ratings[away] = ratings.get(away, 0.0) - change
        return _FittedDynamicRatings(tuple(sorted(ratings.items())))


def dynamic_rating_candidate(
    *,
    model_key: str,
    model_version: str,
    update_rate: float,
    carry_decay: float,
) -> DynamicTeamRatingModel:
    return DynamicTeamRatingModel(
        ModelSpec(
            model_key=model_key,
            model_version=model_version,
            family="dynamic_team_rating",
            feature_names=(),
            hyperparameters=(
                ("update_rate", update_rate),
                ("carry_decay", carry_decay),
                ("unknown_team_rating", 0.0),
            ),
        ),
        update_rate,
        carry_decay,
    )


@dataclass(frozen=True)
class IsotonicCalibrator:
    upper_bounds: tuple[float, ...]
    calibrated_values: tuple[float, ...]

    def predict(self, probability: float) -> float:
        for upper_bound, value in zip(self.upper_bounds, self.calibrated_values):
            if probability <= upper_bound:
                return value
        return self.calibrated_values[-1]


def fit_isotonic_calibrator(
    pairs: tuple[tuple[float, int], ...],
) -> IsotonicCalibrator:
    if len(pairs) < 2 or {outcome for _, outcome in pairs} != {0, 1}:
        raise ResearchError("calibration requires both cover outcomes")
    ordered = sorted(pairs)
    blocks: list[list[float]] = []
    for probability, outcome in ordered:
        if outcome not in (0, 1):
            raise ResearchError("calibration outcomes must be binary")
        blocks.append([probability, probability, float(outcome), 1.0])
        while len(blocks) >= 2:
            left_mean = blocks[-2][2] / blocks[-2][3]
            right_mean = blocks[-1][2] / blocks[-1][3]
            if left_mean <= right_mean:
                break
            right = blocks.pop()
            left = blocks.pop()
            blocks.append(
                [left[0], right[1], left[2] + right[2], left[3] + right[3]]
            )
    return IsotonicCalibrator(
        tuple(block[1] for block in blocks),
        tuple(block[2] / block[3] for block in blocks),
    )


@dataclass(frozen=True)
class ResearchPolicy:
    policy_version: str
    minimum_training_observations: int
    minimum_fit_observations: int
    minimum_calibration_observations: int
    calibration_fraction: float
    minimum_uncertainty_points: float
    probability_clip: float
    calibration_bin_count: int
    minimum_oos_predictions: int
    minimum_oos_seasons: int
    minimum_mae_improvement: float
    minimum_rmse_improvement: float
    minimum_brier_improvement: float
    minimum_log_loss_improvement: float
    maximum_calibration_error_increase: float
    minimum_ats_improvement: float
    minimum_roi_improvement: float
    minimum_clv_improvement: float
    maximum_drawdown_increase: float
    minimum_confidence_monotonicity: float
    confidence_probability_thresholds: tuple[float, float, float, float]
    target_method: str = "opening_market_residual_v1"
    fold_method: str = "weekly_rolling_origin_strict_prior_v1"
    calibration_method: str = "chronological_holdout_isotonic_v1"
    uncertainty_method: str = "holdout_rmse_with_floor_v1"
    promotion_method: str = "all_metrics_then_owner_approval_v1"
    probability_tie_side: str = "away"

    def __post_init__(self) -> None:
        _required_text(self.policy_version, "policy_version")
        training = _positive_integer(
            self.minimum_training_observations,
            "minimum_training_observations",
            4,
        )
        fit = _positive_integer(self.minimum_fit_observations, "minimum_fit_observations", 2)
        calibration = _positive_integer(
            self.minimum_calibration_observations,
            "minimum_calibration_observations",
            2,
        )
        if fit + calibration > training:
            raise ResearchError(
                "minimum fit and calibration samples cannot exceed minimum training"
            )
        fraction = _finite(self.calibration_fraction, "calibration_fraction")
        if fraction <= 0 or fraction >= 1:
            raise ResearchError("calibration_fraction must be within (0, 1)")
        uncertainty = _finite(
            self.minimum_uncertainty_points,
            "minimum_uncertainty_points",
        )
        if uncertainty <= 0:
            raise ResearchError("minimum_uncertainty_points must be positive")
        clip = _finite(self.probability_clip, "probability_clip")
        if clip <= 0 or clip >= 0.5:
            raise ResearchError("probability_clip must be within (0, 0.5)")
        _positive_integer(self.calibration_bin_count, "calibration_bin_count", 2)
        _positive_integer(self.minimum_oos_predictions, "minimum_oos_predictions")
        _positive_integer(self.minimum_oos_seasons, "minimum_oos_seasons")
        nonnegative_fields = (
            "minimum_mae_improvement",
            "minimum_rmse_improvement",
            "minimum_brier_improvement",
            "minimum_log_loss_improvement",
            "maximum_calibration_error_increase",
            "minimum_ats_improvement",
            "minimum_roi_improvement",
            "minimum_clv_improvement",
            "maximum_drawdown_increase",
            "minimum_confidence_monotonicity",
        )
        for field in nonnegative_fields:
            value = _finite(getattr(self, field), field)
            if value < 0:
                raise ResearchError(f"{field} cannot be negative")
        if self.minimum_confidence_monotonicity > 1:
            raise ResearchError("minimum_confidence_monotonicity cannot exceed 1")
        thresholds = self.confidence_probability_thresholds
        for index, threshold in enumerate(thresholds):
            _finite(threshold, f"confidence_probability_thresholds[{index}]")
        if len(thresholds) != 4 or tuple(sorted(thresholds)) != thresholds:
            raise ResearchError("confidence probability thresholds must strictly increase")
        if len(set(thresholds)) != 4 or thresholds[0] <= 0.5 or thresholds[-1] >= 1:
            raise ResearchError("confidence thresholds must be unique within (0.5, 1)")
        fixed_methods = {
            "target_method": "opening_market_residual_v1",
            "fold_method": "weekly_rolling_origin_strict_prior_v1",
            "calibration_method": "chronological_holdout_isotonic_v1",
            "uncertainty_method": "holdout_rmse_with_floor_v1",
            "promotion_method": "all_metrics_then_owner_approval_v1",
        }
        for field, expected in fixed_methods.items():
            if getattr(self, field) != expected:
                raise ResearchError(f"{field} must be {expected}")
        if self.probability_tie_side != "away":
            raise ResearchError("probability_tie_side must be away for v1")


def default_research_policy() -> ResearchPolicy:
    """Pre-registered v1 criteria; do not tune these after observing results."""
    return ResearchPolicy(
        policy_version="weekly-market-residual-research-v1",
        minimum_training_observations=500,
        minimum_fit_observations=400,
        minimum_calibration_observations=100,
        calibration_fraction=0.20,
        minimum_uncertainty_points=1.0,
        probability_clip=0.000001,
        calibration_bin_count=10,
        minimum_oos_predictions=1000,
        minimum_oos_seasons=4,
        minimum_mae_improvement=0.10,
        minimum_rmse_improvement=0.10,
        minimum_brier_improvement=0.002,
        minimum_log_loss_improvement=0.002,
        maximum_calibration_error_increase=0.0,
        minimum_ats_improvement=0.005,
        minimum_roi_improvement=0.005,
        minimum_clv_improvement=0.05,
        maximum_drawdown_increase=0.0,
        minimum_confidence_monotonicity=1.0,
        confidence_probability_thresholds=(0.55, 0.60, 0.65, 0.70),
    )


@dataclass(frozen=True)
class ResearchMetadata:
    code_commit_sha: str
    data_snapshot_sha256: str
    feature_schema_version: str
    configuration_version: str
    generated_at: str

    def __post_init__(self) -> None:
        _sha(self.code_commit_sha, 40, "code_commit_sha")
        _sha(self.data_snapshot_sha256, 64, "data_snapshot_sha256")
        _required_text(self.feature_schema_version, "feature_schema_version")
        _required_text(self.configuration_version, "configuration_version")
        _utc_datetime(self.generated_at, "generated_at")


@dataclass(frozen=True)
class FoldAudit:
    model_key: str
    season: int
    week: int
    training_game_ids: tuple[int, ...]
    fit_game_ids: tuple[int, ...]
    calibration_game_ids: tuple[int, ...]
    test_game_ids: tuple[int, ...]
    uncertainty_points: float


@dataclass(frozen=True)
class SkippedFold:
    season: int
    week: int
    training_count: int
    reason: str


@dataclass(frozen=True)
class OutOfSamplePrediction:
    model_key: str
    model_version: str
    family: str
    game_id: int
    season: int
    week: int
    kickoff_at: str
    home_team: str
    away_team: str
    opening_spread: float
    opening_book: str
    closing_spread: float | None
    closing_book: str | None
    predicted_market_residual: float
    predicted_home_margin: float
    home_cover_probability: float
    uncertainty_points: float
    selected_side: str
    research_confidence: int
    actual_home_margin: float
    ats_result: str
    unit_profit_loss: float
    clv_points: float | None


@dataclass(frozen=True)
class ResearchMetrics:
    model_key: str
    prediction_count: int
    season_count: int
    margin_mae: float
    margin_rmse: float
    brier_score: float
    log_loss: float
    calibration_error: float
    ats_percentage: float
    roi_after_vig: float
    average_clv: float | None
    maximum_drawdown: float
    confidence_rank_monotonicity: float | None
    confidence_tier_rates: tuple[tuple[int, int, float | None], ...]
    average_uncertainty_points: float

    def __post_init__(self) -> None:
        _required_text(self.model_key, "model_key")
        _positive_integer(self.prediction_count, "prediction_count")
        _positive_integer(self.season_count, "season_count")
        for field in (
            "margin_mae",
            "margin_rmse",
            "brier_score",
            "log_loss",
            "calibration_error",
            "maximum_drawdown",
            "average_uncertainty_points",
        ):
            value = _finite(getattr(self, field), field)
            if value < 0:
                raise ResearchError(f"{field} cannot be negative")
        if self.average_uncertainty_points <= 0:
            raise ResearchError("average_uncertainty_points must be positive")
        for field in ("brier_score", "calibration_error", "ats_percentage"):
            value = _finite(getattr(self, field), field)
            if value < 0 or value > 1:
                raise ResearchError(f"{field} must be within [0, 1]")
        _finite(self.roi_after_vig, "roi_after_vig")
        if self.average_clv is not None:
            _finite(self.average_clv, "average_clv")
        if self.confidence_rank_monotonicity is not None:
            monotonicity = _finite(
                self.confidence_rank_monotonicity,
                "confidence_rank_monotonicity",
            )
            if monotonicity < 0 or monotonicity > 1:
                raise ResearchError(
                    "confidence_rank_monotonicity must be within [0, 1]"
                )
        if tuple(tier for tier, _, _ in self.confidence_tier_rates) != tuple(
            range(1, 6)
        ):
            raise ResearchError("confidence tier metrics must cover levels 1 through 5")
        for tier, count, rate in self.confidence_tier_rates:
            _positive_integer(count, f"confidence_tier[{tier}].count", 0)
            if (count == 0) != (rate is None):
                raise ResearchError(
                    "empty confidence tiers require a null rate and populated tiers a rate"
                )
            if rate is not None and not 0 <= _finite(
                rate,
                f"confidence_tier[{tier}].rate",
            ) <= 1:
                raise ResearchError("confidence tier rates must be within [0, 1]")


@dataclass(frozen=True)
class PromotionCriterion:
    criterion_code: str
    passed: bool
    baseline_value: float | int | None
    candidate_value: float | int | None
    required_value: float | int


@dataclass(frozen=True)
class PromotionDecision:
    model_key: str
    proposed_model_version: str
    status: str
    owner_approval_required: bool
    automatic_promotion: bool
    criteria: tuple[PromotionCriterion, ...]


@dataclass(frozen=True)
class ResearchResult:
    metadata: ResearchMetadata
    policy: ResearchPolicy
    dataset_sha256: str
    dataset_feature_names: tuple[str, ...]
    dataset_observation_count: int
    dataset_skips: tuple[ResearchBuildSkip, ...]
    model_specs: tuple[ModelSpec, ...]
    folds: tuple[FoldAudit, ...]
    skipped_folds: tuple[SkippedFold, ...]
    predictions: tuple[OutOfSamplePrediction, ...]
    metrics: tuple[ResearchMetrics, ...]
    promotion_decisions: tuple[PromotionDecision, ...]
    ledger_sha256: str


def _normal_cdf(value: float) -> float:
    return 0.5 * (1 + math.erf(value / math.sqrt(2)))


def _fit_calibration(
    model: ResearchModel,
    training: tuple[ResearchObservation, ...],
    policy: ResearchPolicy,
) -> tuple[IsotonicCalibrator, float, tuple[int, ...], tuple[int, ...]]:
    calibration_count = max(
        policy.minimum_calibration_observations,
        math.ceil(len(training) * policy.calibration_fraction),
    )
    fit_count = len(training) - calibration_count
    if fit_count < policy.minimum_fit_observations:
        raise ResearchError("fold leaves insufficient pre-calibration fit history")
    fit_observations = training[:fit_count]
    calibration_observations = training[fit_count:]
    fitted = model.fit(
        tuple(
            TrainingExample(item.model_input, item.market_residual)
            for item in fit_observations
        )
    )
    errors = [
        item.market_residual - fitted.predict_market_residual(item.model_input)
        for item in calibration_observations
    ]
    uncertainty = max(
        policy.minimum_uncertainty_points,
        math.sqrt(sum(error * error for error in errors) / len(errors)),
    )
    pairs = []
    for item in calibration_observations:
        if item.market_residual == 0:
            continue
        predicted = fitted.predict_market_residual(item.model_input)
        probability = _normal_cdf(predicted / uncertainty)
        pairs.append((probability, int(item.market_residual > 0)))
    calibrator = fit_isotonic_calibrator(tuple(pairs))
    return (
        calibrator,
        uncertainty,
        tuple(item.model_input.game_id for item in fit_observations),
        tuple(item.model_input.game_id for item in calibration_observations),
    )


def _confidence(probability: float, thresholds: tuple[float, ...]) -> int:
    reliability = max(probability, 1 - probability)
    return 1 + sum(reliability > threshold for threshold in thresholds)


def _prediction(
    *,
    model: ResearchModel,
    fitted: FittedResearchModel,
    calibrator: IsotonicCalibrator,
    uncertainty: float,
    observation: ResearchObservation,
    policy: ResearchPolicy,
) -> OutOfSamplePrediction:
    residual = fitted.predict_market_residual(observation.model_input)
    if not math.isfinite(residual):
        raise ResearchError("candidate emitted a non-finite prediction")
    raw_probability = _normal_cdf(residual / uncertainty)
    calibrated = calibrator.predict(raw_probability)
    probability = min(
        1 - policy.probability_clip,
        max(policy.probability_clip, calibrated),
    )
    selected_side = (
        "home"
        if probability > 0.5
        else "away"
        if probability < 0.5
        else policy.probability_tie_side
    )
    actual_residual = observation.market_residual
    if actual_residual == 0:
        result = "push"
    elif (actual_residual > 0) == (selected_side == "home"):
        result = "win"
    else:
        result = "loss"
    clv = None
    if observation.closing_spread is not None:
        selected_team = (
            observation.model_input.home_team
            if selected_side == "home"
            else observation.model_input.away_team
        )
        clv = bh.calculate_clv(
            selected_team,
            observation.model_input.home_team,
            observation.model_input.opening_spread,
            observation.closing_spread,
        )
    predicted_margin = -observation.model_input.opening_spread + residual
    return OutOfSamplePrediction(
        model.spec.model_key,
        model.spec.model_version,
        model.spec.family,
        observation.model_input.game_id,
        observation.model_input.season,
        observation.model_input.week,
        observation.model_input.kickoff_at,
        observation.model_input.home_team,
        observation.model_input.away_team,
        observation.model_input.opening_spread,
        observation.model_input.opening_book,
        observation.closing_spread,
        observation.closing_book,
        round(residual, 8),
        round(predicted_margin, 8),
        round(probability, 8),
        round(uncertainty, 8),
        selected_side,
        _confidence(probability, policy.confidence_probability_thresholds),
        observation.actual_home_margin,
        result,
        bh.unit_pl(result),
        clv,
    )


def calculate_research_metrics(
    model_key: str,
    predictions: tuple[OutOfSamplePrediction, ...],
    *,
    calibration_bin_count: int,
) -> ResearchMetrics:
    if not predictions:
        raise ResearchError("cannot calculate metrics without predictions")
    errors = [
        prediction.predicted_home_margin - prediction.actual_home_margin
        for prediction in predictions
    ]
    mae = sum(abs(error) for error in errors) / len(errors)
    rmse = math.sqrt(sum(error * error for error in errors) / len(errors))
    decisions = [
        prediction for prediction in predictions if prediction.ats_result != "push"
    ]
    if not decisions:
        raise ResearchError("probability metrics require at least one decided game")
    brier = sum(
        (
            prediction.home_cover_probability
            - int(
                (
                    prediction.actual_home_margin
                    + prediction.opening_spread
                )
                > 0
            )
        )
        ** 2
        for prediction in decisions
    ) / len(decisions)
    log_loss = -sum(
        (
            outcome * math.log(prediction.home_cover_probability)
            + (1 - outcome) * math.log(1 - prediction.home_cover_probability)
        )
        for prediction in decisions
        for outcome in (
            int(prediction.actual_home_margin + prediction.opening_spread > 0),
        )
    ) / len(decisions)
    calibration_total = 0.0
    for bin_index in range(calibration_bin_count):
        lower = bin_index / calibration_bin_count
        upper = (bin_index + 1) / calibration_bin_count
        bucket = [
            prediction
            for prediction in decisions
            if lower <= prediction.home_cover_probability
            and (
                prediction.home_cover_probability < upper
                or (bin_index == calibration_bin_count - 1)
            )
        ]
        if not bucket:
            continue
        mean_probability = sum(
            prediction.home_cover_probability for prediction in bucket
        ) / len(bucket)
        outcome_rate = sum(
            prediction.actual_home_margin + prediction.opening_spread > 0
            for prediction in bucket
        ) / len(bucket)
        calibration_total += len(bucket) / len(decisions) * abs(
            mean_probability - outcome_rate
        )
    wins = sum(prediction.ats_result == "win" for prediction in decisions)
    ats = wins / len(decisions)
    roi = sum(prediction.unit_profit_loss for prediction in predictions) / len(
        predictions
    )
    clv_values = [
        prediction.clv_points
        for prediction in predictions
        if prediction.clv_points is not None
    ]
    average_clv = (
        None if not clv_values else sum(clv_values) / len(clv_values)
    )
    cumulative = peak = max_drawdown = 0.0
    ordered = sorted(
        predictions,
        key=lambda item: (item.season, item.week, item.kickoff_at, item.game_id),
    )
    for prediction in ordered:
        cumulative += prediction.unit_profit_loss
        peak = max(peak, cumulative)
        max_drawdown = max(max_drawdown, peak - cumulative)
    tier_rates = []
    populated_rates = []
    for tier in range(1, 6):
        tier_decisions = [
            prediction
            for prediction in decisions
            if prediction.research_confidence == tier
        ]
        rate = (
            None
            if not tier_decisions
            else sum(item.ats_result == "win" for item in tier_decisions)
            / len(tier_decisions)
        )
        tier_rates.append((tier, len(tier_decisions), rate))
        if rate is not None:
            populated_rates.append(rate)
    monotonicity = None
    if len(populated_rates) >= 2:
        comparisons = len(populated_rates) - 1
        monotonicity = sum(
            right >= left
            for left, right in zip(populated_rates, populated_rates[1:])
        ) / comparisons
    return ResearchMetrics(
        model_key,
        len(predictions),
        len({prediction.season for prediction in predictions}),
        round(mae, 8),
        round(rmse, 8),
        round(brier, 8),
        round(log_loss, 8),
        round(calibration_total, 8),
        round(ats, 8),
        round(roi, 8),
        None if average_clv is None else round(average_clv, 8),
        round(max_drawdown, 8),
        None if monotonicity is None else round(monotonicity, 8),
        tuple(tier_rates),
        round(
            sum(item.uncertainty_points for item in predictions) / len(predictions),
            8,
        ),
    )


def evaluate_promotion(
    *,
    baseline: ResearchMetrics,
    candidate: ResearchMetrics,
    candidate_spec: ModelSpec,
    policy: ResearchPolicy,
) -> PromotionDecision:
    if baseline.model_key != "epa_only_baseline":
        raise ResearchError("promotion comparison requires the EPA-only baseline")
    if candidate.model_key != candidate_spec.model_key:
        raise ResearchError("candidate metrics and model spec must identify the same model")
    if candidate_spec.family == "epa_only_baseline":
        raise ResearchError("the baseline cannot be evaluated as its own candidate")

    def criterion(code, passed, baseline_value, candidate_value, required):
        return PromotionCriterion(
            code,
            bool(passed),
            baseline_value,
            candidate_value,
            required,
        )

    criteria = (
        criterion(
            "minimum_oos_predictions",
            candidate.prediction_count >= policy.minimum_oos_predictions,
            baseline.prediction_count,
            candidate.prediction_count,
            policy.minimum_oos_predictions,
        ),
        criterion(
            "minimum_oos_seasons",
            candidate.season_count >= policy.minimum_oos_seasons,
            baseline.season_count,
            candidate.season_count,
            policy.minimum_oos_seasons,
        ),
        criterion(
            "margin_mae_improvement",
            baseline.margin_mae - candidate.margin_mae
            >= policy.minimum_mae_improvement,
            baseline.margin_mae,
            candidate.margin_mae,
            policy.minimum_mae_improvement,
        ),
        criterion(
            "margin_rmse_improvement",
            baseline.margin_rmse - candidate.margin_rmse
            >= policy.minimum_rmse_improvement,
            baseline.margin_rmse,
            candidate.margin_rmse,
            policy.minimum_rmse_improvement,
        ),
        criterion(
            "brier_improvement",
            baseline.brier_score - candidate.brier_score
            >= policy.minimum_brier_improvement,
            baseline.brier_score,
            candidate.brier_score,
            policy.minimum_brier_improvement,
        ),
        criterion(
            "log_loss_improvement",
            baseline.log_loss - candidate.log_loss
            >= policy.minimum_log_loss_improvement,
            baseline.log_loss,
            candidate.log_loss,
            policy.minimum_log_loss_improvement,
        ),
        criterion(
            "calibration_error_limit",
            candidate.calibration_error - baseline.calibration_error
            <= policy.maximum_calibration_error_increase,
            baseline.calibration_error,
            candidate.calibration_error,
            policy.maximum_calibration_error_increase,
        ),
        criterion(
            "ats_improvement",
            candidate.ats_percentage - baseline.ats_percentage
            >= policy.minimum_ats_improvement,
            baseline.ats_percentage,
            candidate.ats_percentage,
            policy.minimum_ats_improvement,
        ),
        criterion(
            "roi_improvement",
            candidate.roi_after_vig - baseline.roi_after_vig
            >= policy.minimum_roi_improvement,
            baseline.roi_after_vig,
            candidate.roi_after_vig,
            policy.minimum_roi_improvement,
        ),
        criterion(
            "clv_improvement",
            baseline.average_clv is not None
            and candidate.average_clv is not None
            and candidate.average_clv - baseline.average_clv
            >= policy.minimum_clv_improvement,
            baseline.average_clv,
            candidate.average_clv,
            policy.minimum_clv_improvement,
        ),
        criterion(
            "drawdown_limit",
            candidate.maximum_drawdown - baseline.maximum_drawdown
            <= policy.maximum_drawdown_increase,
            baseline.maximum_drawdown,
            candidate.maximum_drawdown,
            policy.maximum_drawdown_increase,
        ),
        criterion(
            "confidence_rank_monotonicity",
            candidate.confidence_rank_monotonicity is not None
            and candidate.confidence_rank_monotonicity
            >= policy.minimum_confidence_monotonicity,
            baseline.confidence_rank_monotonicity,
            candidate.confidence_rank_monotonicity,
            policy.minimum_confidence_monotonicity,
        ),
    )
    passed = all(item.passed for item in criteria)
    return PromotionDecision(
        candidate.model_key,
        candidate_spec.model_version,
        "candidate_pending_owner_approval" if passed else "rejected",
        passed,
        False,
        criteria,
    )


def _ledger_hash(payload: dict[str, object]) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_weekly_rolling_origin(
    *,
    dataset: ResearchDataset,
    baseline: ResearchModel,
    candidates: tuple[ResearchModel, ...],
    policy: ResearchPolicy,
    metadata: ResearchMetadata,
) -> ResearchResult:
    """Evaluate baseline and candidates on identical strictly-later folds."""
    models = (baseline, *candidates)
    specs = tuple(model.spec for model in models)
    if baseline.spec.family != "epa_only_baseline" or baseline.spec.feature_names != (
        "epa_differential",
    ):
        raise ResearchError("the registered baseline must be EPA-only")
    keys = [spec.model_key for spec in specs]
    versions = [spec.model_version for spec in specs]
    if len(keys) != len(set(keys)) or len(versions) != len(set(versions)):
        raise ResearchError("model keys and model versions must be unique")
    if any(spec.family == "epa_only_baseline" for spec in specs[1:]):
        raise ResearchError("candidate models cannot masquerade as the baseline")
    available_features = set(dataset.feature_names)
    for spec in specs:
        if set(spec.feature_names) - available_features:
            raise ResearchError(
                f"dataset lacks features required by {spec.model_key}"
            )

    observations = dataset.observations
    fold_keys = sorted({observation.fold_key for observation in observations})
    predictions: list[OutOfSamplePrediction] = []
    fold_audits: list[FoldAudit] = []
    skipped_folds: list[SkippedFold] = []
    for fold_key in fold_keys:
        training = tuple(
            observation
            for observation in observations
            if observation.fold_key < fold_key
        )
        test = tuple(
            observation
            for observation in observations
            if observation.fold_key == fold_key
        )
        if len(training) < policy.minimum_training_observations:
            skipped_folds.append(
                SkippedFold(*fold_key, len(training), "insufficient_training_history")
            )
            continue
        prepared = []
        failure = None
        for model in models:
            try:
                calibrator, uncertainty, fit_ids, calibration_ids = _fit_calibration(
                    model,
                    training,
                    policy,
                )
                fitted = model.fit(
                    tuple(
                        TrainingExample(item.model_input, item.market_residual)
                        for item in training
                    )
                )
                prepared.append(
                    (model, fitted, calibrator, uncertainty, fit_ids, calibration_ids)
                )
            except ResearchError as exc:
                failure = f"model_fit_failed:{model.spec.model_key}:{exc}"
                break
        if failure is not None:
            skipped_folds.append(SkippedFold(*fold_key, len(training), failure))
            continue
        training_ids = tuple(item.model_input.game_id for item in training)
        test_ids = tuple(item.model_input.game_id for item in test)
        if set(training_ids) & set(test_ids):
            raise ResearchError("training and test folds overlap")
        for model, fitted, calibrator, uncertainty, fit_ids, calibration_ids in prepared:
            fold_audits.append(
                FoldAudit(
                    model.spec.model_key,
                    *fold_key,
                    training_ids,
                    fit_ids,
                    calibration_ids,
                    test_ids,
                    round(uncertainty, 8),
                )
            )
            predictions.extend(
                _prediction(
                    model=model,
                    fitted=fitted,
                    calibrator=calibrator,
                    uncertainty=uncertainty,
                    observation=observation,
                    policy=policy,
                )
                for observation in test
            )

    predictions_tuple = tuple(predictions)
    metrics = tuple(
        calculate_research_metrics(
            model.spec.model_key,
            tuple(
                prediction
                for prediction in predictions_tuple
                if prediction.model_key == model.spec.model_key
            ),
            calibration_bin_count=policy.calibration_bin_count,
        )
        for model in models
    )
    game_sets = {
        model.spec.model_key: {
            prediction.game_id
            for prediction in predictions_tuple
            if prediction.model_key == model.spec.model_key
        }
        for model in models
    }
    if len({frozenset(game_ids) for game_ids in game_sets.values()}) != 1:
        raise ResearchError("baseline and candidates were not evaluated on identical games")
    baseline_metrics = metrics[0]
    decisions = tuple(
        evaluate_promotion(
            baseline=baseline_metrics,
            candidate=candidate_metrics,
            candidate_spec=model.spec,
            policy=policy,
        )
        for model, candidate_metrics in zip(models[1:], metrics[1:])
    )
    payload = {
        "metadata": asdict(metadata),
        "policy": asdict(policy),
        "dataset_sha256": dataset.dataset_sha256,
        "dataset_feature_names": dataset.feature_names,
        "dataset_observation_count": len(dataset.observations),
        "dataset_skips": [asdict(skip) for skip in dataset.skips],
        "model_specs": [asdict(spec) for spec in specs],
        "folds": [asdict(fold) for fold in fold_audits],
        "skipped_folds": [asdict(fold) for fold in skipped_folds],
        "predictions": [asdict(prediction) for prediction in predictions_tuple],
        "metrics": [asdict(metric) for metric in metrics],
        "promotion_decisions": [asdict(decision) for decision in decisions],
    }
    return ResearchResult(
        metadata,
        policy,
        dataset.dataset_sha256,
        dataset.feature_names,
        len(dataset.observations),
        dataset.skips,
        specs,
        tuple(fold_audits),
        tuple(skipped_folds),
        predictions_tuple,
        metrics,
        decisions,
        _ledger_hash(payload),
    )
