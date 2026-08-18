"""Add authoritative weekly-controller and official-card publication custody."""

from __future__ import annotations

import sqlite3


VERSION = 14
NAME = "official_weekly_controller"

_UTC_CHECK = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"
_SHA256_CHECK = (
    "length({column}) = 64 AND lower({column}) NOT GLOB '*[^0-9a-f]*'"
)

STATEMENTS = (
    f"""
    CREATE TABLE weekly_controller_policies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        policy_version TEXT NOT NULL UNIQUE CHECK (length(trim(policy_version)) > 0),
        authorized_contest_source TEXT NOT NULL
            CHECK (authorized_contest_source = 'SplashSports'),
        production_model_name TEXT NOT NULL CHECK (production_model_name = 'epa_only'),
        production_model_version TEXT NOT NULL
            CHECK (production_model_version = 'epa-only-linear-v1'),
        production_feature_schema_version TEXT NOT NULL
            CHECK (production_feature_schema_version = 'epa-differential-v1'),
        production_configuration_version TEXT NOT NULL
            CHECK (production_configuration_version = 'walk-forward-prior-seasons-v1'),
        freshness_policy_version TEXT NOT NULL
            CHECK (freshness_policy_version = 'provider_freshness_v1'),
        required_source_count INTEGER NOT NULL CHECK (required_source_count = 5),
        effective_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='effective_at')}),
        created_by TEXT NOT NULL CHECK (length(trim(created_by)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    """
    CREATE TABLE weekly_controller_policy_sources (
        controller_policy_id INTEGER NOT NULL,
        source_order INTEGER NOT NULL CHECK (source_order > 0),
        data_type TEXT NOT NULL CHECK (
            data_type IN ('odds', 'injuries', 'weather', 'game_status', 'contextual')
        ),
        provider TEXT NOT NULL CHECK (length(trim(provider)) > 0),
        permitted_fallback_code TEXT NOT NULL
            CHECK (length(trim(permitted_fallback_code)) > 0),
        PRIMARY KEY (controller_policy_id, data_type),
        UNIQUE (controller_policy_id, source_order),
        FOREIGN KEY (controller_policy_id) REFERENCES weekly_controller_policies(id)
    )
    """,
    f"""
    CREATE TABLE weekly_controller_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_key TEXT NOT NULL UNIQUE CHECK (length(trim(run_key)) > 0),
        request_sha256 TEXT NOT NULL CHECK ({_SHA256_CHECK.format(column='request_sha256')}),
        controller_policy_id INTEGER,
        policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) > 0),
        operation TEXT NOT NULL CHECK (operation IN ('tuesday_lock', 'daily_refresh')),
        execution_mode TEXT NOT NULL CHECK (execution_mode IN ('persist', 'dry_run')),
        contest_id INTEGER,
        prior_publication_id INTEGER,
        card_id INTEGER,
        requested_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='requested_at')}),
        completed_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='completed_at')}),
        status TEXT NOT NULL CHECK (status IN ('completed', 'failed')),
        failure_reason TEXT,
        actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (julianday(completed_at) >= julianday(requested_at)),
        CHECK (
            (status = 'completed' AND controller_policy_id IS NOT NULL
             AND contest_id IS NOT NULL AND card_id IS NOT NULL
             AND failure_reason IS NULL)
            OR
            (status = 'failed' AND controller_policy_id IS NULL
             AND contest_id IS NULL AND card_id IS NULL
             AND length(trim(failure_reason)) > 0)
        ),
        CHECK (
            status = 'failed'
            OR operation = 'tuesday_lock' AND prior_publication_id IS NULL
            OR operation = 'daily_refresh' AND prior_publication_id IS NOT NULL
        ),
        FOREIGN KEY (controller_policy_id) REFERENCES weekly_controller_policies(id),
        FOREIGN KEY (contest_id) REFERENCES contests(id),
        FOREIGN KEY (prior_publication_id) REFERENCES official_card_publications(id),
        FOREIGN KEY (card_id) REFERENCES contest_cards(id)
    )
    """,
    f"""
    CREATE TABLE contest_line_lock_batches (
        controller_run_id INTEGER PRIMARY KEY,
        contest_id INTEGER NOT NULL UNIQUE,
        source TEXT NOT NULL CHECK (length(trim(source)) > 0),
        source_contest_id TEXT NOT NULL CHECK (length(trim(source_contest_id)) > 0),
        raw_payload_reference TEXT NOT NULL
            CHECK (length(trim(raw_payload_reference)) > 0),
        payload_sha256 TEXT NOT NULL CHECK ({_SHA256_CHECK.format(column='payload_sha256')}),
        expected_lined_game_count INTEGER NOT NULL CHECK (expected_lined_game_count > 0),
        imported_line_count INTEGER NOT NULL CHECK (imported_line_count > 0),
        locked_line_count INTEGER NOT NULL CHECK (locked_line_count > 0),
        locked_line_snapshot_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='locked_line_snapshot_sha256')}),
        captured_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='captured_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            expected_lined_game_count = imported_line_count
            AND imported_line_count = locked_line_count
        ),
        FOREIGN KEY (controller_run_id) REFERENCES weekly_controller_runs(id),
        FOREIGN KEY (contest_id) REFERENCES contests(id)
    )
    """,
    f"""
    CREATE TABLE card_source_freshness (
        card_id INTEGER NOT NULL,
        controller_run_id INTEGER NOT NULL,
        data_type TEXT NOT NULL CHECK (
            data_type IN ('odds', 'injuries', 'weather', 'game_status', 'contextual')
        ),
        provider TEXT,
        state TEXT NOT NULL CHECK (state IN ('current', 'partial', 'stale', 'missing')),
        ingestion_run_id INTEGER,
        observed_at TEXT CHECK (
            observed_at IS NULL OR ({_UTC_CHECK.format(column='observed_at')})
        ),
        expires_at TEXT CHECK (
            expires_at IS NULL OR ({_UTC_CHECK.format(column='expires_at')})
        ),
        freshness_policy_version TEXT NOT NULL
            CHECK (freshness_policy_version = 'provider_freshness_v1'),
        fallback_code TEXT,
        fallback_reason TEXT,
        fallback_evidence TEXT,
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        PRIMARY KEY (card_id, data_type),
        FOREIGN KEY (card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (controller_run_id) REFERENCES weekly_controller_runs(id),
        FOREIGN KEY (ingestion_run_id) REFERENCES provider_ingestion_runs(id)
    )
    """,
    f"""
    CREATE TABLE official_card_publications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        publication_key TEXT NOT NULL UNIQUE CHECK (length(trim(publication_key)) > 0),
        controller_run_id INTEGER NOT NULL UNIQUE,
        card_id INTEGER NOT NULL UNIQUE,
        contest_id INTEGER NOT NULL,
        card_version INTEGER NOT NULL CHECK (card_version > 0),
        published_at TEXT NOT NULL CHECK ({_UTC_CHECK.format(column='published_at')}),
        locked_line_snapshot_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='locked_line_snapshot_sha256')}),
        publication_manifest_sha256 TEXT NOT NULL
            CHECK ({_SHA256_CHECK.format(column='publication_manifest_sha256')}),
        expected_locked_line_count INTEGER NOT NULL CHECK (expected_locked_line_count > 0),
        pick_count INTEGER NOT NULL CHECK (pick_count > 0),
        top_five_count INTEGER NOT NULL CHECK (top_five_count BETWEEN 1 AND 5),
        fallback_pick_count INTEGER NOT NULL CHECK (fallback_pick_count >= 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (contest_id, card_version),
        FOREIGN KEY (controller_run_id) REFERENCES weekly_controller_runs(id),
        FOREIGN KEY (card_id) REFERENCES contest_cards(id),
        FOREIGN KEY (contest_id) REFERENCES contests(id)
    )
    """,
    """
    CREATE INDEX idx_weekly_controller_runs_contest
    ON weekly_controller_runs (contest_id, requested_at, id)
    """,
    """
    CREATE INDEX idx_card_source_freshness_run
    ON card_source_freshness (controller_run_id, data_type)
    """,
    """
    CREATE INDEX idx_official_card_publications_contest
    ON official_card_publications (contest_id, card_version)
    """,
    """
    CREATE TRIGGER weekly_controller_policy_sources_validate
    BEFORE INSERT ON weekly_controller_policy_sources
    WHEN NOT EXISTS (
        SELECT 1 FROM weekly_controller_policies AS policy
        WHERE policy.id = NEW.controller_policy_id
          AND NEW.source_order <= policy.required_source_count
    )
    BEGIN
        SELECT RAISE(ABORT, 'controller policy source exceeds the declared source count');
    END
    """,
    """
    CREATE TRIGGER weekly_controller_runs_validate_completed
    BEFORE INSERT ON weekly_controller_runs
    WHEN NEW.status = 'completed' AND NOT EXISTS (
        SELECT 1
        FROM weekly_controller_policies AS policy
        JOIN contest_cards AS card ON card.id = NEW.card_id
        JOIN model_runs AS model ON model.id = card.model_run_id
        WHERE policy.id = NEW.controller_policy_id
          AND policy.policy_version = NEW.policy_version
          AND policy.production_model_name = model.model_name
          AND policy.production_model_version = model.model_version
          AND policy.production_feature_schema_version = model.feature_schema_version
          AND policy.production_configuration_version = model.configuration_version
          AND policy.required_source_count = (
              SELECT COUNT(*) FROM weekly_controller_policy_sources AS source
              WHERE source.controller_policy_id = policy.id
          )
          AND card.contest_id = NEW.contest_id
          AND card.generated_at = NEW.requested_at
          AND julianday(policy.effective_at) <= julianday(NEW.requested_at)
          AND (
              NEW.operation = 'tuesday_lock'
              OR EXISTS (
                  SELECT 1 FROM official_card_publications AS prior
                  WHERE prior.id = NEW.prior_publication_id
                    AND prior.contest_id = NEW.contest_id
                    AND prior.card_version + 1 = card.version
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'completed controller run lacks valid policy, model, card, or revision provenance');
    END
    """,
    """
    CREATE TRIGGER contest_line_lock_batches_validate
    BEFORE INSERT ON contest_line_lock_batches
    WHEN NOT EXISTS (
        SELECT 1
        FROM weekly_controller_runs AS run
        JOIN weekly_controller_policies AS policy ON policy.id = run.controller_policy_id
        JOIN contests AS contest ON contest.id = NEW.contest_id
        WHERE run.id = NEW.controller_run_id
          AND run.status = 'completed'
          AND run.operation = 'tuesday_lock'
          AND run.contest_id = NEW.contest_id
          AND policy.authorized_contest_source = NEW.source
          AND contest.source = NEW.source
          AND contest.source_contest_id IS NEW.source_contest_id
          AND NEW.locked_line_count = (
              SELECT COUNT(*) FROM contest_locked_lines AS locked
              WHERE locked.contest_id = NEW.contest_id
          )
          AND NOT EXISTS (
              SELECT 1 FROM contest_locked_lines AS locked
              WHERE locked.contest_id = NEW.contest_id
                AND (locked.source != NEW.source OR locked.payload_sha256 != NEW.payload_sha256)
          )
          AND NEW.locked_line_count = (
              SELECT COUNT(DISTINCT locked.source_line_id)
              FROM contest_locked_lines AS locked
              WHERE locked.contest_id = NEW.contest_id
          )
          AND NOT EXISTS (
              SELECT 1
              FROM contest_locked_lines AS locked
              LEFT JOIN games AS game
                ON game.game_id = locked.game_id
               AND game.season = locked.season
               AND game.week = locked.week
               AND game.home_team = locked.normalized_home_team
               AND game.away_team = locked.normalized_away_team
              WHERE locked.contest_id = NEW.contest_id
                AND (locked.game_id IS NULL OR locked.source_line_id IS NULL
                     OR game.game_id IS NULL)
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'line-lock batch does not match the authorized immutable contest snapshot');
    END
    """,
    """
    CREATE TRIGGER card_source_freshness_validate
    BEFORE INSERT ON card_source_freshness
    WHEN NOT EXISTS (
        SELECT 1
        FROM weekly_controller_runs AS run
        JOIN weekly_controller_policy_sources AS required
          ON required.controller_policy_id = run.controller_policy_id
         AND required.data_type = NEW.data_type
        JOIN contest_cards AS card ON card.id = NEW.card_id
        WHERE run.id = NEW.controller_run_id
          AND run.status = 'completed'
          AND run.card_id = NEW.card_id
          AND required.provider IS NEW.provider
          AND (
              NEW.state = 'current'
              AND NEW.fallback_code IS NULL
              AND NEW.fallback_reason IS NULL
              AND NEW.fallback_evidence IS NULL
              AND NEW.ingestion_run_id IS NOT NULL
              OR
              NEW.state != 'current'
              AND NEW.fallback_code = required.permitted_fallback_code
              AND length(trim(NEW.fallback_reason)) > 0
              AND length(trim(NEW.fallback_evidence)) > 0
          )
          AND (
              NEW.state = 'missing' AND NEW.ingestion_run_id IS NULL
              AND NEW.observed_at IS NULL AND NEW.expires_at IS NULL
              OR
              NEW.state != 'missing' AND NEW.ingestion_run_id IS NOT NULL
              AND EXISTS (
                  SELECT 1
                  FROM provider_ingestion_runs AS ingestion
                  JOIN provider_data_snapshots AS snapshot
                    ON snapshot.ingestion_run_id = ingestion.id
                  WHERE ingestion.id = NEW.ingestion_run_id
                    AND ingestion.data_type = NEW.data_type
                    AND ingestion.provider = NEW.provider
                    AND snapshot.earliest_observed_at = NEW.observed_at
                    AND snapshot.expires_at = NEW.expires_at
                    AND snapshot.freshness_policy_version = NEW.freshness_policy_version
                    AND julianday(ingestion.requested_at) <= julianday(card.generated_at)
                    AND (
                        NEW.state = 'current'
                        AND snapshot.completeness = 'complete'
                        AND julianday(snapshot.expires_at) >= julianday(card.generated_at)
                        OR NEW.state = 'partial'
                        AND snapshot.completeness = 'partial'
                        AND julianday(snapshot.expires_at) >= julianday(card.generated_at)
                        OR NEW.state = 'stale'
                        AND julianday(snapshot.expires_at) < julianday(card.generated_at)
                    )
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'card source freshness lacks current custody or a permitted explicit fallback');
    END
    """,
    """
    CREATE TRIGGER official_card_publications_validate
    BEFORE INSERT ON official_card_publications
    WHEN NOT EXISTS (
        SELECT 1
        FROM weekly_controller_runs AS run
        JOIN weekly_controller_policies AS policy ON policy.id = run.controller_policy_id
        JOIN contest_cards AS card ON card.id = NEW.card_id
        JOIN card_run_manifests AS manifest ON manifest.card_id = card.id
        JOIN contest_line_lock_batches AS batch ON batch.contest_id = card.contest_id
        WHERE run.id = NEW.controller_run_id
          AND run.status = 'completed'
          AND run.execution_mode IN ('persist', 'dry_run')
          AND run.card_id = NEW.card_id
          AND run.contest_id = NEW.contest_id
          AND card.contest_id = NEW.contest_id
          AND card.version = NEW.card_version
          AND card.status = 'draft'
          AND card.generated_at = NEW.published_at
          AND card.locked_line_snapshot_sha256 = NEW.locked_line_snapshot_sha256
          AND manifest.locked_line_snapshot_sha256 = NEW.locked_line_snapshot_sha256
          AND batch.locked_line_snapshot_sha256 = (
              SELECT first_card.locked_line_snapshot_sha256
              FROM contest_cards AS first_card
              WHERE first_card.contest_id = NEW.contest_id AND first_card.version = 1
          )
          AND NEW.expected_locked_line_count = (
              SELECT COUNT(*) FROM contest_locked_lines AS locked
              WHERE locked.contest_id = NEW.contest_id
                AND julianday(locked.locked_at) <= julianday(card.generated_at)
          )
          AND NEW.pick_count = NEW.expected_locked_line_count
          AND NEW.pick_count = (
              SELECT COUNT(*) FROM contest_picks AS pick WHERE pick.card_id = card.id
          )
          AND NOT EXISTS (
              SELECT 1 FROM contest_picks AS pick
              WHERE pick.card_id = card.id
                AND (pick.selected_side NOT IN ('home', 'away')
                     OR pick.confidence NOT BETWEEN 1 AND 5
                     OR length(trim(pick.provenance)) = 0)
          )
          AND NEW.top_five_count = CASE
              WHEN NEW.expected_locked_line_count >= 5 THEN 5
              ELSE NEW.expected_locked_line_count END
          AND NEW.top_five_count = (
              SELECT COUNT(*) FROM contest_picks AS pick
              WHERE pick.card_id = card.id AND pick.is_top_five = 1
          )
          AND NEW.top_five_count = (
              SELECT COUNT(*) FROM contest_picks AS pick
              WHERE pick.card_id = card.id AND pick.rank IS NOT NULL
          )
          AND NEW.top_five_count = (
              SELECT COUNT(DISTINCT pick.rank) FROM contest_picks AS pick
              WHERE pick.card_id = card.id AND pick.rank IS NOT NULL
          )
          AND 1 = (
              SELECT MIN(pick.rank) FROM contest_picks AS pick
              WHERE pick.card_id = card.id AND pick.rank IS NOT NULL
          )
          AND NEW.top_five_count = (
              SELECT MAX(pick.rank) FROM contest_picks AS pick
              WHERE pick.card_id = card.id AND pick.rank IS NOT NULL
          )
          AND NEW.fallback_pick_count = (
              SELECT COUNT(*) FROM contest_picks AS pick
              WHERE pick.card_id = card.id AND pick.fallback_code IS NOT NULL
          )
          AND EXISTS (
              SELECT 1 FROM contest_card_policy_assignments AS assignment
              WHERE assignment.card_id = card.id
          )
          AND EXISTS (
              SELECT 1 FROM card_adjustment_policy_assignments AS assignment
              WHERE assignment.card_id = card.id
          )
          AND policy.required_source_count = (
              SELECT COUNT(*) FROM card_source_freshness AS freshness
              WHERE freshness.card_id = card.id
                AND freshness.controller_run_id = run.id
          )
          AND (
              run.operation = 'tuesday_lock' AND card.version = 1
              OR run.operation = 'daily_refresh'
              AND EXISTS (
                  SELECT 1
                  FROM official_card_publications AS prior
                  JOIN card_revisions AS revision
                    ON revision.prior_card_id = prior.card_id
                   AND revision.revised_card_id = card.id
                  WHERE prior.id = run.prior_publication_id
                    AND prior.contest_id = card.contest_id
                    AND prior.card_version + 1 = card.version
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'official publication failed completeness, provenance, freshness, policy, or revision gates');
    END
    """,
    """
    CREATE TRIGGER official_card_recommendations_close_after_publication
    BEFORE INSERT ON sportsbook_recommendations
    WHEN NEW.contest_pick_id IS NOT NULL AND EXISTS (
        SELECT 1
        FROM contest_picks AS pick
        JOIN official_card_publications AS publication ON publication.card_id = pick.card_id
        WHERE pick.id = NEW.contest_pick_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'official card sportsbook recommendations are closed after publication');
    END
    """,
)


IMMUTABLE_TABLES = (
    (
        "weekly_controller_policies",
        "id = NEW.id OR policy_version = NEW.policy_version",
    ),
    (
        "weekly_controller_policy_sources",
        "(controller_policy_id = NEW.controller_policy_id "
        "AND (data_type = NEW.data_type OR source_order = NEW.source_order))",
    ),
    ("weekly_controller_runs", "id = NEW.id OR run_key = NEW.run_key"),
    (
        "contest_line_lock_batches",
        "controller_run_id = NEW.controller_run_id OR contest_id = NEW.contest_id",
    ),
    (
        "card_source_freshness",
        "card_id = NEW.card_id AND data_type = NEW.data_type",
    ),
    (
        "official_card_publications",
        "id = NEW.id OR publication_key = NEW.publication_key "
        "OR controller_run_id = NEW.controller_run_id OR card_id = NEW.card_id "
        "OR (contest_id = NEW.contest_id AND card_version = NEW.card_version)",
    ),
)

for _table, _match in IMMUTABLE_TABLES:
    STATEMENTS += (
        f"""
        CREATE TRIGGER {_table}_no_duplicate_insert
        BEFORE INSERT ON {_table}
        WHEN EXISTS (
            SELECT 1 FROM {_table}
            WHERE {_match}
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
