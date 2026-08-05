"""Create the original SQLite schema introduced in Phase 1."""

from __future__ import annotations

import sqlite3


VERSION = 1
NAME = "initial_schema"

STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS teams (
        team_id INTEGER PRIMARY KEY,
        school TEXT NOT NULL UNIQUE,
        conference TEXT,
        division TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS games (
        game_id INTEGER PRIMARY KEY,
        season INTEGER NOT NULL,
        week INTEGER NOT NULL,
        season_type TEXT,
        start_date TEXT,
        home_team TEXT NOT NULL,
        away_team TEXT NOT NULL,
        venue TEXT,
        venue_latitude REAL,
        venue_longitude REAL,
        neutral_site INTEGER DEFAULT 0,
        conference_game INTEGER DEFAULT 0,
        home_points INTEGER,
        away_points INTEGER,
        completed INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS betting_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER,
        season INTEGER,
        week INTEGER,
        home_team TEXT NOT NULL,
        away_team TEXT NOT NULL,
        book TEXT NOT NULL,
        home_spread REAL,
        total REAL,
        home_moneyline INTEGER,
        away_moneyline INTEGER,
        line_type TEXT NOT NULL,
        source TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS team_game_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER,
        season INTEGER NOT NULL,
        week INTEGER,
        team TEXT NOT NULL,
        sp_rating REAL,
        offense_epa_play REAL,
        defense_epa_play REAL,
        wins INTEGER,
        losses INTEGER,
        source TEXT NOT NULL,
        fetched_at TEXT NOT NULL,
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS weather (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER,
        captured_at TEXT NOT NULL,
        temp_f REAL,
        wind_mph REAL,
        precip_pct REAL,
        is_forecast INTEGER DEFAULT 1,
        source TEXT NOT NULL DEFAULT 'open-meteo',
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS injuries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team TEXT NOT NULL,
        player TEXT,
        position TEXT,
        status TEXT,
        report_date TEXT,
        source TEXT NOT NULL,
        fetched_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS picks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        game_id INTEGER,
        week INTEGER NOT NULL,
        year INTEGER NOT NULL,
        home_team TEXT,
        away_team TEXT,
        consensus_spread REAL,
        projected_spread REAL,
        edge REAL,
        recommended_side TEXT,
        units INTEGER,
        confidence_signals TEXT,
        key_factors TEXT,
        line_movement REAL,
        weather TEXT,
        risk_flags TEXT,
        qualifies INTEGER,
        status TEXT NOT NULL DEFAULT 'pending',
        result TEXT,
        clv REAL,
        unit_pl REAL,
        pick_type TEXT NOT NULL DEFAULT 'live',
        created_at TEXT NOT NULL,
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS ingestion_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        rows_added INTEGER DEFAULT 0,
        status TEXT NOT NULL,
        error TEXT
    )
    """,
)

REQUIRED_COLUMNS = {
    "teams": {"team_id", "school", "conference", "division"},
    "games": {
        "game_id",
        "season",
        "week",
        "season_type",
        "start_date",
        "home_team",
        "away_team",
        "venue",
        "venue_latitude",
        "venue_longitude",
        "neutral_site",
        "conference_game",
        "home_points",
        "away_points",
        "completed",
    },
    "betting_lines": {
        "id",
        "game_id",
        "season",
        "week",
        "home_team",
        "away_team",
        "book",
        "home_spread",
        "total",
        "home_moneyline",
        "away_moneyline",
        "line_type",
        "source",
        "fetched_at",
    },
    "team_game_stats": {
        "id",
        "game_id",
        "season",
        "week",
        "team",
        "sp_rating",
        "offense_epa_play",
        "defense_epa_play",
        "wins",
        "losses",
        "source",
        "fetched_at",
    },
    "weather": {
        "id",
        "game_id",
        "captured_at",
        "temp_f",
        "wind_mph",
        "precip_pct",
        "is_forecast",
        "source",
    },
    "injuries": {
        "id",
        "team",
        "player",
        "position",
        "status",
        "report_date",
        "source",
        "fetched_at",
    },
    "picks": {
        "id",
        "game_id",
        "week",
        "year",
        "home_team",
        "away_team",
        "consensus_spread",
        "projected_spread",
        "edge",
        "recommended_side",
        "units",
        "confidence_signals",
        "key_factors",
        "line_movement",
        "weather",
        "risk_flags",
        "qualifies",
        "status",
        "result",
        "clv",
        "unit_pl",
        "pick_type",
        "created_at",
    },
    "ingestion_runs": {
        "id",
        "source",
        "started_at",
        "finished_at",
        "rows_added",
        "status",
        "error",
    },
}


def upgrade(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)


def verify(conn: sqlite3.Connection) -> None:
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    for table, expected_columns in REQUIRED_COLUMNS.items():
        if table not in tables:
            raise RuntimeError(f"required table is missing: {table}")
        actual_columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
        missing = expected_columns - actual_columns
        if missing:
            raise RuntimeError(f"{table} is missing columns: {sorted(missing)}")
