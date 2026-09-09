"""Immutable component-score custody for shadow totals predictions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from business_entities.common import (
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    integer,
    number,
    required_text,
    translate_integrity,
    utc_timestamp,
)


@dataclass(frozen=True)
class TotalScoreComponentPrediction:
    total_model_prediction_id: int
    component_model_version: str
    projected_home_points: float
    projected_away_points: float
    projected_total: float
    generated_at: str
    provenance: str


_COLUMNS = (
    "total_model_prediction_id, component_model_version, projected_home_points, "
    "projected_away_points, projected_total, generated_at, provenance"
)


def get_total_score_component_prediction(
    conn: sqlite3.Connection, total_model_prediction_id: int
) -> TotalScoreComponentPrediction:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM total_score_component_predictions "
        "WHERE total_model_prediction_id = ?",
        (integer(total_model_prediction_id, "total_model_prediction_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            "total score component prediction does not exist: "
            f"{total_model_prediction_id}"
        )
    return TotalScoreComponentPrediction(*row)


def record_total_score_component_prediction(
    conn: sqlite3.Connection,
    *,
    total_model_prediction_id: int,
    component_model_version: str,
    projected_home_points: float | int,
    projected_away_points: float | int,
    generated_at: datetime,
    provenance: str,
) -> TotalScoreComponentPrediction:
    """Bind separately fitted team score expectations to one total prediction."""
    prediction_id = integer(
        total_model_prediction_id, "total_model_prediction_id", 1
    )
    component_version = required_text(
        component_model_version, "component_model_version"
    )
    home = number(projected_home_points, "projected_home_points")
    away = number(projected_away_points, "projected_away_points")
    if home < 0 or away < 0:
        raise BusinessEntityError("projected component points cannot be negative")
    generated = utc_timestamp(generated_at, "generated_at")
    provenance = required_text(provenance, "provenance")
    parent = conn.execute(
        "SELECT projected_total, generated_at FROM total_model_predictions WHERE id = ?",
        (prediction_id,),
    ).fetchone()
    if parent is None:
        raise BusinessEntityError(f"total prediction does not exist: {prediction_id}")
    projected_total = home + away
    if abs(projected_total - float(parent[0])) >= 1e-9:
        raise BusinessEntityError(
            "component score sum must equal the governed projected total"
        )
    requested = (
        prediction_id,
        component_version,
        home,
        away,
        projected_total,
        generated,
        provenance,
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM total_score_component_predictions "
                "WHERE total_model_prediction_id = ?",
                (prediction_id,),
            ).fetchone()
            if row is not None:
                if tuple(row) != requested:
                    raise BusinessEntityConflictError(
                        "total component identity has different immutable values"
                    )
                return TotalScoreComponentPrediction(*row)
            conn.execute(
                "INSERT INTO total_score_component_predictions "
                f"({_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            return get_total_score_component_prediction(conn, prediction_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("total score component prediction", exc) from exc
