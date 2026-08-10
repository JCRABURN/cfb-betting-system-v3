"""Append-only manual context layered over immutable raw model predictions."""

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
    required_text,
    translate_integrity,
    utc_timestamp,
)
from business_entities.modeling import get_model_prediction


@dataclass(frozen=True)
class ManualAdjustment:
    id: int
    adjustment_key: str
    model_prediction_id: int
    contest_pick_id: int | None
    sequence: int
    supersedes_adjustment_id: int | None
    category: str
    affected_side: str
    margin_adjustment: float
    confidence_adjustment: int
    reason: str
    evidence: str
    source: str
    author: str
    recorded_at: str
    provenance: str


_COLUMNS = (
    "id, adjustment_key, model_prediction_id, contest_pick_id, sequence, "
    "supersedes_adjustment_id, category, affected_side, margin_adjustment, "
    "confidence_adjustment, reason, evidence, source, author, recorded_at, provenance"
)


def get_manual_adjustment(
    conn: sqlite3.Connection, adjustment_id: int
) -> ManualAdjustment:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM manual_adjustments WHERE id = ?", (adjustment_id,)
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"manual adjustment does not exist: {adjustment_id}")
    return ManualAdjustment(*row)


def list_manual_adjustments(
    conn: sqlite3.Connection, model_prediction_id: int
) -> tuple[ManualAdjustment, ...]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM manual_adjustments "
        "WHERE model_prediction_id = ? ORDER BY sequence",
        (model_prediction_id,),
    ).fetchall()
    return tuple(ManualAdjustment(*row) for row in rows)


def record_manual_adjustment(
    conn: sqlite3.Connection,
    *,
    adjustment_key: str,
    model_prediction_id: int,
    category: str,
    margin_adjustment: float | int,
    confidence_adjustment: int,
    reason: str,
    affected_side: str,
    evidence: str,
    source: str,
    author: str,
    provenance: str,
    contest_pick_id: int | None = None,
    recorded_at: datetime | None = None,
) -> ManualAdjustment:
    """Append the next contextual adjustment; the raw forecast is never edited."""
    adjustment_key = required_text(adjustment_key, "adjustment_key")
    model_prediction_id = integer(model_prediction_id, "model_prediction_id", 1)
    contest_pick_id = optional_integer(contest_pick_id, "contest_pick_id", 1)
    category = choice(
        category,
        "category",
        (
            "injury",
            "quarterback",
            "coaching",
            "travel",
            "weather",
            "motivation",
            "matchup",
            "other",
        ),
    )
    affected_side = choice(affected_side, "affected_side", ("home", "away", "both"))
    margin_adjustment = number(margin_adjustment, "margin_adjustment")
    confidence_adjustment = integer(confidence_adjustment, "confidence_adjustment")
    if margin_adjustment == 0 and confidence_adjustment == 0:
        raise BusinessEntityError("an adjustment must change margin or confidence")
    reason = required_text(reason, "reason")
    evidence = required_text(evidence, "evidence")
    source = required_text(source, "source")
    author = required_text(author, "author")
    provenance = required_text(provenance, "provenance")
    recorded_at_value = utc_timestamp(recorded_at, "recorded_at")

    try:
        with atomic(conn):
            get_model_prediction(conn, model_prediction_id)
            if contest_pick_id is not None:
                pick = get_contest_pick(conn, contest_pick_id)
                if pick.model_prediction_id != model_prediction_id:
                    raise BusinessEntityError(
                        "contest pick and manual adjustment must share one prediction"
                    )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM manual_adjustments WHERE adjustment_key = ?",
                (adjustment_key,),
            ).fetchone()
            if row is not None:
                existing = ManualAdjustment(*row)
                requested_existing = (
                    adjustment_key,
                    model_prediction_id,
                    contest_pick_id,
                    existing.sequence,
                    existing.supersedes_adjustment_id,
                    category,
                    affected_side,
                    margin_adjustment,
                    confidence_adjustment,
                    reason,
                    evidence,
                    source,
                    author,
                    provenance,
                )
                recorded = (
                    existing.adjustment_key,
                    existing.model_prediction_id,
                    existing.contest_pick_id,
                    existing.sequence,
                    existing.supersedes_adjustment_id,
                    existing.category,
                    existing.affected_side,
                    existing.margin_adjustment,
                    existing.confidence_adjustment,
                    existing.reason,
                    existing.evidence,
                    existing.source,
                    existing.author,
                    existing.provenance,
                )
                if recorded != requested_existing:
                    raise BusinessEntityConflictError(
                        "adjustment key already has different immutable values"
                    )
                return existing
            latest = conn.execute(
                "SELECT id, sequence FROM manual_adjustments "
                "WHERE model_prediction_id = ? ORDER BY sequence DESC LIMIT 1",
                (model_prediction_id,),
            ).fetchone()
            supersedes_id = latest[0] if latest is not None else None
            sequence = latest[1] + 1 if latest is not None else 1
            cursor = conn.execute(
                "INSERT INTO manual_adjustments "
                "(adjustment_key, model_prediction_id, contest_pick_id, sequence, "
                "supersedes_adjustment_id, category, affected_side, margin_adjustment, "
                "confidence_adjustment, reason, evidence, source, author, recorded_at, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    adjustment_key,
                    model_prediction_id,
                    contest_pick_id,
                    sequence,
                    supersedes_id,
                    category,
                    affected_side,
                    margin_adjustment,
                    confidence_adjustment,
                    reason,
                    evidence,
                    source,
                    author,
                    recorded_at_value,
                    provenance,
                ),
            )
            return get_manual_adjustment(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("manual adjustment", exc) from exc
