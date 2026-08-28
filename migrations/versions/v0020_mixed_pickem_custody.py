"""Add dormant Product B contest, spreadsheet-custody, and line-lock tables.

The migration is additive. It seeds only the mixed Pick'em product registry and
its NCAA/NFL allow-list. No source slate, contest season, round, manifest,
approval, deadline, or line lock is created by the migration.
"""

from __future__ import annotations

import sqlite3


VERSION = 20
NAME = "mixed_pickem_custody"

_UTC = "julianday({column}) IS NOT NULL AND substr({column}, -6) = '+00:00'"
_SHA256 = (
    "length({column}) = 64 AND {column} = lower({column}) "
    "AND {column} NOT GLOB '*[^0-9a-f]*'"
)
_KEY = (
    "length({column}) > 0 AND {column} = lower(trim({column})) "
    "AND {column} NOT GLOB '*[^a-z0-9_-]*'"
)


STATEMENTS = (
    f"""
    CREATE TABLE mixed_contest_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_key TEXT NOT NULL UNIQUE CHECK ({_KEY.format(column='product_key')}),
        display_name TEXT NOT NULL CHECK (length(trim(display_name)) > 0),
        line_authority TEXT NOT NULL CHECK (length(trim(line_authority)) > 0),
        policy_namespace TEXT NOT NULL CHECK ({_KEY.format(column='policy_namespace')}),
        created_at TEXT NOT NULL CHECK ({_UTC.format(column='created_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0)
    )
    """,
    f"""
    CREATE TABLE mixed_contest_product_sports (
        product_id INTEGER NOT NULL,
        sport_code TEXT NOT NULL,
        created_at TEXT NOT NULL CHECK ({_UTC.format(column='created_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        PRIMARY KEY (product_id, sport_code),
        FOREIGN KEY (product_id) REFERENCES mixed_contest_products(id),
        FOREIGN KEY (sport_code) REFERENCES football_sports(sport_code)
    )
    """,
    """
    INSERT INTO mixed_contest_products
        (product_key, display_name, line_authority, policy_namespace,
         created_at, provenance)
    VALUES
        ('mixed_pickem', 'Mixed NCAA + NFL ATS Pick''em',
         'weekly_administrator_spreadsheet', 'mixed_pickem',
         '2026-08-28T00:00:00+00:00',
         'migration:v0020:approved-phase-0-product-b')
    """,
    """
    INSERT INTO mixed_contest_product_sports
        (product_id, sport_code, created_at, provenance)
    SELECT id, sport_code, '2026-08-28T00:00:00+00:00',
           'migration:v0020:approved-phase-0-product-b'
    FROM mixed_contest_products
    CROSS JOIN (SELECT 'NCAA' AS sport_code UNION ALL SELECT 'NFL')
    WHERE product_key = 'mixed_pickem'
    """,
    f"""
    CREATE TABLE mixed_contest_seasons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        season_key TEXT NOT NULL CHECK ({_KEY.format(column='season_key')}),
        display_label TEXT NOT NULL CHECK (length(trim(display_label)) > 0),
        planned_round_count INTEGER NOT NULL
            CHECK (planned_round_count >= 1 AND planned_round_count <= 100),
        policy_version TEXT NOT NULL CHECK (length(trim(policy_version)) > 0),
        initial_state TEXT NOT NULL
            CHECK (initial_state IN ('PLANNED', 'ACTIVE', 'INACTIVE')),
        created_at TEXT NOT NULL CHECK ({_UTC.format(column='created_at')}),
        actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (product_id, season_key),
        FOREIGN KEY (product_id) REFERENCES mixed_contest_products(id)
    )
    """,
    f"""
    CREATE TABLE mixed_contest_rounds (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_season_id INTEGER NOT NULL,
        round_number INTEGER NOT NULL CHECK (round_number >= 1),
        round_label TEXT NOT NULL CHECK (length(trim(round_label)) > 0),
        created_at TEXT NOT NULL CHECK ({_UTC.format(column='created_at')}),
        actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (contest_season_id, round_number),
        FOREIGN KEY (contest_season_id) REFERENCES mixed_contest_seasons(id)
    )
    """,
    """
    CREATE TRIGGER mixed_contest_rounds_validate_number
    BEFORE INSERT ON mixed_contest_rounds
    WHEN NOT EXISTS (
        SELECT 1 FROM mixed_contest_seasons AS season
        WHERE season.id = NEW.contest_season_id
          AND NEW.round_number <= season.planned_round_count
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed contest round exceeds its season policy');
    END
    """,
    f"""
    CREATE TABLE mixed_slate_imports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_key TEXT NOT NULL UNIQUE CHECK ({_KEY.format(column='import_key')}),
        product_id INTEGER NOT NULL,
        contest_season_id INTEGER NOT NULL,
        contest_round_id INTEGER NOT NULL,
        source_media_type TEXT NOT NULL CHECK (
            source_media_type IN ('CSV', 'XLSX', 'REVIEWED_TRANSCRIPTION')
        ),
        original_filename TEXT NOT NULL CHECK (
            length(trim(original_filename)) > 0
            AND instr(original_filename, '/') = 0
            AND instr(original_filename, '\\') = 0
        ),
        source_sha256 TEXT NOT NULL CHECK ({_SHA256.format(column='source_sha256')}),
        parser_version TEXT NOT NULL CHECK (length(trim(parser_version)) > 0),
        selected_worksheet TEXT CHECK (
            selected_worksheet IS NULL OR length(trim(selected_worksheet)) > 0
        ),
        resolution_window_start_at TEXT NOT NULL
            CHECK ({_UTC.format(column='resolution_window_start_at')}),
        resolution_window_end_at TEXT NOT NULL
            CHECK ({_UTC.format(column='resolution_window_end_at')}),
        expected_source_row_count INTEGER
            CHECK (expected_source_row_count IS NULL OR expected_source_row_count >= 1),
        received_at TEXT NOT NULL CHECK ({_UTC.format(column='received_at')}),
        imported_at TEXT NOT NULL CHECK ({_UTC.format(column='imported_at')}),
        actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        overall_status TEXT NOT NULL CHECK (
            overall_status IN ('RESOLVED', 'NEEDS_REVIEW', 'AMBIGUOUS', 'REJECTED')
        ),
        CHECK (
            julianday(resolution_window_start_at)
                < julianday(resolution_window_end_at)
        ),
        CHECK (julianday(imported_at) >= julianday(received_at)),
        CHECK (
            (source_media_type = 'XLSX' AND selected_worksheet IS NOT NULL)
            OR (source_media_type != 'XLSX' AND selected_worksheet IS NULL)
        ),
        FOREIGN KEY (product_id) REFERENCES mixed_contest_products(id),
        FOREIGN KEY (contest_season_id) REFERENCES mixed_contest_seasons(id),
        FOREIGN KEY (contest_round_id) REFERENCES mixed_contest_rounds(id)
    )
    """,
    """
    CREATE INDEX idx_mixed_slate_imports_source_identity
    ON mixed_slate_imports (
        contest_round_id, source_sha256, parser_version,
        COALESCE(selected_worksheet, '')
    )
    """,
    """
    CREATE TRIGGER mixed_slate_imports_validate_scope
    BEFORE INSERT ON mixed_slate_imports
    WHEN NOT EXISTS (
        SELECT 1
        FROM mixed_contest_products AS product
        JOIN mixed_contest_seasons AS season ON season.product_id = product.id
        JOIN mixed_contest_rounds AS round
          ON round.contest_season_id = season.id
        WHERE product.id = NEW.product_id
          AND product.product_key = 'mixed_pickem'
          AND season.id = NEW.contest_season_id
          AND round.id = NEW.contest_round_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed slate import product, season, and round disagree');
    END
    """,
    f"""
    CREATE TABLE mixed_slate_import_states (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_id INTEGER NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        state TEXT NOT NULL CHECK (
            state IN (
                'RECEIVED', 'PARSED', 'RESOLVED', 'NEEDS_REVIEW',
                'AMBIGUOUS', 'REJECTED'
            )
        ),
        supersedes_state_id INTEGER UNIQUE,
        recorded_at TEXT NOT NULL CHECK ({_UTC.format(column='recorded_at')}),
        actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
        detail TEXT NOT NULL CHECK (length(trim(detail)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (import_id, sequence),
        FOREIGN KEY (import_id) REFERENCES mixed_slate_imports(id),
        FOREIGN KEY (supersedes_state_id) REFERENCES mixed_slate_import_states(id)
    )
    """,
    """
    CREATE TRIGGER mixed_slate_import_states_validate_chain
    BEFORE INSERT ON mixed_slate_import_states
    WHEN NOT (
        (
            NEW.sequence = 1
            AND NEW.state = 'RECEIVED'
            AND NEW.supersedes_state_id IS NULL
            AND NOT EXISTS (
                SELECT 1 FROM mixed_slate_import_states
                WHERE import_id = NEW.import_id
            )
        )
        OR EXISTS (
            SELECT 1
            FROM mixed_slate_import_states AS prior
            JOIN mixed_slate_imports AS import ON import.id = NEW.import_id
            WHERE prior.id = NEW.supersedes_state_id
              AND prior.import_id = NEW.import_id
              AND prior.sequence = NEW.sequence - 1
              AND prior.sequence = (
                  SELECT MAX(latest.sequence)
                  FROM mixed_slate_import_states AS latest
                  WHERE latest.import_id = NEW.import_id
              )
              AND julianday(NEW.recorded_at) >= julianday(prior.recorded_at)
              AND (
                  (prior.state = 'RECEIVED' AND NEW.state IN ('PARSED', 'REJECTED'))
                  OR (
                      prior.state = 'PARSED'
                      AND NEW.state IN (
                          'RESOLVED', 'NEEDS_REVIEW', 'AMBIGUOUS', 'REJECTED'
                      )
                  )
              )
              AND (
                  NEW.state NOT IN (
                      'RESOLVED', 'NEEDS_REVIEW', 'AMBIGUOUS', 'REJECTED'
                  )
                  OR NEW.state = import.overall_status
              )
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed slate import state transition is invalid');
    END
    """,
    f"""
    CREATE TABLE mixed_slate_import_rows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_id INTEGER NOT NULL,
        source_row_number INTEGER NOT NULL CHECK (source_row_number >= 1),
        source_order INTEGER NOT NULL CHECK (source_order >= 1),
        raw_row_json TEXT NOT NULL CHECK (json_valid(raw_row_json)),
        raw_away_team TEXT,
        raw_home_team TEXT,
        raw_spread_text TEXT,
        raw_spread_side TEXT,
        normalized_spread_side TEXT CHECK (
            normalized_spread_side IS NULL
            OR normalized_spread_side IN ('HOME', 'AWAY')
        ),
        parsed_displayed_spread_millipoints INTEGER CHECK (
            parsed_displayed_spread_millipoints IS NULL
            OR (
                parsed_displayed_spread_millipoints BETWEEN -100000 AND 100000
                AND parsed_displayed_spread_millipoints % 500 = 0
            )
        ),
        raw_sport_hint TEXT,
        raw_kickoff TEXT,
        parsed_kickoff_at TEXT CHECK (
            parsed_kickoff_at IS NULL
            OR ({_UTC.format(column='parsed_kickoff_at')})
        ),
        raw_source_event_id TEXT,
        raw_notes TEXT,
        row_sha256 TEXT NOT NULL CHECK ({_SHA256.format(column='row_sha256')}),
        parse_state TEXT NOT NULL CHECK (
            parse_state IN ('PARSED', 'NEEDS_REVIEW', 'REJECTED')
        ),
        error_codes_json TEXT NOT NULL CHECK (json_valid(error_codes_json)),
        UNIQUE (import_id, source_row_number),
        UNIQUE (import_id, source_order),
        FOREIGN KEY (import_id) REFERENCES mixed_slate_imports(id)
    )
    """,
    f"""
    CREATE TABLE mixed_slate_manifests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        import_id INTEGER NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        supersedes_manifest_id INTEGER UNIQUE,
        product_id INTEGER NOT NULL,
        contest_season_id INTEGER NOT NULL,
        contest_round_id INTEGER NOT NULL,
        source_sha256 TEXT NOT NULL CHECK ({_SHA256.format(column='source_sha256')}),
        parser_version TEXT NOT NULL CHECK (length(trim(parser_version)) > 0),
        expected_source_row_count INTEGER NOT NULL
            CHECK (expected_source_row_count >= 1),
        source_row_count INTEGER NOT NULL CHECK (source_row_count >= 1),
        accepted_count INTEGER NOT NULL CHECK (accepted_count >= 0),
        rejected_count INTEGER NOT NULL CHECK (rejected_count >= 0),
        ambiguous_count INTEGER NOT NULL CHECK (ambiguous_count >= 0),
        duplicate_count INTEGER NOT NULL CHECK (duplicate_count >= 0),
        ordered_canonical_row_set_sha256 TEXT NOT NULL
            CHECK ({_SHA256.format(column='ordered_canonical_row_set_sha256')}),
        manifest_sha256 TEXT NOT NULL UNIQUE
            CHECK ({_SHA256.format(column='manifest_sha256')}),
        lifecycle_state TEXT NOT NULL CHECK (
            lifecycle_state IN (
                'MANIFEST_READY', 'NEEDS_REVIEW', 'AMBIGUOUS', 'REJECTED'
            )
        ),
        generated_at TEXT NOT NULL CHECK ({_UTC.format(column='generated_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (
            accepted_count + rejected_count + ambiguous_count = source_row_count
        ),
        CHECK (duplicate_count <= rejected_count),
        CHECK (
            lifecycle_state != 'MANIFEST_READY'
            OR (
                accepted_count = source_row_count
                AND source_row_count = expected_source_row_count
                AND rejected_count = 0
                AND ambiguous_count = 0
                AND duplicate_count = 0
            )
        ),
        UNIQUE (import_id, sequence),
        FOREIGN KEY (import_id) REFERENCES mixed_slate_imports(id),
        FOREIGN KEY (supersedes_manifest_id) REFERENCES mixed_slate_manifests(id),
        FOREIGN KEY (product_id) REFERENCES mixed_contest_products(id),
        FOREIGN KEY (contest_season_id) REFERENCES mixed_contest_seasons(id),
        FOREIGN KEY (contest_round_id) REFERENCES mixed_contest_rounds(id)
    )
    """,
    """
    CREATE TRIGGER mixed_slate_manifests_validate_scope_chain
    BEFORE INSERT ON mixed_slate_manifests
    WHEN NOT EXISTS (
        SELECT 1
        FROM mixed_slate_imports AS import
        WHERE import.id = NEW.import_id
          AND import.product_id = NEW.product_id
          AND import.contest_season_id = NEW.contest_season_id
          AND import.contest_round_id = NEW.contest_round_id
          AND import.source_sha256 = NEW.source_sha256
          AND import.parser_version = NEW.parser_version
          AND (
              (
                  NEW.sequence = 1
                  AND NEW.supersedes_manifest_id IS NULL
                  AND NOT EXISTS (
                      SELECT 1 FROM mixed_slate_manifests
                      WHERE import_id = NEW.import_id
                  )
              )
              OR EXISTS (
                  SELECT 1 FROM mixed_slate_manifests AS prior
                  WHERE prior.id = NEW.supersedes_manifest_id
                    AND prior.import_id = NEW.import_id
                    AND prior.sequence = NEW.sequence - 1
                    AND prior.sequence = (
                        SELECT MAX(latest.sequence)
                        FROM mixed_slate_manifests AS latest
                        WHERE latest.import_id = NEW.import_id
                    )
                    AND julianday(NEW.generated_at) >= julianday(prior.generated_at)
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed manifest scope, source, or revision chain is invalid');
    END
    """,
    f"""
    CREATE TABLE mixed_slate_manifest_rows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        manifest_id INTEGER NOT NULL,
        import_row_id INTEGER NOT NULL,
        source_order INTEGER NOT NULL CHECK (source_order >= 1),
        raw_away_team TEXT,
        raw_home_team TEXT,
        raw_spread_text TEXT,
        raw_spread_side TEXT,
        sport_code TEXT,
        football_event_id INTEGER,
        canonical_home_team_id INTEGER,
        canonical_away_team_id INTEGER,
        canonical_home_team_name TEXT,
        canonical_away_team_name TEXT,
        canonical_kickoff_at TEXT CHECK (
            canonical_kickoff_at IS NULL
            OR ({_UTC.format(column='canonical_kickoff_at')})
        ),
        event_revision_id INTEGER,
        home_spread_millipoints INTEGER CHECK (
            home_spread_millipoints IS NULL
            OR (
                home_spread_millipoints BETWEEN -100000 AND 100000
                AND home_spread_millipoints % 500 = 0
            )
        ),
        resolution_state TEXT NOT NULL CHECK (
            resolution_state IN ('ACCEPTED', 'REJECTED', 'AMBIGUOUS', 'UNRESOLVED')
        ),
        resolution_method TEXT NOT NULL CHECK (
            resolution_method IN (
                'PROVIDER_EVENT_ID', 'CANONICAL_TEAM_PAIR',
                'PROVIDER_ALIAS', 'NONE'
            )
        ),
        resolution_evidence_json TEXT NOT NULL
            CHECK (json_valid(resolution_evidence_json)),
        warning_codes_json TEXT NOT NULL CHECK (json_valid(warning_codes_json)),
        error_codes_json TEXT NOT NULL CHECK (json_valid(error_codes_json)),
        source_row_sha256 TEXT NOT NULL
            CHECK ({_SHA256.format(column='source_row_sha256')}),
        canonical_row_sha256 TEXT NOT NULL
            CHECK ({_SHA256.format(column='canonical_row_sha256')}),
        CHECK (
            resolution_state != 'ACCEPTED'
            OR (
                sport_code IS NOT NULL
                AND football_event_id IS NOT NULL
                AND canonical_home_team_id IS NOT NULL
                AND canonical_away_team_id IS NOT NULL
                AND canonical_home_team_name IS NOT NULL
                AND canonical_away_team_name IS NOT NULL
                AND canonical_kickoff_at IS NOT NULL
                AND home_spread_millipoints IS NOT NULL
                AND json_array_length(error_codes_json) = 0
            )
        ),
        UNIQUE (manifest_id, import_row_id),
        UNIQUE (manifest_id, source_order),
        UNIQUE (manifest_id, canonical_row_sha256),
        FOREIGN KEY (manifest_id) REFERENCES mixed_slate_manifests(id),
        FOREIGN KEY (import_row_id) REFERENCES mixed_slate_import_rows(id),
        FOREIGN KEY (sport_code) REFERENCES football_sports(sport_code),
        FOREIGN KEY (football_event_id) REFERENCES football_events(id),
        FOREIGN KEY (canonical_home_team_id) REFERENCES football_teams(id),
        FOREIGN KEY (canonical_away_team_id) REFERENCES football_teams(id),
        FOREIGN KEY (event_revision_id) REFERENCES football_event_revisions(id)
    )
    """,
    """
    CREATE TRIGGER mixed_slate_manifest_rows_validate_source_event
    BEFORE INSERT ON mixed_slate_manifest_rows
    WHEN NOT EXISTS (
        SELECT 1
        FROM mixed_slate_manifests AS manifest
        JOIN mixed_slate_import_rows AS source_row
          ON source_row.id = NEW.import_row_id
         AND source_row.import_id = manifest.import_id
        WHERE manifest.id = NEW.manifest_id
          AND source_row.source_order = NEW.source_order
          AND source_row.row_sha256 = NEW.source_row_sha256
          AND source_row.raw_away_team IS NEW.raw_away_team
          AND source_row.raw_home_team IS NEW.raw_home_team
          AND source_row.raw_spread_text IS NEW.raw_spread_text
          AND source_row.raw_spread_side IS NEW.raw_spread_side
          AND (
              NEW.resolution_state != 'ACCEPTED'
              OR EXISTS (
                  SELECT 1
                  FROM football_events AS event
                  WHERE event.id = NEW.football_event_id
                    AND event.sport_code = NEW.sport_code
                    AND (
                        (
                            NEW.event_revision_id IS NULL
                            AND event.home_team_id = NEW.canonical_home_team_id
                            AND event.away_team_id = NEW.canonical_away_team_id
                            AND event.kickoff_at = NEW.canonical_kickoff_at
                            AND NOT EXISTS (
                                SELECT 1 FROM football_event_revisions AS revision
                                WHERE revision.event_id = event.id
                                  AND julianday(revision.recorded_at)
                                      <= julianday(manifest.generated_at)
                            )
                        )
                        OR EXISTS (
                            SELECT 1
                            FROM football_event_revisions AS revision
                            WHERE revision.id = NEW.event_revision_id
                              AND revision.event_id = event.id
                              AND revision.home_team_id = NEW.canonical_home_team_id
                              AND revision.away_team_id = NEW.canonical_away_team_id
                              AND revision.kickoff_at = NEW.canonical_kickoff_at
                              AND julianday(revision.recorded_at)
                                  <= julianday(manifest.generated_at)
                              AND revision.revision_number = (
                                  SELECT MAX(visible.revision_number)
                                  FROM football_event_revisions AS visible
                                  WHERE visible.event_id = event.id
                                    AND julianday(visible.recorded_at)
                                        <= julianday(manifest.generated_at)
                              )
                        )
                    )
              )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed manifest row does not match source or event state');
    END
    """,
    f"""
    CREATE TABLE mixed_deadline_derivations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        manifest_id INTEGER NOT NULL UNIQUE,
        ordered_event_kickoff_set_sha256 TEXT NOT NULL
            CHECK ({_SHA256.format(column='ordered_event_kickoff_set_sha256')}),
        earliest_kickoff_at TEXT NOT NULL
            CHECK ({_UTC.format(column='earliest_kickoff_at')}),
        deadline_policy_version TEXT NOT NULL
            CHECK (length(trim(deadline_policy_version)) > 0),
        calculated_at TEXT NOT NULL CHECK ({_UTC.format(column='calculated_at')}),
        actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (manifest_id) REFERENCES mixed_slate_manifests(id)
    )
    """,
    f"""
    CREATE TABLE mixed_deadline_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        deadline_derivation_id INTEGER NOT NULL,
        manifest_row_id INTEGER NOT NULL UNIQUE,
        source_order INTEGER NOT NULL CHECK (source_order >= 1),
        football_event_id INTEGER NOT NULL,
        sport_code TEXT NOT NULL,
        kickoff_at TEXT NOT NULL CHECK ({_UTC.format(column='kickoff_at')}),
        event_revision_id INTEGER,
        evidence_sha256 TEXT NOT NULL
            CHECK ({_SHA256.format(column='evidence_sha256')}),
        UNIQUE (deadline_derivation_id, source_order),
        UNIQUE (deadline_derivation_id, football_event_id),
        FOREIGN KEY (deadline_derivation_id) REFERENCES mixed_deadline_derivations(id),
        FOREIGN KEY (manifest_row_id) REFERENCES mixed_slate_manifest_rows(id),
        FOREIGN KEY (football_event_id) REFERENCES football_events(id),
        FOREIGN KEY (sport_code) REFERENCES football_sports(sport_code),
        FOREIGN KEY (event_revision_id) REFERENCES football_event_revisions(id)
    )
    """,
    """
    CREATE TRIGGER mixed_deadline_events_validate_manifest_row
    BEFORE INSERT ON mixed_deadline_events
    WHEN NOT EXISTS (
        SELECT 1
        FROM mixed_deadline_derivations AS deadline
        JOIN mixed_slate_manifest_rows AS row
          ON row.id = NEW.manifest_row_id
         AND row.manifest_id = deadline.manifest_id
        WHERE deadline.id = NEW.deadline_derivation_id
          AND row.resolution_state = 'ACCEPTED'
          AND row.source_order = NEW.source_order
          AND row.football_event_id = NEW.football_event_id
          AND row.sport_code = NEW.sport_code
          AND row.canonical_kickoff_at = NEW.kickoff_at
          AND row.event_revision_id IS NEW.event_revision_id
    )
    BEGIN
        SELECT RAISE(ABORT, 'deadline evidence does not match its accepted manifest row');
    END
    """,
    f"""
    CREATE TABLE mixed_slate_approvals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        approval_key TEXT NOT NULL UNIQUE CHECK ({_KEY.format(column='approval_key')}),
        manifest_id INTEGER NOT NULL UNIQUE,
        deadline_derivation_id INTEGER NOT NULL UNIQUE,
        product_id INTEGER NOT NULL,
        contest_season_id INTEGER NOT NULL,
        contest_round_id INTEGER NOT NULL,
        source_sha256 TEXT NOT NULL CHECK ({_SHA256.format(column='source_sha256')}),
        manifest_sha256 TEXT NOT NULL CHECK ({_SHA256.format(column='manifest_sha256')}),
        event_kickoff_set_sha256 TEXT NOT NULL
            CHECK ({_SHA256.format(column='event_kickoff_set_sha256')}),
        approved_row_count INTEGER NOT NULL CHECK (approved_row_count >= 1),
        reviewer TEXT NOT NULL CHECK (length(trim(reviewer)) > 0),
        approved_at TEXT NOT NULL CHECK ({_UTC.format(column='approved_at')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (manifest_id) REFERENCES mixed_slate_manifests(id),
        FOREIGN KEY (deadline_derivation_id) REFERENCES mixed_deadline_derivations(id),
        FOREIGN KEY (product_id) REFERENCES mixed_contest_products(id),
        FOREIGN KEY (contest_season_id) REFERENCES mixed_contest_seasons(id),
        FOREIGN KEY (contest_round_id) REFERENCES mixed_contest_rounds(id)
    )
    """,
    """
    CREATE TRIGGER mixed_slate_approvals_validate_complete_current_manifest
    BEFORE INSERT ON mixed_slate_approvals
    WHEN NOT EXISTS (
        SELECT 1
        FROM mixed_slate_manifests AS manifest
        JOIN mixed_deadline_derivations AS deadline
          ON deadline.id = NEW.deadline_derivation_id
         AND deadline.manifest_id = manifest.id
        WHERE manifest.id = NEW.manifest_id
          AND manifest.product_id = NEW.product_id
          AND manifest.contest_season_id = NEW.contest_season_id
          AND manifest.contest_round_id = NEW.contest_round_id
          AND manifest.source_sha256 = NEW.source_sha256
          AND manifest.manifest_sha256 = NEW.manifest_sha256
          AND deadline.ordered_event_kickoff_set_sha256
              = NEW.event_kickoff_set_sha256
          AND manifest.lifecycle_state = 'MANIFEST_READY'
          AND manifest.accepted_count = NEW.approved_row_count
          AND manifest.source_row_count = NEW.approved_row_count
          AND manifest.expected_source_row_count = NEW.approved_row_count
          AND manifest.sequence = (
              SELECT MAX(latest.sequence)
              FROM mixed_slate_manifests AS latest
              WHERE latest.import_id = manifest.import_id
          )
          AND (
              SELECT COUNT(*) FROM mixed_slate_manifest_rows AS row
              WHERE row.manifest_id = manifest.id
                AND row.resolution_state = 'ACCEPTED'
          ) = NEW.approved_row_count
          AND (
              SELECT COUNT(*) FROM mixed_deadline_events AS evidence
              WHERE evidence.deadline_derivation_id = deadline.id
          ) = NEW.approved_row_count
          AND deadline.earliest_kickoff_at = (
              SELECT MIN(evidence.kickoff_at)
              FROM mixed_deadline_events AS evidence
              WHERE evidence.deadline_derivation_id = deadline.id
          )
          AND julianday(NEW.approved_at) >= julianday(deadline.calculated_at)
          AND julianday(NEW.approved_at) < julianday(deadline.earliest_kickoff_at)
          AND NOT EXISTS (
              SELECT 1
              FROM mixed_deadline_events AS evidence
              JOIN football_event_revisions AS revision
                ON revision.event_id = evidence.football_event_id
              WHERE evidence.deadline_derivation_id = deadline.id
                AND julianday(revision.recorded_at)
                    > julianday(deadline.calculated_at)
                AND julianday(revision.recorded_at) <= julianday(NEW.approved_at)
          )
          AND EXISTS (
              SELECT 1
              FROM mixed_round_state_events AS state
              WHERE state.contest_round_id = manifest.contest_round_id
                AND state.state = 'MANIFEST_READY'
                AND state.manifest_id = manifest.id
                AND state.sequence = (
                    SELECT MAX(latest.sequence)
                    FROM mixed_round_state_events AS latest
                    WHERE latest.contest_round_id = manifest.contest_round_id
                )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed manifest approval is incomplete, stale, or mismatched');
    END
    """,
    f"""
    CREATE TABLE mixed_line_lock_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lock_key TEXT NOT NULL UNIQUE CHECK ({_KEY.format(column='lock_key')}),
        approval_id INTEGER NOT NULL UNIQUE,
        product_id INTEGER NOT NULL,
        contest_season_id INTEGER NOT NULL,
        contest_round_id INTEGER NOT NULL UNIQUE,
        expected_line_count INTEGER NOT NULL CHECK (expected_line_count >= 1),
        locked_line_count INTEGER NOT NULL CHECK (locked_line_count >= 1),
        ordered_line_set_sha256 TEXT NOT NULL
            CHECK ({_SHA256.format(column='ordered_line_set_sha256')}),
        locked_at TEXT NOT NULL CHECK ({_UTC.format(column='locked_at')}),
        actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
        lock_policy_version TEXT NOT NULL
            CHECK (length(trim(lock_policy_version)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (expected_line_count = locked_line_count),
        FOREIGN KEY (approval_id) REFERENCES mixed_slate_approvals(id),
        FOREIGN KEY (product_id) REFERENCES mixed_contest_products(id),
        FOREIGN KEY (contest_season_id) REFERENCES mixed_contest_seasons(id),
        FOREIGN KEY (contest_round_id) REFERENCES mixed_contest_rounds(id)
    )
    """,
    """
    CREATE TRIGGER mixed_line_lock_batches_validate_approval
    BEFORE INSERT ON mixed_line_lock_batches
    WHEN NOT EXISTS (
        SELECT 1
        FROM mixed_slate_approvals AS approval
        JOIN mixed_deadline_derivations AS deadline
          ON deadline.id = approval.deadline_derivation_id
        WHERE approval.id = NEW.approval_id
          AND approval.product_id = NEW.product_id
          AND approval.contest_season_id = NEW.contest_season_id
          AND approval.contest_round_id = NEW.contest_round_id
          AND approval.approved_row_count = NEW.expected_line_count
          AND julianday(NEW.locked_at) >= julianday(approval.approved_at)
          AND julianday(NEW.locked_at) < julianday(deadline.earliest_kickoff_at)
          AND NOT EXISTS (
              SELECT 1
              FROM mixed_deadline_events AS evidence
              JOIN football_event_revisions AS revision
                ON revision.event_id = evidence.football_event_id
              WHERE evidence.deadline_derivation_id = deadline.id
                AND julianday(revision.recorded_at)
                    > julianday(deadline.calculated_at)
                AND julianday(revision.recorded_at) <= julianday(NEW.locked_at)
          )
          AND EXISTS (
              SELECT 1
              FROM mixed_round_state_events AS state
              WHERE state.contest_round_id = approval.contest_round_id
                AND state.state = 'OWNER_APPROVED'
                AND state.approval_id = approval.id
                AND state.sequence = (
                    SELECT MAX(latest.sequence)
                    FROM mixed_round_state_events AS latest
                    WHERE latest.contest_round_id = approval.contest_round_id
                )
          )
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed line-lock batch approval is stale or mismatched');
    END
    """,
    f"""
    CREATE TABLE mixed_contest_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lock_batch_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        contest_round_id INTEGER NOT NULL,
        football_event_id INTEGER NOT NULL,
        sport_code TEXT NOT NULL,
        import_row_id INTEGER NOT NULL,
        manifest_row_id INTEGER NOT NULL,
        raw_away_team TEXT NOT NULL CHECK (length(trim(raw_away_team)) > 0),
        raw_home_team TEXT NOT NULL CHECK (length(trim(raw_home_team)) > 0),
        canonical_away_team_id INTEGER NOT NULL,
        canonical_home_team_id INTEGER NOT NULL,
        canonical_away_team_name TEXT NOT NULL
            CHECK (length(trim(canonical_away_team_name)) > 0),
        canonical_home_team_name TEXT NOT NULL
            CHECK (length(trim(canonical_home_team_name)) > 0),
        raw_spread_text TEXT NOT NULL CHECK (length(trim(raw_spread_text)) > 0),
        home_spread_millipoints INTEGER NOT NULL CHECK (
            home_spread_millipoints BETWEEN -100000 AND 100000
            AND home_spread_millipoints % 500 = 0
        ),
        locked_at TEXT NOT NULL CHECK ({_UTC.format(column='locked_at')}),
        source_sha256 TEXT NOT NULL CHECK ({_SHA256.format(column='source_sha256')}),
        source_row_sha256 TEXT NOT NULL
            CHECK ({_SHA256.format(column='source_row_sha256')}),
        manifest_sha256 TEXT NOT NULL CHECK ({_SHA256.format(column='manifest_sha256')}),
        line_sha256 TEXT NOT NULL UNIQUE CHECK ({_SHA256.format(column='line_sha256')}),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        CHECK (canonical_home_team_id != canonical_away_team_id),
        UNIQUE (contest_round_id, football_event_id),
        UNIQUE (contest_round_id, import_row_id),
        UNIQUE (lock_batch_id, manifest_row_id),
        FOREIGN KEY (lock_batch_id) REFERENCES mixed_line_lock_batches(id),
        FOREIGN KEY (product_id) REFERENCES mixed_contest_products(id),
        FOREIGN KEY (contest_round_id) REFERENCES mixed_contest_rounds(id),
        FOREIGN KEY (football_event_id) REFERENCES football_events(id),
        FOREIGN KEY (sport_code) REFERENCES football_sports(sport_code),
        FOREIGN KEY (import_row_id) REFERENCES mixed_slate_import_rows(id),
        FOREIGN KEY (manifest_row_id) REFERENCES mixed_slate_manifest_rows(id),
        FOREIGN KEY (canonical_away_team_id) REFERENCES football_teams(id),
        FOREIGN KEY (canonical_home_team_id) REFERENCES football_teams(id)
    )
    """,
    """
    CREATE TRIGGER mixed_contest_lines_validate_manifest_batch
    BEFORE INSERT ON mixed_contest_lines
    WHEN NOT EXISTS (
        SELECT 1
        FROM mixed_line_lock_batches AS batch
        JOIN mixed_slate_approvals AS approval ON approval.id = batch.approval_id
        JOIN mixed_slate_manifests AS manifest ON manifest.id = approval.manifest_id
        JOIN mixed_slate_manifest_rows AS row
          ON row.id = NEW.manifest_row_id
         AND row.manifest_id = manifest.id
        JOIN football_events AS event ON event.id = row.football_event_id
        WHERE batch.id = NEW.lock_batch_id
          AND batch.product_id = NEW.product_id
          AND batch.contest_round_id = NEW.contest_round_id
          AND batch.locked_at = NEW.locked_at
          AND approval.source_sha256 = NEW.source_sha256
          AND approval.manifest_sha256 = NEW.manifest_sha256
          AND row.import_row_id = NEW.import_row_id
          AND row.resolution_state = 'ACCEPTED'
          AND row.football_event_id = NEW.football_event_id
          AND row.sport_code = NEW.sport_code
          AND row.raw_away_team = NEW.raw_away_team
          AND row.raw_home_team = NEW.raw_home_team
          AND row.canonical_away_team_id = NEW.canonical_away_team_id
          AND row.canonical_home_team_id = NEW.canonical_home_team_id
          AND row.canonical_away_team_name = NEW.canonical_away_team_name
          AND row.canonical_home_team_name = NEW.canonical_home_team_name
          AND row.raw_spread_text = NEW.raw_spread_text
          AND row.home_spread_millipoints = NEW.home_spread_millipoints
          AND row.source_row_sha256 = NEW.source_row_sha256
          AND event.sport_code = NEW.sport_code
          AND (
              SELECT COUNT(*) FROM mixed_contest_lines AS existing
              WHERE existing.lock_batch_id = batch.id
          ) < batch.locked_line_count
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed contest line does not match its approved manifest');
    END
    """,
    f"""
    CREATE TABLE mixed_line_lock_completions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lock_batch_id INTEGER NOT NULL UNIQUE,
        line_count INTEGER NOT NULL CHECK (line_count >= 1),
        ordered_line_set_sha256 TEXT NOT NULL
            CHECK ({_SHA256.format(column='ordered_line_set_sha256')}),
        completed_at TEXT NOT NULL CHECK ({_UTC.format(column='completed_at')}),
        actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        FOREIGN KEY (lock_batch_id) REFERENCES mixed_line_lock_batches(id)
    )
    """,
    """
    CREATE TRIGGER mixed_line_lock_completions_validate
    BEFORE INSERT ON mixed_line_lock_completions
    WHEN NOT EXISTS (
        SELECT 1
        FROM mixed_line_lock_batches AS batch
        JOIN mixed_slate_approvals AS approval ON approval.id = batch.approval_id
        JOIN mixed_deadline_derivations AS deadline
          ON deadline.id = approval.deadline_derivation_id
        WHERE batch.id = NEW.lock_batch_id
          AND batch.expected_line_count = NEW.line_count
          AND batch.locked_line_count = NEW.line_count
          AND batch.ordered_line_set_sha256 = NEW.ordered_line_set_sha256
          AND (
              SELECT COUNT(*) FROM mixed_contest_lines AS line
              WHERE line.lock_batch_id = batch.id
          ) = NEW.line_count
          AND julianday(NEW.completed_at) >= julianday(batch.locked_at)
          AND julianday(NEW.completed_at) < julianday(deadline.earliest_kickoff_at)
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed line-lock completion is incomplete or mismatched');
    END
    """,
    f"""
    CREATE TABLE mixed_round_state_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        contest_round_id INTEGER NOT NULL,
        sequence INTEGER NOT NULL CHECK (sequence >= 1),
        state TEXT NOT NULL CHECK (
            state IN (
                'OPEN', 'RECEIVED', 'PARSED', 'RESOLVED', 'MANIFEST_READY',
                'OWNER_APPROVED', 'LOCKED', 'NEEDS_REVIEW', 'AMBIGUOUS',
                'REJECTED'
            )
        ),
        supersedes_state_id INTEGER UNIQUE,
        import_id INTEGER,
        manifest_id INTEGER,
        approval_id INTEGER,
        lock_completion_id INTEGER,
        recorded_at TEXT NOT NULL CHECK ({_UTC.format(column='recorded_at')}),
        actor TEXT NOT NULL CHECK (length(trim(actor)) > 0),
        reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
        provenance TEXT NOT NULL CHECK (length(trim(provenance)) > 0),
        UNIQUE (contest_round_id, sequence),
        FOREIGN KEY (contest_round_id) REFERENCES mixed_contest_rounds(id),
        FOREIGN KEY (supersedes_state_id) REFERENCES mixed_round_state_events(id),
        FOREIGN KEY (import_id) REFERENCES mixed_slate_imports(id),
        FOREIGN KEY (manifest_id) REFERENCES mixed_slate_manifests(id),
        FOREIGN KEY (approval_id) REFERENCES mixed_slate_approvals(id),
        FOREIGN KEY (lock_completion_id) REFERENCES mixed_line_lock_completions(id)
    )
    """,
    """
    CREATE TRIGGER mixed_round_state_events_validate_chain
    BEFORE INSERT ON mixed_round_state_events
    WHEN NOT (
        (
            NEW.sequence = 1
            AND NEW.state = 'OPEN'
            AND NEW.supersedes_state_id IS NULL
            AND NEW.import_id IS NULL
            AND NEW.manifest_id IS NULL
            AND NEW.approval_id IS NULL
            AND NEW.lock_completion_id IS NULL
            AND NOT EXISTS (
                SELECT 1 FROM mixed_round_state_events
                WHERE contest_round_id = NEW.contest_round_id
            )
        )
        OR EXISTS (
            SELECT 1
            FROM mixed_round_state_events AS prior
            WHERE prior.id = NEW.supersedes_state_id
              AND prior.contest_round_id = NEW.contest_round_id
              AND prior.sequence = NEW.sequence - 1
              AND prior.sequence = (
                  SELECT MAX(latest.sequence)
                  FROM mixed_round_state_events AS latest
                  WHERE latest.contest_round_id = NEW.contest_round_id
              )
              AND julianday(NEW.recorded_at) >= julianday(prior.recorded_at)
              AND (
                  (
                      prior.state IN ('OPEN', 'NEEDS_REVIEW', 'AMBIGUOUS', 'REJECTED')
                      AND NEW.state = 'RECEIVED'
                  )
                  OR (prior.state = 'RECEIVED' AND NEW.state IN ('PARSED', 'REJECTED'))
                  OR (
                      prior.state = 'PARSED'
                      AND NEW.state IN (
                          'RESOLVED', 'NEEDS_REVIEW', 'AMBIGUOUS', 'REJECTED'
                      )
                  )
                  OR (prior.state = 'RESOLVED' AND NEW.state = 'MANIFEST_READY')
                  OR (prior.state = 'MANIFEST_READY' AND NEW.state = 'OWNER_APPROVED')
                  OR (prior.state = 'OWNER_APPROVED' AND NEW.state = 'LOCKED')
                  OR (
                      prior.state = 'MANIFEST_READY'
                      AND NEW.state = 'RECEIVED'
                      AND EXISTS (
                          SELECT 1
                          FROM mixed_deadline_derivations AS deadline
                          JOIN mixed_deadline_events AS evidence
                            ON evidence.deadline_derivation_id = deadline.id
                          JOIN football_event_revisions AS revision
                            ON revision.event_id = evidence.football_event_id
                          WHERE deadline.manifest_id = prior.manifest_id
                            AND julianday(revision.recorded_at)
                                > julianday(deadline.calculated_at)
                            AND julianday(revision.recorded_at)
                                <= julianday(NEW.recorded_at)
                      )
                  )
                  OR (
                      prior.state = 'OWNER_APPROVED'
                      AND NEW.state = 'RECEIVED'
                      AND EXISTS (
                          SELECT 1
                          FROM mixed_slate_approvals AS approval
                          JOIN mixed_deadline_derivations AS deadline
                            ON deadline.id = approval.deadline_derivation_id
                          JOIN mixed_deadline_events AS evidence
                            ON evidence.deadline_derivation_id = deadline.id
                          JOIN football_event_revisions AS revision
                            ON revision.event_id = evidence.football_event_id
                          WHERE approval.id = prior.approval_id
                            AND julianday(revision.recorded_at)
                                > julianday(deadline.calculated_at)
                            AND julianday(revision.recorded_at)
                                <= julianday(NEW.recorded_at)
                      )
                  )
              )
              AND (
                  (
                      NEW.state IN (
                          'RECEIVED', 'PARSED', 'RESOLVED', 'NEEDS_REVIEW',
                          'AMBIGUOUS', 'REJECTED'
                      )
                      AND EXISTS (
                          SELECT 1 FROM mixed_slate_imports AS import
                          WHERE import.id = NEW.import_id
                            AND import.contest_round_id = NEW.contest_round_id
                      )
                  )
                  OR (
                      NEW.state = 'MANIFEST_READY'
                      AND EXISTS (
                          SELECT 1 FROM mixed_slate_manifests AS manifest
                          WHERE manifest.id = NEW.manifest_id
                            AND manifest.contest_round_id = NEW.contest_round_id
                            AND manifest.lifecycle_state = 'MANIFEST_READY'
                      )
                  )
                  OR (
                      NEW.state = 'OWNER_APPROVED'
                      AND EXISTS (
                          SELECT 1 FROM mixed_slate_approvals AS approval
                          WHERE approval.id = NEW.approval_id
                            AND approval.contest_round_id = NEW.contest_round_id
                      )
                  )
                  OR (
                      NEW.state = 'LOCKED'
                      AND EXISTS (
                          SELECT 1
                          FROM mixed_line_lock_completions AS completion
                          JOIN mixed_line_lock_batches AS batch
                            ON batch.id = completion.lock_batch_id
                          WHERE completion.id = NEW.lock_completion_id
                            AND batch.contest_round_id = NEW.contest_round_id
                      )
                  )
              )
        )
    )
    BEGIN
        SELECT RAISE(ABORT, 'mixed contest round state transition is invalid');
    END
    """,
    """
    CREATE INDEX idx_mixed_import_rows_order
    ON mixed_slate_import_rows (import_id, source_order)
    """,
    """
    CREATE INDEX idx_mixed_manifest_rows_order
    ON mixed_slate_manifest_rows (manifest_id, source_order)
    """,
    """
    CREATE INDEX idx_mixed_lines_round_event
    ON mixed_contest_lines (contest_round_id, football_event_id)
    """,
)


for _table in (
    "mixed_contest_products",
    "mixed_contest_product_sports",
    "mixed_contest_seasons",
    "mixed_contest_rounds",
    "mixed_slate_imports",
    "mixed_slate_import_states",
    "mixed_slate_import_rows",
    "mixed_slate_manifests",
    "mixed_slate_manifest_rows",
    "mixed_deadline_derivations",
    "mixed_deadline_events",
    "mixed_slate_approvals",
    "mixed_line_lock_batches",
    "mixed_contest_lines",
    "mixed_line_lock_completions",
    "mixed_round_state_events",
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
    if len(words) >= 3 and words[0:2] == ["CREATE", "INDEX"]:
        return "index", words[2]
    if len(words) >= 4 and words[0:3] == ["CREATE", "UNIQUE", "INDEX"]:
        return "index", words[3]
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

    product = conn.execute(
        "SELECT product_key, display_name, line_authority, policy_namespace, provenance "
        "FROM mixed_contest_products"
    ).fetchall()
    if product != [
        (
            "mixed_pickem",
            "Mixed NCAA + NFL ATS Pick'em",
            "weekly_administrator_spreadsheet",
            "mixed_pickem",
            "migration:v0020:approved-phase-0-product-b",
        )
    ]:
        raise RuntimeError("mixed Pick'em product registry differs from approved seed")
    sports = conn.execute(
        "SELECT sport.sport_code FROM mixed_contest_product_sports AS sport "
        "JOIN mixed_contest_products AS product ON product.id = sport.product_id "
        "WHERE product.product_key = 'mixed_pickem' ORDER BY sport.sport_code"
    ).fetchall()
    if sports != [("NCAA",), ("NFL",)]:
        raise RuntimeError("mixed Pick'em sport allow-list must be NCAA and NFL")
