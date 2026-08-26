"""Bind injury card-context status to one coherent ESPN ingestion run.

Recovery may drop only the new table after preserving its audit rows, or restore
the pre-migration database copy. No existing status or evidence row is updated.
"""

from __future__ import annotations

import sqlite3


VERSION = 18
NAME = "card_context_snapshot_identity"


STATEMENTS = (
    """
    CREATE TABLE card_context_source_snapshots (
        card_id INTEGER NOT NULL,
        controller_run_id INTEGER NOT NULL,
        context_class TEXT NOT NULL CHECK (context_class = 'injury'),
        provider TEXT NOT NULL CHECK (provider = 'espn'),
        ingestion_run_id INTEGER,
        snapshot_evidence_count INTEGER NOT NULL
            CHECK (snapshot_evidence_count >= 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        PRIMARY KEY (card_id, context_class),
        FOREIGN KEY (card_id, context_class)
            REFERENCES card_context_status(card_id, context_class),
        FOREIGN KEY (controller_run_id) REFERENCES weekly_controller_runs(id),
        FOREIGN KEY (ingestion_run_id) REFERENCES provider_ingestion_runs(id)
    )
    """,
    """
    CREATE INDEX idx_card_context_source_snapshots_run
    ON card_context_source_snapshots (ingestion_run_id, card_id)
    """,
    """
    CREATE TRIGGER card_context_source_snapshots_validate
    BEFORE INSERT ON card_context_source_snapshots
    WHEN NOT EXISTS (
        SELECT 1
        FROM card_context_status AS status
        JOIN weekly_controller_runs AS controller
          ON controller.id = NEW.controller_run_id
        WHERE status.card_id = NEW.card_id
          AND status.context_class = NEW.context_class
          AND status.controller_run_id = NEW.controller_run_id
          AND (
              (
                  NEW.ingestion_run_id IS NULL
                  AND NEW.snapshot_evidence_count = 0
                  AND status.state = 'missing'
                  AND status.latest_observed_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM provider_ingestion_runs AS latest
                      WHERE latest.provider = NEW.provider
                        AND latest.data_type = 'injuries'
                        AND julianday(latest.requested_at)
                            <= julianday(controller.requested_at)
                  )
              )
              OR EXISTS (
                  SELECT 1
                  FROM provider_ingestion_runs AS source
                  WHERE source.id = NEW.ingestion_run_id
                    AND source.provider = NEW.provider
                    AND source.data_type = 'injuries'
                    AND julianday(source.requested_at)
                        <= julianday(controller.requested_at)
                    AND source.id = (
                        SELECT latest.id
                        FROM provider_ingestion_runs AS latest
                        WHERE latest.provider = NEW.provider
                          AND latest.data_type = 'injuries'
                          AND julianday(latest.requested_at)
                              <= julianday(controller.requested_at)
                        ORDER BY julianday(latest.requested_at) DESC, latest.id DESC
                        LIMIT 1
                    )
                    AND NEW.snapshot_evidence_count = (
                        SELECT COUNT(*)
                        FROM provider_context_evidence AS evidence
                        JOIN contest_picks AS pick ON pick.card_id = NEW.card_id
                        JOIN contest_locked_lines AS locked
                          ON locked.id = pick.locked_line_id
                        JOIN games AS game ON game.game_id = locked.game_id
                        WHERE evidence.ingestion_run_id = source.id
                          AND evidence.game_id = locked.game_id
                          AND evidence.context_class = 'injury'
                          AND julianday(evidence.observed_at)
                              <= julianday(controller.requested_at)
                          AND julianday(evidence.expires_at)
                              >= julianday(controller.requested_at)
                          AND julianday(controller.requested_at)
                              < julianday(game.start_date)
                    )
                    AND status.latest_observed_at IS (
                        SELECT MAX(evidence.observed_at)
                        FROM provider_context_evidence AS evidence
                        JOIN contest_picks AS pick ON pick.card_id = NEW.card_id
                        JOIN contest_locked_lines AS locked
                          ON locked.id = pick.locked_line_id
                        JOIN games AS game ON game.game_id = locked.game_id
                        WHERE evidence.ingestion_run_id = source.id
                          AND evidence.game_id = locked.game_id
                          AND evidence.context_class = 'injury'
                          AND julianday(evidence.observed_at)
                              <= julianday(controller.requested_at)
                          AND julianday(controller.requested_at)
                              < julianday(game.start_date)
                    )
                    AND (
                        (
                            status.state = 'current'
                            AND (
                                SELECT COUNT(DISTINCT
                                    CAST(evidence.game_id AS TEXT) || ':'
                                    || evidence.affected_side
                                )
                                FROM provider_context_evidence AS evidence
                                JOIN contest_picks AS pick ON pick.card_id = NEW.card_id
                                JOIN contest_locked_lines AS locked
                                  ON locked.id = pick.locked_line_id
                                JOIN games AS game ON game.game_id = locked.game_id
                                WHERE evidence.ingestion_run_id = source.id
                                  AND evidence.game_id = locked.game_id
                                  AND evidence.context_class = 'injury'
                                  AND evidence.affected_side IN ('home', 'away')
                                  AND julianday(evidence.observed_at)
                                      <= julianday(controller.requested_at)
                                  AND julianday(evidence.expires_at)
                                      >= julianday(controller.requested_at)
                                  AND julianday(controller.requested_at)
                                      < julianday(game.start_date)
                            ) = 2 * (
                                SELECT COUNT(DISTINCT locked.game_id)
                                FROM contest_picks AS pick
                                JOIN contest_locked_lines AS locked
                                  ON locked.id = pick.locked_line_id
                                JOIN games AS game ON game.game_id = locked.game_id
                                WHERE pick.card_id = NEW.card_id
                                  AND julianday(controller.requested_at)
                                      < julianday(game.start_date)
                            )
                        )
                        OR (
                            status.state != 'current'
                            AND (
                                SELECT COUNT(DISTINCT
                                    CAST(evidence.game_id AS TEXT) || ':'
                                    || evidence.affected_side
                                )
                                FROM provider_context_evidence AS evidence
                                JOIN contest_picks AS pick ON pick.card_id = NEW.card_id
                                JOIN contest_locked_lines AS locked
                                  ON locked.id = pick.locked_line_id
                                JOIN games AS game ON game.game_id = locked.game_id
                                WHERE evidence.ingestion_run_id = source.id
                                  AND evidence.game_id = locked.game_id
                                  AND evidence.context_class = 'injury'
                                  AND evidence.affected_side IN ('home', 'away')
                                  AND julianday(evidence.observed_at)
                                      <= julianday(controller.requested_at)
                                  AND julianday(evidence.expires_at)
                                      >= julianday(controller.requested_at)
                                  AND julianday(controller.requested_at)
                                      < julianday(game.start_date)
                            ) != 2 * (
                                SELECT COUNT(DISTINCT locked.game_id)
                                FROM contest_picks AS pick
                                JOIN contest_locked_lines AS locked
                                  ON locked.id = pick.locked_line_id
                                JOIN games AS game ON game.game_id = locked.game_id
                                WHERE pick.card_id = NEW.card_id
                                  AND julianday(controller.requested_at)
                                      < julianday(game.start_date)
                            )
                        )
                    )
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'injury context status lacks the latest coherent ESPN snapshot');
    END
    """,
    """
    CREATE TRIGGER card_context_source_snapshots_no_update
    BEFORE UPDATE ON card_context_source_snapshots
    BEGIN
        SELECT RAISE(ABORT, 'card context source snapshots are immutable');
    END
    """,
    """
    CREATE TRIGGER card_context_source_snapshots_no_delete
    BEFORE DELETE ON card_context_source_snapshots
    BEGIN
        SELECT RAISE(ABORT, 'card context source snapshots are immutable and cannot be deleted');
    END
    """,
)


def _normalize_sql(statement: str) -> str:
    return " ".join(statement.split()).casefold()


def _schema_object(statement: str) -> tuple[str, str] | None:
    words = statement.split()
    if len(words) >= 3 and words[0:2] == ["CREATE", "TABLE"]:
        return "table", words[2]
    if len(words) >= 3 and words[0:2] == ["CREATE", "INDEX"]:
        return "index", words[2]
    if len(words) >= 3 and words[0:2] == ["CREATE", "TRIGGER"]:
        return "trigger", words[2]
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
        if _normalize_sql(str(row[0])) != expected_sql:
            raise RuntimeError(f"{object_type} definition changed: {name}")
