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

from business_entities.live_sportsbook import record_sportsbook_market_offer
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
from operations.context import (
    CONTEXT_EVIDENCE_PARSER_VERSION,
    ContextEvidenceParser,
    write_context_evidence,
)


PROVIDER_BUNDLE_VERSION = "v3-provider-bundle-v1"
CONNECTIVITY_REPORT_VERSION = "v3-provider-connectivity-v1"
CFBD_BASE_URL = "https://api.collegefootballdata.com"
ODDS_BASE_URL = "https://api.the-odds-api.com/v4"
ESPN_INJURIES_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/football/college-football/injuries"
)
OPEN_METEO_FORECAST_URL = "https://api.open-meteo.com/v1/forecast"


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
    if version in ("odds_spread_v1", "odds_spread_v2", "odds_spread_v3"):
        return OddsSpreadParser(version)
    if version == CfbdTeamStatsParser.version:
        return CfbdTeamStatsParser()
    if version == CfbdGamesParser.version:
        return CfbdGamesParser()
    if version == ProviderSnapshotParser.version:
        return ProviderSnapshotParser()
    if version == CONTEXT_EVIDENCE_PARSER_VERSION:
        return ContextEvidenceParser()
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
            snapshot = conn.execute(
                "SELECT id, provider FROM provider_market_snapshots "
                "WHERE provider_matchup_id = ? AND bookmaker = ? "
                "AND observed_at = ? AND parser_version = ?",
                (
                    record.provider_matchup_id,
                    record.bookmaker,
                    record.observed_at.isoformat(),
                    record.parser_version,
                ),
            ).fetchone()
            if snapshot is None:
                raise ProviderIngestionError("market snapshot custody is missing")
            if record.parser_version == "odds_spread_v3" and record.line_type != line_type:
                raise ProviderIngestionError(
                    "two-sided offer line_type conflicts with its provider bundle"
                )
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
                snapshot[1],
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
                line_row = conn.execute(
                    "SELECT id FROM betting_lines WHERE game_id = ? AND book = ? "
                    "AND line_type = ? AND fetched_at = ?",
                    (
                        record.game_id,
                        record.bookmaker,
                        line_type,
                        record.observed_at.isoformat(),
                    ),
                ).fetchone()
                assert line_row is not None
                betting_line_id = int(line_row[0])
            else:
                betting_line_id = int(
                    conn.execute(
                        "INSERT INTO betting_lines "
                        "(game_id, season, week, home_team, away_team, book, home_spread, "
                        "home_moneyline, line_type, source, fetched_at) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        requested,
                    ).lastrowid
                )
            if record.parser_version == "odds_spread_v3":
                assert record.away_spread is not None and record.away_price is not None
                record_sportsbook_market_offer(
                    conn,
                    provider_market_snapshot_id=int(snapshot[0]),
                    betting_line_id=betting_line_id,
                    line_type=line_type,
                    away_spread=record.away_spread,
                    away_price=record.away_price,
                    provenance=(
                        f"provider={snapshot[1]};provider_market_snapshot_id={snapshot[0]};"
                        f"parser_version={record.parser_version}"
                    ),
                )

    return write


def ingest_provider_bundle(
    conn: sqlite3.Connection,
    bundle: ProviderBundle,
) -> tuple[IngestionSummary, ...]:
    """Replay all evidence through governed custody; never touch contest locks."""
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
        elif spec.parser_version in (
            "odds_spread_v1",
            "odds_spread_v2",
            "odds_spread_v3",
        ):
            if spec.line_type is None:
                raise ProductionProviderError("odds payload requires an explicit line_type")
            writer = _odds_writer(spec.line_type)
        elif spec.parser_version == CONTEXT_EVIDENCE_PARSER_VERSION:
            writer = write_context_evidence
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
    response = _safe_get_response(
        session,
        url,
        headers=headers,
        params=params,
    )
    try:
        return response.json()
    except Exception as exc:
        raise ProductionProviderError(
            "provider response was not valid JSON; credential values and response URLs "
            f"are suppressed: {type(exc).__name__}"
        ) from None


def _safe_get_response(
    session: _Session,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, object] | None = None,
) -> _JsonResponse:
    try:
        response = session.get(
            url,
            headers=dict(headers or {}),
            params=dict(params or {}),
            timeout=30,
        )
        response.raise_for_status()
        return response
    except Exception as exc:
        raise ProductionProviderError(
            "provider connectivity failed; credential values and response URLs are suppressed: "
            f"{type(exc).__name__}"
        ) from None


def _quota_header(headers: Mapping[str, str], name: str) -> int:
    raw = next(
        (value for key, value in headers.items() if key.casefold() == name.casefold()),
        None,
    )
    try:
        parsed = int(str(raw))
    except (TypeError, ValueError) as exc:
        raise ProductionProviderError(
            f"The Odds API response is missing valid {name} quota evidence"
        ) from exc
    if parsed < 0:
        raise ProductionProviderError(
            f"The Odds API response contains invalid {name} quota evidence"
        )
    return parsed


def _odds_quota_evidence(response: _JsonResponse) -> dict[str, int]:
    return {
        "remaining": _quota_header(response.headers, "x-requests-remaining"),
        "used": _quota_header(response.headers, "x-requests-used"),
        "last": _quota_header(response.headers, "x-requests-last"),
    }


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
    line_type: str,
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
                away_outcomes = [
                    outcome
                    for outcome in outcomes
                    if isinstance(outcome, Mapping) and outcome.get("name") == away
                ]
                if len(away_outcomes) != 1:
                    raise ProductionProviderError(
                        f"odds event {event_id}/{book} lacks one away spread"
                    )
                outcome = home_outcomes[0]
                away_outcome = away_outcomes[0]
                records.append(
                    {
                        "matchup_id": f"{event_id}:{book}",
                        "home_team": home,
                        "away_team": away,
                        "market_type": "spread",
                        "home_spread": outcome.get("point"),
                        "home_price": outcome.get("price"),
                        "away_spread": away_outcome.get("point"),
                        "away_price": away_outcome.get("price"),
                        "line_type": line_type,
                        "season": season,
                        "week": week,
                        "observed_at": observed.isoformat(),
                        "event_start_at": kickoff.isoformat(),
                        "bookmaker": book,
                    }
                )
    return records


def _payload_records(payload: object, field: str) -> list[Mapping[str, object]]:
    if not isinstance(payload, list) or any(not isinstance(item, Mapping) for item in payload):
        raise ProductionProviderError(f"{field} must be an array of objects")
    return list(payload)


def _game_rows(payload: object, *, season: int, week: int | None = None) -> list[Mapping[str, object]]:
    records = _payload_records(payload, "CFBD games payload")
    selected: list[Mapping[str, object]] = []
    for record in records:
        if record.get("season") != season:
            continue
        if week is not None and record.get("week") != week:
            continue
        if not isinstance(record.get("id"), int):
            raise ProductionProviderError("CFBD game id must be an integer")
        _text(record.get("homeTeam"), "CFBD homeTeam")
        _text(record.get("awayTeam"), "CFBD awayTeam")
        _utc(record.get("startDate"), "CFBD startDate")
        selected.append(record)
    return selected


def _team_name(value: object) -> str | None:
    if not isinstance(value, Mapping):
        return None
    for field in ("displayName", "location", "name", "shortDisplayName"):
        candidate = value.get(field)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _name_matches(provider_name: str, canonical_name: str) -> bool:
    provider = " ".join(provider_name.casefold().replace("’", "'").split())
    canonical = " ".join(canonical_name.casefold().replace("’", "'").split())
    return provider == canonical or provider.startswith(canonical + " ")


def _normalized_injury_records(
    payload: object,
    *,
    games_payload: object,
    season: int,
    week: int,
    requested_at: datetime,
) -> list[dict[str, object]]:
    """Normalize only explicit ESPN team reports; aggregate omissions stay missing.

    The aggregate endpoint does not enumerate teams with no reported injuries.  A
    team therefore has negative coverage only when its own uniquely mapped group
    is present with an explicit empty ``injuries``/``items`` collection.  Missing
    contest-team groups become quarantinable coverage-gap records instead of
    synthetic ``no_reported_injuries`` evidence.
    """
    if not isinstance(payload, Mapping):
        raise ProductionProviderError("ESPN injuries payload must be an object")
    groups_value = payload.get("injuries", payload.get("items"))
    if groups_value is None:
        raise ProductionProviderError("ESPN injuries payload lacks an injuries collection")
    groups = _payload_records(groups_value, "ESPN injuries collection")
    reports: list[tuple[str, Mapping[str, object], list[Mapping[str, object]]]] = []
    for group in groups:
        name = _team_name(group.get("team"))
        if name is None:
            raise ProductionProviderError("ESPN injury group lacks team identity")
        injuries_value = group.get("injuries", group.get("items"))
        if injuries_value is None:
            raise ProductionProviderError(
                f"ESPN injury group for {name} lacks an explicit injuries collection"
            )
        injuries = _payload_records(injuries_value, "ESPN team injuries")
        reports.append((name, group, injuries))
    endpoint_reference = ESPN_INJURIES_URL
    games = [
        game
        for game in _game_rows(games_payload, season=season, week=week)
        if requested_at < _utc(game["startDate"], "CFBD startDate")
    ]
    contest_teams = tuple(
        dict.fromkeys(
            str(team)
            for game in games
            for team in (game["homeTeam"], game["awayTeam"])
        )
    )
    reports_by_team: dict[
        str, list[tuple[str, Mapping[str, object], list[Mapping[str, object]]]]
    ] = {team: [] for team in contest_teams}
    for report in reports:
        candidates = [team for team in contest_teams if _name_matches(report[0], team)]
        if len(candidates) > 1:
            raise ProductionProviderError(
                f"ESPN injuries ambiguously map provider team {report[0]}"
            )
        if candidates:
            reports_by_team[candidates[0]].append(report)
    for team, team_reports in reports_by_team.items():
        if len(team_reports) > 1:
            raise ProductionProviderError(f"ESPN injuries ambiguously map team {team}")

    normalized: list[dict[str, object]] = []
    for game in games:
        for side, team in (("home", str(game["homeTeam"])), ("away", str(game["awayTeam"]))):
            matching = reports_by_team[team]
            if not matching:
                normalized.append(
                    {
                        "record_id": f"{game['id']}:{side}:missing-team-report",
                        "context_class": "injury",
                        "source_mode": "automated",
                        "coverage_status": "missing",
                        "coverage_reason": (
                            "ESPN aggregate injuries response omitted this contest team; "
                            "absence is not evidence of no reported injuries."
                        ),
                        "game_id": game["id"],
                        "season": season,
                        "week": week,
                        "home_team": game["homeTeam"],
                        "away_team": game["awayTeam"],
                        "affected_side": side,
                        "subject": team,
                        "source_name": "ESPN College Football injuries",
                        "source_reference": endpoint_reference,
                        "observed_at": requested_at.isoformat(),
                        "margin_adjustment": 0,
                        "confidence_adjustment": 0,
                        "author": "automated-espn-injury-capture",
                    }
                )
                continue
            injuries = matching[0][2]
            if not injuries:
                normalized.append(
                    {
                        "record_id": f"{game['id']}:{side}:no-reported-injuries",
                        "context_class": "injury",
                        "source_mode": "automated",
                        "game_id": game["id"],
                        "season": season,
                        "week": week,
                        "home_team": game["homeTeam"],
                        "away_team": game["awayTeam"],
                        "affected_side": side,
                        "subject": team,
                        "report_status": "no_reported_injuries",
                        "evidence_summary": (
                            "ESPN returned an explicit team report with an empty injury "
                            "list at capture time."
                        ),
                        "source_name": "ESPN College Football injuries",
                        "source_reference": endpoint_reference,
                        "observed_at": requested_at.isoformat(),
                        "margin_adjustment": 0,
                        "confidence_adjustment": 0,
                        "author": "automated-espn-injury-capture",
                    }
                )
                continue
            for injury_index, injury in enumerate(injuries):
                athlete = injury.get("athlete")
                subject = _team_name(athlete) or _team_name(injury) or f"{team} player"
                status_value = injury.get("status")
                if isinstance(status_value, Mapping):
                    status = _team_name(status_value) or str(status_value.get("type", "")).strip()
                else:
                    status = str(status_value or injury.get("type") or "reported").strip()
                detail = str(
                    injury.get("shortComment")
                    or injury.get("details")
                    or injury.get("description")
                    or status
                ).strip()
                normalized.append(
                    {
                        "record_id": f"{game['id']}:{side}:{injury.get('id', injury_index)}",
                        "context_class": "injury",
                        "source_mode": "automated",
                        "game_id": game["id"],
                        "season": season,
                        "week": week,
                        "home_team": game["homeTeam"],
                        "away_team": game["awayTeam"],
                        "affected_side": side,
                        "subject": subject,
                        "report_status": status,
                        "evidence_summary": detail,
                        "source_name": "ESPN College Football injuries",
                        "source_reference": endpoint_reference,
                        "observed_at": requested_at.isoformat(),
                        "margin_adjustment": 0,
                        "confidence_adjustment": 0,
                        "author": "automated-espn-injury-capture",
                    }
                )
    return normalized


def _venue_coordinates(payload: object) -> dict[int, tuple[float, float, str]]:
    venues = _payload_records(payload, "CFBD venues payload")
    result: dict[int, tuple[float, float, str]] = {}
    for venue in venues:
        venue_id = venue.get("id")
        location = venue.get("location")
        latitude = venue.get("latitude")
        longitude = venue.get("longitude")
        if isinstance(location, Mapping):
            latitude = location.get("latitude", latitude)
            longitude = location.get("longitude", longitude)
        if (
            isinstance(venue_id, int)
            and not isinstance(latitude, bool)
            and isinstance(latitude, (int, float))
            and not isinstance(longitude, bool)
            and isinstance(longitude, (int, float))
        ):
            result[venue_id] = (
                float(latitude),
                float(longitude),
                str(venue.get("name") or venue_id),
            )
    return result


def _forecast_observation(
    payload: object,
    *,
    kickoff: datetime,
) -> tuple[str, float, float, float, object]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("hourly"), Mapping):
        raise ProductionProviderError("Open-Meteo payload lacks hourly forecast data")
    hourly = payload["hourly"]
    fields = (
        "time",
        "temperature_2m",
        "wind_speed_10m",
        "precipitation_probability",
        "weather_code",
    )
    values = [hourly.get(field) for field in fields]
    if any(not isinstance(value, list) for value in values):
        raise ProductionProviderError("Open-Meteo hourly arrays are incomplete")
    assert all(isinstance(value, list) for value in values)
    if len({len(value) for value in values}) != 1:
        raise ProductionProviderError("Open-Meteo hourly arrays have conflicting lengths")
    candidates: list[tuple[float, int, datetime]] = []
    for index, raw in enumerate(values[0]):
        if not isinstance(raw, str):
            continue
        parsed = datetime.fromisoformat(raw)
        parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
        parsed = parsed.astimezone(timezone.utc)
        candidates.append((abs((parsed - kickoff).total_seconds()), index, parsed))
    if not candidates:
        raise ProductionProviderError("Open-Meteo returned no parseable UTC forecast hours")
    distance, index, forecast_for = min(candidates)
    if distance > 3600:
        raise ProductionProviderError("Open-Meteo lacks a forecast hour near kickoff")
    try:
        temperature = float(values[1][index])
        wind = float(values[2][index])
        precipitation = float(values[3][index])
    except (TypeError, ValueError) as exc:
        raise ProductionProviderError("Open-Meteo forecast values are not numeric") from exc
    if not all(math.isfinite(value) for value in (temperature, wind, precipitation)):
        raise ProductionProviderError("Open-Meteo forecast values must be finite")
    return forecast_for.isoformat(), temperature, wind, precipitation, values[4][index]


def _haversine_miles(
    origin: tuple[float, float, str], destination: tuple[float, float, str]
) -> float:
    lat1, lon1 = math.radians(origin[0]), math.radians(origin[1])
    lat2, lon2 = math.radians(destination[0]), math.radians(destination[1])
    delta_lat = lat2 - lat1
    delta_lon = lon2 - lon1
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 3958.8 * 2 * math.asin(math.sqrt(haversine))


def _normalized_travel_rest_records(
    *,
    current_games_payload: object,
    season_games_payload: object,
    venues_payload: object,
    season: int,
    week: int,
    requested_at: datetime,
) -> list[dict[str, object]]:
    current = _game_rows(current_games_payload, season=season, week=week)
    season_games = _game_rows(season_games_payload, season=season)
    venues = _venue_coordinates(venues_payload)
    normalized: list[dict[str, object]] = []
    for game in current:
        kickoff = _utc(game["startDate"], "CFBD startDate")
        if requested_at >= kickoff:
            continue
        destination = venues.get(game.get("venueId"))
        for side, team in (("home", str(game["homeTeam"])), ("away", str(game["awayTeam"]))):
            previous = [
                candidate
                for candidate in season_games
                if candidate.get("id") != game.get("id")
                and team in (candidate.get("homeTeam"), candidate.get("awayTeam"))
                and _utc(candidate["startDate"], "CFBD startDate") < kickoff
            ]
            previous.sort(key=lambda candidate: _utc(candidate["startDate"], "CFBD startDate"))
            prior = previous[-1] if previous else None
            if prior is None:
                rest_days = None
                travel_miles = None
                schedule_state = "season_opener"
                summary = "No earlier game exists in the captured season schedule."
            else:
                prior_start = _utc(prior["startDate"], "CFBD startDate")
                rest_days = int((kickoff - prior_start).total_seconds() // 86400)
                origin = venues.get(prior.get("venueId"))
                travel_miles = (
                    None
                    if origin is None or destination is None
                    else round(_haversine_miles(origin, destination), 1)
                )
                schedule_state = "computed"
                summary = (
                    f"{rest_days} days since prior scheduled game; "
                    + (
                        "travel distance unavailable from venue coordinates."
                        if travel_miles is None
                        else f"approximately {travel_miles:.1f} venue-to-venue miles."
                    )
                )
            normalized.append(
                {
                    "record_id": f"{game['id']}:{side}:travel-rest",
                    "context_class": "travel_rest",
                    "source_mode": "automated",
                    "game_id": game["id"],
                    "season": season,
                    "week": week,
                    "home_team": game["homeTeam"],
                    "away_team": game["awayTeam"],
                    "affected_side": side,
                    "subject": team,
                    "schedule_state": schedule_state,
                    "rest_days": rest_days,
                    "travel_miles": travel_miles,
                    "evidence_summary": summary,
                    "source_name": "CollegeFootballData games",
                    "source_reference": f"{CFBD_BASE_URL}/games",
                    "observed_at": requested_at.isoformat(),
                    "margin_adjustment": 0,
                    "confidence_adjustment": 0,
                    "author": "automated-cfbd-schedule-context",
                }
            )
    return normalized


def _normalized_manual_context_records(
    adjustments: Sequence[Mapping[str, object]],
    *,
    games_payload: object,
    season: int,
    week: int,
) -> list[dict[str, object]]:
    games = {int(game["id"]): game for game in _game_rows(games_payload, season=season, week=week)}
    normalized: list[dict[str, object]] = []
    for adjustment in adjustments:
        category = adjustment.get("category")
        if category not in ("coaching", "motivation"):
            continue
        game_id = adjustment.get("game_id")
        if not isinstance(game_id, int) or game_id not in games:
            raise ProductionProviderError("manual context targets a game outside the captured week")
        game = games[game_id]
        normalized.append(
            {
                "record_id": _text(adjustment.get("adjustment_key"), "adjustment_key"),
                "context_class": category,
                "source_mode": "manual_exception",
                "game_id": game_id,
                "season": season,
                "week": week,
                "home_team": game["homeTeam"],
                "away_team": game["awayTeam"],
                "affected_side": adjustment.get("affected_side"),
                "subject": adjustment.get("subject", category),
                "evidence_summary": adjustment.get("reason"),
                "source_name": adjustment.get("source"),
                "source_reference": adjustment.get("evidence"),
                "observed_at": adjustment.get("observed_at"),
                "margin_adjustment": adjustment.get("margin_adjustment"),
                "confidence_adjustment": adjustment.get("confidence_adjustment"),
                "author": adjustment.get("author"),
            }
        )
    return normalized


def capture_live_provider_bundle(
    environment: Mapping[str, str],
    *,
    repository_root: Path,
    output_directory: Path,
    season: int,
    week: int,
    line_type: str,
    capture_scope: str = "pregame",
    capture_context: bool = False,
    manual_context_adjustments: Sequence[Mapping[str, object]] = (),
    authorized: bool,
    captured_at: datetime | None = None,
    session: _Session | None = None,
    odds_api_minimum_remaining_credits: int | None = None,
    odds_api_estimated_call_cost: int = 1,
) -> Path:
    """Capture replayable governed provider evidence; never ingest or publish it."""
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
    quota_before = None
    quota_after = None
    if odds_api_minimum_remaining_credits is not None and capture_scope == "pregame":
        minimum_remaining = _integer(
            odds_api_minimum_remaining_credits,
            "odds_api_minimum_remaining_credits",
        )
        estimated_cost = _integer(
            odds_api_estimated_call_cost,
            "odds_api_estimated_call_cost",
        )
        if estimated_cost < 1:
            raise ProductionProviderError("Odds API estimated call cost must be positive")
        quota_response = _safe_get_response(
            client,
            f"{ODDS_BASE_URL}/sports",
            params={"apiKey": odds_key},
        )
        try:
            quota_response.json()
        except Exception as exc:
            raise ProductionProviderError(
                "The Odds API quota probe did not return valid JSON"
            ) from exc
        quota_before = _odds_quota_evidence(quota_response)
        if quota_before["remaining"] < minimum_remaining + estimated_cost:
            raise ProductionProviderError(
                "The Odds API quota reserve blocks this paid provider capture"
            )
    games_params = {"year": season, "week": week, "classification": "fbs"}
    games_endpoint = f"{CFBD_BASE_URL}/games"
    games_payload = _safe_get_json(
        client,
        games_endpoint,
        headers={"Authorization": f"Bearer {cfbd_key}"},
        params=games_params,
    )
    season_games_payload = None
    venues_payload = None
    injuries_payload = None
    normalized_injuries = None
    normalized_weather: list[dict[str, object]] | None = None
    normalized_travel_rest = None
    normalized_manual_context = None
    weather_raw_payloads: list[dict[str, object]] = []
    if capture_scope == "pregame" and capture_context:
        season_games_params = {"year": season, "classification": "fbs"}
        season_games_payload = _safe_get_json(
            client,
            f"{CFBD_BASE_URL}/games",
            headers={"Authorization": f"Bearer {cfbd_key}"},
            params=season_games_params,
        )
        venues_payload = _safe_get_json(
            client,
            f"{CFBD_BASE_URL}/venues",
            headers={"Authorization": f"Bearer {cfbd_key}"},
            params={},
        )
        injuries_payload = _safe_get_json(client, ESPN_INJURIES_URL)
        normalized_injuries = _normalized_injury_records(
            injuries_payload,
            games_payload=games_payload,
            season=season,
            week=week,
            requested_at=now,
        )
        venues = _venue_coordinates(venues_payload)
        normalized_weather = []
        for game in _game_rows(games_payload, season=season, week=week):
            kickoff = _utc(game["startDate"], "CFBD startDate")
            if now >= kickoff:
                continue
            coordinate = venues.get(game.get("venueId"))
            if coordinate is None:
                normalized_weather.append(
                    {
                        "record_id": f"{game['id']}:weather:missing-venue",
                        "context_class": "weather",
                        "source_mode": "automated",
                        "game_id": game["id"],
                        "season": season,
                        "week": week,
                        "home_team": game["homeTeam"],
                        "away_team": game["awayTeam"],
                        "affected_side": "both",
                        "subject": str(game.get("venue") or "unknown venue"),
                        "forecast_for": kickoff.isoformat(),
                        "temperature_f": None,
                        "wind_mph": None,
                        "precipitation_probability": None,
                        "weather_code": None,
                        "evidence_summary": "Venue coordinates are missing; weather is quarantined.",
                        "source_name": "Open-Meteo",
                        "source_reference": OPEN_METEO_FORECAST_URL,
                        "observed_at": now.isoformat(),
                        "margin_adjustment": 0,
                        "confidence_adjustment": 0,
                        "author": "automated-open-meteo-capture",
                    }
                )
                continue
            weather_params = {
                "latitude": coordinate[0],
                "longitude": coordinate[1],
                "hourly": (
                    "temperature_2m,wind_speed_10m,precipitation_probability,weather_code"
                ),
                "temperature_unit": "fahrenheit",
                "wind_speed_unit": "mph",
                "timezone": "UTC",
                "forecast_days": 16,
            }
            weather_payload = _safe_get_json(
                client,
                OPEN_METEO_FORECAST_URL,
                params=weather_params,
            )
            weather_raw_payloads.append(
                {
                    "game_id": game["id"],
                    "venue_id": game.get("venueId"),
                    "request_parameters": weather_params,
                    "payload": weather_payload,
                }
            )
            forecast_for, temperature, wind, precipitation, weather_code = (
                _forecast_observation(weather_payload, kickoff=kickoff)
            )
            normalized_weather.append(
                {
                    "record_id": f"{game['id']}:weather:{forecast_for}",
                    "context_class": "weather",
                    "source_mode": "automated",
                    "game_id": game["id"],
                    "season": season,
                    "week": week,
                    "home_team": game["homeTeam"],
                    "away_team": game["awayTeam"],
                    "affected_side": "both",
                    "subject": coordinate[2],
                    "forecast_for": forecast_for,
                    "temperature_f": temperature,
                    "wind_mph": wind,
                    "precipitation_probability": precipitation,
                    "weather_code": weather_code,
                    "evidence_summary": (
                        f"Kickoff forecast: {temperature:.1f} F, {wind:.1f} mph wind, "
                        f"{precipitation:.0f}% precipitation probability."
                    ),
                    "source_name": "Open-Meteo",
                    "source_reference": OPEN_METEO_FORECAST_URL,
                    "observed_at": now.isoformat(),
                    "margin_adjustment": 0,
                    "confidence_adjustment": 0,
                    "author": "automated-open-meteo-capture",
                }
            )
        normalized_travel_rest = _normalized_travel_rest_records(
            current_games_payload=games_payload,
            season_games_payload=season_games_payload,
            venues_payload=venues_payload,
            season=season,
            week=week,
            requested_at=now,
        )
        normalized_manual_context = _normalized_manual_context_records(
            manual_context_adjustments,
            games_payload=games_payload,
            season=season,
            week=week,
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
    odds_api_params = {
        "regions": "us",
        "markets": "spreads",
        "bookmakers": "draftkings,fanduel,betmgm,williamhill_us,bovada",
        "oddsFormat": "american",
    }
    odds_custody_params = {**odds_api_params, "season": season, "week": week}
    odds_endpoint = f"{ODDS_BASE_URL}/sports/americanfootball_ncaaf/odds"
    odds_payload = None
    normalized_odds = None
    if capture_scope == "pregame":
        odds_response = _safe_get_response(
            client,
            odds_endpoint,
            params={**odds_api_params, "apiKey": odds_key},
        )
        try:
            odds_payload = odds_response.json()
        except Exception as exc:
            raise ProductionProviderError(
                "The Odds API odds response did not return valid JSON"
            ) from exc
        if quota_before is not None:
            quota_after = _odds_quota_evidence(odds_response)
            minimum_remaining = int(odds_api_minimum_remaining_credits or 0)
            if quota_after["last"] > odds_api_estimated_call_cost:
                raise ProductionProviderError(
                    "The Odds API charged more credits than the configured call cost"
                )
            if quota_after["remaining"] < minimum_remaining:
                raise ProductionProviderError(
                    "The Odds API quota reserve was crossed by the paid provider capture"
                )
        normalized_odds = _normalized_odds_records(
            odds_payload,
            season=season,
            week=week,
            requested_at=now,
            line_type=line_type,
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
                "request_parameters": odds_custody_params,
                "requested_at": now.isoformat(),
                "parser_version": "odds_spread_v3",
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
    if (
        season_games_payload is not None
        and venues_payload is not None
        and injuries_payload is not None
        and normalized_injuries is not None
        and normalized_weather is not None
        and normalized_travel_rest is not None
        and normalized_manual_context is not None
    ):
        context_raw = (
            ("cfbd-season-games.raw.json", season_games_payload),
            ("cfbd-venues.raw.json", venues_payload),
            ("espn-injuries.raw.json", injuries_payload),
            ("open-meteo.raw.json", weather_raw_payloads),
        )
        for name, raw_payload in context_raw:
            path = output / name
            digest = _write_canonical_json(path, raw_payload)
            raw_evidence.append({"path": path.name, "sha256": digest})
        context_specs = (
            (
                "espn",
                "injuries",
                ESPN_INJURIES_URL,
                {"season": season, "week": week},
                "espn-injuries.raw.json",
                "injuries.normalized.json",
                normalized_injuries,
            ),
            (
                "open_meteo",
                "weather",
                OPEN_METEO_FORECAST_URL,
                {"season": season, "week": week, "timezone": "UTC"},
                "open-meteo.raw.json",
                "weather.normalized.json",
                normalized_weather,
            ),
            (
                "collegefootballdata",
                "contextual",
                f"{CFBD_BASE_URL}/games",
                {"year": season, "week": week, "classification": "fbs"},
                "cfbd-season-games.raw.json",
                "travel-rest.normalized.json",
                normalized_travel_rest,
            ),
        )
        for (
            provider,
            data_type,
            endpoint,
            parameters,
            raw_name,
            normalized_name,
            records,
        ) in context_specs:
            path = output / normalized_name
            digest = _write_canonical_json(path, records)
            payloads.append(
                {
                    "provider": provider,
                    "data_type": data_type,
                    "endpoint": endpoint,
                    "request_parameters": parameters,
                    "requested_at": now.isoformat(),
                    "parser_version": CONTEXT_EVIDENCE_PARSER_VERSION,
                    "raw_payload_reference": str(output / raw_name),
                    "payload_path": path.name,
                    "payload_sha256": digest,
                }
            )
        if normalized_manual_context:
            manual_path = output / "owner-context.normalized.json"
            manual_sha = _write_canonical_json(manual_path, normalized_manual_context)
            payloads.append(
                {
                    "provider": "owner_context_manifest",
                    "data_type": "contextual",
                    "endpoint": "config://weekly-operation/contextual-adjustments",
                    "request_parameters": {"season": season, "week": week},
                    "requested_at": now.isoformat(),
                    "parser_version": CONTEXT_EVIDENCE_PARSER_VERSION,
                    "raw_payload_reference": "config://weekly-operation/contextual-adjustments",
                    "payload_path": manual_path.name,
                    "payload_sha256": manual_sha,
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
        "context_capture": capture_context,
        "raw_evidence": raw_evidence,
        "odds_api_quota": (
            None
            if quota_before is None or quota_after is None
            else {
                "minimum_remaining_credits": odds_api_minimum_remaining_credits,
                "estimated_call_cost": odds_api_estimated_call_cost,
                "before": quota_before,
                "after": quota_after,
            }
        ),
        "payloads": payloads,
    }
    bundle_path = output / "provider-bundle.json"
    _write_canonical_json(bundle_path, bundle)
    return bundle_path
