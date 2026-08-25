"""Point-in-time production context evidence and immutable card snapshots."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from business_entities.weekly_controller import ContextualAdjustmentInput
from ingestion import (
    DEFAULT_FRESHNESS_RULES,
    AcceptedProviderRecord,
    CanonicalTeamResolver,
    IngestionRequest,
    TeamResolution,
    payload_sha256,
)
from ingestion.custody import RecordRejected


CONTEXT_EVIDENCE_PARSER_VERSION = "production_context_evidence_v1"
CONTEXT_CLASSES = ("injury", "weather", "travel_rest", "coaching", "motivation")
AUTOMATED_CONTEXT_CLASSES = ("injury", "weather", "travel_rest")
MANUAL_CONTEXT_CLASSES = ("coaching", "motivation")


class ProductionContextError(RuntimeError):
    """Raised when context cannot be consumed without weakening custody."""


@dataclass(frozen=True)
class ParsedContextEvidence(AcceptedProviderRecord):
    context_class: str
    source_mode: str
    game_id: int
    season: int
    week: int
    affected_side: str
    subject: str | None
    evidence_summary: str
    source_name: str
    source_reference: str
    expires_at: datetime
    margin_adjustment: float
    confidence_adjustment: int
    author: str


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RecordRejected("malformed_record", f"{field} is required")
    return value.strip()


def _integer(value: object, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise RecordRejected("malformed_record", f"{field} must be an integer >= {minimum}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise RecordRejected("malformed_record", f"{field} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise RecordRejected("malformed_record", f"{field} must be finite")
    return converted


def _utc(value: object, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        raw = value.strip()
        raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError as exc:
            raise RecordRejected("invalid_timestamp", f"{field} is not ISO-8601") from exc
    else:
        raise RecordRejected("invalid_timestamp", f"{field} must be a UTC timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise RecordRejected("invalid_timestamp", f"{field} must use a UTC offset")
    return parsed.astimezone(timezone.utc)


def _resolved(resolution: TeamResolution, field: str) -> str:
    if resolution.status == "unknown":
        raise RecordRejected("unknown_team", f"{field} is unknown")
    if resolution.status == "ambiguous":
        raise RecordRejected("ambiguous_team_normalization", f"{field} is ambiguous")
    assert resolution.canonical_name is not None
    return resolution.canonical_name


def _raw_sha(record: Mapping[str, object]) -> str:
    canonical = json.dumps(
        record,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_reference(value: object) -> str:
    reference = _text(value, "source_reference")
    folded = reference.casefold()
    if any(token in folded for token in ("apikey=", "api_key=", "token=", "secret=")):
        raise RecordRejected("malformed_record", "source_reference contains credentials")
    return reference


class ContextEvidenceParser:
    """Validate normalized automated or explicitly manual context evidence."""

    version = CONTEXT_EVIDENCE_PARSER_VERSION

    def parse(
        self,
        conn: sqlite3.Connection,
        resolver: CanonicalTeamResolver,
        provider: str,
        request: IngestionRequest,
        record_index: int,
        record: Mapping[str, object],
    ) -> ParsedContextEvidence:
        context_class = _text(record.get("context_class"), "context_class")
        if context_class not in CONTEXT_CLASSES:
            raise RecordRejected("malformed_record", "context_class is unsupported")
        expected_data_type = {
            "injury": "injuries",
            "weather": "weather",
            "travel_rest": "contextual",
            "coaching": "contextual",
            "motivation": "contextual",
        }[context_class]
        if request.data_type != expected_data_type:
            raise RecordRejected(
                "malformed_record",
                f"{context_class} evidence requires data_type={expected_data_type}",
            )
        source_mode = _text(record.get("source_mode"), "source_mode")
        expected_mode = (
            "automated" if context_class in AUTOMATED_CONTEXT_CLASSES else "manual_exception"
        )
        if source_mode != expected_mode:
            raise RecordRejected(
                "malformed_record",
                f"{context_class} evidence requires source_mode={expected_mode}",
            )
        season = _integer(record.get("season"), "season", 1869)
        week = _integer(record.get("week"), "week", 0)
        game_id = _integer(record.get("game_id"), "game_id", 1)
        home = _resolved(resolver.resolve(provider, record.get("home_team")), "home_team")
        away = _resolved(resolver.resolve(provider, record.get("away_team")), "away_team")
        row = conn.execute(
            "SELECT home_team, away_team, start_date FROM games "
            "WHERE game_id = ? AND season = ? AND week = ?",
            (game_id, season, week),
        ).fetchone()
        if row is None:
            raise RecordRejected("game_mapping_not_found", "context game does not exist")
        if (home, away) != (str(row[0]), str(row[1])):
            raise RecordRejected("conflicting_game_mapping", "context matchup is not canonical")
        observed_at = _utc(record.get("observed_at"), "observed_at")
        requested_at = _utc(request.requested_at, "requested_at")
        kickoff = _utc(str(row[2]), "game.start_date")
        if observed_at > requested_at or observed_at >= kickoff:
            raise RecordRejected(
                "invalid_timestamp", "context evidence must be observed by capture and before kickoff"
            )
        affected_side = _text(record.get("affected_side"), "affected_side")
        if affected_side not in ("home", "away", "both", "neutral"):
            raise RecordRejected("malformed_record", "affected_side is invalid")
        margin = _number(record.get("margin_adjustment", 0), "margin_adjustment")
        confidence_raw = record.get("confidence_adjustment", 0)
        if isinstance(confidence_raw, bool) or not isinstance(confidence_raw, int):
            raise RecordRejected("malformed_record", "confidence_adjustment must be an integer")
        confidence = int(confidence_raw)
        if not -4 <= confidence <= 4 or not -100 <= margin <= 100:
            raise RecordRejected("malformed_record", "context adjustment is outside bounds")
        if source_mode == "automated" and (margin != 0 or confidence != 0):
            raise RecordRejected(
                "malformed_record", "automated observations cannot invent numeric adjustments"
            )
        if source_mode == "manual_exception" and margin == 0 and confidence == 0:
            raise RecordRejected(
                "malformed_record", "manual context must express a non-zero adjustment"
            )
        if affected_side in ("both", "neutral") and margin != 0:
            raise RecordRejected(
                "malformed_record", "margin adjustments must identify home or away"
            )
        if context_class == "injury":
            _text(record.get("report_status"), "report_status")
        elif context_class == "weather":
            forecast_for = _utc(record.get("forecast_for"), "forecast_for")
            if abs((forecast_for - kickoff).total_seconds()) > 3600:
                raise RecordRejected(
                    "invalid_timestamp", "weather forecast must be within one hour of kickoff"
                )
            _number(record.get("temperature_f"), "temperature_f")
            wind = _number(record.get("wind_mph"), "wind_mph")
            precipitation = _number(
                record.get("precipitation_probability"),
                "precipitation_probability",
            )
            if wind < 0 or not 0 <= precipitation <= 100:
                raise RecordRejected("malformed_record", "weather values are outside bounds")
        elif context_class == "travel_rest":
            schedule_state = _text(record.get("schedule_state"), "schedule_state")
            if schedule_state not in ("computed", "season_opener"):
                raise RecordRejected("malformed_record", "schedule_state is invalid")
            if schedule_state == "computed":
                _integer(record.get("rest_days"), "rest_days", 0)
            travel_miles = record.get("travel_miles")
            if travel_miles is not None and _number(travel_miles, "travel_miles") < 0:
                raise RecordRejected("malformed_record", "travel_miles cannot be negative")
        subject_value = record.get("subject")
        subject = None if subject_value is None else _text(subject_value, "subject")
        raw_sha = _raw_sha(record)
        record_id = _text(record.get("record_id"), "record_id")
        max_age = DEFAULT_FRESHNESS_RULES[request.data_type]
        return ParsedContextEvidence(
            record_index=record_index,
            provider_record_id=record_id,
            record_key=payload_sha256(
                {
                    "provider": provider,
                    "record_id": record_id,
                    "observed_at": observed_at.isoformat(),
                    "raw_record_sha256": raw_sha,
                    "parser_version": self.version,
                }
            ),
            observed_at=observed_at,
            parser_version=self.version,
            raw_record_sha256=raw_sha,
            context_class=context_class,
            source_mode=source_mode,
            game_id=game_id,
            season=season,
            week=week,
            affected_side=affected_side,
            subject=subject,
            evidence_summary=_text(record.get("evidence_summary"), "evidence_summary"),
            source_name=_text(record.get("source_name"), "source_name"),
            source_reference=_safe_reference(record.get("source_reference")),
            expires_at=observed_at + timedelta(seconds=max_age),
            margin_adjustment=margin,
            confidence_adjustment=confidence,
            author=_text(record.get("author"), "author"),
        )


def write_context_evidence(
    conn: sqlite3.Connection,
    records: Sequence[AcceptedProviderRecord],
) -> None:
    """Persist semantic context only after the custody service accepted it."""
    for record in records:
        if not isinstance(record, ParsedContextEvidence):
            continue
        acceptance = conn.execute(
            "SELECT id, ingestion_run_id, accepted_at FROM provider_ingestion_acceptances "
            "WHERE record_key = ? AND parser_version = ?",
            (record.record_key, record.parser_version),
        ).fetchone()
        if acceptance is None:
            raise ProductionContextError("accepted context record lacks custody identity")
        conn.execute(
            "INSERT INTO provider_context_evidence "
            "(acceptance_id, ingestion_run_id, record_index, evidence_key, "
            "context_class, source_mode, game_id, season, week, affected_side, subject, "
            "evidence_summary, source_name, source_reference, observed_at, expires_at, "
            "margin_adjustment, confidence_adjustment, author, parser_version, "
            "raw_record_sha256, ingested_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(acceptance[0]),
                int(acceptance[1]),
                record.record_index,
                record.record_key,
                record.context_class,
                record.source_mode,
                record.game_id,
                record.season,
                record.week,
                record.affected_side,
                record.subject,
                record.evidence_summary,
                record.source_name,
                record.source_reference,
                record.observed_at.isoformat(),
                record.expires_at.isoformat(),
                record.margin_adjustment,
                record.confidence_adjustment,
                record.author,
                record.parser_version,
                record.raw_record_sha256,
                str(acceptance[2]),
            ),
        )


def contextual_adjustments_from_evidence(
    conn: sqlite3.Connection,
    *,
    season: int,
    week: int,
    as_of: datetime,
) -> tuple[ContextualAdjustmentInput, ...]:
    """Materialize only current, explicitly manual numeric evidence for a card run."""
    rows = conn.execute(
        "SELECT id, evidence_key, context_class, game_id, affected_side, "
        "margin_adjustment, confidence_adjustment, evidence_summary, source_name, "
        "source_reference, author, observed_at FROM provider_context_evidence "
        "WHERE season = ? AND week = ? AND source_mode = 'manual_exception' "
        "AND julianday(observed_at) <= julianday(?) "
        "AND julianday(expires_at) >= julianday(?) "
        "ORDER BY context_class, game_id, observed_at, id",
        (season, week, as_of.isoformat(), as_of.isoformat()),
    ).fetchall()
    category = {"travel_rest": "travel"}
    return tuple(
        ContextualAdjustmentInput(
            adjustment_key=f"context-evidence:{row[1]}:{as_of.isoformat()}",
            game_id=int(row[3]),
            category=category.get(str(row[2]), str(row[2])),
            affected_side=str(row[4]),
            margin_adjustment=float(row[5]),
            confidence_adjustment=int(row[6]),
            reason=str(row[7]),
            evidence=str(row[9]),
            source=str(row[8]),
            author=str(row[10]),
            provenance=f"provider_context_evidence_id={row[0]};observed_at={row[11]}",
        )
        for row in rows
    )


def record_card_context_status(
    conn: sqlite3.Connection,
    *,
    card_id: int,
    controller_run_id: int,
    as_of: datetime,
    provenance: str,
) -> None:
    """Freeze current/stale/missing context classes used by one official card."""
    existing = conn.execute(
        "SELECT context_class, controller_run_id FROM card_context_status "
        "WHERE card_id = ? ORDER BY context_class",
        (card_id,),
    ).fetchall()
    if existing:
        if (
            len(existing) == len(CONTEXT_CLASSES)
            and {str(row[0]) for row in existing} == set(CONTEXT_CLASSES)
            and {int(row[1]) for row in existing} == {controller_run_id}
        ):
            return
        raise ProductionContextError("card has incomplete or conflicting context status")
    game_ids = tuple(
        int(row[0])
        for row in conn.execute(
            "SELECT locked.game_id FROM contest_picks AS pick "
            "JOIN contest_locked_lines AS locked ON locked.id = pick.locked_line_id "
            "JOIN games AS game ON game.game_id = locked.game_id "
            "WHERE pick.card_id = ? AND julianday(?) < julianday(game.start_date) "
            "ORDER BY locked.game_id",
            (card_id, as_of.isoformat()),
        )
    )
    if not game_ids:
        raise ProductionContextError("card context status requires pre-kickoff contest picks")
    placeholders = ",".join("?" for _ in game_ids)
    for context_class in CONTEXT_CLASSES:
        current = conn.execute(
            "SELECT COUNT(*), COUNT(DISTINCT game_id), MAX(observed_at), "
            "COUNT(DISTINCT source_mode) FROM provider_context_evidence "
            f"WHERE game_id IN ({placeholders}) AND context_class = ? "
            "AND julianday(observed_at) <= julianday(?) "
            "AND julianday(expires_at) >= julianday(?)",
            (*game_ids, context_class, as_of.isoformat(), as_of.isoformat()),
        ).fetchone()
        current_count = int(current[0])
        current_games = int(current[1])
        latest_current = current[2]
        requires_full_coverage = context_class in AUTOMATED_CONTEXT_CLASSES
        is_current = current_count > 0 and (
            not requires_full_coverage or current_games == len(set(game_ids))
        )
        prior = conn.execute(
            "SELECT MAX(observed_at) FROM provider_context_evidence "
            f"WHERE game_id IN ({placeholders}) AND context_class = ? "
            "AND julianday(observed_at) <= julianday(?)",
            (*game_ids, context_class, as_of.isoformat()),
        ).fetchone()[0]
        if is_current:
            state = "current"
            fallback_code = None
            fallback_reason = None
            evidence_count = current_count
            latest = str(latest_current)
        else:
            state = "stale" if prior is not None else "missing"
            fallback_code = (
                "manual_context_not_asserted"
                if context_class in MANUAL_CONTEXT_CLASSES and prior is None
                else f"{context_class}_{state}"
            )
            fallback_reason = (
                "No sourced manual exception was asserted for this context class."
                if fallback_code == "manual_context_not_asserted"
                else f"Governed {context_class} evidence is {state} or lacks full game coverage."
            )
            evidence_count = 0
            latest = None
        source_mode = (
            "manual_exception"
            if context_class in MANUAL_CONTEXT_CLASSES
            else "automated"
        )
        conn.execute(
            "INSERT INTO card_context_status "
            "(card_id, controller_run_id, context_class, state, source_mode, "
            "evidence_count, latest_observed_at, fallback_code, fallback_reason, provenance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                card_id,
                controller_run_id,
                context_class,
                state,
                source_mode,
                evidence_count,
                latest,
                fallback_code,
                fallback_reason,
                provenance,
            ),
        )
