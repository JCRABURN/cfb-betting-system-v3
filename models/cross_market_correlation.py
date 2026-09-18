"""Historical OOS evidence for ATS/total same-game dependence."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from collections.abc import Iterable


RELATION_CODES = (
    "favorite_over",
    "favorite_under",
    "underdog_over",
    "underdog_under",
    "pickem_over",
    "pickem_under",
)
EVIDENCE_METHOD = "phi_fisher_95_lower_bound_v1"
PENALTY_METHOD = "positive_covariance_probability_penalty_v1"


class CrossMarketCorrelationError(ValueError):
    pass


@dataclass(frozen=True)
class CrossMarketOutOfSampleOutcome:
    game_id: int
    season: int
    week: int
    ats_selected_market_status: str
    ats_result: str
    total_selected_direction: str
    total_result: str

    def __post_init__(self) -> None:
        if self.game_id < 1 or self.season < 1869 or self.week < 0:
            raise CrossMarketCorrelationError("invalid game/fold identity")
        if self.ats_selected_market_status not in ("favorite", "underdog", "pickem"):
            raise CrossMarketCorrelationError("invalid ATS market status")
        if self.ats_result not in ("win", "loss", "push"):
            raise CrossMarketCorrelationError("invalid ATS result")
        if self.total_selected_direction not in ("over", "under"):
            raise CrossMarketCorrelationError("invalid totals direction")
        if self.total_result not in ("win", "loss", "push"):
            raise CrossMarketCorrelationError("invalid total result")

    @property
    def relation_code(self) -> str:
        return f"{self.ats_selected_market_status}_{self.total_selected_direction}"


@dataclass(frozen=True)
class CrossMarketCorrelationEstimate:
    relation_code: str
    sample_n: int
    phi_correlation: float | None
    fisher_lower_95: float | None
    fisher_upper_95: float | None
    positive_penalty_weight: float
    evidence_status: str


@dataclass(frozen=True)
class CrossMarketCorrelationResult:
    evidence_method: str
    penalty_method: str
    dataset_sha256: str
    estimates: tuple[CrossMarketCorrelationEstimate, ...]
    ledger_sha256: str


def outcomes_from_prediction_ledgers(
    ats_predictions: Iterable[object], total_predictions: Iterable[object]
) -> tuple[CrossMarketOutOfSampleOutcome, ...]:
    """Join independently produced genuine OOS ledgers by immutable game ID."""
    totals = {
        int(item.game_id): item
        for item in total_predictions
        if getattr(item, "result", None) in ("win", "loss", "push")
    }
    outcomes = []
    for ats in ats_predictions:
        if getattr(ats, "skipped_reason", None) is not None or getattr(
            ats, "result", None
        ) not in ("win", "loss", "push"):
            continue
        total = totals.get(int(ats.game_id))
        if total is None:
            continue
        spread = float(ats.opening_spread)
        if spread == 0:
            market_status = "pickem"
        else:
            favorite = ats.home_team if spread < 0 else ats.away_team
            market_status = "favorite" if ats.side == favorite else "underdog"
        outcomes.append(
            CrossMarketOutOfSampleOutcome(
                game_id=int(ats.game_id),
                season=int(ats.season),
                week=int(ats.week),
                ats_selected_market_status=market_status,
                ats_result=str(ats.result),
                total_selected_direction=str(total.selected_direction),
                total_result=str(total.result),
            )
        )
    return tuple(
        sorted(outcomes, key=lambda item: (item.season, item.week, item.game_id))
    )


def _sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def estimate_cross_market_correlations(
    outcomes: tuple[CrossMarketOutOfSampleOutcome, ...],
) -> CrossMarketCorrelationResult:
    """Estimate phi and use only a positive 95% lower bound as a penalty.

    Pushes are excluded because they are neither wins nor losses.  No minimum-N
    tuning threshold is invented: a cell is penalized only when its Fisher 95%
    interval supports positive dependence.
    """
    ordered = tuple(sorted(outcomes, key=lambda item: (item.season, item.week, item.game_id)))
    ids = [item.game_id for item in ordered]
    if len(ids) != len(set(ids)):
        raise CrossMarketCorrelationError("OOS correlation outcomes require unique games")
    dataset_sha = _sha256([asdict(item) for item in ordered])
    estimates: list[CrossMarketCorrelationEstimate] = []
    for relation in RELATION_CODES:
        rows = tuple(
            item
            for item in ordered
            if item.relation_code == relation
            and item.ats_result != "push"
            and item.total_result != "push"
        )
        if not rows:
            estimates.append(
                CrossMarketCorrelationEstimate(
                    relation, 0, None, None, None, 0.0, "no_data"
                )
            )
            continue
        x = [1.0 if item.ats_result == "win" else 0.0 for item in rows]
        y = [1.0 if item.total_result == "win" else 0.0 for item in rows]
        mean_x = sum(x) / len(x)
        mean_y = sum(y) / len(y)
        variance_x = sum((item - mean_x) ** 2 for item in x)
        variance_y = sum((item - mean_y) ** 2 for item in y)
        if len(rows) <= 3 or variance_x == 0 or variance_y == 0:
            estimates.append(
                CrossMarketCorrelationEstimate(
                    relation,
                    len(rows),
                    None,
                    None,
                    None,
                    0.0,
                    "insufficient_variation",
                )
            )
            continue
        phi = sum(
            (left - mean_x) * (right - mean_y)
            for left, right in zip(x, y)
        ) / math.sqrt(variance_x * variance_y)
        bounded = min(max(phi, -0.999999999), 0.999999999)
        fisher = math.atanh(bounded)
        standard_error = 1 / math.sqrt(len(rows) - 3)
        lower = math.tanh(fisher - 1.96 * standard_error)
        upper = math.tanh(fisher + 1.96 * standard_error)
        estimates.append(
            CrossMarketCorrelationEstimate(
                relation,
                len(rows),
                bounded,
                lower,
                upper,
                max(lower, 0.0),
                "estimated",
            )
        )
    estimate_tuple = tuple(estimates)
    ledger = {
        "evidence_method": EVIDENCE_METHOD,
        "penalty_method": PENALTY_METHOD,
        "dataset_sha256": dataset_sha,
        "estimates": [asdict(item) for item in estimate_tuple],
    }
    return CrossMarketCorrelationResult(
        EVIDENCE_METHOD,
        PENALTY_METHOD,
        dataset_sha,
        estimate_tuple,
        _sha256(ledger),
    )
