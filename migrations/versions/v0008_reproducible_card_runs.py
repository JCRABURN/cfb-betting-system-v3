"""Store immutable selection policies and reproducible card-run manifests."""

from __future__ import annotations

import sqlite3


VERSION = 8
NAME = "reproducible_card_runs"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"
_SHA256_CHECK = (
    "length({column}) = 64 AND lower({column}) NOT GLOB '*[^0-9a-f]*'"
)
_SHA1_CHECK = "length({column}) = 40 AND lower({column}) NOT GLOB '*[^0-9a-f]*'"

STATEMENTS = (
    f"""
    CREATE TABLE contest_selection_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_version TEXT NOT NULL UNIQUE
            CHECK (length(trim(policy_version)) > 0),
        market_book_count INTEGER NOT NULL CHECK (market_book_count >= 0),
        model_tie_side TEXT NOT NULL CHECK (model_tie_side IN ('home', 'away')),
        pickem_tiebreak_side TEXT NOT NULL
            CHECK (pickem_tiebreak_side IN ('home', 'away')),
        effective_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='effective_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    """
    CREATE TABLE contest_selection_policy_books (
        selection_policy_id INTEGER NOT NULL,
        priority INTEGER NOT NULL CHECK (priority > 0),
        book TEXT NOT NULL CHECK (
            length(trim(book)) > 0 AND lower(trim(book)) != 'consensus'
        ),
        PRIMARY KEY (selection_policy_id, priority),
        UNIQUE (selection_policy_id, book),
        FOREIGN KEY (selection_policy_id) REFERENCES contest_selection_policies(id)
    )
    """,
    f"""
    CREATE TABLE card_run_manifests (
        card_id INTEGER PRIMARY KEY,
        model_run_id INTEGER NOT NULL,
        selection_policy_id INTEGER NOT NULL,
        ranking_policy_id INTEGER NOT NULL,
        model_name TEXT NOT NULL CHECK (length(trim(model_name)) > 0),
        model_version TEXT NOT NULL CHECK (length(trim(model_version)) > 0),
        selection_policy_version TEXT NOT NULL
            CHECK (length(trim(selection_policy_version)) > 0),
        confidence_policy_version TEXT NOT NULL
            CHECK (length(trim(confidence_policy_version)) > 0),
        ranking_policy_version TEXT NOT NULL
            CHECK (length(trim(ranking_policy_version)) > 0),
        feature_schema_version TEXT NOT NULL
            CHECK (length(trim(feature_schema_version)) > 0),
        configuration_version TEXT NOT NULL
            CHECK (length(trim(configuration_version)) > 0),
        code_commit_sha TEXT NOT NULL
            CHECK ({_SHA1_CHECK.format(column='code_commit_sha')}),
        data_snapshot_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='data_snapshot_sha256')}),
        locked_line_snapshot_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='locked_line_snapshot_sha256')}),
        adjustment_history_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='adjustment_history_sha256')}),
        adjustment_count INTEGER NOT NULL CHECK (adjustment_count >= 0),
        generated_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='generated_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (model_run_id) REFERENCES model_runs(id),
        FOREIGN KEY (selection_policy_id) REFERENCES contest_selection_policies(id),
        FOREIGN KEY (ranking_policy_id) REFERENCES contest_ranking_policies(id)
    )
    """,
    """
    CREATE INDEX idx_card_run_manifests_model_run
    ON card_run_manifests (model_run_id, card_id)
    """,
    """
    CREATE TRIGGER contest_selection_policies_no_duplicate_insert
    BEFORE INSERT ON contest_selection_policies
    WHEN EXISTS (
        SELECT 1 FROM contest_selection_policies
        WHERE id = NEW.id OR policy_version = NEW.policy_version
    )
    BEGIN
        SELECT RAISE(ABORT, 'contest selection policies cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER contest_selection_policies_no_update
    BEFORE UPDATE ON contest_selection_policies
    BEGIN
        SELECT RAISE(ABORT, 'contest selection policies are immutable');
    END
    """,
    """
    CREATE TRIGGER contest_selection_policies_no_delete
    BEFORE DELETE ON contest_selection_policies
    BEGIN
        SELECT RAISE(ABORT, 'contest selection policies are immutable and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER contest_selection_policy_books_validate_insert
    BEFORE INSERT ON contest_selection_policy_books
    WHEN NOT EXISTS (
        SELECT 1 FROM contest_selection_policies
        WHERE id = NEW.selection_policy_id
          AND NEW.priority <= market_book_count
    ) OR EXISTS (
        SELECT 1 FROM card_run_manifests
        WHERE selection_policy_id = NEW.selection_policy_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'selection policy book order is invalid or frozen');
    END
    """,
    """
    CREATE TRIGGER contest_selection_policy_books_no_duplicate_insert
    BEFORE INSERT ON contest_selection_policy_books
    WHEN EXISTS (
        SELECT 1 FROM contest_selection_policy_books
        WHERE selection_policy_id = NEW.selection_policy_id
          AND (priority = NEW.priority OR book = NEW.book)
    )
    BEGIN
        SELECT RAISE(ABORT, 'contest selection policy books cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER contest_selection_policy_books_no_update
    BEFORE UPDATE ON contest_selection_policy_books
    BEGIN
        SELECT RAISE(ABORT, 'contest selection policy books are immutable');
    END
    """,
    """
    CREATE TRIGGER contest_selection_policy_books_no_delete
    BEFORE DELETE ON contest_selection_policy_books
    BEGIN
        SELECT RAISE(ABORT, 'contest selection policy books are immutable and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER card_run_manifests_validate_metadata
    BEFORE INSERT ON card_run_manifests
    WHEN NOT EXISTS (
        SELECT 1
        FROM contest_cards AS card
        JOIN model_runs AS run ON run.id = card.model_run_id
        JOIN contest_selection_policies AS selection_policy
          ON selection_policy.id = NEW.selection_policy_id
        JOIN contest_card_policy_assignments AS assignment
          ON assignment.card_id = card.id
        JOIN contest_ranking_policies AS ranking_policy
          ON ranking_policy.id = assignment.ranking_policy_id
        WHERE card.id = NEW.card_id
          AND card.model_run_id = NEW.model_run_id
          AND run.id = NEW.model_run_id
          AND selection_policy.id = NEW.selection_policy_id
          AND ranking_policy.id = NEW.ranking_policy_id
          AND assignment.ranking_policy_id = NEW.ranking_policy_id
          AND card.policy_version = selection_policy.policy_version
          AND NEW.model_name = run.model_name
          AND NEW.model_version = run.model_version
          AND NEW.selection_policy_version = selection_policy.policy_version
          AND NEW.confidence_policy_version = ranking_policy.confidence_policy_version
          AND NEW.ranking_policy_version = ranking_policy.ranking_policy_version
          AND NEW.feature_schema_version = run.feature_schema_version
          AND NEW.configuration_version = run.configuration_version
          AND NEW.code_commit_sha = run.code_commit_sha
          AND NEW.data_snapshot_sha256 = run.data_snapshot_sha256
          AND NEW.locked_line_snapshot_sha256 = card.locked_line_snapshot_sha256
          AND NEW.generated_at = card.generated_at
          AND NEW.provenance = card.provenance
          AND julianday(selection_policy.effective_at) <= julianday(card.generated_at)
          AND julianday(ranking_policy.effective_at) <= julianday(card.generated_at)
          AND (
              SELECT COUNT(*) FROM contest_selection_policy_books AS books
              WHERE books.selection_policy_id = selection_policy.id
          ) = selection_policy.market_book_count
          AND NEW.adjustment_count = (
              SELECT COUNT(*)
              FROM manual_adjustments AS adjustment
              JOIN contest_picks AS pick
                ON pick.model_prediction_id = adjustment.model_prediction_id
              WHERE pick.card_id = card.id
                AND julianday(adjustment.recorded_at) <= julianday(card.generated_at)
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'card run manifest metadata is inconsistent');
    END
    """,
    """
    CREATE TRIGGER card_run_manifests_no_duplicate_insert
    BEFORE INSERT ON card_run_manifests
    WHEN EXISTS (SELECT 1 FROM card_run_manifests WHERE card_id = NEW.card_id)
    BEGIN
        SELECT RAISE(ABORT, 'card run manifests cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER card_run_manifests_no_update
    BEFORE UPDATE ON card_run_manifests
    BEGIN
        SELECT RAISE(ABORT, 'card run manifests are immutable');
    END
    """,
    """
    CREATE TRIGGER card_run_manifests_no_delete
    BEFORE DELETE ON card_run_manifests
    BEGIN
        SELECT RAISE(ABORT, 'card run manifests are immutable and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER manual_adjustments_validate_reproducibility_time
    BEFORE INSERT ON manual_adjustments
    WHEN NOT EXISTS (
        SELECT 1 FROM model_predictions
        WHERE id = NEW.model_prediction_id
          AND julianday(generated_at) <= julianday(NEW.recorded_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'manual adjustments cannot predate their prediction');
    END
    """,
    """
    CREATE TRIGGER manual_adjustments_protect_frozen_history
    BEFORE INSERT ON manual_adjustments
    WHEN EXISTS (
        SELECT 1
        FROM card_run_manifests AS manifest
        JOIN contest_picks AS pick ON pick.card_id = manifest.card_id
        WHERE pick.model_prediction_id = NEW.model_prediction_id
          AND julianday(NEW.recorded_at) <= julianday(manifest.generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'manual adjustment would rewrite frozen card history');
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
