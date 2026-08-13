"""Shared validation and transaction helpers for append-only business records."""

from __future__ import annotations

import itertools
import math
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator


SHA1 = re.compile(r"^[0-9a-fA-F]{40}$")
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_SAVEPOINT_IDS = itertools.count(1)


class BusinessEntityError(RuntimeError):
    """Base error for invalid business-entity operations."""


class BusinessEntityConflictError(BusinessEntityError):
    """Raised when an immutable key conflicts with a recorded value."""


@contextmanager
def atomic(conn: sqlite3.Connection) -> Iterator[None]:
    name = f"business_entities_{next(_SAVEPOINT_IDS)}"
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
        raise
    else:
        conn.execute(f"RELEASE SAVEPOINT {name}")


def required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise BusinessEntityError(f"{field} must be non-empty text")
    return value


def optional_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return required_text(value, field)


def integer(value: int, field: str, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise BusinessEntityError(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        raise BusinessEntityError(f"{field} must be at least {minimum}")
    return value


def optional_integer(
    value: int | None, field: str, minimum: int | None = None
) -> int | None:
    if value is None:
        return None
    return integer(value, field, minimum)


def number(value: float | int, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BusinessEntityError(f"{field} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise BusinessEntityError(f"{field} must be finite")
    return converted


def optional_number(value: float | int | None, field: str) -> float | None:
    if value is None:
        return None
    return number(value, field)


def choice(value: str, field: str, allowed: tuple[str, ...]) -> str:
    value = required_text(value, field)
    if value not in allowed:
        raise BusinessEntityError(f"{field} must be one of: {', '.join(allowed)}")
    return value


def checksum(value: str, field: str, pattern: re.Pattern[str]) -> str:
    value = required_text(value, field)
    if pattern.fullmatch(value) is None:
        raise BusinessEntityError(f"{field} must be a lowercase hexadecimal checksum")
    return value.lower()


def utc_timestamp(value: datetime | None, field: str) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise BusinessEntityError(f"{field} must be a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat()


def timestamp_on_or_before(
    conn: sqlite3.Connection, earlier: str, later: str
) -> bool:
    row = conn.execute(
        "SELECT julianday(?) IS NOT NULL AND julianday(?) <= julianday(?)",
        (earlier, earlier, later),
    ).fetchone()
    return row is not None and row[0] == 1


def translate_integrity(entity: str, exc: sqlite3.IntegrityError) -> BusinessEntityConflictError:
    return BusinessEntityConflictError(f"{entity} conflicts with recorded data: {exc}")
