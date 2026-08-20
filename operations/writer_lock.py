"""Cross-process fail-closed writer serialization for one SQLite database."""

from __future__ import annotations

import json
import hashlib
import os
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


class WriterLockError(RuntimeError):
    """Raised when another writer or an unrecovered stale lease exists."""


@dataclass
class ProductionWriterLock:
    database_path: Path
    operation_key: str
    actor: str
    acquired_at: datetime
    _token: str = ""
    _lock_path: Path | None = None

    @property
    def lock_path(self) -> Path:
        return self.database_path.with_name(self.database_path.name + ".v3-writer.lock")

    def acquire(self) -> "ProductionWriterLock":
        if self._token:
            raise WriterLockError("writer lock is already acquired by this instance")
        if self.acquired_at.tzinfo is None or self.acquired_at.utcoffset() is None:
            raise WriterLockError("writer lock timestamp must be timezone-aware")
        token = secrets.token_hex(16)
        payload = json.dumps(
            {
                "operation_key": self.operation_key,
                "actor": self.actor,
                "acquired_at": self.acquired_at.astimezone(timezone.utc).isoformat(),
                "process_id": os.getpid(),
                "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        path = self.lock_path
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise WriterLockError(
                "another writer or unrecovered writer lock exists; engage the kill "
                "switch and follow recovery before retrying"
            ) from exc
        try:
            os.write(descriptor, payload)
            os.fsync(descriptor)
        except Exception:
            os.close(descriptor)
            path.unlink(missing_ok=True)
            raise
        os.close(descriptor)
        self._token = token
        self._lock_path = path
        return self

    def release(self) -> None:
        if not self._token or self._lock_path is None:
            return
        path = self._lock_path
        try:
            recorded = json.loads(path.read_text(encoding="utf-8"))
            expected = hashlib.sha256(self._token.encode()).hexdigest()
            if recorded.get("token_sha256") != expected:
                raise WriterLockError("writer lock ownership changed; lock was not removed")
            path.unlink()
        finally:
            self._token = ""
            self._lock_path = None

    def __enter__(self) -> "ProductionWriterLock":
        return self.acquire()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()
