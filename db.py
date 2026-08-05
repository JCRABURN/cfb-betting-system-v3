"""Shared SQLite access layer for the CFB Betting System.

The committed database lives at ``data/cfb.db``. Schema changes are applied by
the ordered, checksummed migration runner in ``migrations/``; application code
must never issue ad hoc schema patches.
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

from migrations.runner import MigrationResult, apply_migrations


_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_ROOT, "data", "cfb.db")


def _load_dotenv(path: str | None = None) -> None:
    """Load local environment values without overriding real environment vars."""
    path = path or os.path.join(_ROOT, ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_dotenv()


def get_connection() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> tuple[MigrationResult, ...]:
    """Apply pending schema migrations and return the migrations applied."""
    conn = get_connection()
    try:
        return apply_migrations(conn)
    finally:
        conn.close()


@contextmanager
def log_run(source: str):
    """Record an ingestion run as success or error while preserving failures."""
    init_db()
    conn = get_connection()
    started_at = datetime.utcnow().isoformat()
    run = {"rows_added": 0}
    try:
        yield run
        conn.execute(
            "INSERT INTO ingestion_runs (source, started_at, finished_at, rows_added, status) "
            "VALUES (?, ?, ?, ?, 'success')",
            (source, started_at, datetime.utcnow().isoformat(), run["rows_added"]),
        )
        conn.commit()
    except Exception as exc:
        conn.execute(
            "INSERT INTO ingestion_runs "
            "(source, started_at, finished_at, rows_added, status, error) "
            "VALUES (?, ?, ?, ?, 'error', ?)",
            (
                source,
                started_at,
                datetime.utcnow().isoformat(),
                run["rows_added"],
                str(exc),
            ),
        )
        conn.commit()
        raise
    finally:
        conn.close()
