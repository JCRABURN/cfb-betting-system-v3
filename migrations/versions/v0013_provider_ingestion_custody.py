"""Add append-only provider-ingestion custody and freshness records."""

from __future__ import annotations

import sqlite3


VERSION = 13
NAME = "provider_ingestion_custody"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"
_SHA256_CHECK = (
    "length({column}) = 64 AND lower({column}) NOT GLOB '*[^0-9a-f]*'"
)

STATEMENTS = (
    f"""
    CREATE TABLE provider_team_aliases (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
        raw_team_name TEXT NOT NULL CHECK (length(trim(raw_team_name)) > 0),
        canonical_team TEXT NOT NULL CHECK (length(trim(canonical_team)) > 0),
        effective_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='effective_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (provider, raw_team_name),
        FOREIGN KEY (canonical_team) REFERENCES teams(school)
    )
    """,
    f"""
    CREATE TABLE provider_ingestion_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_key TEXT NOT NULL UNIQUE
            CHECK ({_SHA256_CHECK.format(column='run_key')}),
        provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
        endpoint TEXT NOT NULL CHECK (length(trim(endpoint)) > 0),
        request_parameters TEXT NOT NULL CHECK (json_valid(request_parameters)),
        requested_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='requested_at')}),
        parser_version TEXT NOT NULL CHECK (length(trim(parser_version)) > 0),
        payload_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='payload_sha256')}),
        expected_payload_sha256 TEXT CHECK (
            expected_payload_sha256 IS NULL
            OR ({_SHA256_CHECK.format(column='expected_payload_sha256')})
        ),
        raw_payload_reference TEXT NOT NULL
            CHECK (length(trim(raw_payload_reference)) > 0),
        data_type TEXT NOT NULL CHECK (
            data_type IN ('odds', 'injuries', 'weather', 'game_status', 'contextual')
        ),
        freshness_policy_version TEXT NOT NULL
            CHECK (freshness_policy_version = 'provider_freshness_v1'),
        rows_received INTEGER NOT NULL CHECK (rows_received >= 0),
        rows_accepted INTEGER NOT NULL CHECK (rows_accepted >= 0),
        rows_rejected INTEGER NOT NULL CHECK (rows_rejected >= 0),
        status TEXT NOT NULL CHECK (
            status IN (
                'completed', 'partial', 'rejected', 'empty',
                'checksum_mismatch', 'malformed_payload', 'failed'
            )
        ),
        failure_reason TEXT,
        recorded_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='recorded_at')}),
        CHECK (rows_accepted + rows_rejected <= rows_received),
        CHECK (
            (status IN ('completed', 'partial', 'rejected', 'empty')
             AND failure_reason IS NULL)
            OR (status IN ('checksum_mismatch', 'malformed_payload', 'failed')
                AND length(trim(failure_reason)) > 0)
        ),
        CHECK (
            (status = 'completed'
             AND rows_received > 0
             AND rows_accepted = rows_received
             AND rows_rejected = 0)
            OR (status = 'partial'
                AND rows_accepted > 0
                AND rows_rejected > 0
                AND rows_accepted + rows_rejected = rows_received)
            OR (status = 'rejected'
                AND rows_received > 0
                AND rows_accepted = 0
                AND rows_rejected = rows_received)
            OR (status = 'empty'
                AND rows_received = 0
                AND rows_accepted = 0
                AND rows_rejected = 0)
            OR (status IN ('checksum_mismatch', 'malformed_payload', 'failed')
                AND rows_accepted = 0
                AND rows_rejected = 0)
        )
    )
    """,
    f"""
    CREATE TABLE provider_ingestion_rejections (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ingestion_run_id INTEGER NOT NULL,
        record_index INTEGER NOT NULL CHECK (record_index >= 0),
        provider_record_id TEXT,
        rejection_code TEXT NOT NULL CHECK (
            rejection_code IN (
                'unknown_team', 'ambiguous_team_normalization',
                'malformed_spread', 'duplicate_record', 'invalid_timestamp',
                'stale_data', 'unsupported_market_type',
                'missing_matchup_identifier', 'reversed_matchup',
                'game_mapping_not_found', 'conflicting_game_mapping',
                'malformed_record'
            )
        ),
        rejection_reason TEXT NOT NULL CHECK (length(trim(rejection_reason)) > 0),
        raw_record_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='raw_record_sha256')}),
        raw_record TEXT NOT NULL CHECK (json_valid(raw_record)),
        rejected_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='rejected_at')}),
        UNIQUE (ingestion_run_id, record_index),
        FOREIGN KEY (ingestion_run_id) REFERENCES provider_ingestion_runs(id)
    )
    """,
    f"""
    CREATE TABLE provider_ingestion_acceptances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ingestion_run_id INTEGER NOT NULL,
        record_index INTEGER NOT NULL CHECK (record_index >= 0),
        provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
        data_type TEXT NOT NULL CHECK (
            data_type IN ('odds', 'injuries', 'weather', 'game_status', 'contextual')
        ),
        record_key TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='record_key')}),
        provider_record_id TEXT NOT NULL
            CHECK (length(trim(provider_record_id)) > 0),
        observed_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='observed_at')}),
        parser_version TEXT NOT NULL CHECK (length(trim(parser_version)) > 0),
        raw_record_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='raw_record_sha256')}),
        accepted_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='accepted_at')}),
        UNIQUE (ingestion_run_id, record_index),
        UNIQUE (provider, data_type, parser_version, record_key),
        FOREIGN KEY (ingestion_run_id) REFERENCES provider_ingestion_runs(id)
    )
    """,
    f"""
    CREATE TABLE provider_market_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        acceptance_id INTEGER NOT NULL UNIQUE,
        ingestion_run_id INTEGER NOT NULL,
        record_index INTEGER NOT NULL CHECK (record_index >= 0),
        provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
        provider_matchup_id TEXT NOT NULL
            CHECK (length(trim(provider_matchup_id)) > 0),
        game_id INTEGER NOT NULL,
        season INTEGER NOT NULL CHECK (season >= 1869),
        week INTEGER NOT NULL CHECK (week >= 0),
        raw_home_team TEXT NOT NULL CHECK (length(trim(raw_home_team)) > 0),
        raw_away_team TEXT NOT NULL CHECK (length(trim(raw_away_team)) > 0),
        normalized_home_team TEXT NOT NULL
            CHECK (length(trim(normalized_home_team)) > 0),
        normalized_away_team TEXT NOT NULL
            CHECK (length(trim(normalized_away_team)) > 0),
        bookmaker TEXT NOT NULL CHECK (length(trim(bookmaker)) > 0),
        market_type TEXT NOT NULL CHECK (market_type = 'spread'),
        home_spread REAL NOT NULL CHECK (
            typeof(home_spread) IN ('integer', 'real')
            AND home_spread >= -100 AND home_spread <= 100
        ),
        home_price INTEGER,
        observed_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='observed_at')}),
        event_start_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='event_start_at')}),
        parser_version TEXT NOT NULL CHECK (length(trim(parser_version)) > 0),
        raw_record_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='raw_record_sha256')}),
        ingested_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='ingested_at')}),
        CHECK (lower(trim(normalized_home_team)) != lower(trim(normalized_away_team))),
        CHECK (julianday(observed_at) <= julianday(event_start_at)),
        UNIQUE (ingestion_run_id, record_index),
        FOREIGN KEY (acceptance_id) REFERENCES provider_ingestion_acceptances(id),
        FOREIGN KEY (ingestion_run_id) REFERENCES provider_ingestion_runs(id),
        FOREIGN KEY (game_id) REFERENCES games(game_id)
    )
    """,
    f"""
    CREATE TABLE provider_data_snapshots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ingestion_run_id INTEGER NOT NULL UNIQUE,
        provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
        data_type TEXT NOT NULL CHECK (
            data_type IN ('odds', 'injuries', 'weather', 'game_status', 'contextual')
        ),
        earliest_observed_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='earliest_observed_at')}),
        latest_observed_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='latest_observed_at')}),
        expires_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='expires_at')}),
        freshness_policy_version TEXT NOT NULL
            CHECK (freshness_policy_version = 'provider_freshness_v1'),
        max_age_seconds INTEGER NOT NULL CHECK (max_age_seconds > 0),
        completeness TEXT NOT NULL CHECK (completeness IN ('complete', 'partial')),
        created_at TEXT NOT NULL
            CHECK ({_UTC_CHECK.format(column='created_at')}),
        CHECK (julianday(earliest_observed_at) <= julianday(latest_observed_at)),
        CHECK (
            (data_type = 'odds' AND max_age_seconds = 900)
            OR (data_type = 'injuries' AND max_age_seconds = 21600)
            OR (data_type = 'weather' AND max_age_seconds = 10800)
            OR (data_type = 'game_status' AND max_age_seconds = 300)
            OR (data_type = 'contextual' AND max_age_seconds = 86400)
        ),
        CHECK (
            abs(
                (julianday(expires_at) - julianday(earliest_observed_at)) * 86400
                - max_age_seconds
            ) < 1
        ),
        FOREIGN KEY (ingestion_run_id) REFERENCES provider_ingestion_runs(id)
    )
    """,
    """
    CREATE INDEX idx_provider_ingestion_runs_lookup
        ON provider_ingestion_runs (provider, data_type, requested_at, id)
    """,
    """
    CREATE INDEX idx_provider_ingestion_rejections_run
        ON provider_ingestion_rejections (ingestion_run_id, record_index)
    """,
    """
    CREATE INDEX idx_provider_ingestion_acceptances_run
        ON provider_ingestion_acceptances (ingestion_run_id, record_index)
    """,
    """
    CREATE INDEX idx_provider_market_snapshots_game
        ON provider_market_snapshots (game_id, observed_at, provider)
    """,
    """
    CREATE UNIQUE INDEX uq_provider_market_snapshots_observation
        ON provider_market_snapshots (
            provider, provider_matchup_id, bookmaker, observed_at, parser_version
        )
    """,
    """
    CREATE INDEX idx_provider_data_snapshots_freshness
        ON provider_data_snapshots (data_type, provider, expires_at)
    """,
    """
    CREATE TRIGGER provider_market_snapshots_validate_run
    BEFORE INSERT ON provider_market_snapshots
    WHEN NOT EXISTS (
        SELECT 1
        FROM provider_ingestion_runs AS run
        WHERE run.id = NEW.ingestion_run_id
          AND run.provider = NEW.provider
          AND run.parser_version = NEW.parser_version
          AND run.data_type = 'odds'
          AND run.status IN ('completed', 'partial')
    )
    BEGIN
        SELECT RAISE(ABORT, 'market snapshot does not match its accepted ingestion run');
    END
    """,
    """
    CREATE TRIGGER provider_ingestion_acceptances_validate_run
    BEFORE INSERT ON provider_ingestion_acceptances
    WHEN NOT EXISTS (
        SELECT 1
        FROM provider_ingestion_runs AS run
        WHERE run.id = NEW.ingestion_run_id
          AND run.provider = NEW.provider
          AND run.data_type = NEW.data_type
          AND run.parser_version = NEW.parser_version
          AND run.status IN ('completed', 'partial')
          AND NEW.record_index < run.rows_received
          AND julianday(NEW.observed_at) <= julianday(run.requested_at)
          AND (
              (NEW.data_type = 'odds'
               AND (julianday(run.requested_at) - julianday(NEW.observed_at)) * 86400 <= 900)
              OR (NEW.data_type = 'injuries'
                  AND (julianday(run.requested_at) - julianday(NEW.observed_at)) * 86400 <= 21600)
              OR (NEW.data_type = 'weather'
                  AND (julianday(run.requested_at) - julianday(NEW.observed_at)) * 86400 <= 10800)
              OR (NEW.data_type = 'game_status'
                  AND (julianday(run.requested_at) - julianday(NEW.observed_at)) * 86400 <= 300)
              OR (NEW.data_type = 'contextual'
                  AND (julianday(run.requested_at) - julianday(NEW.observed_at)) * 86400 <= 86400)
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'accepted record does not match its ingestion run');
    END
    """,
    """
    CREATE TRIGGER provider_ingestion_rejections_validate_run
    BEFORE INSERT ON provider_ingestion_rejections
    WHEN NOT EXISTS (
        SELECT 1
        FROM provider_ingestion_runs AS run
        WHERE run.id = NEW.ingestion_run_id
          AND run.status IN ('partial', 'rejected')
          AND NEW.record_index < run.rows_received
    )
    BEGIN
        SELECT RAISE(ABORT, 'rejected record does not match its ingestion run');
    END
    """,
    """
    CREATE TRIGGER provider_market_snapshots_validate_acceptance
    BEFORE INSERT ON provider_market_snapshots
    WHEN NOT EXISTS (
        SELECT 1
        FROM provider_ingestion_acceptances AS accepted
        WHERE accepted.id = NEW.acceptance_id
          AND accepted.ingestion_run_id = NEW.ingestion_run_id
          AND accepted.record_index = NEW.record_index
          AND accepted.provider = NEW.provider
          AND accepted.data_type = 'odds'
          AND accepted.provider_record_id = NEW.provider_matchup_id
          AND accepted.observed_at = NEW.observed_at
          AND accepted.parser_version = NEW.parser_version
          AND accepted.raw_record_sha256 = NEW.raw_record_sha256
    )
    BEGIN
        SELECT RAISE(ABORT, 'market snapshot does not match its accepted record');
    END
    """,
    """
    CREATE TRIGGER provider_market_snapshots_validate_game
    BEFORE INSERT ON provider_market_snapshots
    WHEN NOT EXISTS (
        SELECT 1
        FROM games
        WHERE game_id = NEW.game_id
          AND season = NEW.season
          AND week = NEW.week
          AND home_team = NEW.normalized_home_team
          AND away_team = NEW.normalized_away_team
    )
    BEGIN
        SELECT RAISE(ABORT, 'market snapshot game mapping is not canonical');
    END
    """,
    """
    CREATE TRIGGER provider_data_snapshots_validate_run
    BEFORE INSERT ON provider_data_snapshots
    WHEN NOT EXISTS (
        SELECT 1
        FROM provider_ingestion_runs AS run
        WHERE run.id = NEW.ingestion_run_id
          AND run.provider = NEW.provider
          AND run.data_type = NEW.data_type
          AND run.freshness_policy_version = NEW.freshness_policy_version
          AND run.status IN ('completed', 'partial')
          AND (
              (run.status = 'completed' AND NEW.completeness = 'complete')
              OR (run.status = 'partial' AND NEW.completeness = 'partial')
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'freshness snapshot does not match its ingestion run');
    END
    """,
)

for _table in (
    "provider_team_aliases",
    "provider_ingestion_runs",
    "provider_ingestion_rejections",
    "provider_ingestion_acceptances",
    "provider_market_snapshots",
    "provider_data_snapshots",
):
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
