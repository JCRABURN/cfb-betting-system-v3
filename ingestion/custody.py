"""Append-only, offline-testable provider ingestion custody.

The module deliberately owns no HTTP client and reads no credentials. Callers
hand it an already-captured payload or a replay fixture. Records are parsed and
validated before a transaction can expose them to an optional canonical writer.
Invalid records are quarantined with stable reason codes instead of entering a
canonical table.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import unicodedata
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from types import MappingProxyType
from typing import Literal, Protocol
from urllib.parse import urlsplit, urlunsplit


FRESHNESS_POLICY_VERSION = "provider_freshness_v1"
DEFAULT_FRESHNESS_RULES: Mapping[str, int] = MappingProxyType({
    "odds": 15 * 60,
    "injuries": 6 * 60 * 60,
    "weather": 3 * 60 * 60,
    "game_status": 5 * 60,
    "contextual": 24 * 60 * 60,
})
SUPPORTED_DATA_TYPE_ORDER = tuple(DEFAULT_FRESHNESS_RULES)
SUPPORTED_DATA_TYPES = frozenset(SUPPORTED_DATA_TYPE_ORDER)
SENSITIVE_PARAMETER_TOKENS = (
    "api_key",
    "apikey",
    "authorization",
    "bearer",
    "credential",
    "password",
    "private_key",
    "secret",
    "token",
)

# Provider-specific aliases live only at the canonical resolver boundary.
# Downstream parsers and card code must not add one-off corrections.
DEFAULT_TEAM_ALIASES: Mapping[str, Mapping[str, str]] = MappingProxyType({
    "the_odds_api": MappingProxyType({
        "Appalachian State": "App State",
        "UMass": "Massachusetts",
        "Southern Mississippi": "Southern Miss",
    })
})

RejectionCode = Literal[
    "unknown_team",
    "ambiguous_team_normalization",
    "malformed_spread",
    "duplicate_record",
    "invalid_timestamp",
    "stale_data",
    "unsupported_market_type",
    "missing_matchup_identifier",
    "reversed_matchup",
    "game_mapping_not_found",
    "conflicting_game_mapping",
    "malformed_record",
]


class ProviderIngestionError(RuntimeError):
    """Raised when an ingestion request or transaction cannot be trusted."""


class RecordRejected(ValueError):
    """Internal record-level validation failure with a stable audit code."""

    def __init__(self, code: RejectionCode, reason: str) -> None:
        super().__init__(reason)
        self.code = code
        self.reason = reason


@dataclass(frozen=True)
class TeamResolution:
    raw_name: str
    status: Literal["resolved", "unknown", "ambiguous"]
    canonical_name: str | None
    method: str | None
    candidates: tuple[str, ...] = ()


@dataclass(frozen=True)
class IngestionRequest:
    provider: str
    endpoint: str
    request_parameters: Mapping[str, object]
    requested_at: datetime | str
    parser_version: str
    raw_payload_reference: str
    data_type: str
    expected_payload_sha256: str | None = None


@dataclass(frozen=True)
class AcceptedProviderRecord:
    """Provider-neutral accepted-record custody required by every parser."""

    record_index: int
    provider_record_id: str
    record_key: str
    observed_at: datetime
    parser_version: str
    raw_record_sha256: str


@dataclass(frozen=True)
class ParsedMarketRecord(AcceptedProviderRecord):
    game_id: int
    season: int
    week: int
    raw_home_team: str
    raw_away_team: str
    normalized_home_team: str
    normalized_away_team: str
    bookmaker: str
    market_type: str
    home_spread: float
    home_price: int | None
    away_spread: float | None
    away_price: int | None
    line_type: str
    event_start_at: datetime

    @property
    def provider_matchup_id(self) -> str:
        return self.provider_record_id


@dataclass(frozen=True)
class QuarantinedRecord:
    record_index: int
    provider_record_id: str | None
    rejection_code: RejectionCode
    rejection_reason: str
    raw_record_sha256: str
    raw_record: str


@dataclass(frozen=True)
class IngestionSummary:
    ingestion_run_id: int
    run_key: str
    status: str
    rows_received: int
    rows_accepted: int
    rows_rejected: int
    payload_sha256: str
    replayed: bool


@dataclass(frozen=True)
class FreshnessAssessment:
    data_type: str
    provider: str | None
    state: Literal["current", "partial", "stale", "missing"]
    as_of: str
    ingestion_run_id: int | None
    observed_at: str | None
    expires_at: str | None
    policy_version: str
    reason: str

    @property
    def usable_without_fallback(self) -> bool:
        return self.state == "current"


class RecordParser(Protocol):
    version: str

    def parse(
        self,
        conn: sqlite3.Connection,
        resolver: "CanonicalTeamResolver",
        provider: str,
        request: IngestionRequest,
        record_index: int,
        record: Mapping[str, object],
    ) -> AcceptedProviderRecord: ...


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordRejected("malformed_record", f"{field} is required")
    return value.strip()


def _required_integer(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RecordRejected("malformed_record", f"{field} must be an integer")
    return value


def _parse_utc(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise RecordRejected("invalid_timestamp", f"{field} must be a UTC timestamp")
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise RecordRejected("invalid_timestamp", f"{field} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise RecordRejected("invalid_timestamp", f"{field} must have a UTC offset")
    return parsed.astimezone(timezone.utc)


def _request_utc(value: datetime | str) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ProviderIngestionError("requested_at must be timezone-aware UTC")
        return value.astimezone(timezone.utc)
    try:
        return _parse_utc(value, "requested_at")
    except RecordRejected as exc:
        raise ProviderIngestionError(exc.reason) from exc


def _utc_text(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ProviderIngestionError(f"value is not canonical JSON: {exc}") from exc


def _raw_record_json(value: object) -> str:
    try:
        return _canonical_json(value)
    except ProviderIngestionError:
        return _canonical_json({"unserializable_record": repr(value)})


def _payload_bytes(payload: object) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return _canonical_json(payload).encode("utf-8")


def payload_sha256(payload: object) -> str:
    """Return the checksum of exact bytes or canonical JSON for Python values."""
    return hashlib.sha256(_payload_bytes(payload)).hexdigest()


def _normalize_name(name: str) -> str:
    name = name.replace("’", "'").replace("'", "")
    decomposed = unicodedata.normalize("NFKD", name)
    without_marks = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(without_marks.casefold().split())


def _sanitize_parameters(value: object) -> object:
    if isinstance(value, Mapping):
        sanitized: dict[str, object] = {}
        for raw_key, child in value.items():
            key = str(raw_key)
            folded = key.casefold().replace("-", "_")
            if any(token in folded for token in SENSITIVE_PARAMETER_TOKENS):
                continue
            sanitized[key] = _sanitize_parameters(child)
        return sanitized
    if isinstance(value, (list, tuple)):
        return [_sanitize_parameters(child) for child in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _sanitize_endpoint(endpoint: str) -> str:
    endpoint = endpoint.strip()
    if not endpoint:
        raise ProviderIngestionError("endpoint is required")
    split = urlsplit(endpoint)
    if split.username or split.password:
        raise ProviderIngestionError("endpoint must not contain credentials")
    if split.scheme:
        return urlunsplit((split.scheme, split.netloc, split.path, "", ""))
    return endpoint.split("?", 1)[0]


def _validate_sha256(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    normalized = value.strip().casefold()
    if len(normalized) != 64 or any(c not in "0123456789abcdef" for c in normalized):
        raise ProviderIngestionError(f"{field} must be a SHA-256 hexadecimal digest")
    return normalized


class CanonicalTeamResolver:
    """Resolve every provider name at one strict, auditable boundary."""

    def __init__(
        self,
        schools: Iterable[str],
        aliases: Mapping[str, Mapping[str, str]] | None = None,
    ) -> None:
        self.schools = tuple(sorted({school for school in schools if school.strip()}))
        self.aliases = aliases or DEFAULT_TEAM_ALIASES

    @classmethod
    def from_connection(cls, conn: sqlite3.Connection) -> "CanonicalTeamResolver":
        schools = [row[0] for row in conn.execute("SELECT school FROM teams ORDER BY school")]
        aliases = {
            provider: dict(provider_aliases)
            for provider, provider_aliases in DEFAULT_TEAM_ALIASES.items()
        }
        for provider, raw_name, canonical in conn.execute(
            "SELECT provider, raw_team_name, canonical_team "
            "FROM provider_team_aliases ORDER BY id"
        ):
            aliases.setdefault(provider, {})[raw_name] = canonical
        return cls(schools, aliases)

    def resolve(self, provider: str, raw_name: object) -> TeamResolution:
        if not isinstance(raw_name, str) or not raw_name.strip():
            return TeamResolution(str(raw_name or ""), "unknown", None, None)
        raw = raw_name.strip()
        provider_aliases = self.aliases.get(provider, {})
        alias_candidates = {
            canonical
            for alias, canonical in provider_aliases.items()
            if raw == alias or raw.startswith(alias + " ")
            if canonical in self.schools
        }
        if len(alias_candidates) == 1:
            return TeamResolution(
                raw, "resolved", next(iter(alias_candidates)), "provider_alias"
            )
        if len(alias_candidates) > 1:
            return TeamResolution(
                raw, "ambiguous", None, "provider_alias", tuple(sorted(alias_candidates))
            )

        normalized = _normalize_name(raw)
        exact = [school for school in self.schools if _normalize_name(school) == normalized]
        if len(exact) == 1:
            return TeamResolution(raw, "resolved", exact[0], "normalized_exact")
        if len(exact) > 1:
            return TeamResolution(raw, "ambiguous", None, "normalized_exact", tuple(exact))

        prefixes = [
            school
            for school in self.schools
            if normalized.startswith(_normalize_name(school) + " ")
        ]
        if not prefixes:
            return TeamResolution(raw, "unknown", None, None)
        longest_length = max(len(_normalize_name(school)) for school in prefixes)
        longest = sorted(
            school for school in prefixes if len(_normalize_name(school)) == longest_length
        )
        if len(longest) > 1:
            return TeamResolution(raw, "ambiguous", None, "longest_prefix", tuple(longest))
        return TeamResolution(raw, "resolved", longest[0], "longest_prefix")


def _require_resolved(resolution: TeamResolution, side: str) -> str:
    if resolution.status == "unknown":
        raise RecordRejected("unknown_team", f"{side} team is unknown: {resolution.raw_name}")
    if resolution.status == "ambiguous":
        raise RecordRejected(
            "ambiguous_team_normalization",
            f"{side} team is ambiguous: {resolution.raw_name}; candidates={resolution.candidates}",
        )
    assert resolution.canonical_name is not None
    return resolution.canonical_name


class OddsSpreadParser:
    """Strict parser for one provider/book pregame home-spread observation."""

    def __init__(self, version: str = "odds_spread_v1") -> None:
        if not version.strip():
            raise ValueError("parser version is required")
        self.version = version.strip()

    def parse(
        self,
        conn: sqlite3.Connection,
        resolver: CanonicalTeamResolver,
        provider: str,
        request: IngestionRequest,
        record_index: int,
        record: Mapping[str, object],
    ) -> ParsedMarketRecord:
        if request.data_type != "odds":
            raise RecordRejected("malformed_record", "odds parser requires data_type=odds")
        provider_matchup_id = record.get("matchup_id")
        if not isinstance(provider_matchup_id, str) or not provider_matchup_id.strip():
            raise RecordRejected(
                "missing_matchup_identifier", "matchup_id is required for every odds record"
            )
        provider_matchup_id = provider_matchup_id.strip()
        raw_home = _required_text(record.get("home_team"), "home_team")
        raw_away = _required_text(record.get("away_team"), "away_team")
        home = _require_resolved(resolver.resolve(provider, raw_home), "home")
        away = _require_resolved(resolver.resolve(provider, raw_away), "away")
        if home == away:
            raise RecordRejected(
                "conflicting_game_mapping", "home and away resolve to the same canonical team"
            )

        market_type = _required_text(record.get("market_type"), "market_type").casefold()
        if market_type != "spread":
            raise RecordRejected(
                "unsupported_market_type", f"unsupported market type: {market_type}"
            )
        spread_value = record.get("home_spread")
        if (
            isinstance(spread_value, bool)
            or not isinstance(spread_value, (int, float))
            or not math.isfinite(float(spread_value))
            or not -100 <= float(spread_value) <= 100
        ):
            raise RecordRejected("malformed_spread", "home_spread must be finite and within [-100, 100]")
        home_spread = float(spread_value)
        price_value = record.get("home_price")
        if price_value is not None and (
            isinstance(price_value, bool) or not isinstance(price_value, int)
        ):
            raise RecordRejected("malformed_record", "home_price must be an integer when present")
        away_spread_value = record.get("away_spread")
        away_price_value = record.get("away_price")
        line_type_value = record.get("line_type", "current")
        if not isinstance(line_type_value, str) or line_type_value not in (
            "opening",
            "current",
            "closing",
        ):
            raise RecordRejected(
                "malformed_record", "line_type must be opening, current, or closing"
            )
        if self.version == "odds_spread_v3":
            if (
                isinstance(away_spread_value, bool)
                or not isinstance(away_spread_value, (int, float))
                or not math.isfinite(float(away_spread_value))
                or not -100 <= float(away_spread_value) <= 100
            ):
                raise RecordRejected(
                    "malformed_spread",
                    "away_spread must be finite and within [-100, 100]",
                )
            if not math.isclose(
                home_spread + float(away_spread_value), 0.0, abs_tol=1e-6
            ):
                raise RecordRejected(
                    "malformed_spread", "home and away spreads must be exact opposites"
                )
            for field, value in (
                ("home_price", price_value),
                ("away_price", away_price_value),
            ):
                if (
                    isinstance(value, bool)
                    or not isinstance(value, int)
                    or -100 < value < 100
                ):
                    raise RecordRejected(
                        "malformed_record", f"{field} must be valid American odds"
                    )
        elif away_spread_value is not None and (
            isinstance(away_spread_value, bool)
            or not isinstance(away_spread_value, (int, float))
            or not math.isfinite(float(away_spread_value))
        ):
            raise RecordRejected("malformed_spread", "away_spread must be finite")
        elif away_price_value is not None and (
            isinstance(away_price_value, bool) or not isinstance(away_price_value, int)
        ):
            raise RecordRejected(
                "malformed_record", "away_price must be an integer when present"
            )

        season = _required_integer(record.get("season"), "season")
        week = _required_integer(record.get("week"), "week")
        if season < 1869 or week < 0:
            raise RecordRejected("malformed_record", "season/week are outside valid bounds")
        observed_at = _parse_utc(record.get("observed_at"), "observed_at")
        event_start = _parse_utc(record.get("event_start_at"), "event_start_at")
        requested_at = _request_utc(request.requested_at)
        if observed_at > requested_at:
            raise RecordRejected("invalid_timestamp", "observed_at cannot be after requested_at")
        if observed_at > event_start:
            raise RecordRejected("invalid_timestamp", "odds observation cannot be after kickoff")
        max_age = DEFAULT_FRESHNESS_RULES["odds"]
        if requested_at - observed_at > timedelta(seconds=max_age):
            raise RecordRejected(
                "stale_data",
                f"odds observation exceeds {max_age}-second freshness limit",
            )

        exact_rows = list(
            conn.execute(
                "SELECT game_id, start_date FROM games "
                "WHERE season = ? AND week = ? AND home_team = ? AND away_team = ?",
                (season, week, home, away),
            )
        )
        reversed_rows = list(
            conn.execute(
                "SELECT game_id FROM games "
                "WHERE season = ? AND week = ? AND home_team = ? AND away_team = ?",
                (season, week, away, home),
            )
        )
        if not exact_rows and reversed_rows:
            raise RecordRejected(
                "reversed_matchup", "provider home/away orientation is reversed"
            )
        if not exact_rows:
            raise RecordRejected(
                "game_mapping_not_found", "no canonical game matches season, week, and teams"
            )
        if len(exact_rows) != 1 or reversed_rows:
            raise RecordRejected(
                "conflicting_game_mapping", "canonical matchup mapping is not unique"
            )
        game_id, canonical_start = exact_rows[0]
        supplied_game_id = record.get("game_id")
        if supplied_game_id is not None and supplied_game_id != game_id:
            raise RecordRejected(
                "conflicting_game_mapping", "supplied game_id conflicts with canonical matchup"
            )
        if canonical_start:
            try:
                canonical_start_at = _parse_utc(canonical_start, "games.start_date")
            except RecordRejected as exc:
                raise RecordRejected(
                    "conflicting_game_mapping", "canonical game has an invalid kickoff timestamp"
                ) from exc
            if canonical_start_at != event_start:
                raise RecordRejected(
                    "conflicting_game_mapping", "provider kickoff conflicts with canonical game"
                )

        raw_record = _raw_record_json(record)
        return ParsedMarketRecord(
            record_index=record_index,
            provider_record_id=provider_matchup_id,
            record_key=payload_sha256(
                {
                    "bookmaker": _required_text(record.get("bookmaker"), "bookmaker").casefold(),
                    "line_type": line_type_value,
                    "observed_at": _utc_text(observed_at),
                    "provider_matchup_id": provider_matchup_id,
                }
            ),
            observed_at=observed_at,
            parser_version=self.version,
            raw_record_sha256=hashlib.sha256(raw_record.encode("utf-8")).hexdigest(),
            game_id=game_id,
            season=season,
            week=week,
            raw_home_team=raw_home,
            raw_away_team=raw_away,
            normalized_home_team=home,
            normalized_away_team=away,
            bookmaker=_required_text(record.get("bookmaker"), "bookmaker"),
            market_type=market_type,
            home_spread=home_spread,
            home_price=price_value,
            away_spread=(
                float(away_spread_value) if away_spread_value is not None else None
            ),
            away_price=away_price_value,
            line_type=line_type_value,
            event_start_at=event_start,
        )


def _records_from_payload(payload: object) -> list[object]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, Mapping) and isinstance(payload.get("records"), list):
        return list(payload["records"])
    raise ProviderIngestionError("payload must be a JSON list or an object with a records list")


def _decode_payload(payload: object) -> object:
    def reject_nonstandard_constant(value: str) -> object:
        raise ValueError(f"non-standard JSON constant is forbidden: {value}")

    if isinstance(payload, bytes):
        try:
            return json.loads(
                payload.decode("utf-8"), parse_constant=reject_nonstandard_constant
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise ProviderIngestionError(f"payload is not valid UTF-8 JSON: {exc}") from exc
    if isinstance(payload, str):
        try:
            return json.loads(payload, parse_constant=reject_nonstandard_constant)
        except (json.JSONDecodeError, ValueError) as exc:
            raise ProviderIngestionError(f"payload is not valid JSON: {exc}") from exc
    return payload


class ProviderIngestionService:
    """Validate, quarantine, and atomically persist one captured payload."""

    def __init__(self, clock: Callable[[], datetime] | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def ingest_payload(
        self,
        conn: sqlite3.Connection,
        request: IngestionRequest,
        payload: object,
        parser: RecordParser,
        accepted_writer: Callable[[sqlite3.Connection, Sequence[AcceptedProviderRecord]], None]
        | None = None,
    ) -> IngestionSummary:
        provider = request.provider.strip()
        parser_version = request.parser_version.strip()
        raw_reference = _sanitize_endpoint(request.raw_payload_reference)
        if not provider or not parser_version or not raw_reference:
            raise ProviderIngestionError(
                "provider, parser_version, and raw_payload_reference are required"
            )
        if parser.version != parser_version:
            raise ProviderIngestionError("request parser_version does not match parser implementation")
        if request.data_type not in SUPPORTED_DATA_TYPES:
            raise ProviderIngestionError(f"unsupported data_type: {request.data_type}")
        requested_at = _request_utc(request.requested_at)
        endpoint = _sanitize_endpoint(request.endpoint)
        sanitized_params = _sanitize_parameters(request.request_parameters)
        parameters_json = _canonical_json(sanitized_params)
        actual_checksum = payload_sha256(payload)
        expected_checksum = _validate_sha256(
            request.expected_payload_sha256, "expected_payload_sha256"
        )
        run_key = payload_sha256(
            {
                "data_type": request.data_type,
                "endpoint": endpoint,
                "parser_version": parser_version,
                "payload_sha256": actual_checksum,
                "provider": provider,
                "raw_payload_reference": raw_reference,
                "request_parameters": sanitized_params,
                "requested_at": _utc_text(requested_at),
            }
        )

        existing = self._existing_summary(conn, run_key)
        if existing is not None:
            return existing

        if expected_checksum is not None and expected_checksum != actual_checksum:
            return self._persist_terminal_run(
                conn,
                request,
                endpoint,
                parameters_json,
                requested_at,
                actual_checksum,
                expected_checksum,
                run_key,
                "checksum_mismatch",
                0,
                "payload checksum does not match the expected replay checksum",
            )

        try:
            records = _records_from_payload(_decode_payload(payload))
        except ProviderIngestionError as exc:
            return self._persist_terminal_run(
                conn,
                request,
                endpoint,
                parameters_json,
                requested_at,
                actual_checksum,
                expected_checksum,
                run_key,
                "malformed_payload",
                0,
                str(exc),
            )

        resolver = CanonicalTeamResolver.from_connection(conn)
        accepted: list[AcceptedProviderRecord] = []
        rejected: list[QuarantinedRecord] = []
        duplicate_keys: set[str] = set()
        for index, raw_record in enumerate(records):
            exact_raw_json = _raw_record_json(raw_record)
            raw_checksum = hashlib.sha256(exact_raw_json.encode("utf-8")).hexdigest()
            raw_json = _raw_record_json(_sanitize_parameters(raw_record))
            provider_record_id = (
                raw_record.get("matchup_id")
                if isinstance(raw_record, Mapping)
                and isinstance(raw_record.get("matchup_id"), str)
                else None
            )
            if not isinstance(raw_record, Mapping):
                rejected.append(
                    QuarantinedRecord(
                        index,
                        provider_record_id,
                        "malformed_record",
                        "record must be a JSON object",
                        raw_checksum,
                        raw_json,
                    )
                )
                continue
            try:
                parsed = parser.parse(conn, resolver, provider, request, index, raw_record)
                if (
                    parsed.record_index != index
                    or parsed.parser_version != parser_version
                    or not parsed.provider_record_id.strip()
                ):
                    raise ProviderIngestionError(
                        "parser returned inconsistent record identity or version metadata"
                    )
                _validate_sha256(parsed.record_key, "accepted record_key")
                _validate_sha256(parsed.raw_record_sha256, "accepted raw_record_sha256")
                if parsed.raw_record_sha256 != raw_checksum:
                    raise ProviderIngestionError(
                        "parser raw-record checksum does not match the captured record"
                    )
                provider_record_id = parsed.provider_record_id
                if (
                    not isinstance(parsed.observed_at, datetime)
                    or parsed.observed_at.tzinfo is None
                    or parsed.observed_at.utcoffset() != timedelta(0)
                ):
                    raise RecordRejected(
                        "invalid_timestamp", "accepted observed_at must be timezone-aware UTC"
                    )
                if parsed.observed_at > requested_at:
                    raise RecordRejected(
                        "invalid_timestamp", "accepted observed_at cannot be after requested_at"
                    )
                max_age = DEFAULT_FRESHNESS_RULES[request.data_type]
                if requested_at - parsed.observed_at > timedelta(seconds=max_age):
                    raise RecordRejected(
                        "stale_data",
                        f"{request.data_type} record exceeds {max_age}-second freshness limit",
                    )
                prior_duplicate = conn.execute(
                    """
                    SELECT 1 FROM provider_ingestion_acceptances
                    WHERE provider = ? AND data_type = ?
                      AND parser_version = ? AND record_key = ?
                    LIMIT 1
                    """,
                    (
                        provider,
                        request.data_type,
                        parser_version,
                        parsed.record_key,
                    ),
                ).fetchone()
                if parsed.record_key in duplicate_keys or prior_duplicate is not None:
                    raise RecordRejected(
                        "duplicate_record",
                        "duplicate provider record for this parser version",
                    )
                duplicate_keys.add(parsed.record_key)
                accepted.append(parsed)
            except RecordRejected as exc:
                rejected.append(
                    QuarantinedRecord(
                        index,
                        provider_record_id,
                        exc.code,
                        exc.reason,
                        raw_checksum,
                        raw_json,
                    )
                )
            except Exception as exc:
                failure = self._persist_terminal_run(
                    conn,
                    request,
                    endpoint,
                    parameters_json,
                    requested_at,
                    actual_checksum,
                    expected_checksum,
                    run_key,
                    "failed",
                    len(records),
                    f"parser failed at record {index}: {type(exc).__name__}: {exc}",
                )
                raise ProviderIngestionError(
                    f"parser failed; failure run {failure.ingestion_run_id} recorded"
                ) from exc

        if not records:
            status = "empty"
        elif accepted and rejected:
            status = "partial"
        elif accepted:
            status = "completed"
        else:
            status = "rejected"

        recorded_at = self._now()
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            run_id = self._insert_run(
                conn,
                request,
                endpoint,
                parameters_json,
                requested_at,
                actual_checksum,
                expected_checksum,
                run_key,
                status,
                len(records),
                len(accepted),
                len(rejected),
                None,
                recorded_at,
            )
            self._insert_rejections(conn, run_id, rejected, recorded_at)
            acceptance_ids = self._insert_acceptances(
                conn,
                run_id,
                provider,
                request.data_type,
                accepted,
                recorded_at,
            )
            self._insert_market_snapshots(
                conn, run_id, provider, accepted, acceptance_ids, recorded_at
            )
            if accepted:
                self._insert_freshness_snapshot(
                    conn, run_id, provider, request.data_type, status, accepted, recorded_at
                )
            if accepted_writer is not None:
                accepted_writer(conn, tuple(accepted))
            conn.commit()
        except Exception as exc:
            conn.rollback()
            failure = self._persist_terminal_run(
                conn,
                request,
                endpoint,
                parameters_json,
                requested_at,
                actual_checksum,
                expected_checksum,
                run_key,
                "failed",
                len(records),
                f"transaction rolled back: {type(exc).__name__}: {exc}",
            )
            raise ProviderIngestionError(
                f"ingestion transaction rolled back; failure run {failure.ingestion_run_id} recorded"
            ) from exc

        return IngestionSummary(
            run_id,
            run_key,
            status,
            len(records),
            len(accepted),
            len(rejected),
            actual_checksum,
            False,
        )

    def _now(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ProviderIngestionError("ingestion clock must return timezone-aware UTC")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _existing_summary(conn: sqlite3.Connection, run_key: str) -> IngestionSummary | None:
        row = conn.execute(
            "SELECT id, status, rows_received, rows_accepted, rows_rejected, payload_sha256 "
            "FROM provider_ingestion_runs WHERE run_key = ?",
            (run_key,),
        ).fetchone()
        if row is None:
            return None
        return IngestionSummary(row[0], run_key, row[1], row[2], row[3], row[4], row[5], True)

    def _persist_terminal_run(
        self,
        conn: sqlite3.Connection,
        request: IngestionRequest,
        endpoint: str,
        parameters_json: str,
        requested_at: datetime,
        actual_checksum: str,
        expected_checksum: str | None,
        run_key: str,
        status: str,
        rows_received: int,
        reason: str,
    ) -> IngestionSummary:
        recorded_at = self._now()
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("BEGIN IMMEDIATE")
        try:
            run_id = self._insert_run(
                conn,
                request,
                endpoint,
                parameters_json,
                requested_at,
                actual_checksum,
                expected_checksum,
                run_key,
                status,
                rows_received,
                0,
                0,
                reason,
                recorded_at,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        return IngestionSummary(
            run_id, run_key, status, rows_received, 0, 0, actual_checksum, False
        )

    @staticmethod
    def _insert_run(
        conn: sqlite3.Connection,
        request: IngestionRequest,
        endpoint: str,
        parameters_json: str,
        requested_at: datetime,
        actual_checksum: str,
        expected_checksum: str | None,
        run_key: str,
        status: str,
        rows_received: int,
        rows_accepted: int,
        rows_rejected: int,
        failure_reason: str | None,
        recorded_at: datetime,
    ) -> int:
        cursor = conn.execute(
            """
            INSERT INTO provider_ingestion_runs (
                run_key, provider, endpoint, request_parameters, requested_at,
                parser_version, payload_sha256, expected_payload_sha256,
                raw_payload_reference, data_type, freshness_policy_version,
                rows_received, rows_accepted, rows_rejected, status,
                failure_reason, recorded_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_key,
                request.provider.strip(),
                endpoint,
                parameters_json,
                _utc_text(requested_at),
                request.parser_version.strip(),
                actual_checksum,
                expected_checksum,
                _sanitize_endpoint(request.raw_payload_reference),
                request.data_type,
                FRESHNESS_POLICY_VERSION,
                rows_received,
                rows_accepted,
                rows_rejected,
                status,
                failure_reason,
                _utc_text(recorded_at),
            ),
        )
        return int(cursor.lastrowid)

    @staticmethod
    def _insert_rejections(
        conn: sqlite3.Connection,
        run_id: int,
        rejected: Sequence[QuarantinedRecord],
        recorded_at: datetime,
    ) -> None:
        conn.executemany(
            """
            INSERT INTO provider_ingestion_rejections (
                ingestion_run_id, record_index, provider_record_id,
                rejection_code, rejection_reason, raw_record_sha256,
                raw_record, rejected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    run_id,
                    record.record_index,
                    record.provider_record_id,
                    record.rejection_code,
                    record.rejection_reason,
                    record.raw_record_sha256,
                    record.raw_record,
                    _utc_text(recorded_at),
                )
                for record in rejected
            ],
        )

    @staticmethod
    def _insert_acceptances(
        conn: sqlite3.Connection,
        run_id: int,
        provider: str,
        data_type: str,
        accepted: Sequence[AcceptedProviderRecord],
        recorded_at: datetime,
    ) -> dict[int, int]:
        acceptance_ids: dict[int, int] = {}
        for record in accepted:
            cursor = conn.execute(
                """
                INSERT INTO provider_ingestion_acceptances (
                    ingestion_run_id, record_index, provider, data_type,
                    record_key, provider_record_id, observed_at, parser_version,
                    raw_record_sha256, accepted_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    record.record_index,
                    provider,
                    data_type,
                    record.record_key,
                    record.provider_record_id,
                    _utc_text(record.observed_at),
                    record.parser_version,
                    record.raw_record_sha256,
                    _utc_text(recorded_at),
                ),
            )
            acceptance_ids[record.record_index] = int(cursor.lastrowid)
        return acceptance_ids

    @staticmethod
    def _insert_market_snapshots(
        conn: sqlite3.Connection,
        run_id: int,
        provider: str,
        accepted: Sequence[AcceptedProviderRecord],
        acceptance_ids: Mapping[int, int],
        recorded_at: datetime,
    ) -> None:
        conn.executemany(
            """
            INSERT INTO provider_market_snapshots (
                acceptance_id, ingestion_run_id, record_index, provider, provider_matchup_id,
                game_id, season, week, raw_home_team, raw_away_team,
                normalized_home_team, normalized_away_team, bookmaker,
                market_type, home_spread, home_price, observed_at,
                event_start_at, parser_version, raw_record_sha256, ingested_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    acceptance_ids[record.record_index],
                    run_id,
                    record.record_index,
                    provider,
                    record.provider_matchup_id,
                    record.game_id,
                    record.season,
                    record.week,
                    record.raw_home_team,
                    record.raw_away_team,
                    record.normalized_home_team,
                    record.normalized_away_team,
                    record.bookmaker,
                    record.market_type,
                    record.home_spread,
                    record.home_price,
                    _utc_text(record.observed_at),
                    _utc_text(record.event_start_at),
                    record.parser_version,
                    record.raw_record_sha256,
                    _utc_text(recorded_at),
                )
                for record in accepted
                if isinstance(record, ParsedMarketRecord)
            ],
        )

    @staticmethod
    def _insert_freshness_snapshot(
        conn: sqlite3.Connection,
        run_id: int,
        provider: str,
        data_type: str,
        status: str,
        accepted: Sequence[AcceptedProviderRecord],
        recorded_at: datetime,
    ) -> None:
        observations = [record.observed_at for record in accepted]
        earliest = min(observations)
        latest = max(observations)
        max_age = DEFAULT_FRESHNESS_RULES[data_type]
        conn.execute(
            """
            INSERT INTO provider_data_snapshots (
                ingestion_run_id, provider, data_type, earliest_observed_at,
                latest_observed_at, expires_at, freshness_policy_version,
                max_age_seconds, completeness, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                provider,
                data_type,
                _utc_text(earliest),
                _utc_text(latest),
                _utc_text(earliest + timedelta(seconds=max_age)),
                FRESHNESS_POLICY_VERSION,
                max_age,
                "complete" if status == "completed" else "partial",
                _utc_text(recorded_at),
            ),
        )


def assess_required_freshness(
    conn: sqlite3.Connection,
    *,
    as_of: datetime | str,
    required_data_types: Iterable[str] = SUPPORTED_DATA_TYPE_ORDER,
    provider_by_data_type: Mapping[str, str] | None = None,
) -> tuple[FreshnessAssessment, ...]:
    """Assess latest point-in-time-safe source custody for a card as-of time."""
    as_of_utc = _request_utc(as_of)
    provider_by_data_type = provider_by_data_type or {}
    assessments: list[FreshnessAssessment] = []
    for data_type in required_data_types:
        if data_type not in SUPPORTED_DATA_TYPES:
            raise ProviderIngestionError(f"unsupported data_type: {data_type}")
        provider = provider_by_data_type.get(data_type)
        sql = (
            "SELECT snapshot.ingestion_run_id, snapshot.provider, "
            "snapshot.earliest_observed_at, snapshot.expires_at, "
            "snapshot.freshness_policy_version, snapshot.completeness "
            "FROM provider_data_snapshots AS snapshot "
            "JOIN provider_ingestion_runs AS run ON run.id = snapshot.ingestion_run_id "
            "WHERE snapshot.data_type = ? AND julianday(run.requested_at) <= julianday(?)"
        )
        params: list[object] = [data_type, _utc_text(as_of_utc)]
        if provider is not None:
            sql += " AND snapshot.provider = ?"
            params.append(provider)
        sql += " ORDER BY julianday(run.requested_at) DESC, run.id DESC LIMIT 1"
        row = conn.execute(sql, params).fetchone()
        if row is None:
            assessments.append(
                FreshnessAssessment(
                    data_type,
                    provider,
                    "missing",
                    _utc_text(as_of_utc),
                    None,
                    None,
                    None,
                    FRESHNESS_POLICY_VERSION,
                    "no accepted point-in-time snapshot is available",
                )
            )
            continue
        run_id, actual_provider, observed_at, expires_at, policy_version, completeness = row
        expires = _parse_utc(expires_at, "expires_at")
        if as_of_utc > expires:
            state: Literal["current", "partial", "stale", "missing"] = "stale"
            reason = "latest accepted snapshot exceeds its freshness window"
        elif completeness == "partial":
            state = "partial"
            reason = "provider run contains quarantined records and requires an explicit fallback"
        else:
            state = "current"
            reason = "complete accepted snapshot is within its freshness window"
        assessments.append(
            FreshnessAssessment(
                data_type,
                actual_provider,
                state,
                _utc_text(as_of_utc),
                run_id,
                observed_at,
                expires_at,
                policy_version,
                reason,
            )
        )
    return tuple(assessments)
