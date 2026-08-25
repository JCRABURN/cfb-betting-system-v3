"""Add immutable production context evidence and per-card context status."""

from __future__ import annotations

import sqlite3


VERSION = 17
NAME = "production_context_evidence"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"
_SHA256_CHECK = (
    "length({column}) = 64 AND lower({column}) NOT GLOB '*[^0-9a-f]*'"
)

STATEMENTS = (
    f"""
    CREATE TABLE provider_context_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        acceptance_id INTEGER NOT NULL UNIQUE,
        ingestion_run_id INTEGER NOT NULL,
        record_index INTEGER NOT NULL CHECK (record_index >= 0),
        evidence_key TEXT NOT NULL UNIQUE
            CHECK ({_SHA256_CHECK.format(column='evidence_key')}),
        context_class TEXT NOT NULL CHECK (
            context_class IN ('injury', 'weather', 'travel_rest', 'coaching', 'motivation')
        ),
        source_mode TEXT NOT NULL CHECK (
            source_mode IN ('automated', 'manual_exception')
        ),
        game_id INTEGER NOT NULL,
        season INTEGER NOT NULL CHECK (season >= 1869),
        week INTEGER NOT NULL CHECK (week >= 0),
        affected_side TEXT NOT NULL CHECK (
            affected_side IN ('home', 'away', 'both', 'neutral')
        ),
        subject TEXT,
        evidence_summary TEXT NOT NULL CHECK (length(trim(evidence_summary)) > 0),
        source_name TEXT NOT NULL CHECK (length(trim(source_name)) > 0),
        source_reference TEXT NOT NULL CHECK (length(trim(source_reference)) > 0),
        observed_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='observed_at')}),
        expires_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='expires_at')}),
        margin_adjustment REAL NOT NULL CHECK (
            typeof(margin_adjustment) IN ('integer', 'real')
            AND margin_adjustment >= -100 AND margin_adjustment <= 100
        ),
        confidence_adjustment INTEGER NOT NULL CHECK (
            confidence_adjustment BETWEEN -4 AND 4
        ),
        author TEXT NOT NULL CHECK (length(trim(author)) > 0),
        parser_version TEXT NOT NULL CHECK (length(trim(parser_version)) > 0),
        raw_record_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='raw_record_sha256')}),
        ingested_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='ingested_at')}),
        CHECK (julianday(observed_at) <= julianday(expires_at)),
        CHECK (
            source_mode = 'manual_exception'
            OR (margin_adjustment = 0 AND confidence_adjustment = 0)
        ),
        UNIQUE (ingestion_run_id, record_index),
        FOREIGN KEY (acceptance_id) REFERENCES provider_ingestion_acceptances(id),
        FOREIGN KEY (ingestion_run_id) REFERENCES provider_ingestion_runs(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    f"""
    CREATE TABLE card_context_status (
        card_id INTEGER NOT NULL,
        controller_run_id INTEGER NOT NULL,
        context_class TEXT NOT NULL CHECK (
            context_class IN ('injury', 'weather', 'travel_rest', 'coaching', 'motivation')
        ),
        state TEXT NOT NULL CHECK (state IN ('current', 'stale', 'missing')),
        source_mode TEXT NOT NULL CHECK (
            source_mode IN ('automated', 'manual_exception', 'mixed')
        ),
        evidence_count INTEGER NOT NULL CHECK (evidence_count >= 0),
        latest_observed_at TEXT CHECK (
            latest_observed_at IS NULL OR ({_UTC_CHECK.format(column='latest_observed_at')})
        ),
        fallback_code TEXT,
        fallback_reason TEXT,
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            (state = 'current' AND evidence_count > 0
             AND latest_observed_at IS NOT NULL
             AND fallback_code IS NULL AND fallback_reason IS NULL)
            OR (state IN ('stale', 'missing')
                AND length(trim(fallback_code)) > 0
                AND length(trim(fallback_reason)) > 0)
        ),
        PRIMARY KEY (card_id, context_class),
        FOREIGN KEY (card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (controller_run_id) REFERENCES weekly_controller_runs(id)
    )
    """,
    """
    CREATE INDEX idx_provider_context_evidence_lookup
    ON provider_context_evidence (season, week, context_class, observed_at, id)
    """,
    """
    CREATE INDEX idx_provider_context_evidence_game
    ON provider_context_evidence (game_id, context_class, observed_at, id)
    """,
    """
    CREATE INDEX idx_card_context_status_run
    ON card_context_status (controller_run_id, context_class)
    """,
    """
    CREATE TRIGGER provider_context_evidence_validate_acceptance
    BEFORE INSERT ON provider_context_evidence
    WHEN NOT EXISTS (
        SELECT 1
        FROM provider_ingestion_acceptances AS accepted
        JOIN provider_ingestion_runs AS run ON run.id = accepted.ingestion_run_id
        JOIN games AS game ON game.game_id = NEW.game_id
        WHERE accepted.id = NEW.acceptance_id
          AND accepted.ingestion_run_id = NEW.ingestion_run_id
          AND accepted.record_index = NEW.record_index
          AND accepted.record_key = NEW.evidence_key
          AND accepted.observed_at = NEW.observed_at
          AND accepted.parser_version = NEW.parser_version
          AND accepted.raw_record_sha256 = NEW.raw_record_sha256
          AND run.status IN ('completed', 'partial')
          AND (
              (NEW.context_class = 'injury' AND run.data_type = 'injuries')
              OR (NEW.context_class = 'weather' AND run.data_type = 'weather')
              OR (NEW.context_class IN ('travel_rest', 'coaching', 'motivation')
                  AND run.data_type = 'contextual')
          )
          AND game.season = NEW.season
          AND game.week = NEW.week
          AND julianday(NEW.observed_at) <= julianday(run.requested_at)
          AND julianday(NEW.observed_at) < julianday(game.start_date)
    )
    BEGIN
        SELECT RAISE(ABORT, 'context evidence lacks accepted PIT provider custody');
    END
    """,
    """
    CREATE TRIGGER card_context_status_validate_run
    BEFORE INSERT ON card_context_status
    WHEN NOT EXISTS (
        SELECT 1
        FROM weekly_controller_runs AS run
        WHERE run.id = NEW.controller_run_id
          AND run.status = 'completed'
          AND run.card_id = NEW.card_id
          AND run.operation IN ('tuesday_lock', 'daily_refresh')
          AND (
              NEW.state != 'current'
              OR NEW.evidence_count = (
                  SELECT COUNT(*)
                  FROM provider_context_evidence AS evidence
                  JOIN contest_picks AS pick ON pick.card_id = NEW.card_id
                  JOIN contest_locked_lines AS locked ON locked.id = pick.locked_line_id
                  JOIN games AS game ON game.game_id = locked.game_id
                  WHERE evidence.game_id = locked.game_id
                    AND evidence.context_class = NEW.context_class
                    AND julianday(evidence.observed_at) <= julianday(run.requested_at)
                    AND julianday(evidence.expires_at) >= julianday(run.requested_at)
                    AND julianday(run.requested_at) < julianday(game.start_date)
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'card context status lacks matching immutable evidence');
    END
    """,
)

for _table in ("provider_context_evidence", "card_context_status"):
    STATEMENTS += (
        f"""
        CREATE TRIGGER {_table}_no_update
        BEFORE UPDATE ON {_table}
        BEGIN
            SELECT RAISE(ABORT, '{_table} records are immutable');
        END
        """,
        f"""
        CREATE TRIGGER {_table}_no_delete
        BEFORE DELETE ON {_table}
        BEGIN
            SELECT RAISE(ABORT, '{_table} records are immutable and cannot be deleted');
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
    if len(words) >= 3 and words[0:2] == ["CREATE", "INDEX"]:
        return "index", words[2]
    return None


EXPECTED_OBJECT_SQL = {
    schema_object: _normalize_sql(statement)
    for statement in STATEMENTS
    if (schema_object := _schema_object(statement)) is not None
}


def upgrade(conn: sqlite3.Connection) -> None:
    for statement in STATEMENTS:
        conn.execute(statement)


def verify(conn: sqlite3.Connection) -> None:
    for (object_type, name), expected_sql in EXPECTED_OBJECT_SQL.items():
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = ? AND name = ?",
            (object_type, name),
        ).fetchone()
        if row is None or row[0] is None:
            raise RuntimeError(f"required {object_type} is missing: {name}")
        if _normalize_sql(row[0]) != expected_sql:
            raise RuntimeError(f"{object_type} definition changed: {name}")
