"""Comparative diagnostics for the governed totals rolling-origin ledger."""

from __future__ import annotations

import math
from dataclasses import dataclass

from models.totals_research import TotalsResearchDataset, TotalsResearchResult


@dataclass(frozen=True)
class ForecastBaselineMetrics:
    name: str
    sample_n: int
    mae: float
    rmse: float


@dataclass(frozen=True)
class TotalsSeasonMetrics:
    season: int
    forecast_n: int
    decision_n: int
    wins: int
    losses: int
    pushes: int
    win_rate_excluding_pushes: float | None
    roi_at_minus_110: float | None
    mae: float
    rmse: float


@dataclass(frozen=True)
class TotalsEdgeBucketMetrics:
    bucket: str
    sample_n: int
    wins: int
    losses: int
    pushes: int
    average_predicted_probability: float | None
    win_rate_excluding_pushes: float | None
    roi_at_minus_110: float | None


@dataclass(frozen=True)
class TotalsComparativeEvaluation:
    model_same_market_sample: ForecastBaselineMetrics
    market_total_baseline: ForecastBaselineMetrics
    rolling_historical_mean_baseline: ForecastBaselineMetrics
    seasons: tuple[TotalsSeasonMetrics, ...]
    edge_buckets: tuple[TotalsEdgeBucketMetrics, ...]
    minus_110_break_even_probability: float
    proposed_minimum_oos_decisions: int
    proposed_threshold_basis: str
    totals_production_eligible: bool


def _forecast_metrics(name: str, errors: list[float]) -> ForecastBaselineMetrics:
    return ForecastBaselineMetrics(
        name,
        len(errors),
        sum(abs(error) for error in errors) / len(errors),
        math.sqrt(sum(error * error for error in errors) / len(errors)),
    )


def _edge_bucket(edge: float) -> str:
    for upper, label in (
        (1.5, "under_1_5"),
        (3, "1_5_to_under_3"),
        (5, "3_to_under_5"),
        (8, "5_to_under_8"),
        (12, "8_to_under_12"),
        (20, "12_to_under_20"),
    ):
        if edge < upper:
            return label
    return "20_plus"


def evaluate_totals_research(
    dataset: TotalsResearchDataset, result: TotalsResearchResult
) -> TotalsComparativeEvaluation:
    """Compare only observations forecast in the governed OOS result."""
    by_game = {item.game_id: item for item in dataset.observations}
    lined = tuple(item for item in result.predictions if item.opening_total is not None)
    if not lined:
        raise ValueError("comparative totals evaluation requires lined OOS predictions")
    model_errors = [item.error for item in lined]
    market_errors = [
        float(item.opening_total) - item.actual_total for item in lined
    ]

    rolling_mean_errors: list[float] = []
    for prediction in result.predictions:
        observation = by_game[prediction.game_id]
        training = tuple(
            item for item in dataset.observations if item.fold_key < observation.fold_key
        )
        if len(training) < result.policy.minimum_training_examples:
            continue
        rolling_mean = sum(item.actual_total for item in training) / len(training)
        rolling_mean_errors.append(rolling_mean - observation.actual_total)

    seasons: list[TotalsSeasonMetrics] = []
    for season in sorted({item.season for item in result.predictions}):
        forecasts = tuple(item for item in result.predictions if item.season == season)
        graded = tuple(item for item in forecasts if item.result is not None)
        wins = sum(item.result == "win" for item in graded)
        losses = sum(item.result == "loss" for item in graded)
        pushes = sum(item.result == "push" for item in graded)
        decisions = wins + losses
        seasons.append(
            TotalsSeasonMetrics(
                season,
                len(forecasts),
                len(graded),
                wins,
                losses,
                pushes,
                wins / decisions if decisions else None,
                (
                    sum(item.unit_profit or 0 for item in graded) / len(graded)
                    if graded
                    else None
                ),
                sum(abs(item.error) for item in forecasts) / len(forecasts),
                math.sqrt(
                    sum(item.error**2 for item in forecasts) / len(forecasts)
                ),
            )
        )

    groups: dict[str, list] = {}
    for item in lined:
        edge = abs(item.projected_total - float(item.opening_total))
        groups.setdefault(_edge_bucket(edge), []).append(item)
    edge_buckets: list[TotalsEdgeBucketMetrics] = []
    for bucket, rows in sorted(groups.items()):
        wins = sum(item.result == "win" for item in rows)
        losses = sum(item.result == "loss" for item in rows)
        pushes = sum(item.result == "push" for item in rows)
        decisions = wins + losses
        probabilities = [
            item.selected_probability
            for item in rows
            if item.result != "push" and item.selected_probability is not None
        ]
        edge_buckets.append(
            TotalsEdgeBucketMetrics(
                bucket,
                len(rows),
                wins,
                losses,
                pushes,
                sum(probabilities) / len(probabilities) if probabilities else None,
                wins / decisions if decisions else None,
                sum(item.unit_profit or 0 for item in rows) / len(rows),
            )
        )

    # One-sided 5% / 80% normal-approximation power for detecting 55% against
    # the -110 break-even null. This is a proposed future gate, not a claim that
    # the current model has reached it.
    break_even = 110 / 210
    target = 0.55
    minimum = math.ceil(
        (
            1.6448536269514722 * math.sqrt(break_even * (1 - break_even))
            + 0.8416212335729143 * math.sqrt(target * (1 - target))
        )
        ** 2
        / (target - break_even) ** 2
    )
    return TotalsComparativeEvaluation(
        _forecast_metrics("pit_epa_total_linear", model_errors),
        _forecast_metrics("market_total", market_errors),
        _forecast_metrics("rolling_prior_historical_mean", rolling_mean_errors),
        tuple(seasons),
        tuple(edge_buckets),
        break_even,
        minimum,
        (
            "one-sided alpha=0.05, power=0.80 normal approximation for a "
            "predeclared 55% alternative versus the -110 break-even null; promotion "
            "would also require baseline improvement, stable season results, and "
            "acceptable calibration"
        ),
        False,
    )
