"""Versioned reliability-based Confidence and Top 5 policy storage."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from business_entities.cards import get_contest_card
from business_entities.common import (
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    integer,
    number,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)


RELIABILITY_METRIC = "model_uncertainty_points"
RANKING_METHOD = "confidence_desc_uncertainty_asc"
TIE_BREAKER = "locked_line_id_asc"
UNSCORED_CONFIDENCE = 1
TOP_FIVE_COUNT = 5


@dataclass(frozen=True)
class ConfidenceRankingPolicy:
    """Approved thresholds for relative reliability, never raw model edge."""

    policy_key: str
    confidence_policy_version: str
    ranking_policy_version: str
    confidence_5_max_uncertainty: float
    confidence_4_max_uncertainty: float
    confidence_3_max_uncertainty: float
    confidence_2_max_uncertainty: float
    effective_at: datetime
    created_by: str
    provenance: str


@dataclass(frozen=True)
class ContestRankingPolicy:
    id: int
    policy_key: str
    confidence_policy_version: str
    ranking_policy_version: str
    confidence_5_max_uncertainty: float
    confidence_4_max_uncertainty: float
    confidence_3_max_uncertainty: float
    confidence_2_max_uncertainty: float
    unscored_confidence: int
    top_five_count: int
    reliability_metric: str
    ranking_method: str
    tie_breaker: str
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class CardPolicyAssignment:
    card_id: int
    ranking_policy_id: int
    assigned_at: str
    provenance: str


_POLICY_COLUMNS = (
    "id, policy_key, confidence_policy_version, ranking_policy_version, "
    "confidence_5_max_uncertainty, confidence_4_max_uncertainty, "
    "confidence_3_max_uncertainty, confidence_2_max_uncertainty, "
    "unscored_confidence, top_five_count, reliability_metric, ranking_method, "
    "tie_breaker, effective_at, created_by, provenance"
)
_ASSIGNMENT_COLUMNS = "card_id, ranking_policy_id, assigned_at, provenance"


def validate_confidence_ranking_policy(
    policy: ConfidenceRankingPolicy,
) -> ConfidenceRankingPolicy:
    if not isinstance(policy, ConfidenceRankingPolicy):
        raise BusinessEntityError("confidence_policy must be a ConfidenceRankingPolicy")
    thresholds = (
        number(
            policy.confidence_5_max_uncertainty,
            "confidence_5_max_uncertainty",
        ),
        number(
            policy.confidence_4_max_uncertainty,
            "confidence_4_max_uncertainty",
        ),
        number(
            policy.confidence_3_max_uncertainty,
            "confidence_3_max_uncertainty",
        ),
        number(
            policy.confidence_2_max_uncertainty,
            "confidence_2_max_uncertainty",
        ),
    )
    if thresholds[0] < 0 or not all(
        lower < upper for lower, upper in zip(thresholds, thresholds[1:])
    ):
        raise BusinessEntityError(
            "uncertainty thresholds must be nonnegative and strictly increasing"
        )
    effective_at = datetime.fromisoformat(
        utc_timestamp(policy.effective_at, "policy.effective_at")
    )
    return ConfidenceRankingPolicy(
        policy_key=required_text(policy.policy_key, "policy.policy_key"),
        confidence_policy_version=required_text(
            policy.confidence_policy_version,
            "policy.confidence_policy_version",
        ),
        ranking_policy_version=required_text(
            policy.ranking_policy_version,
            "policy.ranking_policy_version",
        ),
        confidence_5_max_uncertainty=thresholds[0],
        confidence_4_max_uncertainty=thresholds[1],
        confidence_3_max_uncertainty=thresholds[2],
        confidence_2_max_uncertainty=thresholds[3],
        effective_at=effective_at,
        created_by=required_text(policy.created_by, "policy.created_by"),
        provenance=required_text(policy.provenance, "policy.provenance"),
    )


def get_contest_ranking_policy(
    conn: sqlite3.Connection, ranking_policy_id: int
) -> ContestRankingPolicy:
    row = conn.execute(
        f"SELECT {_POLICY_COLUMNS} FROM contest_ranking_policies WHERE id = ?",
        (integer(ranking_policy_id, "ranking_policy_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"contest ranking policy does not exist: {ranking_policy_id}"
        )
    return ContestRankingPolicy(*row)


def register_confidence_ranking_policy(
    conn: sqlite3.Connection,
    policy: ConfidenceRankingPolicy,
) -> ContestRankingPolicy:
    """Register one immutable policy; a version pair can never change meaning."""
    policy = validate_confidence_ranking_policy(policy)
    effective_at = policy.effective_at.isoformat()
    requested = (
        policy.policy_key,
        policy.confidence_policy_version,
        policy.ranking_policy_version,
        policy.confidence_5_max_uncertainty,
        policy.confidence_4_max_uncertainty,
        policy.confidence_3_max_uncertainty,
        policy.confidence_2_max_uncertainty,
        UNSCORED_CONFIDENCE,
        TOP_FIVE_COUNT,
        RELIABILITY_METRIC,
        RANKING_METHOD,
        TIE_BREAKER,
        effective_at,
        policy.created_by,
        policy.provenance,
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM contest_ranking_policies "
                "WHERE policy_key = ? OR (confidence_policy_version = ? "
                "AND ranking_policy_version = ?) "
                "ORDER BY policy_key = ? DESC LIMIT 1",
                (
                    policy.policy_key,
                    policy.confidence_policy_version,
                    policy.ranking_policy_version,
                    policy.policy_key,
                ),
            ).fetchone()
            if row is not None:
                existing = ContestRankingPolicy(*row)
                if tuple(row[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "policy key or version pair has different immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO contest_ranking_policies "
                "(policy_key, confidence_policy_version, ranking_policy_version, "
                "confidence_5_max_uncertainty, confidence_4_max_uncertainty, "
                "confidence_3_max_uncertainty, confidence_2_max_uncertainty, "
                "unscored_confidence, top_five_count, reliability_metric, "
                "ranking_method, tie_breaker, effective_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            return get_contest_ranking_policy(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("contest ranking policy", exc) from exc


def get_card_policy_assignment(
    conn: sqlite3.Connection, card_id: int
) -> CardPolicyAssignment:
    row = conn.execute(
        f"SELECT {_ASSIGNMENT_COLUMNS} FROM contest_card_policy_assignments "
        "WHERE card_id = ?",
        (integer(card_id, "card_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"contest card has no ranking policy: {card_id}")
    return CardPolicyAssignment(*row)


def get_card_ranking_policy(
    conn: sqlite3.Connection, card_id: int
) -> ContestRankingPolicy:
    assignment = get_card_policy_assignment(conn, card_id)
    return get_contest_ranking_policy(conn, assignment.ranking_policy_id)


def assign_card_ranking_policy(
    conn: sqlite3.Connection,
    *,
    card_id: int,
    ranking_policy_id: int,
    provenance: str,
    assigned_at: datetime,
) -> CardPolicyAssignment:
    """Bind one immutable policy to the card at the card generation instant."""
    card_id = integer(card_id, "card_id", 1)
    ranking_policy_id = integer(ranking_policy_id, "ranking_policy_id", 1)
    provenance = required_text(provenance, "provenance")
    assigned_at_value = utc_timestamp(assigned_at, "assigned_at")
    try:
        with atomic(conn):
            card = get_contest_card(conn, card_id)
            policy = get_contest_ranking_policy(conn, ranking_policy_id)
            if assigned_at_value != card.generated_at or not timestamp_on_or_before(
                conn, policy.effective_at, card.generated_at
            ):
                raise BusinessEntityError(
                    "card ranking policy must be effective at generation"
                )
            row = conn.execute(
                f"SELECT {_ASSIGNMENT_COLUMNS} "
                "FROM contest_card_policy_assignments WHERE card_id = ?",
                (card_id,),
            ).fetchone()
            requested = (
                card_id,
                ranking_policy_id,
                assigned_at_value,
                provenance,
            )
            if row is not None:
                existing = CardPolicyAssignment(*row)
                if tuple(row) != requested:
                    raise BusinessEntityConflictError(
                        "card already has a different immutable ranking policy"
                    )
                return existing
            conn.execute(
                "INSERT INTO contest_card_policy_assignments "
                "(card_id, ranking_policy_id, assigned_at, provenance) "
                "VALUES (?, ?, ?, ?)",
                requested,
            )
            return get_card_policy_assignment(conn, card_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("contest card policy assignment", exc) from exc


def recorded_policy_matches(
    recorded: ContestRankingPolicy,
    requested: ConfidenceRankingPolicy,
) -> bool:
    requested = validate_confidence_ranking_policy(requested)
    return (
        recorded.policy_key,
        recorded.confidence_policy_version,
        recorded.ranking_policy_version,
        recorded.confidence_5_max_uncertainty,
        recorded.confidence_4_max_uncertainty,
        recorded.confidence_3_max_uncertainty,
        recorded.confidence_2_max_uncertainty,
        recorded.unscored_confidence,
        recorded.top_five_count,
        recorded.reliability_metric,
        recorded.ranking_method,
        recorded.tie_breaker,
        recorded.effective_at,
        recorded.created_by,
        recorded.provenance,
    ) == (
        requested.policy_key,
        requested.confidence_policy_version,
        requested.ranking_policy_version,
        requested.confidence_5_max_uncertainty,
        requested.confidence_4_max_uncertainty,
        requested.confidence_3_max_uncertainty,
        requested.confidence_2_max_uncertainty,
        UNSCORED_CONFIDENCE,
        TOP_FIVE_COUNT,
        RELIABILITY_METRIC,
        RANKING_METHOD,
        TIE_BREAKER,
        requested.effective_at.isoformat(),
        requested.created_by,
        requested.provenance,
    )


def confidence_for_uncertainty(
    policy: ConfidenceRankingPolicy,
    uncertainty_points: float | None,
) -> int:
    """Map explicit model uncertainty to Confidence; missing input gets 1."""
    policy = validate_confidence_ranking_policy(policy)
    if uncertainty_points is None:
        return UNSCORED_CONFIDENCE
    uncertainty = number(uncertainty_points, "uncertainty_points")
    if uncertainty < 0:
        raise BusinessEntityError("uncertainty_points cannot be negative")
    if uncertainty <= policy.confidence_5_max_uncertainty:
        return 5
    if uncertainty <= policy.confidence_4_max_uncertainty:
        return 4
    if uncertainty <= policy.confidence_3_max_uncertainty:
        return 3
    if uncertainty <= policy.confidence_2_max_uncertainty:
        return 2
    return 1
