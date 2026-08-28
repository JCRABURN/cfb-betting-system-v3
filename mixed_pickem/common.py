"""Deterministic validation and hashing primitives for Product B custody."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone


KEY = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class MixedPickemValidationError(ValueError):
    """Raised when Product B input cannot be represented without guessing."""


def canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise MixedPickemValidationError("value is not canonical JSON") from exc


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def require_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MixedPickemValidationError(f"{field} must be non-empty text")
    return value.strip()


def require_key(value: str, field: str) -> str:
    value = require_text(value, field)
    if KEY.fullmatch(value) is None:
        raise MixedPickemValidationError(
            f"{field} must contain only lowercase letters, digits, underscores, or hyphens"
        )
    return value


def require_sha256(value: str, field: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise MixedPickemValidationError(
            f"{field} must be a lowercase 64-character SHA-256"
        )
    return value


def utc_datetime(value: datetime, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise MixedPickemValidationError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def utc_text(value: datetime, field: str) -> str:
    return utc_datetime(value, field).isoformat()


def parse_explicit_timestamp(value: str) -> str:
    raw = require_text(value, "kickoff")
    normalized = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MixedPickemValidationError("kickoff is not valid ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise MixedPickemValidationError("kickoff requires an explicit timezone offset")
    return parsed.astimezone(timezone.utc).isoformat()
