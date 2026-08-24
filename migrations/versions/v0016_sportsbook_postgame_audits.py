"""Add immutable sportsbook recommendation settlement and CLV audits."""

from __future__ import annotations

import sqlite3


VERSION = 16
NAME = "sportsbook_postgame_audits"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"
_SHA256_CHECK = "length({column}) = 64 AND lower({column}) NOT GLOB '*[^0-9a-f]*'"
_NUMBER_CHECK = "typeof({column}) IN ('integer', 'real')"


STATEMENTS = (
    f"""
    CREATE TABLE sportsbook_closing_designations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        designation_key TEXT NOT NULL UNIQUE CHECK (length(trim(designation_key)) > 0),
        market_offer_id INTEGER NOT NULL UNIQUE,
        closing_betting_line_id INTEGER NOT NULL UNIQUE,
        game_id INTEGER NOT NULL,
        bookmaker TEXT NOT NULL CHECK (length(trim(bookmaker)) > 0),
        designated_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='designated_at')}),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (market_offer_id) REFERENCES sportsbook_market_offers(id),
        FOREIGN KEY (closing_betting_line_id) REFERENCES betting_lines(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    f"""
    CREATE TABLE sportsbook_postgame_audit_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_run_key TEXT NOT NULL UNIQUE CHECK (length(trim(audit_run_key)) > 0),
        season INTEGER NOT NULL CHECK (season >= 1869),
        week INTEGER NOT NULL CHECK (week >= 0 AND week <= 20),
        policy_id INTEGER NOT NULL,
        policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) > 0),
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        supersedes_run_id INTEGER UNIQUE,
        expected_evaluation_count INTEGER NOT NULL CHECK (expected_evaluation_count >= 0),
        expected_bet_count INTEGER NOT NULL CHECK (
            expected_bet_count >= 0
            AND expected_bet_count <= expected_evaluation_count
        ),
        audited_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='audited_at')}),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (season, week, policy_id, sequence),
        FOREIGN KEY (policy_id) REFERENCES sportsbook_recommendation_policies(id),
        FOREIGN KEY (supersedes_run_id) REFERENCES sportsbook_postgame_audit_runs(id)
    )
    """,
    f"""
    CREATE TABLE sportsbook_postgame_audit_details (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        audit_run_id INTEGER NOT NULL,
        evaluation_id INTEGER NOT NULL,
        recommendation_id INTEGER NOT NULL,
        market_offer_id INTEGER NOT NULL,
        game_id INTEGER NOT NULL,
        decision TEXT NOT NULL CHECK (decision IN ('bet', 'no_bet')),
        lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('active', 'expired')),
        selected_side TEXT NOT NULL CHECK (selected_side IN ('home', 'away')),
        bookmaker TEXT NOT NULL CHECK (length(trim(bookmaker)) > 0),
        offered_spread REAL NOT NULL CHECK ({_NUMBER_CHECK.format(column='offered_spread')}),
        offered_price INTEGER NOT NULL CHECK (
            typeof(offered_price) = 'integer'
            AND (offered_price <= -100 OR offered_price >= 100)
        ),
        stake_units REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='stake_units')} AND stake_units >= 0
        ),
        final_home_points INTEGER NOT NULL CHECK (final_home_points >= 0),
        final_away_points INTEGER NOT NULL CHECK (final_away_points >= 0),
        actual_home_margin INTEGER NOT NULL,
        covered_margin REAL NOT NULL CHECK ({_NUMBER_CHECK.format(column='covered_margin')}),
        ats_result TEXT NOT NULL CHECK (ats_result IN ('win', 'loss', 'push')),
        realized_profit_units REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='realized_profit_units')}
        ),
        closing_designation_id INTEGER,
        closing_evidence_status TEXT NOT NULL CHECK (
            closing_evidence_status IN ('available', 'missing')
        ),
        closing_selected_spread REAL CHECK (
            closing_selected_spread IS NULL
            OR {_NUMBER_CHECK.format(column='closing_selected_spread')}
        ),
        closing_selected_price INTEGER CHECK (
            closing_selected_price IS NULL
            OR closing_selected_price <= -100
            OR closing_selected_price >= 100
        ),
        clv_points REAL CHECK (
            clv_points IS NULL OR {_NUMBER_CHECK.format(column='clv_points')}
        ),
        clv_evidence_status TEXT NOT NULL CHECK (
            clv_evidence_status IN ('available', 'missing')
        ),
        graded_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='graded_at')}),
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            (closing_evidence_status = 'available'
             AND clv_evidence_status = 'available'
             AND closing_designation_id IS NOT NULL
             AND closing_selected_spread IS NOT NULL
             AND closing_selected_price IS NOT NULL
             AND clv_points IS NOT NULL)
            OR
            (closing_evidence_status = 'missing'
             AND clv_evidence_status = 'missing'
             AND closing_designation_id IS NULL
             AND closing_selected_spread IS NULL
             AND closing_selected_price IS NULL
             AND clv_points IS NULL)
        ),
        UNIQUE (audit_run_id, evaluation_id),
        FOREIGN KEY (audit_run_id) REFERENCES sportsbook_postgame_audit_runs(id),
        FOREIGN KEY (evaluation_id) REFERENCES sportsbook_recommendation_evaluations(id),
        FOREIGN KEY (recommendation_id) REFERENCES sportsbook_recommendations(id),
        FOREIGN KEY (market_offer_id) REFERENCES sportsbook_market_offers(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id),
        FOREIGN KEY (closing_designation_id) REFERENCES sportsbook_closing_designations(id)
    )
    """,
    f"""
    CREATE TABLE sportsbook_postgame_audit_completions (
        audit_run_id INTEGER PRIMARY KEY,
        audit_count INTEGER NOT NULL CHECK (audit_count >= 0),
        bet_count INTEGER NOT NULL CHECK (bet_count >= 0 AND bet_count <= audit_count),
        no_bet_count INTEGER NOT NULL CHECK (no_bet_count >= 0 AND no_bet_count <= audit_count),
        win_count INTEGER NOT NULL CHECK (win_count >= 0 AND win_count <= audit_count),
        loss_count INTEGER NOT NULL CHECK (loss_count >= 0 AND loss_count <= audit_count),
        push_count INTEGER NOT NULL CHECK (push_count >= 0 AND push_count <= audit_count),
        clv_graded_count INTEGER NOT NULL CHECK (
            clv_graded_count >= 0 AND clv_graded_count <= audit_count
        ),
        missing_clv_count INTEGER NOT NULL CHECK (
            missing_clv_count >= 0 AND missing_clv_count <= audit_count
        ),
        total_staked_units REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='total_staked_units')} AND total_staked_units >= 0
        ),
        realized_profit_units REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='realized_profit_units')}
        ),
        roi_percent REAL CHECK (roi_percent IS NULL OR {_NUMBER_CHECK.format(column='roi_percent')}),
        average_clv_points REAL CHECK (
            average_clv_points IS NULL OR {_NUMBER_CHECK.format(column='average_clv_points')}
        ),
        ledger_sha256 TEXT NOT NULL CHECK ({_SHA256_CHECK.format(column='ledger_sha256')}),
        completed_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='completed_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (audit_count = bet_count + no_bet_count),
        CHECK (audit_count = win_count + loss_count + push_count),
        CHECK (audit_count = clv_graded_count + missing_clv_count),
        CHECK (
            (total_staked_units = 0 AND roi_percent IS NULL)
            OR (total_staked_units > 0 AND roi_percent IS NOT NULL)
        ),
        CHECK (
            (clv_graded_count = 0 AND average_clv_points IS NULL)
            OR (clv_graded_count > 0 AND average_clv_points IS NOT NULL)
        ),
        FOREIGN KEY (audit_run_id) REFERENCES sportsbook_postgame_audit_runs(id)
    )
    """,
    """
    CREATE INDEX idx_sportsbook_postgame_audit_week
        ON sportsbook_postgame_audit_runs (season, week, policy_id, sequence)
    """,
    """
    CREATE INDEX idx_sportsbook_postgame_audit_game
        ON sportsbook_postgame_audit_details (game_id, bookmaker, evaluation_id)
    """,
    """
    CREATE TRIGGER sportsbook_closing_designations_validate
    BEFORE INSERT ON sportsbook_closing_designations
    WHEN NOT EXISTS (
        SELECT 1
        FROM sportsbook_market_offers AS offer
        JOIN betting_lines AS closing ON closing.id = NEW.closing_betting_line_id
        WHERE offer.id = NEW.market_offer_id
          AND offer.line_type = 'current'
          AND offer.game_id = NEW.game_id
          AND offer.bookmaker = NEW.bookmaker
          AND julianday(offer.observed_at) <= julianday(NEW.designated_at)
          AND julianday(NEW.designated_at) < julianday(offer.event_start_at)
          AND closing.game_id = offer.game_id
          AND closing.book = offer.bookmaker
          AND closing.home_spread = offer.home_spread
          AND closing.home_moneyline = offer.home_price
          AND closing.line_type = 'closing'
          AND closing.source = offer.provider
          AND closing.fetched_at = offer.observed_at
          AND NOT EXISTS (
              SELECT 1 FROM sportsbook_market_offers AS newer
              WHERE newer.game_id = offer.game_id
                AND newer.bookmaker = offer.bookmaker
                AND newer.line_type = 'current'
                AND julianday(newer.observed_at) <= julianday(NEW.designated_at)
                AND (
                    julianday(newer.observed_at) > julianday(offer.observed_at)
                    OR newer.observed_at = offer.observed_at AND newer.id > offer.id
                )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'sportsbook closing designation is not the latest exact offer');
    END
    """,
    """
    CREATE TRIGGER sportsbook_postgame_audit_runs_validate
    BEFORE INSERT ON sportsbook_postgame_audit_runs
    WHEN NOT EXISTS (
        SELECT 1
        FROM sportsbook_recommendation_policies AS policy
        WHERE policy.id = NEW.policy_id
          AND policy.policy_version = NEW.policy_version
          AND julianday(policy.effective_at) <= julianday(NEW.audited_at)
          AND NEW.expected_evaluation_count = (
              SELECT COUNT(*)
              FROM sportsbook_recommendation_evaluations AS evaluation
              JOIN sportsbook_market_offers AS offer
                ON offer.id = evaluation.market_offer_id
              JOIN games AS game ON game.game_id = offer.game_id
              WHERE evaluation.policy_id = NEW.policy_id
                AND game.season = NEW.season
                AND game.week = NEW.week
                AND julianday(evaluation.evaluated_at) <= julianday(NEW.audited_at)
          )
          AND NEW.expected_bet_count = (
              SELECT COUNT(*)
              FROM sportsbook_recommendation_evaluations AS evaluation
              JOIN sportsbook_market_offers AS offer
                ON offer.id = evaluation.market_offer_id
              JOIN games AS game ON game.game_id = offer.game_id
              WHERE evaluation.policy_id = NEW.policy_id
                AND evaluation.decision = 'bet'
                AND game.season = NEW.season
                AND game.week = NEW.week
                AND julianday(evaluation.evaluated_at) <= julianday(NEW.audited_at)
          )
          AND (
              NEW.sequence = 1 AND NEW.supersedes_run_id IS NULL
              AND NOT EXISTS (
                  SELECT 1 FROM sportsbook_postgame_audit_runs
                  WHERE season = NEW.season AND week = NEW.week
                    AND policy_id = NEW.policy_id
              )
              OR EXISTS (
                  SELECT 1 FROM sportsbook_postgame_audit_runs AS prior
                  WHERE prior.id = NEW.supersedes_run_id
                    AND prior.season = NEW.season
                    AND prior.week = NEW.week
                    AND prior.policy_id = NEW.policy_id
                    AND prior.sequence = NEW.sequence - 1
                    AND NOT EXISTS (
                        SELECT 1 FROM sportsbook_postgame_audit_runs AS later
                        WHERE later.season = NEW.season AND later.week = NEW.week
                          AND later.policy_id = NEW.policy_id
                          AND later.sequence > prior.sequence
                    )
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'sportsbook postgame audit run is incomplete or inconsistent');
    END
    """,
    """
    CREATE TRIGGER sportsbook_postgame_audit_details_validate
    BEFORE INSERT ON sportsbook_postgame_audit_details
    WHEN NOT EXISTS (
        SELECT 1
        FROM sportsbook_postgame_audit_runs AS run
        JOIN sportsbook_recommendation_evaluations AS evaluation
          ON evaluation.id = NEW.evaluation_id
        JOIN sportsbook_market_offers AS offer
          ON offer.id = evaluation.market_offer_id
        JOIN games AS game ON game.game_id = offer.game_id
        WHERE run.id = NEW.audit_run_id
          AND evaluation.policy_id = run.policy_id
          AND evaluation.recommendation_id = NEW.recommendation_id
          AND evaluation.market_offer_id = NEW.market_offer_id
          AND offer.game_id = NEW.game_id
          AND game.season = run.season
          AND game.week = run.week
          AND game.completed = 1
          AND game.home_points = NEW.final_home_points
          AND game.away_points = NEW.final_away_points
          AND NEW.actual_home_margin = game.home_points - game.away_points
          AND evaluation.decision = NEW.decision
          AND evaluation.lifecycle_state = NEW.lifecycle_state
          AND evaluation.selected_side = NEW.selected_side
          AND evaluation.bookmaker = NEW.bookmaker
          AND evaluation.offered_spread = NEW.offered_spread
          AND evaluation.offered_price = NEW.offered_price
          AND evaluation.stake_units = NEW.stake_units
          AND julianday(evaluation.evaluated_at) <= julianday(run.audited_at)
          AND julianday(game.start_date) <= julianday(run.audited_at)
          AND abs(NEW.covered_margin - CASE NEW.selected_side
              WHEN 'home' THEN NEW.actual_home_margin + NEW.offered_spread
              ELSE -NEW.actual_home_margin + NEW.offered_spread
          END) < 0.000000001
          AND NEW.ats_result = CASE
              WHEN NEW.covered_margin > 0 THEN 'win'
              WHEN NEW.covered_margin < 0 THEN 'loss'
              ELSE 'push'
          END
          AND abs(NEW.realized_profit_units - CASE
              WHEN NEW.decision = 'no_bet' OR NEW.ats_result = 'push' THEN 0
              WHEN NEW.ats_result = 'loss' THEN -NEW.stake_units
              WHEN NEW.offered_price < 0
                  THEN NEW.stake_units * 100.0 / abs(NEW.offered_price)
              ELSE NEW.stake_units * NEW.offered_price / 100.0
          END) < 0.000000001
          AND (
              NEW.closing_evidence_status = 'missing'
              AND NEW.clv_evidence_status = 'missing'
              AND NOT EXISTS (
                  SELECT 1 FROM sportsbook_closing_designations AS designation
                  WHERE designation.game_id = offer.game_id
                    AND designation.bookmaker = offer.bookmaker
              )
              OR NEW.closing_evidence_status = 'available'
              AND NEW.clv_evidence_status = 'available'
              AND EXISTS (
                  SELECT 1
                  FROM sportsbook_closing_designations AS designation
                  JOIN sportsbook_market_offers AS closing
                    ON closing.id = designation.market_offer_id
                  WHERE designation.id = NEW.closing_designation_id
                    AND designation.game_id = offer.game_id
                    AND designation.bookmaker = offer.bookmaker
                    AND NOT EXISTS (
                        SELECT 1 FROM sportsbook_closing_designations AS later
                        WHERE later.game_id = designation.game_id
                          AND later.bookmaker = designation.bookmaker
                          AND later.id > designation.id
                    )
                    AND NEW.closing_selected_spread = CASE NEW.selected_side
                        WHEN 'home' THEN closing.home_spread ELSE closing.away_spread
                    END
                    AND NEW.closing_selected_price = CASE NEW.selected_side
                        WHEN 'home' THEN closing.home_price ELSE closing.away_price
                    END
                    AND abs(NEW.clv_points - (
                        NEW.offered_spread - NEW.closing_selected_spread
                    )) < 0.000000001
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'sportsbook postgame audit detail does not match immutable sources');
    END
    """,
    """
    CREATE TRIGGER sportsbook_postgame_audit_completions_validate
    BEFORE INSERT ON sportsbook_postgame_audit_completions
    WHEN NOT EXISTS (
        SELECT 1
        FROM sportsbook_postgame_audit_runs AS run
        WHERE run.id = NEW.audit_run_id
          AND NEW.completed_at = run.audited_at
          AND NEW.provenance = run.provenance
          AND NEW.audit_count = run.expected_evaluation_count
          AND NEW.bet_count = run.expected_bet_count
          AND NEW.audit_count = (
              SELECT COUNT(*) FROM sportsbook_postgame_audit_details
              WHERE audit_run_id = run.id
          )
          AND NEW.bet_count = (
              SELECT COUNT(*) FROM sportsbook_postgame_audit_details
              WHERE audit_run_id = run.id AND decision = 'bet'
          )
          AND NEW.no_bet_count = (
              SELECT COUNT(*) FROM sportsbook_postgame_audit_details
              WHERE audit_run_id = run.id AND decision = 'no_bet'
          )
          AND NEW.win_count = (
              SELECT COUNT(*) FROM sportsbook_postgame_audit_details
              WHERE audit_run_id = run.id AND ats_result = 'win'
          )
          AND NEW.loss_count = (
              SELECT COUNT(*) FROM sportsbook_postgame_audit_details
              WHERE audit_run_id = run.id AND ats_result = 'loss'
          )
          AND NEW.push_count = (
              SELECT COUNT(*) FROM sportsbook_postgame_audit_details
              WHERE audit_run_id = run.id AND ats_result = 'push'
          )
          AND NEW.clv_graded_count = (
              SELECT COUNT(*) FROM sportsbook_postgame_audit_details
              WHERE audit_run_id = run.id AND clv_evidence_status = 'available'
          )
          AND NEW.missing_clv_count = (
              SELECT COUNT(*) FROM sportsbook_postgame_audit_details
              WHERE audit_run_id = run.id AND clv_evidence_status = 'missing'
          )
          AND abs(NEW.total_staked_units - coalesce((
              SELECT sum(stake_units) FROM sportsbook_postgame_audit_details
              WHERE audit_run_id = run.id AND decision = 'bet'
          ), 0)) < 0.000000001
          AND abs(NEW.realized_profit_units - coalesce((
              SELECT sum(realized_profit_units) FROM sportsbook_postgame_audit_details
              WHERE audit_run_id = run.id
          ), 0)) < 0.000000001
          AND (
              NEW.total_staked_units = 0 AND NEW.roi_percent IS NULL
              OR abs(NEW.roi_percent -
                  (NEW.realized_profit_units / NEW.total_staked_units * 100.0)
              ) < 0.000000001
          )
          AND (
              NEW.clv_graded_count = 0 AND NEW.average_clv_points IS NULL
              OR abs(NEW.average_clv_points - (
                  SELECT avg(clv_points) FROM sportsbook_postgame_audit_details
                  WHERE audit_run_id = run.id AND clv_evidence_status = 'available'
              )) < 0.000000001
          )
          AND NOT EXISTS (
              SELECT 1
              FROM sportsbook_recommendation_evaluations AS evaluation
              JOIN sportsbook_market_offers AS offer
                ON offer.id = evaluation.market_offer_id
              JOIN games AS game ON game.game_id = offer.game_id
              WHERE evaluation.policy_id = run.policy_id
                AND game.season = run.season
                AND game.week = run.week
                AND julianday(evaluation.evaluated_at) <= julianday(run.audited_at)
                AND NOT EXISTS (
                    SELECT 1 FROM sportsbook_postgame_audit_details AS detail
                    WHERE detail.audit_run_id = run.id
                      AND detail.evaluation_id = evaluation.id
                )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'sportsbook postgame audit completion requires full coverage');
    END
    """,
)


for _table, _identity in (
    (
        "sportsbook_closing_designations",
        "id = NEW.id OR designation_key = NEW.designation_key "
        "OR market_offer_id = NEW.market_offer_id "
        "OR closing_betting_line_id = NEW.closing_betting_line_id",
    ),
    (
        "sportsbook_postgame_audit_runs",
        "id = NEW.id OR audit_run_key = NEW.audit_run_key "
        "OR (season = NEW.season AND week = NEW.week "
        "AND policy_id = NEW.policy_id AND sequence = NEW.sequence)",
    ),
    (
        "sportsbook_postgame_audit_details",
        "id = NEW.id OR (audit_run_id = NEW.audit_run_id "
        "AND evaluation_id = NEW.evaluation_id)",
    ),
    ("sportsbook_postgame_audit_completions", "audit_run_id = NEW.audit_run_id"),
):
    STATEMENTS += (
        f"""
        CREATE TRIGGER {_table}_no_duplicate_insert
        BEFORE INSERT ON {_table}
        WHEN EXISTS (SELECT 1 FROM {_table} WHERE {_identity})
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
        if _normalize_sql(row[0]) != expected_sql:
            raise RuntimeError(f"{object_type} definition changed: {name}")
