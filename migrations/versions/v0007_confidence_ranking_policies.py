"""Store immutable Confidence and Top 5 policy definitions and assignments."""

from __future__ import annotations

import sqlite3


VERSION = 7
NAME = "confidence_ranking_policies"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"

STATEMENTS = (
    f"""
    CREATE TABLE contest_ranking_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_key TEXT NOT NULL UNIQUE CHECK (length(trim(policy_key)) > 0),
        confidence_policy_version TEXT NOT NULL
            CHECK (length(trim(confidence_policy_version)) > 0),
        ranking_policy_version TEXT NOT NULL
            CHECK (length(trim(ranking_policy_version)) > 0),
        confidence_5_max_uncertainty REAL NOT NULL CHECK (
            typeof(confidence_5_max_uncertainty) IN ('integer', 'real')
            AND confidence_5_max_uncertainty >= 0
        ),
        confidence_4_max_uncertainty REAL NOT NULL CHECK (
            typeof(confidence_4_max_uncertainty) IN ('integer', 'real')
            AND confidence_4_max_uncertainty >= 0
        ),
        confidence_3_max_uncertainty REAL NOT NULL CHECK (
            typeof(confidence_3_max_uncertainty) IN ('integer', 'real')
            AND confidence_3_max_uncertainty >= 0
        ),
        confidence_2_max_uncertainty REAL NOT NULL CHECK (
            typeof(confidence_2_max_uncertainty) IN ('integer', 'real')
            AND confidence_2_max_uncertainty >= 0
        ),
        unscored_confidence INTEGER NOT NULL CHECK (unscored_confidence = 1),
        top_five_count INTEGER NOT NULL CHECK (top_five_count = 5),
        reliability_metric TEXT NOT NULL
            CHECK (reliability_metric = 'model_uncertainty_points'),
        ranking_method TEXT NOT NULL CHECK (
            ranking_method = 'confidence_desc_uncertainty_asc'
        ),
        tie_breaker TEXT NOT NULL CHECK (tie_breaker = 'locked_line_id_asc'),
        effective_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='effective_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            confidence_5_max_uncertainty < confidence_4_max_uncertainty
            AND confidence_4_max_uncertainty < confidence_3_max_uncertainty
            AND confidence_3_max_uncertainty < confidence_2_max_uncertainty
        ),
        UNIQUE (confidence_policy_version, ranking_policy_version)
    )
    """,
    f"""
    CREATE TABLE contest_card_policy_assignments (
        card_id INTEGER PRIMARY KEY,
        ranking_policy_id INTEGER NOT NULL,
        assigned_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='assigned_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (ranking_policy_id) REFERENCES contest_ranking_policies(id)
    )
    """,
    """
    CREATE INDEX idx_contest_card_policy_assignments_policy
    ON contest_card_policy_assignments (ranking_policy_id, card_id)
    """,
    """
    CREATE TRIGGER contest_cards_block_unvalidated_official_insert
    BEFORE INSERT ON contest_cards
    WHEN NEW.status = 'official'
    BEGIN
        SELECT RAISE(ABORT, 'official cards require validated publication');
    END
    """,
    """
    CREATE TRIGGER contest_card_policy_assignments_validate_timing
    BEFORE INSERT ON contest_card_policy_assignments
    WHEN NOT EXISTS (
        SELECT 1
        FROM contest_cards AS card
        JOIN contest_ranking_policies AS policy
          ON policy.id = NEW.ranking_policy_id
        WHERE card.id = NEW.card_id
          AND NEW.assigned_at = card.generated_at
          AND julianday(policy.effective_at) <= julianday(card.generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'card ranking policy must be effective at generation');
    END
    """,
    """
    CREATE TRIGGER contest_ranking_policies_no_duplicate_insert
    BEFORE INSERT ON contest_ranking_policies
    WHEN EXISTS (
        SELECT 1 FROM contest_ranking_policies
        WHERE id = NEW.id
           OR policy_key = NEW.policy_key
           OR (
               confidence_policy_version = NEW.confidence_policy_version
               AND ranking_policy_version = NEW.ranking_policy_version
           )
    )
    BEGIN
        SELECT RAISE(ABORT, 'contest ranking policies cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER contest_ranking_policies_no_update
    BEFORE UPDATE ON contest_ranking_policies
    BEGIN
        SELECT RAISE(ABORT, 'contest ranking policies are immutable');
    END
    """,
    """
    CREATE TRIGGER contest_ranking_policies_no_delete
    BEFORE DELETE ON contest_ranking_policies
    BEGIN
        SELECT RAISE(ABORT, 'contest ranking policies are immutable and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER contest_card_policy_assignments_no_duplicate_insert
    BEFORE INSERT ON contest_card_policy_assignments
    WHEN EXISTS (
        SELECT 1 FROM contest_card_policy_assignments
        WHERE card_id = NEW.card_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'contest card policy assignments cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER contest_card_policy_assignments_no_update
    BEFORE UPDATE ON contest_card_policy_assignments
    BEGIN
        SELECT RAISE(ABORT, 'contest card policy assignments are immutable');
    END
    """,
    """
    CREATE TRIGGER contest_card_policy_assignments_no_delete
    BEFORE DELETE ON contest_card_policy_assignments
    BEGIN
        SELECT RAISE(ABORT, 'contest card policy assignments are immutable and cannot be deleted');
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
