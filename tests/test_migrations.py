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

    assert [result.version for result in applied] == [1, 2, 3, 4]
    assert after_counts["team_game_stats"] == before_counts["team_game_stats"] == 1
    assert {"offense_success_rate", "defense_success_rate", "havoc_rate"} <= columns
    assert row == (2025, 1, "Test", "fixture")


def test_authoritative_database_copy_preserves_rows_integrity_and_source(tmp_path):
    source_hash_before = _file_hash(AUTHORITATIVE_DATABASE)
    source_copy = tmp_path / "authoritative-copy.db"
    shutil.copy2(AUTHORITATIVE_DATABASE, source_copy)

    result = verify_database_copy(source_copy)

    assert result.applied_versions == (1, 2, 3, 4)
    assert result.before_counts == result.after_counts
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
