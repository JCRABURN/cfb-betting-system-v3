"""Add versioned contextual-adjustment application and frozen card outputs."""

from __future__ import annotations

import sqlite3


VERSION = 10
NAME = "manual_contextual_adjustments"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"
_SHA256_CHECK = (
    "length({column}) = 64 AND lower({column}) NOT GLOB '*[^0-9a-f]*'"
)

STATEMENTS = (
    f"""
    CREATE TABLE manual_adjustment_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_version TEXT NOT NULL UNIQUE
            CHECK (length(trim(policy_version)) > 0),
        margin_method TEXT NOT NULL
            CHECK (margin_method = 'additive_home_margin'),
        confidence_method TEXT NOT NULL
            CHECK (confidence_method = 'additive_clamped_1_5'),
        confidence_min INTEGER NOT NULL CHECK (confidence_min = 1),
        confidence_max INTEGER NOT NULL CHECK (confidence_max = 5),
        effective_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='effective_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    f"""
    CREATE TABLE card_adjustment_policy_assignments (
        card_id INTEGER PRIMARY KEY,
        adjustment_policy_id INTEGER NOT NULL,
        assigned_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='assigned_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (adjustment_policy_id) REFERENCES manual_adjustment_policies(id)
    )
    """,
    """
    CREATE TABLE contest_pick_adjustment_items (
        contest_pick_id INTEGER NOT NULL,
        adjustment_id INTEGER NOT NULL,
        history_order INTEGER NOT NULL CHECK (history_order > 0),
        PRIMARY KEY (contest_pick_id, adjustment_id),
        UNIQUE (contest_pick_id, history_order),
        FOREIGN KEY (contest_pick_id) REFERENCES contest_picks(id),
        FOREIGN KEY (adjustment_id) REFERENCES manual_adjustments(id)
    )
    """,
    f"""
    CREATE TABLE contest_pick_adjustment_snapshots (
        contest_pick_id INTEGER PRIMARY KEY,
        adjustment_policy_id INTEGER NOT NULL,
        model_prediction_id INTEGER NOT NULL,
        raw_model_margin REAL NOT NULL
            CHECK (typeof(raw_model_margin) IN ('integer', 'real')),
        margin_adjustment_total REAL NOT NULL
            CHECK (typeof(margin_adjustment_total) IN ('integer', 'real')),
        adjusted_model_margin REAL NOT NULL
            CHECK (typeof(adjusted_model_margin) IN ('integer', 'real')),
        raw_confidence INTEGER NOT NULL CHECK (raw_confidence BETWEEN 1 AND 5),
        confidence_adjustment_total INTEGER NOT NULL,
        adjusted_confidence INTEGER NOT NULL
            CHECK (adjusted_confidence BETWEEN 1 AND 5),
        adjustment_count INTEGER NOT NULL CHECK (adjustment_count >= 0),
        adjustment_history_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='adjustment_history_sha256')}),
        generated_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='generated_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            abs(adjusted_model_margin - (raw_model_margin + margin_adjustment_total))
                < 0.000000001
        ),
        FOREIGN KEY (contest_pick_id) REFERENCES contest_picks(id),
        FOREIGN KEY (adjustment_policy_id) REFERENCES manual_adjustment_policies(id),
        FOREIGN KEY (model_prediction_id) REFERENCES model_predictions(id)
    )
    """,
    """
    CREATE INDEX idx_pick_adjustment_items_adjustment
    ON contest_pick_adjustment_items (adjustment_id, contest_pick_id)
    """,
    """
    CREATE INDEX idx_pick_adjustment_snapshots_policy
    ON contest_pick_adjustment_snapshots (adjustment_policy_id, contest_pick_id)
    """,
    """
    CREATE TRIGGER manual_adjustment_policies_no_duplicate_insert
    BEFORE INSERT ON manual_adjustment_policies
    WHEN EXISTS (
        SELECT 1 FROM manual_adjustment_policies
        WHERE id = NEW.id OR policy_version = NEW.policy_version
    )
    BEGIN
        SELECT RAISE(ABORT, 'manual adjustment policies cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER manual_adjustment_policies_no_update
    BEFORE UPDATE ON manual_adjustment_policies
    BEGIN
        SELECT RAISE(ABORT, 'manual adjustment policies are immutable');
    END
    """,
    """
    CREATE TRIGGER manual_adjustment_policies_no_delete
    BEFORE DELETE ON manual_adjustment_policies
    BEGIN
        SELECT RAISE(ABORT, 'manual adjustment policies are immutable and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER card_adjustment_policy_assignments_validate
    BEFORE INSERT ON card_adjustment_policy_assignments
    WHEN NOT EXISTS (
        SELECT 1
        FROM contest_cards AS card
        JOIN manual_adjustment_policies AS policy
          ON policy.id = NEW.adjustment_policy_id
        WHERE card.id = NEW.card_id
          AND NEW.assigned_at = card.generated_at
          AND julianday(policy.effective_at) <= julianday(card.generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'card adjustment policy must be effective at generation');
    END
    """,
    """
    CREATE TRIGGER card_adjustment_policy_assignments_no_duplicate_insert
    BEFORE INSERT ON card_adjustment_policy_assignments
    WHEN EXISTS (
        SELECT 1 FROM card_adjustment_policy_assignments WHERE card_id = NEW.card_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'card adjustment policy assignments cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER card_adjustment_policy_assignments_no_update
    BEFORE UPDATE ON card_adjustment_policy_assignments
    BEGIN
        SELECT RAISE(ABORT, 'card adjustment policy assignments are immutable');
    END
    """,
    """
    CREATE TRIGGER card_adjustment_policy_assignments_no_delete
    BEFORE DELETE ON card_adjustment_policy_assignments
    BEGIN
        SELECT RAISE(ABORT, 'card adjustment policy assignments are immutable and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER contest_pick_adjustment_items_validate
    BEFORE INSERT ON contest_pick_adjustment_items
    WHEN EXISTS (
        SELECT 1 FROM contest_pick_adjustment_snapshots
        WHERE contest_pick_id = NEW.contest_pick_id
    )
    OR NOT EXISTS (
        SELECT 1
        FROM contest_picks AS pick
        JOIN contest_cards AS card ON card.id = pick.card_id
        JOIN model_predictions AS prediction
          ON prediction.id = pick.model_prediction_id
        JOIN manual_adjustments AS adjustment
          ON adjustment.model_prediction_id = prediction.id
        JOIN card_adjustment_policy_assignments AS assignment
          ON assignment.card_id = card.id
        WHERE pick.id = NEW.contest_pick_id
          AND adjustment.id = NEW.adjustment_id
          AND NEW.history_order = adjustment.sequence
          AND julianday(adjustment.recorded_at) <= julianday(pick.generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'pick adjustment item is invalid or snapshot is frozen');
    END
    """,
    """
    CREATE TRIGGER contest_pick_adjustment_items_no_duplicate_insert
    BEFORE INSERT ON contest_pick_adjustment_items
    WHEN EXISTS (
        SELECT 1 FROM contest_pick_adjustment_items
        WHERE contest_pick_id = NEW.contest_pick_id
          AND (adjustment_id = NEW.adjustment_id OR history_order = NEW.history_order)
    )
    BEGIN
        SELECT RAISE(ABORT, 'pick adjustment items cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER contest_pick_adjustment_items_no_update
    BEFORE UPDATE ON contest_pick_adjustment_items
    BEGIN
        SELECT RAISE(ABORT, 'pick adjustment items are immutable');
    END
    """,
    """
    CREATE TRIGGER contest_pick_adjustment_items_no_delete
    BEFORE DELETE ON contest_pick_adjustment_items
    BEGIN
        SELECT RAISE(ABORT, 'pick adjustment items are immutable and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER contest_pick_adjustment_snapshots_validate
    BEFORE INSERT ON contest_pick_adjustment_snapshots
    WHEN NOT EXISTS (
        SELECT 1
        FROM contest_picks AS pick
        JOIN contest_cards AS card ON card.id = pick.card_id
        JOIN model_predictions AS prediction
          ON prediction.id = pick.model_prediction_id
        JOIN card_adjustment_policy_assignments AS assignment
          ON assignment.card_id = card.id
        JOIN manual_adjustment_policies AS policy
          ON policy.id = assignment.adjustment_policy_id
        WHERE pick.id = NEW.contest_pick_id
          AND NEW.adjustment_policy_id = policy.id
          AND NEW.model_prediction_id = prediction.id
          AND NEW.raw_model_margin = prediction.predicted_home_margin
          AND NEW.generated_at = pick.generated_at
          AND NEW.generated_at = card.generated_at
          AND NEW.adjusted_confidence = pick.confidence
          AND NEW.adjustment_count = (
              SELECT COUNT(*) FROM contest_pick_adjustment_items AS item
              WHERE item.contest_pick_id = pick.id
          )
          AND NEW.adjustment_count = (
              SELECT COUNT(*) FROM manual_adjustments AS adjustment
              WHERE adjustment.model_prediction_id = prediction.id
                AND julianday(adjustment.recorded_at)
                    <= julianday(pick.generated_at)
          )
          AND NEW.margin_adjustment_total = COALESCE((
              SELECT SUM(adjustment.margin_adjustment)
              FROM contest_pick_adjustment_items AS item
              JOIN manual_adjustments AS adjustment
                ON adjustment.id = item.adjustment_id
              WHERE item.contest_pick_id = pick.id
          ), 0)
          AND NEW.confidence_adjustment_total = COALESCE((
              SELECT SUM(adjustment.confidence_adjustment)
              FROM contest_pick_adjustment_items AS item
              JOIN manual_adjustments AS adjustment
                ON adjustment.id = item.adjustment_id
              WHERE item.contest_pick_id = pick.id
          ), 0)
          AND NEW.adjusted_confidence = CASE
              WHEN NEW.raw_confidence + NEW.confidence_adjustment_total < 1 THEN 1
              WHEN NEW.raw_confidence + NEW.confidence_adjustment_total > 5 THEN 5
              ELSE NEW.raw_confidence + NEW.confidence_adjustment_total
          END
    )
    BEGIN
        SELECT RAISE(ABORT, 'pick adjustment snapshot does not match frozen inputs');
    END
    """,
    """
    CREATE TRIGGER contest_pick_adjustment_snapshots_no_duplicate_insert
    BEFORE INSERT ON contest_pick_adjustment_snapshots
    WHEN EXISTS (
        SELECT 1 FROM contest_pick_adjustment_snapshots
        WHERE contest_pick_id = NEW.contest_pick_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'pick adjustment snapshots cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER contest_pick_adjustment_snapshots_no_update
    BEFORE UPDATE ON contest_pick_adjustment_snapshots
    BEGIN
        SELECT RAISE(ABORT, 'pick adjustment snapshots are immutable');
    END
    """,
    """
    CREATE TRIGGER contest_pick_adjustment_snapshots_no_delete
    BEFORE DELETE ON contest_pick_adjustment_snapshots
    BEGIN
        SELECT RAISE(ABORT, 'pick adjustment snapshots are immutable and cannot be deleted');
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
