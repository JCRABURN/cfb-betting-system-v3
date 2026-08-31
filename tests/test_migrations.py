import hashlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from migrations.runner import (
    Migration,
    MigrationError,
    apply_migrations,
    load_migrations,
    table_row_counts,
)
from scripts.verify_migrations import verify_database_copy


ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_DATABASE = ROOT / "data" / "cfb.db"


def _connect(path):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migration(version, name, checksum, upgrade, verify=lambda conn: None):
    return Migration(
        version=version,
        name=name,
        checksum=checksum,
        upgrade=upgrade,
        verify=verify,
    )


def _file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_new_database_records_complete_ordered_history(temp_db):
    conn = temp_db.get_connection()
    rows = list(
        conn.execute(
            "SELECT version, name, checksum, applied_at "
            "FROM schema_migrations ORDER BY version"
        )
    )
    conn.close()

    migrations = load_migrations()
    assert [(row[0], row[1]) for row in rows] == [
        (migration.version, migration.name) for migration in migrations
    ]
    assert all(len(row[2]) == 64 for row in rows)
    assert all(row[3].endswith("+00:00") for row in rows)


def test_init_db_is_idempotent_and_does_not_change_rows(temp_db):
    conn = temp_db.get_connection()
    before_counts = table_row_counts(conn)
    before_schema = list(
        conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
    )
    conn.close()

    assert temp_db.init_db() == ()

    conn = temp_db.get_connection()
    assert table_row_counts(conn) == before_counts
    assert list(
        conn.execute(
            "SELECT type, name, sql FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' ORDER BY type, name"
        )
    ) == before_schema
    conn.close()


def test_legacy_database_gains_feature_columns_without_data_loss(tmp_path):
    database = tmp_path / "legacy.db"
    conn = _connect(database)
    conn.execute(
        """
        CREATE TABLE team_game_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER,
            season INTEGER NOT NULL,
            week INTEGER,
            team TEXT NOT NULL,
            sp_rating REAL,
            offense_epa_play REAL,
            defense_epa_play REAL,
            wins INTEGER,
            losses INTEGER,
            source TEXT NOT NULL,
            fetched_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO team_game_stats "
        "(season, week, team, source, fetched_at) VALUES (2025, 1, 'Test', 'fixture', 'now')"
    )
    conn.commit()

    before_counts = table_row_counts(conn)
    applied = apply_migrations(conn)
    after_counts = table_row_counts(conn)
    columns = {row[1] for row in conn.execute("PRAGMA table_info(team_game_stats)")}
    row = conn.execute(
        "SELECT season, week, team, source FROM team_game_stats"
    ).fetchone()
    conn.close()

    assert [result.version for result in applied] == [
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21
    ]
    assert after_counts["team_game_stats"] == before_counts["team_game_stats"] == 1
    assert {"offense_success_rate", "defense_success_rate", "havoc_rate"} <= columns
    assert row == (2025, 1, "Test", "fixture")


def test_authoritative_database_copy_preserves_rows_integrity_and_source(tmp_path):
    source_hash_before = _file_hash(AUTHORITATIVE_DATABASE)
    source_copy = tmp_path / "authoritative-copy.db"
    shutil.copy2(AUTHORITATIVE_DATABASE, source_copy)

    result = verify_database_copy(source_copy)

    assert result.source_unchanged is True
    assert result.source_hash_after == result.source_hash
    assert result.integrity_result == "ok"
    assert result.foreign_key_violation_count == 0
    assert result.applied_versions == (
        1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21
    )
    assert all(
        result.after_counts[table] == count
        for table, count in result.before_counts.items()
    )
    assert result.after_counts["contests"] == 0
    assert result.after_counts["contest_locked_lines"] == 0
    assert result.after_counts["contest_line_corrections"] == 0
    for table in (
        "model_runs",
        "model_predictions",
        "contest_cards",
        "contest_picks",
        "sportsbook_recommendations",
        "card_revisions",
        "manual_adjustments",
        "pick_audits",
        "contest_ranking_policies",
        "contest_card_policy_assignments",
        "contest_selection_policies",
        "contest_selection_policy_books",
        "card_run_manifests",
        "card_refresh_policies",
        "card_revision_pick_changes",
        "card_refresh_revisions",
        "manual_adjustment_policies",
        "card_adjustment_policy_assignments",
        "contest_pick_adjustment_items",
        "contest_pick_adjustment_snapshots",
        "postgame_audit_policies",
        "postgame_audit_key_numbers",
        "postgame_audit_spread_buckets",
        "postgame_audit_failure_taxonomy",
        "card_postgame_audit_runs",
        "pick_audit_details",
        "pick_audit_key_number_crossings",
        "pick_audit_failures",
        "card_postgame_audit_completions",
        "weekly_diagnostic_policies",
        "weekly_diagnostic_runs",
        "weekly_diagnostic_segments",
        "weekly_diagnostic_lessons",
        "policy_change_recommendations",
        "weekly_diagnostic_completions",
        "provider_team_aliases",
        "provider_ingestion_runs",
        "provider_ingestion_rejections",
        "provider_ingestion_acceptances",
        "provider_market_snapshots",
        "provider_data_snapshots",
        "weekly_controller_policies",
        "weekly_controller_policy_sources",
        "weekly_controller_runs",
        "contest_line_lock_batches",
        "card_source_freshness",
        "official_card_publications",
        "sportsbook_market_offers",
        "sportsbook_recommendation_policies",
        "sportsbook_recommendation_evaluations",
        "sportsbook_closing_designations",
        "sportsbook_postgame_audit_runs",
        "sportsbook_postgame_audit_details",
        "sportsbook_postgame_audit_completions",
        "card_context_source_snapshots",
        "football_franchises",
        "football_teams",
        "football_team_seasons",
        "football_team_aliases",
        "football_venues",
        "football_venue_versions",
        "football_events",
        "football_event_revisions",
        "football_provider_event_ids",
        "legacy_cfb_game_links",
        "total_model_runs",
        "total_model_predictions",
        "total_reliability_policies",
        "total_shadow_cards",
        "total_card_candidates",
        "total_card_skips",
        "total_shadow_card_completions",
        "unified_top_five_policies",
        "unified_top_five_runs",
        "unified_top_five_candidates",
        "unified_top_five_completions",
    ):
        assert result.after_counts[table] == 0
    assert result.after_counts["football_sports"] == 2
    assert result.new_table_counts["football_sports"] == 2
    assert result.after_counts["mixed_contest_products"] == 1
    assert result.after_counts["mixed_contest_product_sports"] == 2
    assert result.new_table_counts["mixed_contest_products"] == 1
    assert result.new_table_counts["mixed_contest_product_sports"] == 2
    assert all(
        result.new_table_counts[table] == 0
        for table in (
            "football_franchises",
            "football_teams",
            "football_team_seasons",
            "football_team_aliases",
            "football_venues",
            "football_venue_versions",
            "football_events",
            "football_event_revisions",
            "football_provider_event_ids",
            "legacy_cfb_game_links",
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
            "total_model_runs",
            "total_model_predictions",
            "total_reliability_policies",
            "total_shadow_cards",
            "total_card_candidates",
            "total_card_skips",
            "total_shadow_card_completions",
            "unified_top_five_policies",
            "unified_top_five_runs",
            "unified_top_five_candidates",
            "unified_top_five_completions",
        )
    )
    assert _file_hash(AUTHORITATIVE_DATABASE) == source_hash_before


def test_failed_migration_rolls_back_schema_and_ledger(tmp_path):
    conn = _connect(tmp_path / "failure.db")

    def fail_after_ddl(connection):
        connection.execute("CREATE TABLE partial_change (id INTEGER PRIMARY KEY)")
        raise ValueError("forced failure")

    migration = _migration(1, "forced_failure", "a" * 64, fail_after_ddl)
    with pytest.raises(MigrationError, match="forced failure"):
        apply_migrations(conn, (migration,))

    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'partial_change'"
    ).fetchone() is None
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0
    conn.close()


def test_row_count_change_rolls_back_migration(tmp_path):
    conn = _connect(tmp_path / "row-count.db")
    conn.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
    conn.execute("INSERT INTO sentinel VALUES ('preserve-me')")
    conn.commit()

    migration = _migration(
        1,
        "unsafe_delete",
        "b" * 64,
        lambda connection: connection.execute("DELETE FROM sentinel"),
    )
    with pytest.raises(MigrationError, match="changed existing table row counts"):
        apply_migrations(conn, (migration,))

    assert conn.execute("SELECT value FROM sentinel").fetchone()[0] == "preserve-me"
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0
    conn.close()


def test_checksum_change_is_rejected_after_application(tmp_path):
    conn = _connect(tmp_path / "checksum.db")
    original = _migration(1, "stable", "c" * 64, lambda connection: None)
    changed = _migration(1, "stable", "d" * 64, lambda connection: None)

    apply_migrations(conn, (original,))
    with pytest.raises(MigrationError, match="checksum changed"):
        apply_migrations(conn, (changed,))
    conn.close()


def test_out_of_order_history_is_rejected(tmp_path):
    conn = _connect(tmp_path / "history.db")
    conn.execute(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        "INSERT INTO schema_migrations VALUES (2, 'second', ?, 'now')",
        ("f" * 64,),
    )
    conn.commit()
    migrations = (
        _migration(1, "first", "e" * 64, lambda connection: None),
        _migration(2, "second", "f" * 64, lambda connection: None),
    )

    with pytest.raises(MigrationError, match="not a valid ordered prefix"):
        apply_migrations(conn, migrations)
    conn.close()


def test_foreign_key_violation_blocks_and_rolls_back_migration(tmp_path):
    conn = sqlite3.connect(tmp_path / "foreign-key.db")
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
    conn.execute(
        "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
    )
    conn.execute("INSERT INTO child VALUES (1, 999)")
    conn.commit()
    migration = _migration(1, "no_op", "1" * 64, lambda connection: None)

    with pytest.raises(MigrationError, match="foreign-key check"):
        apply_migrations(conn, (migration,))
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0
    conn.close()


def test_index_definition_drift_is_detected_after_migrations_are_recorded(tmp_path):
    conn = _connect(tmp_path / "drift.db")
    apply_migrations(conn)
    conn.execute("DROP INDEX idx_games_season_week")
    conn.execute("CREATE INDEX idx_games_season_week ON games (week, season)")
    conn.commit()

    with pytest.raises(MigrationError, match="schema verification failed"):
        apply_migrations(conn)
    conn.close()


def test_missing_immutability_trigger_is_detected_as_schema_drift(tmp_path):
    conn = _connect(tmp_path / "contest-trigger-drift.db")
    apply_migrations(conn)
    conn.execute("DROP TRIGGER contest_locked_lines_no_update")
    conn.commit()

    with pytest.raises(MigrationError, match="schema verification failed"):
        apply_migrations(conn)
    conn.close()


def test_changed_immutability_trigger_definition_is_detected(tmp_path):
    conn = _connect(tmp_path / "contest-trigger-definition-drift.db")
    apply_migrations(conn)
    conn.execute("DROP TRIGGER contest_locked_lines_no_update")
    conn.execute(
        "CREATE TRIGGER contest_locked_lines_no_update "
        "BEFORE UPDATE ON contest_locked_lines BEGIN SELECT 1; END"
    )
    conn.commit()

    with pytest.raises(MigrationError, match="definition changed"):
        apply_migrations(conn)
    conn.close()


def test_business_entity_trigger_definition_drift_is_detected(tmp_path):
    conn = _connect(tmp_path / "business-entity-trigger-drift.db")
    apply_migrations(conn)
    conn.execute("DROP TRIGGER model_predictions_no_update")
    conn.execute(
        "CREATE TRIGGER model_predictions_no_update "
        "BEFORE UPDATE ON model_predictions BEGIN SELECT 1; END"
    )
    conn.commit()

    with pytest.raises(MigrationError, match="definition changed"):
        apply_migrations(conn)
    conn.close()


def test_daily_refresh_trigger_definition_drift_is_detected(tmp_path):
    conn = _connect(tmp_path / "daily-refresh-trigger-drift.db")
    apply_migrations(conn)
    conn.execute("DROP TRIGGER card_refresh_revisions_validate_history")
    conn.execute(
        "CREATE TRIGGER card_refresh_revisions_validate_history "
        "BEFORE INSERT ON card_refresh_revisions BEGIN SELECT 1; END"
    )
    conn.commit()

    with pytest.raises(MigrationError, match="definition changed"):
        apply_migrations(conn)
    conn.close()


def test_contextual_adjustment_trigger_definition_drift_is_detected(tmp_path):
    conn = _connect(tmp_path / "contextual-adjustment-trigger-drift.db")
    apply_migrations(conn)
    conn.execute("DROP TRIGGER contest_pick_adjustment_snapshots_validate")
    conn.execute(
        "CREATE TRIGGER contest_pick_adjustment_snapshots_validate "
        "BEFORE INSERT ON contest_pick_adjustment_snapshots BEGIN SELECT 1; END"
    )
    conn.commit()

    with pytest.raises(MigrationError, match="definition changed"):
        apply_migrations(conn)
    conn.close()


def test_complete_postgame_audit_trigger_definition_drift_is_detected(tmp_path):
    conn = _connect(tmp_path / "complete-postgame-audit-trigger-drift.db")
    apply_migrations(conn)
    conn.execute("DROP TRIGGER card_postgame_audit_completions_validate")
    conn.execute(
        "CREATE TRIGGER card_postgame_audit_completions_validate "
        "BEFORE INSERT ON card_postgame_audit_completions BEGIN SELECT 1; END"
    )
    conn.commit()

    with pytest.raises(MigrationError, match="definition changed"):
        apply_migrations(conn)
    conn.close()


def test_weekly_diagnostic_trigger_definition_drift_is_detected(tmp_path):
    conn = _connect(tmp_path / "weekly-diagnostic-trigger-drift.db")
    apply_migrations(conn)
    conn.execute("DROP TRIGGER weekly_diagnostic_completions_validate")
    conn.execute(
        "CREATE TRIGGER weekly_diagnostic_completions_validate "
        "BEFORE INSERT ON weekly_diagnostic_completions BEGIN SELECT 1; END"
    )
    conn.commit()

    with pytest.raises(MigrationError, match="definition changed"):
        apply_migrations(conn)
    conn.close()


def test_official_publication_trigger_definition_drift_is_detected(tmp_path):
    conn = _connect(tmp_path / "official-publication-trigger-drift.db")
    apply_migrations(conn)
    conn.execute("DROP TRIGGER official_card_publications_validate")
    conn.execute(
        "CREATE TRIGGER official_card_publications_validate "
        "BEFORE INSERT ON official_card_publications BEGIN SELECT 1; END"
    )
    conn.commit()

    with pytest.raises(MigrationError, match="schema verification failed"):
        apply_migrations(conn)
    conn.close()


def test_totals_shadow_trigger_definition_drift_is_detected(tmp_path):
    conn = _connect(tmp_path / "totals-shadow-trigger-drift.db")
    apply_migrations(conn)
    conn.execute("DROP TRIGGER total_card_candidates_validate")
    conn.execute(
        "CREATE TRIGGER total_card_candidates_validate "
        "BEFORE INSERT ON total_card_candidates BEGIN SELECT 1; END"
    )
    conn.commit()

    with pytest.raises(MigrationError, match="definition changed"):
        apply_migrations(conn)
    conn.close()


def test_unknown_legacy_line_type_blocks_migration_5_and_rolls_back(tmp_path):
    conn = _connect(tmp_path / "unsupported-line-type.db")
    migrations = load_migrations()
    apply_migrations(conn, migrations[:4])
    conn.execute(
        "INSERT INTO betting_lines "
        "(season, week, home_team, away_team, book, line_type, source, fetched_at) "
        "VALUES (2026, 1, 'A', 'B', 'fixture', 'contest', 'fixture', 'now')"
    )
    conn.commit()

    with pytest.raises(MigrationError, match="unsupported market line types"):
        apply_migrations(conn)

    versions = [
        row[0]
        for row in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )
    ]
    contest_table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'contests'"
    ).fetchone()
    assert versions == [1, 2, 3, 4]
    assert contest_table is None
    assert conn.execute("SELECT COUNT(*) FROM betting_lines").fetchone()[0] == 1
    conn.close()
