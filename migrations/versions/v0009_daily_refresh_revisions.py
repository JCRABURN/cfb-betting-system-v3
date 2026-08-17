"""Add versioned daily refresh policy and complete card revision history."""

from __future__ import annotations

import sqlite3


VERSION = 9
NAME = "daily_refresh_revisions"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"

STATEMENTS = (
    f"""
    CREATE TABLE card_refresh_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_version TEXT NOT NULL UNIQUE
            CHECK (length(trim(policy_version)) > 0),
        timezone_name TEXT NOT NULL CHECK (timezone_name = 'UTC'),
        allowed_weekday_mask INTEGER NOT NULL CHECK (allowed_weekday_mask = 62),
        effective_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='effective_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    """
    CREATE TABLE card_revision_pick_changes (
        revision_id INTEGER NOT NULL,
        locked_line_id INTEGER NOT NULL,
        prior_pick_id INTEGER NOT NULL,
        revised_pick_id INTEGER NOT NULL,
        prior_model_prediction_id INTEGER,
        revised_model_prediction_id INTEGER,
        prior_selected_side TEXT NOT NULL CHECK (prior_selected_side IN ('home', 'away')),
        revised_selected_side TEXT NOT NULL CHECK (revised_selected_side IN ('home', 'away')),
        prior_confidence INTEGER NOT NULL CHECK (prior_confidence BETWEEN 1 AND 5),
        revised_confidence INTEGER NOT NULL CHECK (revised_confidence BETWEEN 1 AND 5),
        prior_rank INTEGER CHECK (prior_rank IS NULL OR prior_rank BETWEEN 1 AND 5),
        revised_rank INTEGER CHECK (revised_rank IS NULL OR revised_rank BETWEEN 1 AND 5),
        prior_is_top_five INTEGER NOT NULL CHECK (prior_is_top_five IN (0, 1)),
        revised_is_top_five INTEGER NOT NULL CHECK (revised_is_top_five IN (0, 1)),
        prior_fallback_code TEXT,
        revised_fallback_code TEXT,
        side_changed INTEGER NOT NULL CHECK (side_changed IN (0, 1)),
        confidence_changed INTEGER NOT NULL CHECK (confidence_changed IN (0, 1)),
        rank_changed INTEGER NOT NULL CHECK (rank_changed IN (0, 1)),
        top_five_changed INTEGER NOT NULL CHECK (top_five_changed IN (0, 1)),
        model_prediction_changed INTEGER NOT NULL
            CHECK (model_prediction_changed IN (0, 1)),
        fallback_changed INTEGER NOT NULL CHECK (fallback_changed IN (0, 1)),
        PRIMARY KEY (revision_id, locked_line_id),
        UNIQUE (revision_id, prior_pick_id),
        UNIQUE (revision_id, revised_pick_id),
        FOREIGN KEY (revision_id) REFERENCES card_revisions(id),
        FOREIGN KEY (locked_line_id) REFERENCES contest_locked_lines(id),
        FOREIGN KEY (prior_pick_id) REFERENCES contest_picks(id),
        FOREIGN KEY (revised_pick_id) REFERENCES contest_picks(id),
        FOREIGN KEY (prior_model_prediction_id) REFERENCES model_predictions(id),
        FOREIGN KEY (revised_model_prediction_id) REFERENCES model_predictions(id)
    )
    """,
    f"""
    CREATE TABLE card_refresh_revisions (
        revision_id INTEGER PRIMARY KEY,
        refresh_policy_id INTEGER NOT NULL,
        operating_date TEXT NOT NULL CHECK (
            length(operating_date) = 10 AND date(operating_date) IS NOT NULL
        ),
        operating_weekday INTEGER NOT NULL CHECK (operating_weekday BETWEEN 2 AND 6),
        timezone_name TEXT NOT NULL CHECK (timezone_name = 'UTC'),
        refreshed_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='refreshed_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (revision_id) REFERENCES card_revisions(id),
        FOREIGN KEY (refresh_policy_id) REFERENCES card_refresh_policies(id)
    )
    """,
    """
    CREATE INDEX idx_card_revision_pick_changes_line
    ON card_revision_pick_changes (locked_line_id, revision_id)
    """,
    """
    CREATE INDEX idx_card_refresh_revisions_policy
    ON card_refresh_revisions (refresh_policy_id, refreshed_at)
    """,
    """
    CREATE TRIGGER card_revisions_validate_locked_snapshot
    BEFORE INSERT ON card_revisions
    WHEN EXISTS (
        SELECT 1
        FROM contest_cards AS prior
        JOIN contest_cards AS revised ON revised.id = NEW.revised_card_id
        WHERE prior.id = NEW.prior_card_id
          AND prior.locked_line_snapshot_sha256 != revised.locked_line_snapshot_sha256
          AND (
              NEW.change_type != 'data_correction'
              OR NOT EXISTS (
                  SELECT 1
                  FROM contest_line_corrections AS correction
                  JOIN contest_locked_lines AS locked
                    ON locked.id = correction.locked_line_id
                  WHERE locked.contest_id = prior.contest_id
                    AND julianday(correction.corrected_at) > julianday(prior.generated_at)
                    AND julianday(correction.corrected_at) <= julianday(revised.generated_at)
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'card revision cannot replace the locked-line snapshot');
    END
    """,
    """
    CREATE TRIGGER card_refresh_policies_no_duplicate_insert
    BEFORE INSERT ON card_refresh_policies
    WHEN EXISTS (
        SELECT 1 FROM card_refresh_policies
        WHERE id = NEW.id OR policy_version = NEW.policy_version
    )
    BEGIN
        SELECT RAISE(ABORT, 'card refresh policies cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER card_refresh_policies_no_update
    BEFORE UPDATE ON card_refresh_policies
    BEGIN
        SELECT RAISE(ABORT, 'card refresh policies are immutable');
    END
    """,
    """
    CREATE TRIGGER card_refresh_policies_no_delete
    BEFORE DELETE ON card_refresh_policies
    BEGIN
        SELECT RAISE(ABORT, 'card refresh policies are immutable and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER card_revision_pick_changes_validate_values
    BEFORE INSERT ON card_revision_pick_changes
    WHEN NOT EXISTS (
        SELECT 1
        FROM card_revisions AS revision
        JOIN contest_picks AS prior_pick
          ON prior_pick.card_id = revision.prior_card_id
        JOIN contest_picks AS revised_pick
          ON revised_pick.card_id = revision.revised_card_id
        WHERE revision.id = NEW.revision_id
          AND prior_pick.id = NEW.prior_pick_id
          AND revised_pick.id = NEW.revised_pick_id
          AND prior_pick.locked_line_id = NEW.locked_line_id
          AND revised_pick.locked_line_id = NEW.locked_line_id
          AND NEW.prior_model_prediction_id IS prior_pick.model_prediction_id
          AND NEW.revised_model_prediction_id IS revised_pick.model_prediction_id
          AND NEW.prior_selected_side = prior_pick.selected_side
          AND NEW.revised_selected_side = revised_pick.selected_side
          AND NEW.prior_confidence = prior_pick.confidence
          AND NEW.revised_confidence = revised_pick.confidence
          AND NEW.prior_rank IS prior_pick.rank
          AND NEW.revised_rank IS revised_pick.rank
          AND NEW.prior_is_top_five = prior_pick.is_top_five
          AND NEW.revised_is_top_five = revised_pick.is_top_five
          AND NEW.prior_fallback_code IS prior_pick.fallback_code
          AND NEW.revised_fallback_code IS revised_pick.fallback_code
          AND NEW.side_changed = CASE
              WHEN prior_pick.selected_side != revised_pick.selected_side THEN 1 ELSE 0 END
          AND NEW.confidence_changed = CASE
              WHEN prior_pick.confidence != revised_pick.confidence THEN 1 ELSE 0 END
          AND NEW.rank_changed = CASE
              WHEN prior_pick.rank IS NOT revised_pick.rank THEN 1 ELSE 0 END
          AND NEW.top_five_changed = CASE
              WHEN prior_pick.is_top_five != revised_pick.is_top_five THEN 1 ELSE 0 END
          AND NEW.model_prediction_changed = CASE
              WHEN prior_pick.model_prediction_id IS NOT revised_pick.model_prediction_id
              THEN 1 ELSE 0 END
          AND NEW.fallback_changed = CASE
              WHEN prior_pick.fallback_code IS NOT revised_pick.fallback_code THEN 1 ELSE 0 END
    )
    BEGIN
        SELECT RAISE(ABORT, 'card revision pick values do not match both snapshots');
    END
    """,
    """
    CREATE TRIGGER card_revision_pick_changes_no_duplicate_insert
    BEFORE INSERT ON card_revision_pick_changes
    WHEN EXISTS (
        SELECT 1 FROM card_revision_pick_changes
        WHERE revision_id = NEW.revision_id
          AND (
              locked_line_id = NEW.locked_line_id
              OR prior_pick_id = NEW.prior_pick_id
              OR revised_pick_id = NEW.revised_pick_id
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'card revision pick changes cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER card_revision_pick_changes_no_update
    BEFORE UPDATE ON card_revision_pick_changes
    BEGIN
        SELECT RAISE(ABORT, 'card revision pick changes are immutable');
    END
    """,
    """
    CREATE TRIGGER card_revision_pick_changes_no_delete
    BEFORE DELETE ON card_revision_pick_changes
    BEGIN
        SELECT RAISE(ABORT, 'card revision pick changes are immutable and cannot be deleted');
    END
    """,
    """
    CREATE TRIGGER card_refresh_revisions_validate_history
    BEFORE INSERT ON card_refresh_revisions
    WHEN NOT EXISTS (
        SELECT 1
        FROM card_revisions AS revision
        JOIN contest_cards AS prior ON prior.id = revision.prior_card_id
        JOIN contest_cards AS revised ON revised.id = revision.revised_card_id
        JOIN card_run_manifests AS prior_manifest
          ON prior_manifest.card_id = prior.id
        JOIN card_run_manifests AS revised_manifest
          ON revised_manifest.card_id = revised.id
        JOIN card_refresh_policies AS policy
          ON policy.id = NEW.refresh_policy_id
        WHERE revision.id = NEW.revision_id
          AND NEW.refreshed_at = revision.revised_at
          AND NEW.refreshed_at = revised.generated_at
          AND julianday(revised.generated_at) > julianday(prior.generated_at)
          AND NEW.timezone_name = policy.timezone_name
          AND NEW.timezone_name = 'UTC'
          AND policy.allowed_weekday_mask = 62
          AND julianday(policy.effective_at) <= julianday(prior.generated_at)
          AND NEW.operating_date = date(NEW.refreshed_at)
          AND NEW.operating_weekday =
              CAST(strftime('%w', NEW.refreshed_at) AS INTEGER)
          AND NEW.operating_weekday BETWEEN 2 AND 6
          AND prior_manifest.selection_policy_id = revised_manifest.selection_policy_id
          AND prior_manifest.ranking_policy_id = revised_manifest.ranking_policy_id
          AND (
              revision.change_type != 'data_refresh'
              OR (
                  prior_manifest.adjustment_history_sha256 =
                      revised_manifest.adjustment_history_sha256
                  AND prior_manifest.model_name = revised_manifest.model_name
                  AND prior_manifest.model_version = revised_manifest.model_version
                  AND prior_manifest.feature_schema_version =
                      revised_manifest.feature_schema_version
                  AND prior_manifest.configuration_version =
                      revised_manifest.configuration_version
                  AND prior_manifest.code_commit_sha = revised_manifest.code_commit_sha
              )
          )
          AND (
              revision.change_type != 'contextual_adjustment'
              OR (
                  prior_manifest.model_run_id = revised_manifest.model_run_id
                  AND prior_manifest.adjustment_history_sha256 !=
                      revised_manifest.adjustment_history_sha256
              )
          )
          AND (
              SELECT COUNT(*) FROM card_revision_pick_changes AS changes
              WHERE changes.revision_id = revision.id
          ) = (
              SELECT COUNT(*) FROM contest_picks WHERE card_id = prior.id
          )
          AND (
              SELECT COUNT(*) FROM card_revision_pick_changes AS changes
              WHERE changes.revision_id = revision.id
          ) = (
              SELECT COUNT(*) FROM contest_picks WHERE card_id = revised.id
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'card refresh history is incomplete or mixes change sources');
    END
    """,
    """
    CREATE TRIGGER card_refresh_revisions_no_duplicate_insert
    BEFORE INSERT ON card_refresh_revisions
    WHEN EXISTS (
        SELECT 1 FROM card_refresh_revisions WHERE revision_id = NEW.revision_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'card refresh revisions cannot be replaced');
    END
    """,
    """
    CREATE TRIGGER card_refresh_revisions_no_update
    BEFORE UPDATE ON card_refresh_revisions
    BEGIN
        SELECT RAISE(ABORT, 'card refresh revisions are immutable');
    END
    """,
    """
    CREATE TRIGGER card_refresh_revisions_no_delete
    BEFORE DELETE ON card_refresh_revisions
    BEGIN
        SELECT RAISE(ABORT, 'card refresh revisions are immutable and cannot be deleted');
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
