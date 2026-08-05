"""Add success-rate and havoc columns to historical team snapshots."""

from __future__ import annotations

import sqlite3


VERSION = 2
NAME = "team_game_stats_features"
COLUMNS = (
    ("offense_success_rate", "REAL"),
    ("defense_success_rate", "REAL"),
    ("havoc_rate", "REAL"),
)


def upgrade(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute('PRAGMA table_info("team_game_stats")')}
    for name, column_type in COLUMNS:
        if name not in existing:
            conn.execute(f'ALTER TABLE "team_game_stats" ADD COLUMN "{name}" {column_type}')


def verify(conn: sqlite3.Connection) -> None:
    existing = {row[1] for row in conn.execute('PRAGMA table_info("team_game_stats")')}
    missing = {name for name, _ in COLUMNS} - existing
    if missing:
        raise RuntimeError(f"team_game_stats is missing feature columns: {sorted(missing)}")
