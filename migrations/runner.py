"""Transactional, checksummed SQLite migration runner."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType

from migrations.versions import MIGRATION_MODULES


LEDGER_TABLE = "schema_migrations"
LEDGER_SQL = f"""
CREATE TABLE IF NOT EXISTS {LEDGER_TABLE} (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


class MigrationError(RuntimeError):
    """Raised when migration history, execution, or validation is unsafe."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    checksum: str
    upgrade: Callable[[sqlite3.Connection], None]
    verify: Callable[[sqlite3.Connection], None]
    preserve_row_counts: bool = True


@dataclass(frozen=True)
class MigrationResult:
    version: int
    name: str
    before_counts: dict[str, int]
    after_counts: dict[str, int]


def _module_checksum(module: ModuleType) -> str:
    path = Path(module.__file__ or "")
    normalized = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def load_migrations() -> tuple[Migration, ...]:
    migrations = tuple(
        Migration(
            version=module.VERSION,
            name=module.NAME,
            checksum=_module_checksum(module),
            upgrade=module.upgrade,
            verify=module.verify,
        )
        for module in MIGRATION_MODULES
    )
    _validate_migration_definitions(migrations)
    return migrations


def _validate_migration_definitions(migrations: Sequence[Migration]) -> None:
    versions = [migration.version for migration in migrations]
    names = [migration.name for migration in migrations]
    if versions != list(range(1, len(migrations) + 1)):
        raise MigrationError(f"migration versions must be contiguous from 1: {versions}")
    if len(names) != len(set(names)):
        raise MigrationError("migration names must be unique")
    if any(not migration.checksum for migration in migrations):
        raise MigrationError("every migration requires a checksum")


def table_row_counts(conn: sqlite3.Connection) -> dict[str, int]:
    """Return row counts for application tables, excluding migration metadata."""
    tables = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name != ? "
            "ORDER BY name",
            (LEDGER_TABLE,),
        )
    ]
    counts: dict[str, int] = {}
    for table in tables:
        quoted = table.replace('"', '""')
        counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{quoted}"').fetchone()[0]
    return counts


def _ensure_ledger(conn: sqlite3.Connection) -> None:
    if conn.in_transaction:
        raise MigrationError("migrations require a connection with no active transaction")
    conn.execute(LEDGER_SQL)
    conn.commit()


def _applied_rows(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    return list(
        conn.execute(
            f"SELECT version, name, checksum FROM {LEDGER_TABLE} ORDER BY version"
        )
    )


def _validate_history(conn: sqlite3.Connection, migrations: Sequence[Migration]) -> None:
    applied = _applied_rows(conn)
    known_versions = [migration.version for migration in migrations]
    applied_versions = [row[0] for row in applied]
    if applied_versions != known_versions[: len(applied_versions)]:
        raise MigrationError(
            f"applied migration history is not a valid ordered prefix: {applied_versions}"
        )

    by_version = {migration.version: migration for migration in migrations}
    for version, name, checksum in applied:
        migration = by_version[version]
        if name != migration.name:
            raise MigrationError(
                f"migration {version} name changed: database={name}, code={migration.name}"
            )
        if checksum != migration.checksum:
            raise MigrationError(f"migration {version} checksum changed after application")


def _verify_integrity(conn: sqlite3.Connection) -> None:
    integrity_rows = [row[0] for row in conn.execute("PRAGMA integrity_check")]
    if integrity_rows != ["ok"]:
        raise MigrationError(f"SQLite integrity check failed: {integrity_rows}")
    foreign_key_rows = list(conn.execute("PRAGMA foreign_key_check"))
    if foreign_key_rows:
        raise MigrationError(
            f"SQLite foreign-key check found {len(foreign_key_rows)} violation(s)"
        )


def _verify_preserved_rows(
    before: dict[str, int], after: dict[str, int], migration: Migration
) -> None:
    if not migration.preserve_row_counts:
        return
    changed = {
        table: (count, after.get(table))
        for table, count in before.items()
        if after.get(table) != count
    }
    if changed:
        raise MigrationError(
            f"migration {migration.version} changed existing table row counts: {changed}"
        )


def apply_migrations(
    conn: sqlite3.Connection,
    migrations: Sequence[Migration] | None = None,
) -> tuple[MigrationResult, ...]:
    """Apply every pending migration atomically and verify the resulting schema."""
    selected = tuple(migrations) if migrations is not None else load_migrations()
    _validate_migration_definitions(selected)
    conn.execute("PRAGMA foreign_keys = ON")
    _ensure_ledger(conn)
    _validate_history(conn, selected)

    applied_versions = {row[0] for row in _applied_rows(conn)}
    results: list[MigrationResult] = []
    for migration in selected:
        if migration.version in applied_versions:
            continue

        conn.execute("BEGIN IMMEDIATE")
        try:
            before = table_row_counts(conn)
            migration.upgrade(conn)
            migration.verify(conn)
            after = table_row_counts(conn)
            _verify_preserved_rows(before, after, migration)
            _verify_integrity(conn)
            conn.execute(
                f"INSERT INTO {LEDGER_TABLE} (version, name, checksum, applied_at) "
                "VALUES (?, ?, ?, ?)",
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            if isinstance(exc, MigrationError):
                raise
            raise MigrationError(
                f"migration {migration.version} ({migration.name}) failed: {exc}"
            ) from exc

        results.append(
            MigrationResult(
                version=migration.version,
                name=migration.name,
                before_counts=before,
                after_counts=after,
            )
        )

    for migration in selected:
        try:
            migration.verify(conn)
        except Exception as exc:
            raise MigrationError(
                f"schema verification failed for migration {migration.version} "
                f"({migration.name}): {exc}"
            ) from exc
    _verify_integrity(conn)
    return tuple(results)
