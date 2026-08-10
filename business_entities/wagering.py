"""Typed append-only sportsbook recommendations, separate from contest picks."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from business_entities.cards import get_contest_pick
from business_entities.common import (
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    choice,
    integer,
    number,
    optional_integer,
    optional_number,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)
from business_entities.modeling import get_model_prediction


@dataclass(frozen=True)
class SportsbookRecommendation:
    id: int
    recommendation_key: str
    model_prediction_id: int
    contest_pick_id: int | None
    market_line_id: int | None
    decision: str
    recommended_side: str | None
    offered_price: int | None
    expected_value: float | None
    stake_units: float
    policy_version: str
    reason_code: str
    generated_at: str
    provenance: str


_COLUMNS = (
    "id, recommendation_key, model_prediction_id, contest_pick_id, market_line_id, "
    "decision, recommended_side, offered_price, expected_value, stake_units, "
    "policy_version, reason_code, generated_at, provenance"
)


def get_sportsbook_recommendation(
    conn: sqlite3.Connection, recommendation_id: int
) -> SportsbookRecommendation:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM sportsbook_recommendations WHERE id = ?",
        (recommendation_id,),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"sportsbook recommendation does not exist: {recommendation_id}"
        )
    return SportsbookRecommendation(*row)


def record_sportsbook_recommendation(
    conn: sqlite3.Connection,
    *,
    recommendation_key: str,
    model_prediction_id: int,
    decision: str,
    policy_version: str,
    reason_code: str,
    provenance: str,
    contest_pick_id: int | None = None,
    market_line_id: int | None = None,
    recommended_side: str | None = None,
    offered_price: int | None = None,
    expected_value: float | int | None = None,
    stake_units: float | int = 0,
    generated_at: datetime | None = None,
) -> SportsbookRecommendation:
    """Record wagering advice without changing a forecast or contest selection."""
    recommendation_key = required_text(recommendation_key, "recommendation_key")
    model_prediction_id = integer(model_prediction_id, "model_prediction_id", 1)
    contest_pick_id = optional_integer(contest_pick_id, "contest_pick_id", 1)
    market_line_id = optional_integer(market_line_id, "market_line_id", 1)
    decision = choice(decision, "decision", ("bet", "no_bet"))
    if recommended_side is not None:
        recommended_side = choice(
            recommended_side, "recommended_side", ("home", "away")
        )
    offered_price = optional_integer(offered_price, "offered_price")
    expected_value = optional_number(expected_value, "expected_value")
    stake_units = number(stake_units, "stake_units")
    if stake_units < 0:
        raise BusinessEntityError("stake_units cannot be negative")
    policy_version = required_text(policy_version, "policy_version")
    reason_code = required_text(reason_code, "reason_code")
    provenance = required_text(provenance, "provenance")
    bet_fields = (market_line_id, recommended_side, offered_price, expected_value)
    if decision == "bet" and (any(value is None for value in bet_fields) or stake_units <= 0):
        raise BusinessEntityError(
            "bet recommendations require a line, side, price, value, and positive stake"
        )
    if decision == "no_bet" and (
        any(value is not None for value in bet_fields) or stake_units != 0
    ):
        raise BusinessEntityError(
            "no_bet recommendations cannot carry line, side, price, value, or stake"
        )
    generated_at_value = utc_timestamp(generated_at, "generated_at")

    try:
        with atomic(conn):
            prediction = get_model_prediction(conn, model_prediction_id)
            if contest_pick_id is not None:
                pick = get_contest_pick(conn, contest_pick_id)
                if pick.model_prediction_id != model_prediction_id:
                    raise BusinessEntityError(
                        "contest pick and recommendation must share one prediction"
                    )
            if market_line_id is not None:
                row = conn.execute(
                    "SELECT game_id, line_type, fetched_at FROM betting_lines WHERE id = ?",
                    (market_line_id,),
                ).fetchone()
                if row is None or row[0] != prediction.game_id:
                    raise BusinessEntityError(
                        "market line and recommendation must refer to one game"
                    )
                if row[1] not in ("opening", "current"):
                    raise BusinessEntityError(
                        "sportsbook advice requires an opening or current offered line"
                    )
                if not timestamp_on_or_before(conn, row[2], generated_at_value):
                    raise BusinessEntityError(
                        "offered market line must be captured before recommendation generation"
                    )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM sportsbook_recommendations "
                "WHERE recommendation_key = ?",
                (recommendation_key,),
            ).fetchone()
            requested = (
                recommendation_key,
                model_prediction_id,
                contest_pick_id,
                market_line_id,
                decision,
                recommended_side,
                offered_price,
                expected_value,
                stake_units,
                policy_version,
                reason_code,
                provenance,
            )
            if row is not None:
                existing = SportsbookRecommendation(*row)
                recorded = (
                    existing.recommendation_key,
                    existing.model_prediction_id,
                    existing.contest_pick_id,
                    existing.market_line_id,
                    existing.decision,
                    existing.recommended_side,
                    existing.offered_price,
                    existing.expected_value,
                    existing.stake_units,
                    existing.policy_version,
                    existing.reason_code,
                    existing.provenance,
                )
                if recorded != requested:
                    raise BusinessEntityConflictError(
                        "recommendation key already has different immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO sportsbook_recommendations "
                "(recommendation_key, model_prediction_id, contest_pick_id, "
                "market_line_id, decision, recommended_side, offered_price, "
                "expected_value, stake_units, policy_version, reason_code, "
                "generated_at, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*requested[:-1], generated_at_value, provenance),
            )
            return get_sportsbook_recommendation(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("sportsbook recommendation", exc) from exc
