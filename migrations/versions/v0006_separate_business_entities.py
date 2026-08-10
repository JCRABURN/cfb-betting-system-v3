"""Separate forecasts, contest selections, wagering advice, and audit history."""

from __future__ import annotations

import sqlite3


VERSION = 6
NAME = "separate_business_entities"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"
_SHA256_CHECK = (
    "length({column}) = 64 AND lower({column}) NOT GLOB '*[^0-9a-f]*'"
)
_SHA1_CHECK = "length({column}) = 40 AND lower({column}) NOT GLOB '*[^0-9a-f]*'"

STATEMENTS = (
    f"""
    CREATE TABLE model_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_key TEXT NOT NULL UNIQUE CHECK (length(trim(run_key)) > 0),
        model_name TEXT NOT NULL CHECK (length(trim(model_name)) > 0),
        model_version TEXT NOT NULL CHECK (length(trim(model_version)) > 0),
        feature_schema_version TEXT NOT NULL
            CHECK (length(trim(feature_schema_version)) > 0),
        configuration_version TEXT NOT NULL
            CHECK (length(trim(configuration_version)) > 0),
        code_commit_sha TEXT NOT NULL CHECK ({_SHA1_CHECK.format(column='code_commit_sha')}),
        data_snapshot_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='data_snapshot_sha256')}),
        status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
        failure_reason TEXT CHECK (
            (status = 'completed' AND failure_reason IS NULL)
            OR (status = 'failed' AND length(trim(failure_reason)) > 0)
        ),
        generated_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='generated_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    f"""
    CREATE TABLE model_predictions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        prediction_key TEXT NOT NULL UNIQUE CHECK (length(trim(prediction_key)) > 0),
        model_run_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        predicted_home_margin REAL NOT NULL
            CHECK (typeof(predicted_home_margin) IN ('integer', 'real')),
        home_win_probability REAL CHECK (
            home_win_probability IS NULL
            OR (typeof(home_win_probability) IN ('integer', 'real')
                AND home_win_probability BETWEEN 0 AND 1)
        ),
        uncertainty_points REAL CHECK (
            uncertainty_points IS NULL
            OR (typeof(uncertainty_points) IN ('integer', 'real')
                AND uncertainty_points >= 0)
        ),
        entry_market_line_id INTEGER,
        entry_locked_line_id INTEGER,
        generated_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='generated_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (entry_market_line_id IS NULL OR entry_locked_line_id IS NULL),
        UNIQUE (model_run_id, game_id),
        FOREIGN KEY (model_run_id) REFERENCES model_runs(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id),
        FOREIGN KEY (entry_market_line_id) REFERENCES betting_lines(id),
        FOREIGN KEY (entry_locked_line_id) REFERENCES contest_locked_lines(id)
    )
    """,
    f"""
    CREATE TABLE contest_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_key TEXT NOT NULL UNIQUE CHECK (length(trim(card_key)) > 0),
        contest_id INTEGER NOT NULL,
        model_run_id INTEGER,
        version INTEGER NOT NULL CHECK (version > 0),
        status TEXT NOT NULL CHECK (status IN ('draft', 'official')),
        policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) > 0),
        locked_line_snapshot_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='locked_line_snapshot_sha256')}),
        generated_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='generated_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (contest_id, version),
        FOREIGN KEY (contest_id) REFERENCES contests(id),
        FOREIGN KEY (model_run_id) REFERENCES model_runs(id)
    )
    """,
    f"""
    CREATE TABLE contest_picks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pick_key TEXT NOT NULL UNIQUE CHECK (length(trim(pick_key)) > 0),
        card_id INTEGER NOT NULL,
        locked_line_id INTEGER NOT NULL,
        model_prediction_id INTEGER,
        selected_side TEXT NOT NULL CHECK (selected_side IN ('home', 'away', 'pass')),
        confidence INTEGER CHECK (confidence IS NULL OR confidence BETWEEN 1 AND 5),
        rank INTEGER CHECK (rank IS NULL OR rank > 0),
        is_top_five INTEGER NOT NULL DEFAULT 0 CHECK (is_top_five IN (0, 1)),
        fallback_code TEXT CHECK (fallback_code IS NULL OR length(trim(fallback_code)) > 0),
        generated_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='generated_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (selected_side != 'pass' OR (confidence IS NULL AND rank IS NULL AND is_top_five = 0)),
        UNIQUE (card_id, locked_line_id),
        FOREIGN KEY (card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (locked_line_id) REFERENCES contest_locked_lines(id),
        FOREIGN KEY (model_prediction_id) REFERENCES model_predictions(id)
    )
    """,
    f"""
    CREATE TABLE sportsbook_recommendations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recommendation_key TEXT NOT NULL UNIQUE
            CHECK (length(trim(recommendation_key)) > 0),
        model_prediction_id INTEGER NOT NULL,
        contest_pick_id INTEGER,
        market_line_id INTEGER,
        decision TEXT NOT NULL CHECK (decision IN ('bet', 'no_bet')),
        recommended_side TEXT CHECK (recommended_side IN ('home', 'away')),
        offered_price INTEGER,
        expected_value REAL CHECK (
            expected_value IS NULL OR typeof(expected_value) IN ('integer', 'real')
        ),
        stake_units REAL NOT NULL CHECK (
            typeof(stake_units) IN ('integer', 'real') AND stake_units >= 0
        ),
        policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) > 0),
        reason_code TEXT NOT NULL CHECK (length(trim(reason_code)) > 0),
        generated_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='generated_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            (decision = 'bet' AND recommended_side IS NOT NULL
             AND market_line_id IS NOT NULL AND offered_price IS NOT NULL
             AND expected_value IS NOT NULL AND stake_units > 0)
            OR
            (decision = 'no_bet' AND recommended_side IS NULL
             AND market_line_id IS NULL AND offered_price IS NULL
             AND expected_value IS NULL AND stake_units = 0)
        ),
        FOREIGN KEY (model_prediction_id) REFERENCES model_predictions(id),
        FOREIGN KEY (contest_pick_id) REFERENCES contest_picks(id),
        FOREIGN KEY (market_line_id) REFERENCES betting_lines(id)
    )
    """,
    f"""
    CREATE TABLE card_revisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        revision_key TEXT NOT NULL UNIQUE CHECK (length(trim(revision_key)) > 0),
        prior_card_id INTEGER NOT NULL,
        revised_card_id INTEGER NOT NULL UNIQUE,
        change_type TEXT NOT NULL CHECK (
            change_type IN ('data_refresh', 'contextual_adjustment', 'bug_fix', 'data_correction')
        ),
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        author TEXT NOT NULL CHECK (length(trim(author)) > 0),
        revised_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='revised_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (prior_card_id != revised_card_id),
        FOREIGN KEY (prior_card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (revised_card_id) REFERENCES contest_cards(id)
    )
    """,
    f"""
    CREATE TABLE manual_adjustments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        adjustment_key TEXT NOT NULL UNIQUE CHECK (length(trim(adjustment_key)) > 0),
        model_prediction_id INTEGER NOT NULL,
        contest_pick_id INTEGER,
        sequence INTEGER NOT NULL CHECK (sequence > 0),
        supersedes_adjustment_id INTEGER,
        category TEXT NOT NULL CHECK (
            category IN ('injury', 'quarterback', 'coaching', 'travel', 'weather',
                         'motivation', 'matchup', 'other')
        ),
        affected_side TEXT NOT NULL CHECK (affected_side IN ('home', 'away', 'both')),
        margin_adjustment REAL NOT NULL CHECK (
            typeof(margin_adjustment) IN ('integer', 'real')
        ),
        confidence_adjustment INTEGER NOT NULL,
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        evidence TEXT NOT NULL CHECK (length(trim(evidence)) > 0),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        author TEXT NOT NULL CHECK (length(trim(author)) > 0),
        recorded_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='recorded_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (margin_adjustment != 0 OR confidence_adjustment != 0),
        UNIQUE (model_prediction_id, sequence),
        FOREIGN KEY (model_prediction_id) REFERENCES model_predictions(id),
        FOREIGN KEY (contest_pick_id) REFERENCES contest_picks(id),
        FOREIGN KEY (supersedes_adjustment_id) REFERENCES manual_adjustments(id)
    )
    """,
    f"""
    CREATE TABLE pick_audits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_key TEXT NOT NULL UNIQUE CHECK (length(trim(audit_key)) > 0),
        contest_pick_id INTEGER NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence > 0),
        supersedes_audit_id INTEGER,
        audit_status TEXT NOT NULL CHECK (audit_status IN ('pending', 'final')),
        result TEXT NOT NULL CHECK (result IN ('pending', 'win', 'loss', 'push')),
        final_home_points INTEGER CHECK (final_home_points IS NULL OR final_home_points >= 0),
        final_away_points INTEGER CHECK (final_away_points IS NULL OR final_away_points >= 0),
        closing_market_line_id INTEGER,
        clv_points REAL CHECK (clv_points IS NULL OR typeof(clv_points) IN ('integer', 'real')),
        policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) > 0),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        audited_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='audited_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            (audit_status = 'pending' AND result = 'pending'
             AND final_home_points IS NULL AND final_away_points IS NULL)
            OR
            (audit_status = 'final' AND result != 'pending'
             AND final_home_points IS NOT NULL AND final_away_points IS NOT NULL)
        ),
        UNIQUE (contest_pick_id, sequence),
        FOREIGN KEY (contest_pick_id) REFERENCES contest_picks(id),
        FOREIGN KEY (supersedes_audit_id) REFERENCES pick_audits(id),
        FOREIGN KEY (closing_market_line_id) REFERENCES betting_lines(id)
    )
    """,
    "CREATE INDEX idx_model_predictions_run ON model_predictions (model_run_id, game_id)",
    "CREATE INDEX idx_contest_cards_contest ON contest_cards (contest_id, version)",
    "CREATE INDEX idx_contest_picks_card ON contest_picks (card_id, id)",
    "CREATE INDEX idx_sportsbook_recommendations_prediction ON sportsbook_recommendations (model_prediction_id, id)",
    "CREATE INDEX idx_manual_adjustments_prediction ON manual_adjustments (model_prediction_id, sequence)",
    "CREATE INDEX idx_pick_audits_pick ON pick_audits (contest_pick_id, sequence)",
    """
    CREATE TRIGGER model_predictions_validate_entry_market_line
    BEFORE INSERT ON model_predictions
    WHEN NEW.entry_market_line_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM betting_lines
        WHERE id = NEW.entry_market_line_id
          AND game_id = NEW.game_id
          AND line_type IN ('opening', 'current')
          AND julianday(fetched_at) IS NOT NULL
          AND julianday(fetched_at) <= julianday(NEW.generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'entry market line must belong to the predicted game');
    END
    """,
    """
    CREATE TRIGGER model_predictions_validate_entry_locked_line
    BEFORE INSERT ON model_predictions
    WHEN NEW.entry_locked_line_id IS NOT NULL AND EXISTS (
        SELECT 1 FROM contest_locked_lines
        WHERE id = NEW.entry_locked_line_id
          AND game_id IS NOT NULL
          AND game_id != NEW.game_id
    )
    OR NEW.entry_locked_line_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM contest_locked_lines
        WHERE id = NEW.entry_locked_line_id
          AND julianday(locked_at) <= julianday(NEW.generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'entry locked line must belong to the predicted game');
    END
    """,
    """
    CREATE TRIGGER model_predictions_validate_run
    BEFORE INSERT ON model_predictions
    WHEN NOT EXISTS (
        SELECT 1 FROM model_runs
        WHERE id = NEW.model_run_id
          AND status = 'completed'
          AND julianday(NEW.generated_at) >= julianday(generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'prediction requires an earlier completed model run');
    END
    """,
    """
    CREATE TRIGGER contest_cards_validate_run
    BEFORE INSERT ON contest_cards
    WHEN NEW.model_run_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM model_runs
        WHERE id = NEW.model_run_id
          AND status = 'completed'
          AND julianday(NEW.generated_at) >= julianday(generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'card requires an earlier completed model run');
    END
    """,
    """
    CREATE TRIGGER contest_picks_validate_relationships
    BEFORE INSERT ON contest_picks
    WHEN NOT EXISTS (
        SELECT 1
        FROM contest_cards AS card
        JOIN contest_locked_lines AS locked ON locked.contest_id = card.contest_id
        WHERE card.id = NEW.card_id AND locked.id = NEW.locked_line_id
    )
    OR (
        NEW.model_prediction_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1
            FROM model_predictions AS prediction
            JOIN contest_locked_lines AS locked ON locked.id = NEW.locked_line_id
            WHERE prediction.id = NEW.model_prediction_id
              AND (locked.game_id IS NULL OR prediction.game_id = locked.game_id)
        )
    )
    OR NOT EXISTS (
        SELECT 1 FROM contest_cards
        WHERE id = NEW.card_id
          AND julianday(NEW.generated_at) >= julianday(generated_at)
    )
    OR NOT EXISTS (
        SELECT 1 FROM contest_locked_lines
        WHERE id = NEW.locked_line_id
          AND julianday(locked_at) <= julianday(NEW.generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'contest pick relationships do not refer to one contest game');
    END
    """,
    """
    CREATE TRIGGER sportsbook_recommendations_validate_relationships
    BEFORE INSERT ON sportsbook_recommendations
    WHEN (
        NEW.contest_pick_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM contest_picks
            WHERE id = NEW.contest_pick_id
              AND model_prediction_id = NEW.model_prediction_id
        )
    )
    OR (
        NEW.market_line_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1
            FROM betting_lines AS line
            JOIN model_predictions AS prediction ON prediction.game_id = line.game_id
            WHERE line.id = NEW.market_line_id
              AND prediction.id = NEW.model_prediction_id
              AND line.line_type IN ('opening', 'current')
              AND julianday(line.fetched_at) IS NOT NULL
              AND julianday(line.fetched_at) <= julianday(NEW.generated_at)
        )
    )
    OR NOT EXISTS (
        SELECT 1 FROM model_predictions
        WHERE id = NEW.model_prediction_id
          AND julianday(NEW.generated_at) >= julianday(generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'sportsbook recommendation relationships do not refer to one game');
    END
    """,
    """
    CREATE TRIGGER card_revisions_validate_chain
    BEFORE INSERT ON card_revisions
    WHEN NOT EXISTS (
        SELECT 1
        FROM contest_cards AS prior
        JOIN contest_cards AS revised ON revised.contest_id = prior.contest_id
        WHERE prior.id = NEW.prior_card_id
          AND revised.id = NEW.revised_card_id
          AND revised.version = prior.version + 1
          AND julianday(NEW.revised_at) >= julianday(revised.generated_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'card revision must link consecutive versions of one contest');
    END
    """,
    """
    CREATE TRIGGER manual_adjustments_validate_chain
    BEFORE INSERT ON manual_adjustments
    WHEN NEW.sequence != COALESCE(
        (SELECT MAX(sequence) + 1 FROM manual_adjustments
         WHERE model_prediction_id = NEW.model_prediction_id), 1
    )
    OR NEW.supersedes_adjustment_id IS NOT (
        SELECT id FROM manual_adjustments
        WHERE model_prediction_id = NEW.model_prediction_id
        ORDER BY sequence DESC LIMIT 1
    )
    OR (
        NEW.contest_pick_id IS NOT NULL
        AND NOT EXISTS (
            SELECT 1 FROM contest_picks
            WHERE id = NEW.contest_pick_id
              AND model_prediction_id = NEW.model_prediction_id
        )
    )
    OR EXISTS (
        SELECT 1 FROM model_predictions
        WHERE id = NEW.model_prediction_id
          AND julianday(NEW.recorded_at) < julianday(generated_at)
    )
    OR EXISTS (
        SELECT 1 FROM manual_adjustments
        WHERE id = NEW.supersedes_adjustment_id
          AND julianday(NEW.recorded_at) < julianday(recorded_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'manual adjustment history or relationships are invalid');
    END
    """,
    """
    CREATE TRIGGER pick_audits_validate_chain
    BEFORE INSERT ON pick_audits
    WHEN NEW.sequence != COALESCE(
        (SELECT MAX(sequence) + 1 FROM pick_audits
         WHERE contest_pick_id = NEW.contest_pick_id), 1
    )
    OR NEW.supersedes_audit_id IS NOT (
        SELECT id FROM pick_audits
        WHERE contest_pick_id = NEW.contest_pick_id
        ORDER BY sequence DESC LIMIT 1
    )
    OR EXISTS (
        SELECT 1 FROM contest_picks
        WHERE id = NEW.contest_pick_id
          AND julianday(NEW.audited_at) < julianday(generated_at)
    )
    OR EXISTS (
        SELECT 1 FROM pick_audits
        WHERE id = NEW.supersedes_audit_id
          AND julianday(NEW.audited_at) < julianday(audited_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'pick audit history must be append-only and contiguous');
    END
    """,
    """
    CREATE TRIGGER pick_audits_validate_closing_line
    BEFORE INSERT ON pick_audits
    WHEN NEW.closing_market_line_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM betting_lines AS line
        JOIN contest_picks AS pick ON pick.id = NEW.contest_pick_id
        JOIN model_predictions AS prediction ON prediction.id = pick.model_prediction_id
        WHERE line.id = NEW.closing_market_line_id
          AND line.game_id = prediction.game_id
          AND line.line_type = 'closing'
          AND julianday(line.fetched_at) IS NOT NULL
          AND julianday(line.fetched_at) <= julianday(NEW.audited_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'audit closing line must be a captured closing line for the pick game');
    END
    """,
)


IMMUTABLE_TABLES = (
    ("model_runs", "run_key", ""),
    (
        "model_predictions",
        "prediction_key",
        " OR (model_run_id = NEW.model_run_id AND game_id = NEW.game_id)",
    ),
    (
        "contest_cards",
        "card_key",
        " OR (contest_id = NEW.contest_id AND version = NEW.version)",
    ),
    (
        "contest_picks",
        "pick_key",
        " OR (card_id = NEW.card_id AND locked_line_id = NEW.locked_line_id)",
    ),
    ("sportsbook_recommendations", "recommendation_key", ""),
    ("card_revisions", "revision_key", " OR revised_card_id = NEW.revised_card_id"),
    (
        "manual_adjustments",
        "adjustment_key",
        " OR (model_prediction_id = NEW.model_prediction_id AND sequence = NEW.sequence)",
    ),
    (
        "pick_audits",
        "audit_key",
        " OR (contest_pick_id = NEW.contest_pick_id AND sequence = NEW.sequence)",
    ),
)

for _table, _key, _natural_key in IMMUTABLE_TABLES:
    STATEMENTS += (
        f"""
        CREATE TRIGGER {_table}_no_duplicate_insert
        BEFORE INSERT ON {_table}
        WHEN EXISTS (
            SELECT 1 FROM {_table}
            WHERE id = NEW.id OR {_key} = NEW.{_key}{_natural_key}
        )
        BEGIN
            SELECT RAISE(ABORT, '{_table} records cannot be replaced');
        END
        """,
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
