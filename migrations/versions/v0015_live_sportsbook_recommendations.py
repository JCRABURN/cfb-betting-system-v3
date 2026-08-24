"""Add two-sided sportsbook offers and governed recommendation evaluations."""

from __future__ import annotations

import sqlite3


VERSION = 15
NAME = "live_sportsbook_recommendations"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"
_SHA256_CHECK = (
    "length({column}) = 64 AND lower({column}) NOT GLOB '*[^0-9a-f]*'"
)
_NUMBER_CHECK = "typeof({column}) IN ('integer', 'real')"
_AMERICAN_PRICE_CHECK = (
    "typeof({column}) = 'integer' AND ({column} <= -100 OR {column} >= 100)"
)


STATEMENTS = (
    f"""
    CREATE TABLE sportsbook_market_offers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider_market_snapshot_id INTEGER NOT NULL UNIQUE,
        betting_line_id INTEGER NOT NULL UNIQUE,
        provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
        bookmaker TEXT NOT NULL CHECK (length(trim(bookmaker)) > 0),
        game_id INTEGER NOT NULL,
        line_type TEXT NOT NULL CHECK (line_type IN ('opening', 'current', 'closing')),
        home_spread REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='home_spread')}
            AND home_spread >= -100 AND home_spread <= 100
        ),
        home_price INTEGER NOT NULL CHECK (
            {_AMERICAN_PRICE_CHECK.format(column='home_price')}
        ),
        away_spread REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='away_spread')}
            AND away_spread >= -100 AND away_spread <= 100
        ),
        away_price INTEGER NOT NULL CHECK (
            {_AMERICAN_PRICE_CHECK.format(column='away_price')}
        ),
        observed_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='observed_at')}),
        event_start_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='event_start_at')}),
        parser_version TEXT NOT NULL CHECK (length(trim(parser_version)) > 0),
        raw_record_sha256 TEXT NOT NULL CHECK (
            {_SHA256_CHECK.format(column='raw_record_sha256')}
        ),
        recorded_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='recorded_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (abs(home_spread + away_spread) < 0.000001),
        CHECK (julianday(observed_at) <= julianday(event_start_at)),
        FOREIGN KEY (provider_market_snapshot_id) REFERENCES provider_market_snapshots(id),
        FOREIGN KEY (betting_line_id) REFERENCES betting_lines(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    f"""
    CREATE TABLE sportsbook_recommendation_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_version TEXT NOT NULL UNIQUE CHECK (length(trim(policy_version)) > 0),
        production_model_name TEXT NOT NULL CHECK (production_model_name = 'epa_only'),
        production_model_version TEXT NOT NULL
            CHECK (production_model_version = 'epa-only-linear-v1'),
        probability_model_version TEXT NOT NULL
            CHECK (probability_model_version = 'normal-margin-v1'),
        residual_stddev_points REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='residual_stddev_points')}
            AND residual_stddev_points > 0
        ),
        minimum_spread_edge_points REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='minimum_spread_edge_points')}
            AND minimum_spread_edge_points >= 0
        ),
        minimum_cover_probability REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='minimum_cover_probability')}
            AND minimum_cover_probability >= 0.5
            AND minimum_cover_probability <= 1
        ),
        minimum_expected_value REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='minimum_expected_value')}
            AND minimum_expected_value >= 0
        ),
        maximum_odds_age_seconds INTEGER NOT NULL CHECK (
            maximum_odds_age_seconds > 0 AND maximum_odds_age_seconds <= 900
        ),
        material_update_seconds INTEGER NOT NULL CHECK (material_update_seconds > 0),
        material_spread_change_points REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='material_spread_change_points')}
            AND material_spread_change_points > 0
        ),
        material_price_change INTEGER NOT NULL CHECK (material_price_change > 0),
        maximum_stake_units REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='maximum_stake_units')}
            AND maximum_stake_units > 0
        ),
        stake_units_per_expected_value REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='stake_units_per_expected_value')}
            AND stake_units_per_expected_value > 0
        ),
        stake_increment_units REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='stake_increment_units')}
            AND stake_increment_units > 0
            AND stake_increment_units <= maximum_stake_units
        ),
        effective_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='effective_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    f"""
    CREATE TABLE sportsbook_recommendation_evaluations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        evaluation_key TEXT NOT NULL UNIQUE CHECK (length(trim(evaluation_key)) > 0),
        recommendation_id INTEGER NOT NULL UNIQUE,
        policy_id INTEGER NOT NULL,
        policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) > 0),
        market_offer_id INTEGER NOT NULL,
        model_prediction_id INTEGER NOT NULL,
        supersedes_evaluation_id INTEGER UNIQUE,
        lifecycle_state TEXT NOT NULL CHECK (lifecycle_state IN ('active', 'expired')),
        decision TEXT NOT NULL CHECK (decision IN ('bet', 'no_bet')),
        selected_side TEXT NOT NULL CHECK (selected_side IN ('home', 'away')),
        selected_team TEXT NOT NULL CHECK (length(trim(selected_team)) > 0),
        bookmaker TEXT NOT NULL CHECK (length(trim(bookmaker)) > 0),
        offered_spread REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='offered_spread')}
        ),
        offered_price INTEGER NOT NULL CHECK (
            {_AMERICAN_PRICE_CHECK.format(column='offered_price')}
        ),
        captured_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='captured_at')}),
        event_start_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='event_start_at')}),
        model_fair_spread REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='model_fair_spread')}
        ),
        spread_edge_points REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='spread_edge_points')}
        ),
        estimated_cover_probability REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='estimated_cover_probability')}
            AND estimated_cover_probability >= 0
            AND estimated_cover_probability <= 1
        ),
        break_even_probability REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='break_even_probability')}
            AND break_even_probability > 0
            AND break_even_probability < 1
        ),
        expected_value REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='expected_value')}
        ),
        stake_units REAL NOT NULL CHECK (
            {_NUMBER_CHECK.format(column='stake_units')} AND stake_units >= 0
        ),
        reason_code TEXT NOT NULL CHECK (length(trim(reason_code)) > 0),
        evaluated_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='evaluated_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            (lifecycle_state = 'active' AND decision = 'bet' AND stake_units > 0)
            OR (decision = 'no_bet' AND stake_units = 0)
        ),
        CHECK (lifecycle_state != 'expired' OR decision = 'no_bet'),
        CHECK (julianday(captured_at) <= julianday(evaluated_at)),
        CHECK (julianday(evaluated_at) < julianday(event_start_at)),
        UNIQUE (market_offer_id, model_prediction_id, policy_id, lifecycle_state),
        FOREIGN KEY (recommendation_id) REFERENCES sportsbook_recommendations(id),
        FOREIGN KEY (policy_id) REFERENCES sportsbook_recommendation_policies(id),
        FOREIGN KEY (market_offer_id) REFERENCES sportsbook_market_offers(id),
        FOREIGN KEY (model_prediction_id) REFERENCES model_predictions(id),
        FOREIGN KEY (supersedes_evaluation_id)
            REFERENCES sportsbook_recommendation_evaluations(id)
    )
    """,
    """
    CREATE INDEX idx_sportsbook_market_offers_board
        ON sportsbook_market_offers (game_id, bookmaker, observed_at, id)
    """,
    """
    CREATE INDEX idx_sportsbook_evaluations_board
        ON sportsbook_recommendation_evaluations (
            policy_id, bookmaker, model_prediction_id, evaluated_at, id
        )
    """,
    """
    CREATE TRIGGER sportsbook_market_offers_validate_custody
    BEFORE INSERT ON sportsbook_market_offers
    WHEN NOT EXISTS (
        SELECT 1
        FROM provider_market_snapshots AS snapshot
        JOIN betting_lines AS line ON line.id = NEW.betting_line_id
        WHERE snapshot.id = NEW.provider_market_snapshot_id
          AND snapshot.provider = NEW.provider
          AND snapshot.bookmaker = NEW.bookmaker
          AND snapshot.game_id = NEW.game_id
          AND snapshot.home_spread = NEW.home_spread
          AND snapshot.home_price = NEW.home_price
          AND snapshot.observed_at = NEW.observed_at
          AND snapshot.event_start_at = NEW.event_start_at
          AND snapshot.parser_version = NEW.parser_version
          AND snapshot.raw_record_sha256 = NEW.raw_record_sha256
          AND line.game_id = NEW.game_id
          AND line.book = NEW.bookmaker
          AND line.home_spread = NEW.home_spread
          AND line.home_moneyline = NEW.home_price
          AND line.line_type = NEW.line_type
          AND line.source = NEW.provider
          AND line.fetched_at = NEW.observed_at
    )
    BEGIN
        SELECT RAISE(ABORT, 'sportsbook offer does not match provider and market-line custody');
    END
    """,
    """
    CREATE TRIGGER sportsbook_recommendation_evaluations_validate_relationships
    BEFORE INSERT ON sportsbook_recommendation_evaluations
    WHEN NOT EXISTS (
        SELECT 1
        FROM sportsbook_recommendations AS recommendation
        JOIN sportsbook_recommendation_policies AS policy
          ON policy.id = NEW.policy_id
        JOIN sportsbook_market_offers AS offer
          ON offer.id = NEW.market_offer_id
        JOIN model_predictions AS prediction
          ON prediction.id = NEW.model_prediction_id
        JOIN model_runs AS run ON run.id = prediction.model_run_id
        WHERE recommendation.id = NEW.recommendation_id
          AND recommendation.model_prediction_id = prediction.id
          AND recommendation.policy_version = policy.policy_version
          AND NEW.policy_version = policy.policy_version
          AND recommendation.decision = NEW.decision
          AND recommendation.reason_code = NEW.reason_code
          AND recommendation.generated_at = NEW.evaluated_at
          AND recommendation.provenance = NEW.provenance
          AND prediction.game_id = offer.game_id
          AND run.model_name = policy.production_model_name
          AND run.model_version = policy.production_model_version
          AND run.status = 'completed'
          AND julianday(prediction.generated_at) <= julianday(NEW.evaluated_at)
          AND julianday(policy.effective_at) <= julianday(NEW.evaluated_at)
          AND offer.line_type IN ('opening', 'current')
          AND offer.bookmaker = NEW.bookmaker
          AND offer.observed_at = NEW.captured_at
          AND offer.event_start_at = NEW.event_start_at
          AND (
              NEW.selected_side = 'home'
              AND NEW.selected_team = (
                  SELECT home_team FROM games WHERE game_id = offer.game_id
              )
              AND NEW.offered_spread = offer.home_spread
              AND NEW.offered_price = offer.home_price
              OR NEW.selected_side = 'away'
              AND NEW.selected_team = (
                  SELECT away_team FROM games WHERE game_id = offer.game_id
              )
              AND NEW.offered_spread = offer.away_spread
              AND NEW.offered_price = offer.away_price
          )
          AND (
              NEW.decision = 'bet'
              AND recommendation.contest_pick_id IS NULL
              AND recommendation.market_line_id = offer.betting_line_id
              AND recommendation.recommended_side = NEW.selected_side
              AND recommendation.offered_price = NEW.offered_price
              AND recommendation.expected_value = NEW.expected_value
              AND recommendation.stake_units = NEW.stake_units
              OR NEW.decision = 'no_bet'
              AND recommendation.contest_pick_id IS NULL
              AND recommendation.market_line_id IS NULL
              AND recommendation.recommended_side IS NULL
              AND recommendation.offered_price IS NULL
              AND recommendation.expected_value IS NULL
              AND recommendation.stake_units = 0
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'sportsbook evaluation relationships are invalid');
    END
    """,
    """
    CREATE TRIGGER sportsbook_recommendation_evaluations_validate_supersession
    BEFORE INSERT ON sportsbook_recommendation_evaluations
    WHEN NEW.supersedes_evaluation_id IS NOT NULL AND NOT EXISTS (
        SELECT 1
        FROM sportsbook_recommendation_evaluations AS prior
        JOIN sportsbook_market_offers AS prior_offer ON prior_offer.id = prior.market_offer_id
        JOIN sportsbook_market_offers AS new_offer ON new_offer.id = NEW.market_offer_id
        WHERE prior.id = NEW.supersedes_evaluation_id
          AND prior.policy_id = NEW.policy_id
          AND prior_offer.game_id = new_offer.game_id
          AND prior_offer.bookmaker = new_offer.bookmaker
          AND julianday(prior.evaluated_at) <= julianday(NEW.evaluated_at)
          AND (
              julianday(prior_offer.observed_at) < julianday(new_offer.observed_at)
              OR prior.market_offer_id = NEW.market_offer_id
                 AND prior.lifecycle_state = 'active'
                 AND NEW.lifecycle_state = 'expired'
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'sportsbook recommendation supersession is invalid');
    END
    """,
)


for _table, _identity in (
    ("sportsbook_market_offers", "id = NEW.id OR provider_market_snapshot_id = NEW.provider_market_snapshot_id OR betting_line_id = NEW.betting_line_id"),
    ("sportsbook_recommendation_policies", "id = NEW.id OR policy_version = NEW.policy_version"),
    ("sportsbook_recommendation_evaluations", "id = NEW.id OR evaluation_key = NEW.evaluation_key OR recommendation_id = NEW.recommendation_id"),
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
    if len(words) >= 4 and words[0:3] == ["CREATE", "UNIQUE", "INDEX"]:
        return "index", words[3]
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
