"""Replayable provider bundles and controlled credential-safe connectivity."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol

import requests

from ingestion import (
    AcceptedProviderRecord,
    CanonicalTeamResolver,
    IngestionRequest,
    IngestionSummary,
    OddsSpreadParser,
    ProviderIngestionError,
    ProviderIngestionService,
    TeamResolution,
    payload_sha256,
)
from ingestion.custody import ParsedMarketRecord, RecordRejected

from operations.config import EXPECTED_REPOSITORY


PROVIDER_BUNDLE_VERSION = "v3-provider-bundle-v1"
CONNECTIVITY_REPORT_VERSION = "v3-provider-connectivity-v1"
CFBD_BASE_URL = "https://api.collegefootballdata.com"
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"


class ProductionProviderError(RuntimeError):
    """Raised when provider input or connectivity cannot be trusted."""


@dataclass(frozen=True)
class ProviderPayload:
    provider: str
    data_type: str
    endpoint: str
    request_parameters: Mapping[str, object]
    requested_at: datetime
    parser_version: str
    raw_payload_reference: str
    payload_path: Path
    payload_sha256: str
    line_type: str | None


@dataclass(frozen=True)
class ProviderBundle:
    path: Path
    season: int
    week: int
    payloads: tuple[ProviderPayload, ...]
    sha256: str


@dataclass(frozen=True)
class ParsedTeamStatsRecord(AcceptedProviderRecord):
    season: int
    snapshot_week: int
    team: str
    offense_epa_play: float
    defense_epa_play: float
    offense_success_rate: float | None
    defense_success_rate: float | None
    havoc_rate: float | None


@dataclass(frozen=True)
class ParsedGameRecord(AcceptedProviderRecord):
    game_id: int
    season: int
    week: int
    home_team: str
    away_team: str
    start_date: str
    season_type: str | None
    venue: str | None
    neutral_site: bool
    conference_game: bool
    home_points: int | None
    away_points: int | None
    completed: bool


class _JsonResponse(Protocol):
    status_code: int
    headers: Mapping[str, str]

    def raise_for_status(self) -> None: ...

    def json(self) -> object: ...


class _Session(Protocol):
    def get(self, url: str, **kwargs: object) -> _JsonResponse: ...


def _utc(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ProductionProviderError(f"{field} is not ISO-8601") from exc
    else:
        raise ProductionProviderError(f"{field} must be a UTC timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ProductionProviderError(f"{field} must use a UTC offset")
    return parsed.astimezone(timezone.utc)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductionProviderError(f"{field} must be non-empty text")
    return value.strip()


def _integer(value: object, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ProductionProviderError(f"{field} must be an integer >= {minimum}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordRejected("malformed_record", f"{field} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise RecordRejected("malformed_record", f"{field} must be finite")
    return converted


def _record_integer(value: object, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RecordRejected("malformed_record", f"{field} must be an integer >= {minimum}")
    return value


def _record_bool(value: object, field: str) -> bool:
    if not isinstance(value, bool):
        raise RecordRejected("malformed_record", f"{field} must be boolean")
    return value


def _record_utc(value: object, field: str) -> datetime:
    try:
        return _utc(value, field)
    except ProductionProviderError as exc:
        raise RecordRejected("invalid_timestamp", str(exc)) from exc


def _optional_number(value: object, field: str) -> float | None:
    return None if value is None else _number(value, field)


def _record_sha(record: Mapping[str, object]) -> str:
    canonical = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _resolved(resolution: TeamResolution, side: str) -> str:
    if resolution.status == "unknown":
        raise RecordRejected("unknown_team", f"{side} team is unknown")
    if resolution.status == "ambiguous":
        raise RecordRejected(
            "ambiguous_team_normalization", f"{side} team is ambiguous"
        )
    assert resolution.canonical_name is not None
    return resolution.canonical_name


class CfbdTeamStatsParser:
    version = "cfbd_team_stats_v1"

    def parse(
        self,
        conn: sqlite3.Connection,
        resolver: CanonicalTeamResolver,
        provider: str,
        request: IngestionRequest,
        record_index: int,
        record: Mapping[str, object],
    ) -> ParsedTeamStatsRecord:
        if provider != "collegefootballdata" or request.data_type != "contextual":
            raise RecordRejected(
                "malformed_record", "CFBD stats require contextual custody"
            )
        season = _integer(request.request_parameters.get("year"), "year", 1869)
        snapshot_week = _integer(
            request.request_parameters.get("endWeek"), "endWeek", 0
        )
        team = _resolved(resolver.resolve(provider, record.get("team")), "team")
        offense = record.get("offense")
        defense = record.get("defense")
        if not isinstance(offense, Mapping) or not isinstance(defense, Mapping):
            raise RecordRejected(
                "malformed_record", "CFBD stats require offense and defense objects"
            )
        havoc = defense.get("havoc")
        havoc_total = havoc.get("total") if isinstance(havoc, Mapping) else None
        observed_at = _utc(request.requested_at, "requested_at")
        raw_sha = _record_sha(record)
        return ParsedTeamStatsRecord(
            record_index=record_index,
            provider_record_id=f"{season}:{snapshot_week}:{team}",
            record_key=payload_sha256(
                {
                    "parser": self.version,
                    "season": season,
                    "snapshot_week": snapshot_week,
                    "team": team,
                    "raw_record_sha256": raw_sha,
                }
            ),
            observed_at=observed_at,
            parser_version=self.version,
            raw_record_sha256=raw_sha,
            season=season,
            snapshot_week=snapshot_week,
            team=team,
            offense_epa_play=_number(offense.get("ppa"), "offense.ppa"),
            defense_epa_play=_number(defense.get("ppa"), "defense.ppa"),
            offense_success_rate=_optional_number(
                offense.get("successRate"), "offense.successRate"
            ),
            defense_success_rate=_optional_number(
                defense.get("successRate"), "defense.successRate"
            ),
            havoc_rate=_optional_number(havoc_total, "defense.havoc.total"),
        )


class CfbdGamesParser:
    version = "cfbd_games_v1"

    def parse(
        self,
        conn: sqlite3.Connection,
        resolver: CanonicalTeamResolver,
        provider: str,
        request: IngestionRequest,
        record_index: int,
        record: Mapping[str, object],
    ) -> ParsedGameRecord:
        if provider != "collegefootballdata" or request.data_type != "game_status":
            raise RecordRejected(
                "malformed_record", "CFBD games require game_status custody"
            )
        game_id = _record_integer(record.get("id"), "id", 1)
        season = _record_integer(record.get("season"), "season", 1869)
        week = _record_integer(record.get("week"), "week", 0)
        if (
            season != request.request_parameters.get("year")
            or week != request.request_parameters.get("week")
            or request.request_parameters.get("classification") != "fbs"
        ):
            raise RecordRejected(
                "conflicting_game_mapping",
                "CFBD game conflicts with requested season/week/FBS classification",
            )
        home = _resolved(resolver.resolve(provider, record.get("homeTeam")), "home")
        away = _resolved(resolver.resolve(provider, record.get("awayTeam")), "away")
        if home == away:
            raise RecordRejected("conflicting_game_mapping", "teams resolve identically")
        start = _record_utc(record.get("startDate"), "startDate")
        requested_at = _utc(request.requested_at, "requested_at")
        home_points = record.get("homePoints")
        away_points = record.get("awayPoints")
        if (home_points is None) != (away_points is None):
            raise RecordRejected("malformed_record", "scores must be supplied together")
        if home_points is not None:
            home_points = _record_integer(home_points, "homePoints", 0)
            away_points = _record_integer(away_points, "awayPoints", 0)
        completed_value = record.get("completed", home_points is not None)
        completed = _record_bool(completed_value, "completed")
        if completed and home_points is None:
            raise RecordRejected("malformed_record", "completed game requires final scores")
        raw_sha = _record_sha(record)
        return ParsedGameRecord(
            record_index=record_index,
            provider_record_id=str(game_id),
            record_key=payload_sha256(
                {
                    "parser": self.version,
                    "game_id": game_id,
                    "requested_at": requested_at.isoformat(),
                    "raw_record_sha256": raw_sha,
                }
            ),
            observed_at=requested_at,
            parser_version=self.version,
            raw_record_sha256=raw_sha,
            game_id=game_id,
            season=season,
            week=week,
            home_team=home,
            away_team=away,
            start_date=start.isoformat(),
            season_type=(
                str(record.get("seasonType")).strip()
                if record.get("seasonType") is not None
                else None
            ),
            venue=(
                str(record.get("venue")).strip()
                if record.get("venue") is not None
                else None
            ),
            neutral_site=_record_bool(record.get("neutralSite", False), "neutralSite"),
            conference_game=_record_bool(
                record.get("conferenceGame", False), "conferenceGame"
            ),
            home_points=home_points,
            away_points=away_points,
            completed=completed,
        )


class ProviderSnapshotParser:
    version = "provider_snapshot_v1"

    def parse(
        self,
        conn: sqlite3.Connection,
        resolver: CanonicalTeamResolver,
        provider: str,
        request: IngestionRequest,
        record_index: int,
        record: Mapping[str, object],
    ) -> AcceptedProviderRecord:
        record_id = record.get("record_id")
        if not isinstance(record_id, str) or not record_id.strip():
            raise RecordRejected("malformed_record", "record_id is required")
        try:
            observed_at = _utc(record.get("observed_at"), "observed_at")
        except ProductionProviderError as exc:
            raise RecordRejected("invalid_timestamp", str(exc)) from exc
        raw_sha = _record_sha(record)
        return AcceptedProviderRecord(
            record_index=record_index,
            provider_record_id=record_id.strip(),
            record_key=payload_sha256(
                {
                    "data_type": request.data_type,
                    "provider": provider,
                    "record_id": record_id.strip(),
                    "observed_at": observed_at.isoformat(),
                    "raw_record_sha256": raw_sha,
                }
            ),
            observed_at=observed_at,
            parser_version=self.version,
            raw_record_sha256=raw_sha,
        )


def _parser(version: str):
    if version == "odds_spread_v1":
        return OddsSpreadParser(version)
    if version == CfbdTeamStatsParser.version:
        return CfbdTeamStatsParser()
    if version == CfbdGamesParser.version:
        return CfbdGamesParser()
    if version == ProviderSnapshotParser.version:
        return ProviderSnapshotParser()
    raise ProductionProviderError(f"unsupported parser version: {version}")


def load_provider_bundle(
    path: Path,
    *,
    repository_root: Path,
    season: int,
    week: int,
) -> ProviderBundle:
    root = repository_root.resolve()
    bundle_path = path.resolve()
    try:
        inside = bundle_path.is_relative_to(root)
    except ValueError:
        inside = False
    if not inside or not bundle_path.is_file():
        raise ProductionProviderError("provider bundle must be a file inside V3")
    raw_bytes = bundle_path.read_bytes()
    try:
        payload = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionProviderError("provider bundle is not valid UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise ProductionProviderError("provider bundle must be a JSON object")
    if (
        payload.get("bundle_version") != PROVIDER_BUNDLE_VERSION
        or payload.get("repository") != EXPECTED_REPOSITORY
        or payload.get("season") != season
        or payload.get("week") != week
    ):
        raise ProductionProviderError("provider bundle identity is invalid")
    raw_payloads = payload.get("payloads")
    if not isinstance(raw_payloads, list):
        raise ProductionProviderError("provider bundle requires a payloads array")
    raw_evidence = payload.get("raw_evidence", [])
    if not isinstance(raw_evidence, list):
        raise ProductionProviderError("provider bundle raw_evidence must be an array")
    for index, evidence in enumerate(raw_evidence):
        if not isinstance(evidence, Mapping):
            raise ProductionProviderError(f"raw_evidence[{index}] must be an object")
        evidence_path = Path(
            _text(evidence.get("path"), f"raw_evidence[{index}].path")
        )
        if not evidence_path.is_absolute():
            evidence_path = bundle_path.parent / evidence_path
        evidence_path = evidence_path.resolve()
        try:
            evidence_inside = evidence_path.is_relative_to(root)
        except ValueError:
            evidence_inside = False
        if not evidence_inside or not evidence_path.is_file():
            raise ProductionProviderError(
                f"raw_evidence[{index}] must be a file inside V3"
            )
        if hashlib.sha256(evidence_path.read_bytes()).hexdigest() != _text(
            evidence.get("sha256"), f"raw_evidence[{index}].sha256"
        ).casefold():
            raise ProductionProviderError(f"raw_evidence[{index}] checksum mismatch")
    specs: list[ProviderPayload] = []
    seen: set[tuple[str, str, str, str]] = set()
    for index, raw in enumerate(raw_payloads):
        if not isinstance(raw, Mapping):
            raise ProductionProviderError(f"payloads[{index}] must be an object")
        parameters = raw.get("request_parameters")
        if not isinstance(parameters, Mapping):
            raise ProductionProviderError(
                f"payloads[{index}].request_parameters must be an object"
            )
        provider = _text(raw.get("provider"), f"payloads[{index}].provider")
        data_type = _text(raw.get("data_type"), f"payloads[{index}].data_type")
        parser_version = _text(
            raw.get("parser_version"), f"payloads[{index}].parser_version"
        )
        _parser(parser_version)
        payload_path = Path(
            _text(raw.get("payload_path"), f"payloads[{index}].payload_path")
        )
        if not payload_path.is_absolute():
            payload_path = bundle_path.parent / payload_path
        payload_path = payload_path.resolve()
        try:
            payload_inside = payload_path.is_relative_to(root)
        except ValueError:
            payload_inside = False
        if not payload_inside or not payload_path.is_file():
            raise ProductionProviderError(
                f"payloads[{index}] evidence must be a file inside V3"
            )
        expected_sha = _text(
            raw.get("payload_sha256"), f"payloads[{index}].payload_sha256"
        ).casefold()
        actual_sha = hashlib.sha256(payload_path.read_bytes()).hexdigest()
        if expected_sha != actual_sha:
            raise ProductionProviderError(f"payloads[{index}] checksum mismatch")
        line_type = raw.get("line_type")
        if line_type is not None:
            line_type = _text(line_type, f"payloads[{index}].line_type")
            if line_type not in ("opening", "current", "closing"):
                raise ProductionProviderError(f"payloads[{index}].line_type is invalid")
        identity = (provider, data_type, parser_version, actual_sha)
        if identity in seen:
            raise ProductionProviderError("provider bundle contains a duplicate payload")
        seen.add(identity)
        specs.append(
            ProviderPayload(
                provider=provider,
                data_type=data_type,
                endpoint=_text(raw.get("endpoint"), f"payloads[{index}].endpoint"),
                request_parameters=dict(parameters),
                requested_at=_utc(
                    raw.get("requested_at"), f"payloads[{index}].requested_at"
                ),
                parser_version=parser_version,
                raw_payload_reference=_text(
                    raw.get("raw_payload_reference"),
                    f"payloads[{index}].raw_payload_reference",
                ),
                payload_path=payload_path,
                payload_sha256=actual_sha,
                line_type=line_type,
            )
        )
    return ProviderBundle(
        bundle_path,
        season,
        week,
        tuple(specs),
        hashlib.sha256(raw_bytes).hexdigest(),
    )


def _write_team_stats(
    conn: sqlite3.Connection,
    records: Sequence[AcceptedProviderRecord],
) -> None:
    for record in records:
        if not isinstance(record, ParsedTeamStatsRecord):
            continue
        requested = (
            record.offense_epa_play,
            record.defense_epa_play,
            record.offense_success_rate,
            record.defense_success_rate,
            record.havoc_rate,
        )
        existing = conn.execute(
            "SELECT offense_epa_play, defense_epa_play, offense_success_rate, "
            "defense_success_rate, havoc_rate FROM team_game_stats "
            "WHERE season = ? AND week = ? AND team = ? "
            "AND source = 'cfbd_point_in_time'",
            (record.season, record.snapshot_week, record.team),
        ).fetchall()
        if existing:
            if len(existing) != 1 or tuple(existing[0]) != requested:
                raise ProviderIngestionError(
                    "CFBD point-in-time snapshot conflicts with immutable prior custody"
                )
            continue
        conn.execute(
            "INSERT INTO team_game_stats "
            "(game_id, season, week, team, sp_rating, offense_epa_play, "
            "defense_epa_play, offense_success_rate, defense_success_rate, "
            "havoc_rate, wins, losses, source, fetched_at) "
            "VALUES (NULL, ?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, NULL, "
            "'cfbd_point_in_time', ?)",
            (
                record.season,
                record.snapshot_week,
                record.team,
                *requested,
                record.observed_at.isoformat(),
            ),
        )


def _write_games(
    conn: sqlite3.Connection,
    records: Sequence[AcceptedProviderRecord],
) -> None:
    for record in records:
        if not isinstance(record, ParsedGameRecord):
            continue
        existing = conn.execute(
            "SELECT season, week, home_team, away_team, start_date, home_points, "
            "away_points, completed FROM games WHERE game_id = ?",
            (record.game_id,),
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO games "
                "(game_id, season, week, season_type, start_date, home_team, away_team, "
                "venue, neutral_site, conference_game, home_points, away_points, completed) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record.game_id,
                    record.season,
                    record.week,
                    record.season_type,
                    record.start_date,
                    record.home_team,
                    record.away_team,
                    record.venue,
                    int(record.neutral_site),
                    int(record.conference_game),
                    record.home_points,
                    record.away_points,
                    int(record.completed),
                ),
            )
            continue
        stored_identity = tuple(existing[:4])
        requested_identity = (
            record.season,
            record.week,
            record.home_team,
            record.away_team,
        )
        try:
            stored_start = _utc(existing[4], "stored game start_date")
            requested_start = _utc(record.start_date, "provider game start_date")
        except ProductionProviderError as exc:
            raise ProviderIngestionError("canonical game kickoff is invalid") from exc
        if stored_identity != requested_identity or stored_start != requested_start:
            raise ProviderIngestionError("CFBD game conflicts with canonical identity")
        stored_scores = tuple(existing[5:7])
        requested_scores = (record.home_points, record.away_points)
        if bool(existing[7]):
            if stored_scores != requested_scores or not record.completed:
                raise ProviderIngestionError("completed game result conflicts with custody")
            continue
        if record.completed:
            conn.execute(
                "UPDATE games SET home_points = ?, away_points = ?, completed = 1 "
                "WHERE game_id = ? AND completed = 0",
                (record.home_points, record.away_points, record.game_id),
            )


def _odds_writer(line_type: str):
    def write(
        conn: sqlite3.Connection,
        records: Sequence[AcceptedProviderRecord],
    ) -> None:
        for record in records:
            if not isinstance(record, ParsedMarketRecord):
                continue
            if record.bookmaker.casefold() == "consensus":
                raise ProviderIngestionError("synthetic consensus rows are never canonical")
            requested = (
                record.game_id,
                record.season,
                record.week,
                record.normalized_home_team,
                record.normalized_away_team,
                record.bookmaker,
                record.home_spread,
                record.home_price,
                line_type,
                "the_odds_api",
                record.observed_at.isoformat(),
            )
            existing = conn.execute(
                "SELECT game_id, season, week, home_team, away_team, book, home_spread, "
                "home_moneyline, line_type, source, fetched_at FROM betting_lines "
                "WHERE game_id = ? AND book = ? AND line_type = ? AND fetched_at = ?",
                (
                    record.game_id,
                    record.bookmaker,
                    line_type,
                    record.observed_at.isoformat(),
                ),
            ).fetchall()
            if existing:
                if len(existing) != 1 or tuple(existing[0]) != requested:
                    raise ProviderIngestionError("market line conflicts with prior custody")
                continue
            conn.execute(
                "INSERT INTO betting_lines "
                "(game_id, season, week, home_team, away_team, book, home_spread, "
                "home_moneyline, line_type, source, fetched_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )

    return write


def ingest_provider_bundle(
    conn: sqlite3.Connection,
    bundle: ProviderBundle,
) -> tuple[IngestionSummary, ...]:
    """Replay all evidence through M14 custody; never touch contest locks."""
    service = ProviderIngestionService()
    summaries: list[IngestionSummary] = []
    for spec in bundle.payloads:
        try:
            payload = spec.payload_path.read_bytes()
            json.loads(payload.decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProductionProviderError(
                f"provider payload is not valid UTF-8 JSON: {spec.payload_path.name}"
            ) from exc
        parser = _parser(spec.parser_version)
        writer = None
        if spec.parser_version == CfbdTeamStatsParser.version:
            writer = _write_team_stats
        elif spec.parser_version == CfbdGamesParser.version:
            writer = _write_games
        elif spec.parser_version == "odds_spread_v1":
            if spec.line_type is None:
                raise ProductionProviderError("odds payload requires an explicit line_type")
            writer = _odds_writer(spec.line_type)
        summary = service.ingest_payload(
            conn,
            IngestionRequest(
                provider=spec.provider,
                endpoint=spec.endpoint,
                request_parameters=spec.request_parameters,
                requested_at=spec.requested_at,
                parser_version=spec.parser_version,
                raw_payload_reference=spec.raw_payload_reference,
                data_type=spec.data_type,
                expected_payload_sha256=spec.payload_sha256,
            ),
            payload,
            parser,
            accepted_writer=writer,
        )
        summaries.append(summary)
    return tuple(summaries)


def _safe_get_json(
    session: _Session,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, object] | None = None,
) -> object:
    try:
        response = session.get(
            url,
            headers=dict(headers or {}),
            params=dict(params or {}),
            timeout=30,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        raise ProductionProviderError(
            "provider connectivity failed; credential values and response URLs are suppressed: "
            f"{type(exc).__name__}"
        ) from None


def run_controlled_connectivity_checks(
    environment: Mapping[str, str],
    *,
    season: int,
    authorized: bool,
    session: _Session | None = None,
    checked_at: datetime | None = None,
) -> dict[str, object]:
    """Make two minimal live auth checks only after explicit authorization."""
    if not authorized:
        raise ProductionProviderError("live connectivity requires explicit authorization")
    cfbd_key = str(environment.get("CFBD_API_KEY", "")).strip()
    odds_key = str(environment.get("ODDS_API_KEY", "")).strip()
    if not cfbd_key or not odds_key:
        raise ProductionProviderError(
            "CFBD_API_KEY and ODDS_API_KEY must be present for connectivity"
        )
    now = _utc(checked_at or datetime.now(timezone.utc), "checked_at")
    client = session or requests.Session()
    cfbd_payload = _safe_get_json(
        client,
        f"{CFBD_BASE_URL}/calendar",
        headers={"Authorization": f"Bearer {cfbd_key}"},
        params={"year": season},
    )
    odds_payload = _safe_get_json(
        client,
        f"{ODDS_BASE_URL}/sports",
        params={"apiKey": odds_key},
    )
    report = {
        "report_version": CONNECTIVITY_REPORT_VERSION,
        "repository": EXPECTED_REPOSITORY,
        "checked_at": now.isoformat(),
        "credential_variables": ["CFBD_API_KEY", "ODDS_API_KEY"],
        "checks": [
            {
                "provider": "collegefootballdata",
                "endpoint": f"{CFBD_BASE_URL}/calendar",
                "request_parameters": {"year": season},
                "payload_sha256": payload_sha256(cfbd_payload),
                "status": "passed",
            },
            {
                "provider": "the_odds_api",
                "endpoint": f"{ODDS_BASE_URL}/sports",
                "request_parameters": {},
                "payload_sha256": payload_sha256(odds_payload),
                "status": "passed",
            },
        ],
    }
    canonical = json.dumps(report, sort_keys=True, separators=(",", ":"))
    report["report_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return report


def _write_canonical_json(path: Path, payload: object) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    path.write_text(canonical + "\n", encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_odds_records(
    payload: object,
    *,
    season: int,
    week: int,
    requested_at: datetime,
) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise ProductionProviderError("The Odds API payload must be an array")
    records: list[dict[str, object]] = []
    for event in payload:
        if not isinstance(event, Mapping):
            raise ProductionProviderError("The Odds API event must be an object")
        event_id = _text(event.get("id"), "odds event id")
        home = _text(event.get("home_team"), "odds home_team")
        away = _text(event.get("away_team"), "odds away_team")
        kickoff = _utc(event.get("commence_time"), "odds commence_time")
        if requested_at >= kickoff:
            raise ProductionProviderError(
                f"odds event {event_id} is not a pre-kickoff observation"
            )
        bookmakers = event.get("bookmakers")
        if not isinstance(bookmakers, list):
            raise ProductionProviderError("odds bookmakers must be an array")
        for bookmaker in bookmakers:
            if not isinstance(bookmaker, Mapping):
                raise ProductionProviderError("odds bookmaker must be an object")
            book = _text(bookmaker.get("key"), "odds bookmaker key")
            observed_raw = bookmaker.get("last_update") or requested_at.isoformat()
            observed = _utc(observed_raw, "odds bookmaker last_update")
            markets = bookmaker.get("markets")
            if not isinstance(markets, list):
                continue
            for market in markets:
                if not isinstance(market, Mapping) or market.get("key") != "spreads":
                    continue
                outcomes = market.get("outcomes")
                if not isinstance(outcomes, list):
                    continue
                home_outcomes = [
                    outcome
                    for outcome in outcomes
                    if isinstance(outcome, Mapping) and outcome.get("name") == home
                ]
                if len(home_outcomes) != 1:
                    raise ProductionProviderError(
                        f"odds event {event_id}/{book} lacks one home spread"
                    )
                outcome = home_outcomes[0]
                records.append(
                    {
                        "matchup_id": f"{event_id}:{book}",
                        "home_team": home,
                        "away_team": away,
                        "market_type": "spread",
                        "home_spread": outcome.get("point"),
                        "home_price": outcome.get("price"),
                        "season": season,
                        "week": week,
                        "observed_at": observed.isoformat(),
                        "event_start_at": kickoff.isoformat(),
                        "bookmaker": book,
                    }
                )
    return records


def capture_live_provider_bundle(
    environment: Mapping[str, str],
    *,
    repository_root: Path,
    output_directory: Path,
    season: int,
    week: int,
    line_type: str,
    capture_scope: str = "pregame",
    authorized: bool,
    captured_at: datetime | None = None,
    session: _Session | None = None,
) -> Path:
    """Capture replayable CFBD/Odds evidence; never ingest or publish it."""
    if not authorized:
        raise ProductionProviderError("live provider capture requires authorization")
    if line_type not in ("opening", "current", "closing"):
        raise ProductionProviderError("line_type must be opening, current, or closing")
    if capture_scope not in ("pregame", "postgame"):
        raise ProductionProviderError("capture_scope must be pregame or postgame")
    root = repository_root.resolve()
    if root.name != "cfb-betting-system-v3":
        raise ProductionProviderError("live capture is restricted to the V3 repository")
    output = output_directory.resolve()
    try:
        inside = output.is_relative_to(root)
    except ValueError:
        inside = False
    if not inside or output.exists() or not output.parent.is_dir():
        raise ProductionProviderError("capture output must be a new directory inside V3")
    cfbd_key = str(environment.get("CFBD_API_KEY", "")).strip()
    odds_key = str(environment.get("ODDS_API_KEY", "")).strip()
    if not cfbd_key:
        raise ProductionProviderError("CFBD_API_KEY is required")
    if capture_scope == "pregame" and not odds_key:
        raise ProductionProviderError("ODDS_API_KEY is required for pregame capture")
    now = _utc(captured_at or datetime.now(timezone.utc), "captured_at")
    client = session or requests.Session()
    games_params = {"year": season, "week": week, "classification": "fbs"}
    games_endpoint = f"{CFBD_BASE_URL}/games"
    games_payload = _safe_get_json(
        client,
        games_endpoint,
        headers={"Authorization": f"Bearer {cfbd_key}"},
        params=games_params,
    )
    stats_payload = None
    stats_params = None
    stats_endpoint = f"{CFBD_BASE_URL}/stats/season/advanced"
    if capture_scope == "pregame" and week > 1:
        stats_params = {
            "year": season,
            "endWeek": week - 1,
            "excludeGarbageTime": True,
        }
        stats_payload = _safe_get_json(
            client,
            stats_endpoint,
            headers={"Authorization": f"Bearer {cfbd_key}"},
            params=stats_params,
        )
    odds_params = {
        "regions": "us",
        "markets": "spreads",
        "bookmakers": "draftkings,fanduel,betmgm,williamhill_us,bovada",
        "oddsFormat": "american",
    }
    odds_endpoint = f"{ODDS_BASE_URL}/sports/americanfootball_ncaaf/odds"
    odds_payload = None
    normalized_odds = None
    if capture_scope == "pregame":
        odds_payload = _safe_get_json(
            client,
            odds_endpoint,
            params={**odds_params, "apiKey": odds_key},
        )
        normalized_odds = _normalized_odds_records(
            odds_payload,
            season=season,
            week=week,
            requested_at=now,
        )

    output.mkdir()
    games_path = output / "cfbd-games.raw.json"
    games_sha = _write_canonical_json(games_path, games_payload)
    raw_evidence = [
        {"path": games_path.name, "sha256": games_sha},
    ]
    payloads: list[dict[str, object]] = [
        {
            "provider": "collegefootballdata",
            "data_type": "game_status",
            "endpoint": games_endpoint,
            "request_parameters": games_params,
            "requested_at": now.isoformat(),
            "parser_version": CfbdGamesParser.version,
            "raw_payload_reference": str(games_path),
            "payload_path": games_path.name,
            "payload_sha256": games_sha,
        },
    ]
    if odds_payload is not None and normalized_odds is not None:
        odds_raw_path = output / "odds.raw.json"
        odds_raw_sha = _write_canonical_json(odds_raw_path, odds_payload)
        odds_path = output / "odds.normalized.json"
        odds_sha = _write_canonical_json(odds_path, normalized_odds)
        raw_evidence.append({"path": odds_raw_path.name, "sha256": odds_raw_sha})
        payloads.append(
            {
                "provider": "the_odds_api",
                "data_type": "odds",
                "endpoint": odds_endpoint,
                "request_parameters": odds_params,
                "requested_at": now.isoformat(),
                "parser_version": "odds_spread_v1",
                "raw_payload_reference": str(odds_raw_path),
                "payload_path": odds_path.name,
                "payload_sha256": odds_sha,
                "line_type": line_type,
            }
        )
    if stats_payload is not None and stats_params is not None:
        stats_path = output / "cfbd-stats.raw.json"
        stats_sha = _write_canonical_json(stats_path, stats_payload)
        raw_evidence.append({"path": stats_path.name, "sha256": stats_sha})
        payloads.append(
            {
                "provider": "collegefootballdata",
                "data_type": "contextual",
                "endpoint": stats_endpoint,
                "request_parameters": stats_params,
                "requested_at": now.isoformat(),
                "parser_version": CfbdTeamStatsParser.version,
                "raw_payload_reference": str(stats_path),
                "payload_path": stats_path.name,
                "payload_sha256": stats_sha,
            }
        )
    bundle = {
        "bundle_version": PROVIDER_BUNDLE_VERSION,
        "repository": EXPECTED_REPOSITORY,
        "season": season,
        "week": week,
        "captured_at": now.isoformat(),
        "capture_scope": capture_scope,
        "credential_variables": (
            ["CFBD_API_KEY", "ODDS_API_KEY"]
            if capture_scope == "pregame"
            else ["CFBD_API_KEY"]
        ),
        "raw_evidence": raw_evidence,
        "payloads": payloads,
    }
    bundle_path = output / "provider-bundle.json"
    _write_canonical_json(bundle_path, bundle)
    return bundle_path
