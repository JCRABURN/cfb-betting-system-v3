"""Create lookup indexes used by card and walk-forward queries."""

from __future__ import annotations

import sqlite3


VERSION = 3
NAME = "lookup_indexes"
INDEXES = {
    "idx_team_game_stats_lookup": (
        "CREATE INDEX IF NOT EXISTS idx_team_game_stats_lookup "
        "ON team_game_stats (source, team, season, week)",
        ("source", "team", "season", "week"),
    ),
    "idx_betting_lines_lookup": (
        "CREATE INDEX IF NOT EXISTS idx_betting_lines_lookup "
        "ON betting_lines (game_id, line_type, book)",
        ("game_id", "line_type", "book"),
    ),
    "idx_games_season_week": (
        "CREATE INDEX IF NOT EXISTS idx_games_season_week ON games (season, week)",
        ("season", "week"),
    ),
}


def upgrade(conn: sqlite3.Connection) -> None:
    for statement, _ in INDEXES.values():
        conn.execute(statement)


def verify(conn: sqlite3.Connection) -> None:
    actual = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }
    missing = set(INDEXES) - actual
    if missing:
        raise RuntimeError(f"required lookup indexes are missing: {sorted(missing)}")
    for index_name, (_, expected_columns) in INDEXES.items():
        actual_columns = tuple(
            row[2] for row in conn.execute(f'PRAGMA index_info("{index_name}")')
        )
        if actual_columns != expected_columns:
            raise RuntimeError(
                f"{index_name} columns changed: "
                f"expected={expected_columns}, actual={actual_columns}"
            )
