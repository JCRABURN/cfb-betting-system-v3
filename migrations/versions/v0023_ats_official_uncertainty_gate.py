"""Fail closed when an official model-backed Top 5 lacks uncertainty."""

from __future__ import annotations

import sqlite3


VERSION = 23
NAME = "ats_official_uncertainty_gate"
TRIGGER = "official_card_publications_require_model_uncertainty"


STATEMENT = f"""
CREATE TRIGGER {TRIGGER}
BEFORE INSERT ON official_card_publications
WHEN EXISTS (
    SELECT 1
    FROM contest_picks AS pick
    LEFT JOIN model_predictions AS prediction
      ON prediction.id = pick.model_prediction_id
    WHERE pick.card_id = NEW.card_id
      AND pick.is_top_five = 1
      AND pick.model_prediction_id IS NOT NULL
      AND (
          prediction.id IS NULL
          OR prediction.uncertainty_points IS NULL
          OR prediction.uncertainty_points <= 0
      )
)
BEGIN
    SELECT RAISE(
        ABORT,
        'official model-backed Top 5 requires positive governed uncertainty'
    );
END
"""


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(STATEMENT)


def verify(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'trigger' AND name = ?",
        (TRIGGER,),
    ).fetchone()
    if row is None or "uncertainty_points" not in str(row[0]):
        raise RuntimeError("missing migration-23 official ATS uncertainty gate")
