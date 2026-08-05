"""Add supplemental dates used to calculate rest across FCS games."""

from __future__ import annotations

import sqlite3


VERSION = 4
NAME = "supplemental_game_dates"


def upgrade(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS supplemental_game_dates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team TEXT NOT NULL,
            season INTEGER NOT NULL,
            week INTEGER NOT NULL,
            start_date TEXT NOT NULL,
            opponent_classification TEXT,
            source TEXT NOT NULL DEFAULT 'cfbd_supplemental_dates',
            fetched_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_supplemental_game_dates_lookup "
        "ON supplemental_game_dates (team, season, week)"
    )


def verify(conn: sqlite3.Connection) -> None:
    expected_columns = {
        "id",
        "team",
        "season",
        "week",
        "start_date",
        "opponent_classification",
        "source",
        "fetched_at",
    }
    actual_columns = {
        row[1] for row in conn.execute('PRAGMA table_info("supplemental_game_dates")')
    }
    missing = expected_columns - actual_columns
    if missing:
        raise RuntimeError(f"supplemental_game_dates is missing columns: {sorted(missing)}")

    index = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'index' "
        "AND name = 'idx_supplemental_game_dates_lookup'"
    ).fetchone()
    if index is None:
        raise RuntimeError("idx_supplemental_game_dates_lookup is missing")
    index_columns = tuple(
        row[2]
        for row in conn.execute(
            'PRAGMA index_info("idx_supplemental_game_dates_lookup")'
        )
    )
    if index_columns != ("team", "season", "week"):
        raise RuntimeError(
            "idx_supplemental_game_dates_lookup columns changed: "
            f"{index_columns}"
        )
