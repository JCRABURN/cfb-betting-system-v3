"""Add first-class contests and immutable locked contest lines."""

from __future__ import annotations

import sqlite3


VERSION = 5
NAME = "immutable_contest_lines"

MARKET_LINE_TYPES = ("opening", "current", "closing")

STATEMENTS = (
    """
    CREATE TABLE contests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_key TEXT NOT NULL CHECK (length(trim(contest_key)) > 0),
        name TEXT NOT NULL CHECK (length(trim(name)) > 0),
        season INTEGER NOT NULL CHECK (season >= 1869),
        week INTEGER NOT NULL CHECK (week >= 0),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        source_contest_id TEXT CHECK (
            source_contest_id IS NULL OR length(trim(source_contest_id)) > 0
        ),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        created_at TEXT NOT NULL CHECK (
            julianday(created_at) IS NOT NULL AND substr(created_at, -6) = '+00:00'
        ),
        UNIQUE (contest_key, season, week),
        UNIQUE (source, source_contest_id, season, week),
        UNIQUE (id, season, week)
    )
    """,
    """
    CREATE TABLE contest_locked_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_id INTEGER NOT NULL,
        game_id INTEGER,
        season INTEGER NOT NULL CHECK (season >= 1869),
        week INTEGER NOT NULL CHECK (week >= 0),
        raw_home_team TEXT NOT NULL CHECK (length(trim(raw_home_team)) > 0),
        raw_away_team TEXT NOT NULL CHECK (length(trim(raw_away_team)) > 0),
        normalized_home_team TEXT NOT NULL
            CHECK (length(trim(normalized_home_team)) > 0),
        normalized_away_team TEXT NOT NULL
            CHECK (length(trim(normalized_away_team)) > 0),
        home_spread REAL NOT NULL CHECK (typeof(home_spread) IN ('integer', 'real')),
        total REAL CHECK (total IS NULL OR (typeof(total) IN ('integer', 'real') AND total >= 0)),
        locked_at TEXT NOT NULL CHECK (
            julianday(locked_at) IS NOT NULL AND substr(locked_at, -6) = '+00:00'
        ),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        source_line_id TEXT CHECK (
            source_line_id IS NULL OR length(trim(source_line_id)) > 0
        ),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        payload_sha256 TEXT NOT NULL CHECK (
            length(payload_sha256) = 64
            AND lower(payload_sha256) NOT GLOB '*[^0-9a-f]*'
        ),
        CHECK (lower(trim(normalized_home_team)) != lower(trim(normalized_away_team))),
        FOREIGN KEY (contest_id, season, week)
            REFERENCES contests(id, season, week),
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    """
    CREATE TABLE contest_line_corrections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        locked_line_id INTEGER NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence > 0),
        supersedes_correction_id INTEGER,
        game_id INTEGER,
        raw_home_team TEXT NOT NULL CHECK (length(trim(raw_home_team)) > 0),
        raw_away_team TEXT NOT NULL CHECK (length(trim(raw_away_team)) > 0),
        normalized_home_team TEXT NOT NULL
            CHECK (length(trim(normalized_home_team)) > 0),
        normalized_away_team TEXT NOT NULL
            CHECK (length(trim(normalized_away_team)) > 0),
        home_spread REAL NOT NULL CHECK (typeof(home_spread) IN ('integer', 'real')),
        total REAL CHECK (total IS NULL OR (typeof(total) IN ('integer', 'real') AND total >= 0)),
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        author TEXT NOT NULL CHECK (length(trim(author)) > 0),
        corrected_at TEXT NOT NULL CHECK (
            julianday(corrected_at) IS NOT NULL AND substr(corrected_at, -6) = '+00:00'
        ),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        source_line_id TEXT CHECK (
            source_line_id IS NULL OR length(trim(source_line_id)) > 0
        ),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        payload_sha256 TEXT NOT NULL CHECK (
            length(payload_sha256) = 64
            AND lower(payload_sha256) NOT GLOB '*[^0-9a-f]*'
        ),
        CHECK (lower(trim(normalized_home_team)) != lower(trim(normalized_away_team))),
        UNIQUE (locked_line_id, sequence),
        FOREIGN KEY (locked_line_id) REFERENCES contest_locked_lines(id),
        FOREIGN KEY (supersedes_correction_id) REFERENCES contest_line_corrections(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    "CREATE INDEX idx_contests_season_week ON contests (season, week)",
    """
    CREATE INDEX idx_contest_locked_lines_contest
        ON contest_locked_lines (contest_id, id)
    """,
    """
    CREATE UNIQUE INDEX uq_contest_locked_lines_game
        ON contest_locked_lines (contest_id, game_id)
        WHERE game_id IS NOT NULL
    """,
    """
    CREATE UNIQUE INDEX uq_contest_locked_lines_matchup
        ON contest_locked_lines (
            contest_id,
            CASE
                WHEN lower(trim(normalized_home_team)) < lower(trim(normalized_away_team))
                THEN lower(trim(normalized_home_team))
                ELSE lower(trim(normalized_away_team))
            END,
            CASE
                WHEN lower(trim(normalized_home_team)) < lower(trim(normalized_away_team))
                THEN lower(trim(normalized_away_team))
                ELSE lower(trim(normalized_home_team))
            END
        )
    """,
    """
    CREATE INDEX idx_contest_line_corrections_history
        ON contest_line_corrections (locked_line_id, sequence)
    """,
    """
    CREATE TRIGGER contests_no_duplicate_insert
    BEFORE INSERT ON contests
    WHEN EXISTS (
        SELECT 1 FROM contests
        WHERE id = NEW.id
           OR (contest_key = NEW.contest_key
               AND season = NEW.season
               AND week = NEW.week)
           OR (NEW.source_contest_id IS NOT NULL
               AND source = NEW.source
               AND source_contest_id = NEW.source_contest_id
               AND season = NEW.season
               AND week = NEW.week)
    )
    BEGIN
        SELECT RAISE(ABORT, 'contest already exists and cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER contests_no_update
    BEFORE UPDATE ON contests
    BEGIN
        SELECT RAISE(ABORT, 'contests are immutable; create a new contest record');
    END
    """,
    """
    CREATE TRIGGER contests_no_delete
    BEFORE DELETE ON contests
    BEGIN
        SELECT RAISE(ABORT, 'contests are immutable and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER contest_locked_lines_validate_game
    BEFORE INSERT ON contest_locked_lines
    WHEN NEW.game_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM games
        WHERE game_id = NEW.game_id
          AND season = NEW.season
          AND week = NEW.week
          AND home_team = NEW.normalized_home_team
          AND away_team = NEW.normalized_away_team
    )
    BEGIN
        SELECT RAISE(ABORT, 'game does not match the locked line season, week, and teams');
    END
    """,
    """
    CREATE TRIGGER contest_locked_lines_no_relock
    BEFORE INSERT ON contest_locked_lines
    WHEN EXISTS (SELECT 1 FROM contest_locked_lines WHERE id = NEW.id)
      OR EXISTS (
          SELECT 1
          FROM contest_locked_lines
          WHERE contest_id = NEW.contest_id
            AND (
                (NEW.game_id IS NOT NULL AND game_id = NEW.game_id)
                OR (
                    min(lower(trim(normalized_home_team)), lower(trim(normalized_away_team)))
                        = min(lower(trim(NEW.normalized_home_team)), lower(trim(NEW.normalized_away_team)))
                    AND max(lower(trim(normalized_home_team)), lower(trim(normalized_away_team)))
                        = max(lower(trim(NEW.normalized_home_team)), lower(trim(NEW.normalized_away_team)))
                )
            )
      )
      OR EXISTS (
          SELECT 1
          FROM contest_line_corrections AS correction
          JOIN contest_locked_lines AS locked
            ON locked.id = correction.locked_line_id
          WHERE locked.contest_id = NEW.contest_id
            AND correction.id = (
                SELECT latest.id
                FROM contest_line_corrections AS latest
                WHERE latest.locked_line_id = locked.id
                ORDER BY latest.sequence DESC
                LIMIT 1
            )
            AND (
                (NEW.game_id IS NOT NULL AND correction.game_id = NEW.game_id)
                OR (
                    min(lower(trim(correction.normalized_home_team)), lower(trim(correction.normalized_away_team)))
                        = min(lower(trim(NEW.normalized_home_team)), lower(trim(NEW.normalized_away_team)))
                    AND max(lower(trim(correction.normalized_home_team)), lower(trim(correction.normalized_away_team)))
                        = max(lower(trim(NEW.normalized_home_team)), lower(trim(NEW.normalized_away_team)))
                )
            )
      )
    BEGIN
        SELECT RAISE(ABORT, 'contest line is already locked; record a correction');
    END
    """,
    """
    CREATE TRIGGER contest_locked_lines_no_update
    BEFORE UPDATE ON contest_locked_lines
    BEGIN
        SELECT RAISE(ABORT, 'locked contest lines are immutable; record a correction');
    END
    """,
    """
    CREATE TRIGGER contest_locked_lines_no_delete
    BEFORE DELETE ON contest_locked_lines
    BEGIN
        SELECT RAISE(ABORT, 'locked contest lines are immutable and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER contest_line_corrections_validate_game
    BEFORE INSERT ON contest_line_corrections
    WHEN NEW.game_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM games AS g
        JOIN contest_locked_lines AS locked
          ON locked.id = NEW.locked_line_id
        WHERE g.game_id = NEW.game_id
          AND g.season = locked.season
          AND g.week = locked.week
          AND g.home_team = NEW.normalized_home_team
          AND g.away_team = NEW.normalized_away_team
    )
    BEGIN
        SELECT RAISE(ABORT, 'game does not match the corrected line season, week, and teams');
    END
    """,
    """
    CREATE TRIGGER contest_line_corrections_validate_sequence
    BEFORE INSERT ON contest_line_corrections
    WHEN EXISTS (SELECT 1 FROM contest_line_corrections WHERE id = NEW.id)
      OR NEW.sequence != COALESCE(
          (SELECT MAX(sequence) + 1
           FROM contest_line_corrections
           WHERE locked_line_id = NEW.locked_line_id),
          1
      )
      OR NEW.supersedes_correction_id IS NOT (
          SELECT id
          FROM contest_line_corrections
          WHERE locked_line_id = NEW.locked_line_id
          ORDER BY sequence DESC
          LIMIT 1
      )
    BEGIN
        SELECT RAISE(ABORT, 'correction history must be append-only and contiguous');
    END
    """,
    """
    CREATE TRIGGER contest_line_corrections_no_matchup_collision
    BEFORE INSERT ON contest_line_corrections
    WHEN EXISTS (
        SELECT 1
        FROM contest_locked_lines AS target
        JOIN contest_locked_lines AS other
          ON other.contest_id = target.contest_id
         AND other.id != target.id
        LEFT JOIN contest_line_corrections AS latest
          ON latest.id = (
              SELECT prior.id
              FROM contest_line_corrections AS prior
              WHERE prior.locked_line_id = other.id
              ORDER BY prior.sequence DESC
              LIMIT 1
          )
        WHERE target.id = NEW.locked_line_id
          AND (
              (NEW.game_id IS NOT NULL AND NEW.game_id = other.game_id)
              OR (
                  min(lower(trim(NEW.normalized_home_team)), lower(trim(NEW.normalized_away_team)))
                      = min(lower(trim(other.normalized_home_team)), lower(trim(other.normalized_away_team)))
                  AND max(lower(trim(NEW.normalized_home_team)), lower(trim(NEW.normalized_away_team)))
                      = max(lower(trim(other.normalized_home_team)), lower(trim(other.normalized_away_team)))
              )
              OR (NEW.game_id IS NOT NULL AND latest.id IS NOT NULL AND NEW.game_id = latest.game_id)
              OR (
                  latest.id IS NOT NULL
                  AND
                  min(lower(trim(NEW.normalized_home_team)), lower(trim(NEW.normalized_away_team)))
                      = min(
                          lower(trim(latest.normalized_home_team)),
                          lower(trim(latest.normalized_away_team))
                      )
                  AND max(lower(trim(NEW.normalized_home_team)), lower(trim(NEW.normalized_away_team)))
                      = max(
                          lower(trim(latest.normalized_home_team)),
                          lower(trim(latest.normalized_away_team))
                      )
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'corrected matchup conflicts with another locked contest line');
    END
    """,
    """
    CREATE TRIGGER contest_line_corrections_validate_timestamp
    BEFORE INSERT ON contest_line_corrections
    WHEN EXISTS (
        SELECT 1
        FROM contest_locked_lines AS locked
        LEFT JOIN contest_line_corrections AS latest
          ON latest.id = (
              SELECT prior.id
              FROM contest_line_corrections AS prior
              WHERE prior.locked_line_id = locked.id
              ORDER BY prior.sequence DESC
              LIMIT 1
          )
        WHERE locked.id = NEW.locked_line_id
          AND julianday(NEW.corrected_at) <= julianday(
              CASE WHEN latest.id IS NULL THEN locked.locked_at ELSE latest.corrected_at END
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'correction timestamp must follow the prior recorded value');
    END
    """,
    """
    CREATE TRIGGER contest_line_corrections_require_change
    BEFORE INSERT ON contest_line_corrections
    WHEN EXISTS (
        SELECT 1
        FROM contest_locked_lines AS locked
        LEFT JOIN contest_line_corrections AS latest
          ON latest.id = (
              SELECT prior.id
              FROM contest_line_corrections AS prior
              WHERE prior.locked_line_id = locked.id
              ORDER BY prior.sequence DESC
              LIMIT 1
          )
        WHERE locked.id = NEW.locked_line_id
          AND NEW.game_id IS (CASE WHEN latest.id IS NULL THEN locked.game_id ELSE latest.game_id END)
          AND NEW.raw_home_team = CASE WHEN latest.id IS NULL THEN locked.raw_home_team ELSE latest.raw_home_team END
          AND NEW.raw_away_team = CASE WHEN latest.id IS NULL THEN locked.raw_away_team ELSE latest.raw_away_team END
          AND NEW.normalized_home_team = CASE WHEN latest.id IS NULL THEN locked.normalized_home_team ELSE latest.normalized_home_team END
          AND NEW.normalized_away_team = CASE WHEN latest.id IS NULL THEN locked.normalized_away_team ELSE latest.normalized_away_team END
          AND NEW.home_spread = CASE WHEN latest.id IS NULL THEN locked.home_spread ELSE latest.home_spread END
          AND NEW.total IS (CASE WHEN latest.id IS NULL THEN locked.total ELSE latest.total END)
    )
    BEGIN
        SELECT RAISE(ABORT, 'correction must change at least one line field');
    END
    """,
    """
    CREATE TRIGGER contest_line_corrections_no_update
    BEFORE UPDATE ON contest_line_corrections
    BEGIN
        SELECT RAISE(ABORT, 'contest line corrections are immutable');
    END
    """,
    """
    CREATE TRIGGER contest_line_corrections_no_delete
    BEFORE DELETE ON contest_line_corrections
    BEGIN
        SELECT RAISE(ABORT, 'contest line corrections are immutable and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER betting_lines_market_type_insert
    BEFORE INSERT ON betting_lines
    WHEN NEW.line_type NOT IN ('opening', 'current', 'closing')
    BEGIN
        SELECT RAISE(ABORT, 'betting_lines accepts only opening, current, or closing market lines');
    END
    """,
    """
    CREATE TRIGGER betting_lines_market_type_update
    BEFORE UPDATE OF line_type ON betting_lines
    WHEN NEW.line_type NOT IN ('opening', 'current', 'closing')
    BEGIN
        SELECT RAISE(ABORT, 'betting_lines accepts only opening, current, or closing market lines');
    END
    """,
)


def _normalize_sql(statement: str) -> str:
    return " ".join(statement.split()).casefold()


def _schema_object(statement: str) -> tuple[str, str] | None:
    words = statement.split()
    if len(words) >= 3 and words[0:2] == ["CREATE", "TABLE"]:
        return "table", words[2]
    if len(words) >= 3 and words[0:2] == ["CREATE", "TRIGGER"]:
        return "trigger", words[2]
    if len(words) >= 4 and words[0:3] == ["CREATE", "UNIQUE", "INDEX"]:
        return "index", words[3]
    if len(words) >= 3 and words[0:2] == ["CREATE", "INDEX"]:
        return "index", words[2]
    return None


EXPECTED_OBJECT_SQL = {
    schema_object: _normalize_sql(statement)
    for statement in STATEMENTS
    if (schema_object := _schema_object(statement)) is not None
}

REQUIRED_COLUMNS = {
    "contests": {
        "id",
        "contest_key",
        "name",
        "season",
        "week",
        "source",
        "source_contest_id",
        "provenance",
        "created_at",
    },
    "contest_locked_lines": {
        "id",
        "contest_id",
        "game_id",
        "season",
        "week",
        "raw_home_team",
        "raw_away_team",
        "normalized_home_team",
        "normalized_away_team",
        "home_spread",
        "total",
        "locked_at",
        "source",
        "source_line_id",
        "provenance",
        "payload_sha256",
    },
    "contest_line_corrections": {
        "id",
        "locked_line_id",
        "sequence",
        "supersedes_correction_id",
        "game_id",
        "raw_home_team",
        "raw_away_team",
        "normalized_home_team",
        "normalized_away_team",
        "home_spread",
        "total",
        "reason",
        "author",
        "corrected_at",
        "source",
        "source_line_id",
        "provenance",
        "payload_sha256",
    },
}

REQUIRED_INDEXES = {
    name for object_type, name in EXPECTED_OBJECT_SQL if object_type == "index"
}
REQUIRED_TRIGGERS = {
    name for object_type, name in EXPECTED_OBJECT_SQL if object_type == "trigger"
}


def upgrade(conn: sqlite3.Connection) -> None:
    invalid_types = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT line_type FROM betting_lines "
            "WHERE line_type NOT IN ('opening', 'current', 'closing') "
            "ORDER BY line_type"
        )
    ]
    if invalid_types:
        raise RuntimeError(
            f"betting_lines contains unsupported market line types: {invalid_types}"
        )
    for statement in STATEMENTS:
        conn.execute(statement)


def verify(conn: sqlite3.Connection) -> None:
    objects = {
        (row[0], row[1])
        for row in conn.execute(
            "SELECT type, name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'"
        )
    }
    for table, expected_columns in REQUIRED_COLUMNS.items():
        if ("table", table) not in objects:
            raise RuntimeError(f"required table is missing: {table}")
        actual_columns = {row[1] for row in conn.execute(f'PRAGMA table_info("{table}")')}
        missing = expected_columns - actual_columns
        if missing:
            raise RuntimeError(f"{table} is missing columns: {sorted(missing)}")

    missing_indexes = {
        index for index in REQUIRED_INDEXES if ("index", index) not in objects
    }
    if missing_indexes:
        raise RuntimeError(f"contest-line indexes are missing: {sorted(missing_indexes)}")

    missing_triggers = {
        trigger for trigger in REQUIRED_TRIGGERS if ("trigger", trigger) not in objects
    }
    if missing_triggers:
        raise RuntimeError(f"contest-line triggers are missing: {sorted(missing_triggers)}")

    for (object_type, name), expected_sql in EXPECTED_OBJECT_SQL.items():
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
            (object_type, name),
        ).fetchone()
        if row is None or row[0] is None:
            raise RuntimeError(f"required {object_type} is missing: {name}")
        if _normalize_sql(row[0]) != expected_sql:
            raise RuntimeError(f"{object_type} definition changed: {name}")

    invalid_types = [
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT line_type FROM betting_lines "
            "WHERE line_type NOT IN ('opening', 'current', 'closing') "
            "ORDER BY line_type"
        )
    ]
    if invalid_types:
        raise RuntimeError(
            f"betting_lines contains unsupported market line types: {invalid_types}"
        )
