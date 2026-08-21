"""Durable PostgreSQL snapshots for ephemeral production runners."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from migrations.runner import load_migrations


CLOUD_MIGRATION_LEDGER = "cfb_v3_cloud_schema_migrations"
CLOUD_MIGRATION_LOCK_KEY = 0x43464256334D4947
MAX_SNAPSHOT_BYTES = 256 * 1024 * 1024


class CloudPersistenceError(RuntimeError):
    """Raised with a redacted message when managed persistence fails safely."""


class CloudWriterBusy(CloudPersistenceError):
    """Raised when another ephemeral runner owns the production writer lock."""


@dataclass(frozen=True)
class CloudMigration:
    version: int
    name: str
    checksum: str
    sql: str = field(repr=False)


@dataclass(frozen=True)
class CloudSnapshot:
    snapshot_id: int
    generation: int
    payload_sha256: str
    payload_bytes: int
    domain_schema_version: int
    code_commit_sha: str


@dataclass(frozen=True)
class CloudCommit:
    snapshot: CloudSnapshot
    replayed: bool
    state_changed: bool


class SnapshotLease(Protocol):
    snapshot: CloudSnapshot

    def materialize(self, target: Path) -> None: ...

    def publish(
        self,
        source: Path,
        *,
        result_sha256: str,
        metadata: Mapping[str, object],
    ) -> CloudCommit: ...


class SnapshotStore(Protocol):
    def apply_migrations(self) -> tuple[int, ...]: ...

    @contextmanager
    def writer(
        self,
        *,
        stream_key: str,
        operation_key: str,
        actor: str,
        code_commit_sha: str,
    ) -> Iterator[SnapshotLease]: ...


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _lock_key(value: str) -> int:
    return int.from_bytes(
        hashlib.sha256(value.encode("utf-8")).digest()[:8],
        byteorder="big",
        signed=True,
    )


def _validate_sha256(value: str, field_name: str) -> str:
    normalized = value.casefold()
    if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
        raise CloudPersistenceError(f"{field_name} must be lowercase SHA-256")
    return normalized


def _validate_commit_sha(value: str) -> str:
    normalized = value.casefold()
    if len(normalized) != 40 or any(character not in "0123456789abcdef" for character in normalized):
        raise CloudPersistenceError("code commit must be lowercase SHA-1")
    return normalized


def _validate_identifier(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized or len(normalized) > 512:
        raise CloudPersistenceError(f"{field_name} must be non-empty and at most 512 characters")
    return normalized


def load_cloud_migrations(root: Path | None = None) -> tuple[CloudMigration, ...]:
    """Load the complete ordered PostgreSQL migration inventory."""
    migration_root = (
        root.resolve()
        if root is not None
        else Path(__file__).resolve().parents[1] / "cloud_migrations" / "versions"
    )
    migrations: list[CloudMigration] = []
    for path in sorted(migration_root.glob("v[0-9][0-9][0-9][0-9]_*.sql")):
        version = int(path.name[1:5])
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            CloudMigration(
                version=version,
                name=path.stem[6:],
                checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                sql=sql,
            )
        )
    expected = list(range(1, len(migrations) + 1))
    if not migrations or [migration.version for migration in migrations] != expected:
        raise CloudPersistenceError("cloud migration inventory must be contiguous from version 1")
    return tuple(migrations)


def _validate_sqlite_snapshot(path: Path) -> tuple[bytes, str, int]:
    """Read and verify one closed SQLite snapshot without modifying it."""
    resolved = path.resolve()
    if not resolved.is_file():
        raise CloudPersistenceError("snapshot source is not a regular file")
    for suffix in ("-journal", "-wal", "-shm"):
        if Path(str(resolved) + suffix).exists():
            raise CloudPersistenceError("snapshot has an uncheckpointed SQLite sidecar")
    size = resolved.stat().st_size
    if size <= 0 or size > MAX_SNAPSHOT_BYTES:
        raise CloudPersistenceError("snapshot size is outside the governed range")
    uri = f"file:{resolved.as_posix()}?mode=ro"
    try:
        connection = sqlite3.connect(uri, uri=True)
        connection.execute("PRAGMA query_only = ON")
        try:
            integrity = tuple(row[0] for row in connection.execute("PRAGMA integrity_check"))
            violations = tuple(connection.execute("PRAGMA foreign_key_check"))
            ledger = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise CloudPersistenceError("snapshot SQLite verification failed") from None
    expected_version = load_migrations()[-1].version
    domain_version = int(ledger[0]) if ledger is not None else 0
    if integrity != ("ok",) or violations or domain_version != expected_version:
        raise CloudPersistenceError("snapshot integrity, foreign keys, or migration version is invalid")
    payload = resolved.read_bytes()
    if len(payload) != size:
        raise CloudPersistenceError("snapshot changed while it was being read")
    return payload, _sha256_bytes(payload), domain_version


def _migration_ledger_sql() -> str:
    return f"""
        CREATE TABLE IF NOT EXISTS {CLOUD_MIGRATION_LEDGER} (
            version INTEGER PRIMARY KEY CHECK (version > 0),
            name TEXT NOT NULL,
            checksum CHAR(64) NOT NULL CHECK (checksum ~ '^[0-9a-f]{{64}}$'),
            applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """


class PostgreSQLSnapshotStore:
    """Managed PostgreSQL system of record; credentials are never represented."""

    def __init__(
        self,
        database_url: str,
        *,
        connect: Callable[[str], Any] | None = None,
    ) -> None:
        if not database_url.strip():
            raise CloudPersistenceError("CFB_V3_DATABASE_URL is required")
        self._database_url = database_url
        self._connector = connect

    def __repr__(self) -> str:
        return "PostgreSQLSnapshotStore(database_url=<redacted>)"

    def _connect(self) -> Any:
        try:
            if self._connector is not None:
                return self._connector(self._database_url)
            import psycopg

            return psycopg.connect(
                self._database_url,
                connect_timeout=15,
                application_name="cfb-betting-system-v3",
            )
        except Exception:
            raise CloudPersistenceError("managed PostgreSQL connection failed") from None

    def apply_migrations(self) -> tuple[int, ...]:
        """Apply and checksum the complete cloud schema in one transaction."""
        migrations = load_cloud_migrations()
        connection = self._connect()
        applied_now: list[int] = []
        try:
            with connection.transaction():
                connection.execute("SELECT pg_advisory_xact_lock(%s)", (CLOUD_MIGRATION_LOCK_KEY,))
                connection.execute(_migration_ledger_sql())
                rows = connection.execute(
                    f"SELECT version, name, checksum FROM {CLOUD_MIGRATION_LEDGER} ORDER BY version"
                ).fetchall()
                applied = {int(row[0]): (str(row[1]), str(row[2])) for row in rows}
                known = {migration.version: migration for migration in migrations}
                if any(version not in known for version in applied):
                    raise CloudPersistenceError("cloud migration ledger contains an unknown version")
                for version, (name, checksum) in applied.items():
                    migration = known[version]
                    if name != migration.name or checksum != migration.checksum:
                        raise CloudPersistenceError("cloud migration history checksum mismatch")
                for migration in migrations:
                    if migration.version in applied:
                        continue
                    connection.execute(migration.sql)
                    connection.execute(
                        f"INSERT INTO {CLOUD_MIGRATION_LEDGER} (version, name, checksum) "
                        "VALUES (%s, %s, %s)",
                        (migration.version, migration.name, migration.checksum),
                    )
                    applied_now.append(migration.version)
        except CloudPersistenceError:
            raise
        except Exception:
            raise CloudPersistenceError("cloud migration transaction failed and was rolled back") from None
        finally:
            connection.close()
        return tuple(applied_now)

    def bootstrap(
        self,
        source: Path,
        *,
        stream_key: str,
        actor: str,
        code_commit_sha: str,
        metadata: Mapping[str, object],
    ) -> CloudCommit:
        """Create generation zero once; an existing different state fails closed."""
        stream = _validate_identifier(stream_key, "stream_key")
        owner = _validate_identifier(actor, "actor")
        commit_sha = _validate_commit_sha(code_commit_sha)
        payload, payload_sha, domain_version = _validate_sqlite_snapshot(source)
        metadata_json = json.dumps(dict(metadata), sort_keys=True, separators=(",", ":"))
        connection = self._connect()
        try:
            with connection.transaction():
                acquired = connection.execute(
                    "SELECT pg_try_advisory_xact_lock(%s)", (_lock_key(stream),)
                ).fetchone()
                if acquired is None or acquired[0] is not True:
                    raise CloudWriterBusy("another cloud writer currently owns this production stream")
                existing = connection.execute(
                    "SELECT snapshot.id, snapshot.generation, snapshot.payload_sha256, "
                    "snapshot.payload_bytes, snapshot.domain_schema_version, "
                    "snapshot.code_commit_sha FROM cfb_v3_state_heads AS head "
                    "JOIN cfb_v3_state_snapshots AS snapshot ON snapshot.id = head.snapshot_id "
                    "WHERE head.stream_key = %s FOR UPDATE OF head",
                    (stream,),
                ).fetchone()
                if existing is not None:
                    snapshot = _snapshot_from_row(existing)
                    if snapshot.payload_sha256 != payload_sha:
                        raise CloudPersistenceError("cloud stream is already bootstrapped with different state")
                    return CloudCommit(snapshot=snapshot, replayed=True, state_changed=False)
                row = connection.execute(
                    "INSERT INTO cfb_v3_state_snapshots "
                    "(stream_key, generation, parent_snapshot_id, payload, payload_sha256, "
                    "payload_bytes, domain_schema_version, code_commit_sha, metadata) "
                    "VALUES (%s, 0, NULL, %s, %s, %s, %s, %s, %s::jsonb) "
                    "RETURNING id, generation, payload_sha256, payload_bytes, "
                    "domain_schema_version, code_commit_sha",
                    (
                        stream,
                        payload,
                        payload_sha,
                        len(payload),
                        domain_version,
                        commit_sha,
                        metadata_json,
                    ),
                ).fetchone()
                if row is None:
                    raise CloudPersistenceError("cloud bootstrap did not return a snapshot")
                snapshot = _snapshot_from_row(row)
                connection.execute(
                    "INSERT INTO cfb_v3_state_heads (stream_key, snapshot_id, generation) "
                    "VALUES (%s, %s, %s)",
                    (stream, snapshot.snapshot_id, snapshot.generation),
                )
                return CloudCommit(snapshot=snapshot, replayed=False, state_changed=True)
        except (CloudPersistenceError, CloudWriterBusy):
            raise
        except Exception:
            raise CloudPersistenceError("cloud bootstrap transaction failed and was rolled back") from None
        finally:
            connection.close()

    @contextmanager
    def writer(
        self,
        *,
        stream_key: str,
        operation_key: str,
        actor: str,
        code_commit_sha: str,
    ) -> Iterator[SnapshotLease]:
        """Hold one PostgreSQL transaction and advisory lock across an operation."""
        stream = _validate_identifier(stream_key, "stream_key")
        operation = _validate_identifier(operation_key, "operation_key")
        owner = _validate_identifier(actor, "actor")
        commit_sha = _validate_commit_sha(code_commit_sha)
        connection = self._connect()
        try:
            with connection.transaction():
                acquired = connection.execute(
                    "SELECT pg_try_advisory_xact_lock(%s)", (_lock_key(stream),)
                ).fetchone()
                if acquired is None or acquired[0] is not True:
                    raise CloudWriterBusy("another cloud writer currently owns this production stream")
                row = connection.execute(
                    "SELECT snapshot.id, snapshot.generation, snapshot.payload_sha256, "
                    "snapshot.payload_bytes, snapshot.domain_schema_version, "
                    "snapshot.code_commit_sha, snapshot.payload "
                    "FROM cfb_v3_state_heads AS head "
                    "JOIN cfb_v3_state_snapshots AS snapshot ON snapshot.id = head.snapshot_id "
                    "WHERE head.stream_key = %s FOR UPDATE OF head",
                    (stream,),
                ).fetchone()
                if row is None:
                    raise CloudPersistenceError("cloud production stream is not bootstrapped")
                snapshot = _snapshot_from_row(row[:6])
                payload = bytes(row[6])
                if len(payload) != snapshot.payload_bytes or _sha256_bytes(payload) != snapshot.payload_sha256:
                    raise CloudPersistenceError("durable cloud snapshot checksum mismatch")
                lease = _PostgreSQLSnapshotLease(
                    connection=connection,
                    stream_key=stream,
                    operation_key=operation,
                    actor=owner,
                    code_commit_sha=commit_sha,
                    snapshot=snapshot,
                    payload=payload,
                )
                yield lease
                if not lease.finalized:
                    raise CloudPersistenceError("cloud writer exited without an atomic publication")
        except (CloudPersistenceError, CloudWriterBusy):
            raise
        except Exception:
            raise CloudPersistenceError("cloud writer transaction failed and was rolled back") from None
        finally:
            connection.close()


def _snapshot_from_row(row: Any) -> CloudSnapshot:
    return CloudSnapshot(
        snapshot_id=int(row[0]),
        generation=int(row[1]),
        payload_sha256=str(row[2]),
        payload_bytes=int(row[3]),
        domain_schema_version=int(row[4]),
        code_commit_sha=str(row[5]),
    )


@dataclass
class _PostgreSQLSnapshotLease:
    connection: Any = field(repr=False)
    stream_key: str
    operation_key: str
    actor: str
    code_commit_sha: str
    snapshot: CloudSnapshot
    payload: bytes = field(repr=False)
    finalized: bool = False

    def materialize(self, target: Path) -> None:
        if self.finalized:
            raise CloudPersistenceError("cloud lease is already finalized")
        destination = target.resolve()
        if destination.exists() or not destination.parent.is_dir():
            raise CloudPersistenceError("ephemeral snapshot target must be new")
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, self.payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if _sha256_bytes(destination.read_bytes()) != self.snapshot.payload_sha256:
            destination.unlink(missing_ok=True)
            raise CloudPersistenceError("ephemeral snapshot materialization checksum mismatch")

    def publish(
        self,
        source: Path,
        *,
        result_sha256: str,
        metadata: Mapping[str, object],
    ) -> CloudCommit:
        if self.finalized:
            raise CloudPersistenceError("cloud lease is already finalized")
        result_hash = _validate_sha256(result_sha256, "result_sha256")
        payload, payload_sha, domain_version = _validate_sqlite_snapshot(source)
        metadata_json = json.dumps(dict(metadata), sort_keys=True, separators=(",", ":"))
        existing = self.connection.execute(
            "SELECT snapshot.id, snapshot.generation, snapshot.payload_sha256, "
            "snapshot.payload_bytes, snapshot.domain_schema_version, snapshot.code_commit_sha "
            "FROM cfb_v3_operation_commits AS operation "
            "JOIN cfb_v3_state_snapshots AS snapshot ON snapshot.id = operation.snapshot_id "
            "WHERE operation.stream_key = %s AND operation.operation_key = %s",
            (self.stream_key, self.operation_key),
        ).fetchone()
        if existing is not None:
            if payload_sha != self.snapshot.payload_sha256:
                raise CloudPersistenceError("idempotent replay produced different durable state")
            self.finalized = True
            return CloudCommit(snapshot=self.snapshot, replayed=True, state_changed=False)

        state_changed = payload_sha != self.snapshot.payload_sha256
        if state_changed:
            row = self.connection.execute(
                "INSERT INTO cfb_v3_state_snapshots "
                "(stream_key, generation, parent_snapshot_id, payload, payload_sha256, "
                "payload_bytes, domain_schema_version, code_commit_sha, metadata) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb) "
                "RETURNING id, generation, payload_sha256, payload_bytes, "
                "domain_schema_version, code_commit_sha",
                (
                    self.stream_key,
                    self.snapshot.generation + 1,
                    self.snapshot.snapshot_id,
                    payload,
                    payload_sha,
                    len(payload),
                    domain_version,
                    self.code_commit_sha,
                    metadata_json,
                ),
            ).fetchone()
            if row is None:
                raise CloudPersistenceError("cloud publication did not return a snapshot")
            published = _snapshot_from_row(row)
            updated = self.connection.execute(
                "UPDATE cfb_v3_state_heads SET snapshot_id = %s, generation = %s, "
                "updated_at = CURRENT_TIMESTAMP WHERE stream_key = %s AND snapshot_id = %s",
                (
                    published.snapshot_id,
                    published.generation,
                    self.stream_key,
                    self.snapshot.snapshot_id,
                ),
            )
            if updated.rowcount != 1:
                raise CloudPersistenceError("cloud head changed despite the writer lock")
        else:
            published = self.snapshot
        self.connection.execute(
            "INSERT INTO cfb_v3_operation_commits "
            "(stream_key, operation_key, snapshot_id, result_sha256, actor, code_commit_sha) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (
                self.stream_key,
                self.operation_key,
                published.snapshot_id,
                result_hash,
                self.actor,
                self.code_commit_sha,
            ),
        )
        self.finalized = True
        return CloudCommit(snapshot=published, replayed=not state_changed, state_changed=state_changed)
