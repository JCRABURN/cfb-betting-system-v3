import hashlib
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from migrations.runner import apply_migrations

from operations.cloud_execution import execute_cloud_production_operation
from operations.cloud_persistence import (
    CloudCommit,
    CloudPersistenceError,
    CloudSnapshot,
    CloudWriterBusy,
    PostgreSQLSnapshotStore,
    _validate_sqlite_snapshot,
    load_cloud_migrations,
)


ROOT = Path(__file__).resolve().parents[1]
COMMIT_SHA = "a" * 40


@dataclass(frozen=True)
class _CloudSettings:
    operation: str
    idempotency_key: str
    database_path: Path


class _Result:
    def __init__(self, row=None, rows=(), rowcount=0):
        self._row = row
        self._rows = rows
        self.rowcount = rowcount

    def fetchone(self):
        return self._row

    def fetchall(self):
        return self._rows


class _SharedDatabase:
    def __init__(self):
        self.writer_lock = threading.Lock()
        self.payload = b"durable-state"
        self.payload_sha = hashlib.sha256(self.payload).hexdigest()
        self.transactions = []


class _Transaction:
    def __init__(self, connection):
        self.connection = connection
        self.rolled_back = False
        self.committed = False

    def __enter__(self):
        self.connection.shared.transactions.append(self)
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.rolled_back = exc_type is not None
        self.committed = exc_type is None
        if self.connection.owns_writer_lock:
            self.connection.shared.writer_lock.release()
            self.connection.owns_writer_lock = False
        return False


class _Connection:
    def __init__(self, shared):
        self.shared = shared
        self.owns_writer_lock = False
        self.closed = False

    def transaction(self):
        return _Transaction(self)

    def execute(self, sql, parameters=None):
        if "pg_try_advisory_xact_lock" in sql:
            acquired = self.shared.writer_lock.acquire(blocking=False)
            self.owns_writer_lock = acquired
            return _Result((acquired,))
        if "FROM cfb_v3_state_heads" in sql and "snapshot.payload" in sql:
            return _Result(
                (
                    1,
                    0,
                    self.shared.payload_sha,
                    len(self.shared.payload),
                    14,
                    COMMIT_SHA,
                    self.shared.payload,
                )
            )
        raise AssertionError(f"unexpected SQL in test connector: {sql}")

    def close(self):
        self.closed = True


def test_cloud_migrations_are_ordered_and_preserve_immutable_unique_history():
    migrations = load_cloud_migrations()
    assert [migration.version for migration in migrations] == [1, 2]
    combined = "\n".join(migration.sql for migration in migrations)
    assert "UNIQUE (stream_key, operation_key)" in combined
    assert "UNIQUE (stream_key, generation)" in combined
    assert "cfb_v3_state_snapshots_immutable" in combined
    assert "cfb_v3_operation_commits_immutable" in combined
    assert "ON DELETE RESTRICT" in combined


def test_sqlite_remains_a_valid_ephemeral_execution_snapshot(tmp_path):
    snapshot = tmp_path / "cfb.db"
    shutil.copy2(ROOT / "data" / "cfb.db", snapshot)
    connection = sqlite3.connect(snapshot)
    try:
        apply_migrations(connection)
    finally:
        connection.close()
    payload, checksum, schema_version = _validate_sqlite_snapshot(snapshot)
    assert len(payload) > 0
    assert checksum == hashlib.sha256(payload).hexdigest()
    assert schema_version == 14


def test_postgresql_writer_lock_serializes_ephemeral_runners():
    shared = _SharedDatabase()
    store = PostgreSQLSnapshotStore(
        "database-url-sentinel",
        connect=lambda _: _Connection(shared),
    )
    entered = threading.Event()
    release = threading.Event()
    failures = []

    def first_runner():
        try:
            with store.writer(
                stream_key="production",
                operation_key="v3:2026:week:1:tuesday_lock",
                actor="first",
                code_commit_sha=COMMIT_SHA,
            ) as lease:
                entered.set()
                release.wait(timeout=5)
                lease.finalized = True
        except Exception as exc:  # pragma: no cover - surfaced by assertion below
            failures.append(exc)

    thread = threading.Thread(target=first_runner)
    thread.start()
    assert entered.wait(timeout=5)
    with pytest.raises(CloudWriterBusy, match="another cloud writer"):
        with store.writer(
            stream_key="production",
            operation_key="v3:2026:week:1:tuesday_lock",
            actor="second",
            code_commit_sha=COMMIT_SHA,
        ):
            pytest.fail("a concurrent runner must not enter the publication boundary")
    release.set()
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert failures == []
    assert sum(transaction.committed for transaction in shared.transactions) == 1
    assert sum(transaction.rolled_back for transaction in shared.transactions) == 1


def test_cloud_writer_failure_rolls_back_and_never_finalizes_state():
    shared = _SharedDatabase()
    store = PostgreSQLSnapshotStore("database-url-sentinel", connect=lambda _: _Connection(shared))
    with pytest.raises(CloudPersistenceError, match="rolled back"):
        with store.writer(
            stream_key="production",
            operation_key="v3:2026:week:1:tuesday_lock",
            actor="runner",
            code_commit_sha=COMMIT_SHA,
        ):
            raise RuntimeError("simulated operation failure")
    assert len(shared.transactions) == 1
    assert shared.transactions[0].rolled_back is True
    assert shared.transactions[0].committed is False


def test_database_credentials_are_redacted_from_repr_and_connection_errors():
    secret = "database-url-secret-sentinel"

    def fail_connection(_):
        raise RuntimeError(f"cannot connect to {secret}")

    store = PostgreSQLSnapshotStore(secret, connect=fail_connection)
    assert secret not in repr(store)
    with pytest.raises(CloudPersistenceError) as captured:
        store.apply_migrations()
    assert secret not in str(captured.value)


def test_cloud_execution_commits_to_store_then_discards_runner_workspace(
    tmp_path, monkeypatch
):
    seed = tmp_path / "seed.db"
    shutil.copy2(ROOT / "data" / "cfb.db", seed)
    connection = sqlite3.connect(seed)
    try:
        apply_migrations(connection)
    finally:
        connection.close()
    seed_payload = seed.read_bytes()
    initial = CloudSnapshot(
        snapshot_id=10,
        generation=4,
        payload_sha256=hashlib.sha256(seed_payload).hexdigest(),
        payload_bytes=len(seed_payload),
        domain_schema_version=14,
        code_commit_sha=COMMIT_SHA,
    )

    class Lease:
        snapshot = initial

        def materialize(self, target):
            self.target = target
            target.write_bytes(seed_payload)

        def publish(self, source, *, result_sha256, metadata):
            assert source == self.target
            assert source.is_file()
            self.published = True
            published = CloudSnapshot(
                snapshot_id=11,
                generation=5,
                payload_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                payload_bytes=source.stat().st_size,
                domain_schema_version=14,
                code_commit_sha=COMMIT_SHA,
            )
            return CloudCommit(published, replayed=False, state_changed=True)

    class Store:
        def __init__(self):
            self.lease = Lease()
            self.migrated = False

        def apply_migrations(self):
            self.migrated = True
            return ()

        @contextmanager
        def writer(self, **kwargs):
            yield self.lease

    def fake_operation(settings, configuration, **kwargs):
        assert kwargs["managed_workspace"] is True
        assert settings.database_path.is_file()
        operation = SimpleNamespace(
            result_sha256="b" * 64,
            weekly_configuration_sha256="c" * 64,
            completed_at="2026-08-21T12:00:00+00:00",
        )
        return operation, SimpleNamespace(production_ready=True)

    monkeypatch.setattr(
        "operations.cloud_execution.execute_production_operation", fake_operation
    )
    store = Store()
    settings = _CloudSettings(
        operation="tuesday_lock",
        idempotency_key="v3:2026:week:1:tuesday_lock",
        database_path=seed,
    )
    configuration = SimpleNamespace(actor="owner")
    result, preflight = execute_cloud_production_operation(
        store,
        settings,
        configuration,
        code_commit_sha=COMMIT_SHA,
    )
    assert store.migrated is True
    assert store.lease.published is True
    assert result.durable_generation_before == 4
    assert result.durable_generation_after == 5
    assert result.runner_state_disposable is True
    assert preflight.production_ready is True
    assert not store.lease.target.exists()
