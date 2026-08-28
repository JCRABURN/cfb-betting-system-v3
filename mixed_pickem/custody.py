"""Governed Product B import, manifest, approval, deadline, and line locking."""

from __future__ import annotations

import itertools
import json
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator

from mixed_pickem.common import (
    MixedPickemValidationError,
    canonical_json,
    require_key,
    require_sha256,
    require_text,
    sha256_text,
    utc_datetime,
    utc_text,
)
from mixed_pickem.spreadsheets import (
    PARSER_VERSION,
    ParsedSource,
    SourceRow,
    SpreadsheetContractError,
    normalize_kickoff,
    normalize_sport_hint,
    normalize_spread,
    read_source,
)


DEADLINE_POLICY_VERSION = "mixed-earliest-kickoff-v1"
LOCK_POLICY_VERSION = "mixed-immutable-lines-v1"
_SAVEPOINTS = itertools.count(1)
_AMBIGUOUS_CODES = {
    "AMBIGUOUS_TEAM",
    "AMBIGUOUS_EVENT",
    "SOURCE_EVENT_ID_AMBIGUOUS",
    "KICKOFF_REQUIRED_FOR_UNIQUE_RESOLUTION",
}
_DUPLICATE_CODES = {
    "DUPLICATE_RAW_ROW",
    "DUPLICATE_RAW_MATCHUP",
    "CONFLICTING_RAW_MATCHUP_SPREAD",
    "DUPLICATE_CANONICAL_EVENT",
    "CONFLICTING_EVENT_SPREAD",
    "SOURCE_EVENT_ID_CONFLICT",
}


class MixedPickemCustodyError(RuntimeError):
    """Raised when a Product B custody transition cannot be proven safe."""


@dataclass(frozen=True)
class ManifestBuildRequest:
    source_path: Path
    media_type: str
    contest_round_id: int
    import_key: str
    resolution_window_start_at: datetime
    resolution_window_end_at: datetime
    received_at: datetime
    imported_at: datetime
    generated_at: datetime
    actor: str
    provenance: str
    worksheet: str | None = None
    expected_source_row_count: int | None = None
    source_event_provider: str | None = None
    alias_provider: str = "mixed_pickem_admin"


@dataclass(frozen=True)
class ManifestBuildResult:
    import_id: int
    manifest_id: int
    deadline_derivation_id: int | None
    import_status: str
    manifest_state: str
    source_row_count: int
    accepted_count: int
    rejected_count: int
    ambiguous_count: int
    duplicate_count: int
    source_sha256: str
    ordered_row_set_sha256: str
    manifest_sha256: str
    event_kickoff_set_sha256: str | None
    earliest_kickoff_at: str | None
    review: dict[str, object]


@dataclass(frozen=True)
class ApprovalResult:
    approval_id: int
    manifest_id: int
    deadline_derivation_id: int
    manifest_sha256: str
    approved_row_count: int
    approved_at: str


@dataclass(frozen=True)
class LockResult:
    lock_batch_id: int
    completion_id: int
    contest_round_id: int
    line_count: int
    ordered_line_set_sha256: str
    locked_at: str


@dataclass(frozen=True)
class _EventState:
    event_id: int
    canonical_event_key: str
    sport_code: str
    league_season: int
    home_team_id: int
    away_team_id: int
    kickoff_at: str
    event_revision_id: int | None


@dataclass
class _WorkingRow:
    source: SourceRow
    raw_away_team: str = ""
    raw_home_team: str = ""
    raw_spread_text: str = ""
    raw_spread_side: str = ""
    normalized_spread_side: str | None = None
    displayed_spread_millipoints: int | None = None
    home_spread_millipoints: int | None = None
    raw_sport_hint: str = ""
    sport_hint: str | None = None
    raw_kickoff: str = ""
    parsed_kickoff_at: str | None = None
    raw_source_event_id: str = ""
    raw_notes: str = ""
    sport_code: str | None = None
    event: _EventState | None = None
    canonical_home_team_name: str | None = None
    canonical_away_team_name: str | None = None
    resolution_method: str = "NONE"
    evidence: dict[str, object] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    resolution_state: str = "REJECTED"
    canonical_row_sha256: str = ""


@contextmanager
def _atomic(conn: sqlite3.Connection) -> Iterator[None]:
    name = f"mixed_pickem_{next(_SAVEPOINTS)}"
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
        raise
    else:
        conn.execute(f"RELEASE SAVEPOINT {name}")


def _positive_integer(value: int, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MixedPickemCustodyError(f"{field_name} must be a positive integer")
    return value


def _scope(conn: sqlite3.Connection, round_id: int) -> tuple[int, int, int, str, int]:
    row = conn.execute(
        "SELECT product.id, season.id, round.id, season.season_key, "
        "round.round_number FROM mixed_contest_rounds AS round "
        "JOIN mixed_contest_seasons AS season ON season.id = round.contest_season_id "
        "JOIN mixed_contest_products AS product ON product.id = season.product_id "
        "WHERE round.id = ? AND product.product_key = 'mixed_pickem'",
        (round_id,),
    ).fetchone()
    if row is None:
        raise MixedPickemCustodyError("mixed contest round does not exist")
    return int(row[0]), int(row[1]), int(row[2]), str(row[3]), int(row[4])


def _latest_round_state(conn: sqlite3.Connection, round_id: int) -> tuple[int, int, str] | None:
    row = conn.execute(
        "SELECT id, sequence, state FROM mixed_round_state_events "
        "WHERE contest_round_id = ? ORDER BY sequence DESC LIMIT 1",
        (round_id,),
    ).fetchone()
    return None if row is None else (int(row[0]), int(row[1]), str(row[2]))


def _stale_manifest_for_round_state(
    conn: sqlite3.Connection,
    *,
    state_id: int,
    state: str,
    as_of: str,
) -> bool:
    if state == "MANIFEST_READY":
        row = conn.execute(
            "SELECT state.manifest_id, deadline.ordered_event_kickoff_set_sha256 "
            "FROM mixed_round_state_events AS state "
            "JOIN mixed_deadline_derivations AS deadline "
            "ON deadline.manifest_id = state.manifest_id WHERE state.id = ?",
            (state_id,),
        ).fetchone()
    elif state == "OWNER_APPROVED":
        row = conn.execute(
            "SELECT approval.manifest_id, approval.event_kickoff_set_sha256 "
            "FROM mixed_round_state_events AS state "
            "JOIN mixed_slate_approvals AS approval ON approval.id = state.approval_id "
            "WHERE state.id = ?",
            (state_id,),
        ).fetchone()
    else:
        return False
    if row is None:
        raise MixedPickemCustodyError("prior round state lacks deadline evidence")
    current_hash, _ = _current_event_set_for_manifest(conn, int(row[0]), as_of)
    return current_hash != str(row[1])


def _append_round_state(
    conn: sqlite3.Connection,
    *,
    round_id: int,
    state: str,
    recorded_at: str,
    actor: str,
    reason: str,
    provenance: str,
    import_id: int | None = None,
    manifest_id: int | None = None,
    approval_id: int | None = None,
    lock_completion_id: int | None = None,
) -> int:
    prior = _latest_round_state(conn, round_id)
    sequence = 1 if prior is None else prior[1] + 1
    cursor = conn.execute(
        "INSERT INTO mixed_round_state_events "
        "(contest_round_id, sequence, state, supersedes_state_id, import_id, "
        "manifest_id, approval_id, lock_completion_id, recorded_at, actor, "
        "reason, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            round_id,
            sequence,
            state,
            None if prior is None else prior[0],
            import_id,
            manifest_id,
            approval_id,
            lock_completion_id,
            recorded_at,
            actor,
            reason,
            provenance,
        ),
    )
    return int(cursor.lastrowid)


def create_contest_season(
    conn: sqlite3.Connection,
    *,
    season_key: str,
    display_label: str,
    planned_round_count: int,
    policy_version: str,
    actor: str,
    provenance: str,
    created_at: datetime,
    initial_state: str = "ACTIVE",
) -> int:
    """Create one immutable Product B season; 20 is policy, not a global rule."""
    try:
        season_key = require_key(season_key, "season_key")
        display_label = require_text(display_label, "display_label")
        policy_version = require_text(policy_version, "policy_version")
        actor = require_text(actor, "actor")
        provenance = require_text(provenance, "provenance")
        created = utc_text(created_at, "created_at")
    except MixedPickemValidationError as exc:
        raise MixedPickemCustodyError(str(exc)) from exc
    planned_round_count = _positive_integer(planned_round_count, "planned_round_count")
    if planned_round_count > 100:
        raise MixedPickemCustodyError("planned_round_count exceeds the schema bound")
    if initial_state not in ("PLANNED", "ACTIVE", "INACTIVE"):
        raise MixedPickemCustodyError("initial_state is invalid")
    product = conn.execute(
        "SELECT id FROM mixed_contest_products WHERE product_key = 'mixed_pickem'"
    ).fetchone()
    if product is None:
        raise MixedPickemCustodyError("mixed_pickem product registry is missing")
    try:
        cursor = conn.execute(
            "INSERT INTO mixed_contest_seasons "
            "(product_id, season_key, display_label, planned_round_count, "
            "policy_version, initial_state, created_at, actor, provenance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                int(product[0]),
                season_key,
                display_label,
                planned_round_count,
                policy_version,
                initial_state,
                created,
                actor,
                provenance,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise MixedPickemCustodyError(f"contest season was rejected: {exc}") from exc
    return int(cursor.lastrowid)


def create_contest_round(
    conn: sqlite3.Connection,
    *,
    contest_season_id: int,
    round_number: int,
    round_label: str,
    actor: str,
    provenance: str,
    created_at: datetime,
) -> int:
    """Create a contest round independent of either sport's week number."""
    contest_season_id = _positive_integer(contest_season_id, "contest_season_id")
    round_number = _positive_integer(round_number, "round_number")
    try:
        round_label = require_text(round_label, "round_label")
        actor = require_text(actor, "actor")
        provenance = require_text(provenance, "provenance")
        created = utc_text(created_at, "created_at")
    except MixedPickemValidationError as exc:
        raise MixedPickemCustodyError(str(exc)) from exc
    try:
        with _atomic(conn):
            cursor = conn.execute(
                "INSERT INTO mixed_contest_rounds "
                "(contest_season_id, round_number, round_label, created_at, actor, "
                "provenance) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    contest_season_id,
                    round_number,
                    round_label,
                    created,
                    actor,
                    provenance,
                ),
            )
            round_id = int(cursor.lastrowid)
            _scope(conn, round_id)
            _append_round_state(
                conn,
                round_id=round_id,
                state="OPEN",
                recorded_at=created,
                actor=actor,
                reason="Contest round created under its season policy.",
                provenance=provenance,
            )
            return round_id
    except sqlite3.IntegrityError as exc:
        raise MixedPickemCustodyError(f"contest round was rejected: {exc}") from exc


def _effective_events(
    conn: sqlite3.Connection,
    *,
    as_of: str,
) -> tuple[_EventState, ...]:
    events: list[_EventState] = []
    base_rows = conn.execute(
        "SELECT id, canonical_event_key, sport_code, league_season, home_team_id, "
        "away_team_id, kickoff_at FROM football_events "
        "WHERE julianday(created_at) <= julianday(?) ORDER BY id",
        (as_of,),
    ).fetchall()
    for base in base_rows:
        revision = conn.execute(
            "SELECT id, home_team_id, away_team_id, kickoff_at "
            "FROM football_event_revisions WHERE event_id = ? "
            "AND julianday(recorded_at) <= julianday(?) "
            "ORDER BY revision_number DESC LIMIT 1",
            (base[0], as_of),
        ).fetchone()
        events.append(
            _EventState(
                event_id=int(base[0]),
                canonical_event_key=str(base[1]),
                sport_code=str(base[2]),
                league_season=int(base[3]),
                home_team_id=int(base[4] if revision is None else revision[1]),
                away_team_id=int(base[5] if revision is None else revision[2]),
                kickoff_at=str(base[6] if revision is None else revision[3]),
                event_revision_id=None if revision is None else int(revision[0]),
            )
        )
    return tuple(events)


def _team_record(conn: sqlite3.Connection, team_id: int) -> tuple[str, str, str]:
    row = conn.execute(
        "SELECT sport_code, canonical_key, display_name FROM football_teams WHERE id = ?",
        (team_id,),
    ).fetchone()
    if row is None:
        raise MixedPickemCustodyError(f"football team does not exist: {team_id}")
    return str(row[0]), str(row[1]), str(row[2])


def _team_match_kind(
    conn: sqlite3.Connection,
    *,
    raw_name: str,
    team_id: int,
    sport_code: str,
    league_season: int,
    alias_provider: str,
    as_of: str,
) -> str | None:
    _, canonical_key, display_name = _team_record(conn, team_id)
    key = raw_name.strip().casefold()
    if key in (canonical_key.casefold(), display_name.strip().casefold()):
        return "CANONICAL_TEAM_PAIR"
    alias = conn.execute(
        "SELECT team_id FROM football_team_aliases "
        "WHERE provider = ? AND sport_code = ? AND alias_key = ? "
        "AND effective_from_season <= ? "
        "AND julianday(created_at) <= julianday(?) "
        "ORDER BY effective_from_season DESC, id DESC LIMIT 1",
        (alias_provider, sport_code, key, league_season, as_of),
    ).fetchone()
    if alias is not None and int(alias[0]) == team_id:
        return "PROVIDER_ALIAS"
    return None


def _event_in_window(event: _EventState, start: str, end: str) -> bool:
    kickoff = datetime.fromisoformat(event.kickoff_at)
    return datetime.fromisoformat(start) <= kickoff <= datetime.fromisoformat(end)


def _candidate_team_ids(
    conn: sqlite3.Connection,
    *,
    raw_name: str,
    events: tuple[_EventState, ...],
    sport_hint: str | None,
    alias_provider: str,
    as_of: str,
) -> set[int]:
    result: set[int] = set()
    for event in events:
        if sport_hint is not None and event.sport_code != sport_hint:
            continue
        for team_id in (event.home_team_id, event.away_team_id):
            if _team_match_kind(
                conn,
                raw_name=raw_name,
                team_id=team_id,
                sport_code=event.sport_code,
                league_season=event.league_season,
                alias_provider=alias_provider,
                as_of=as_of,
            ):
                result.add(team_id)
    return result


def _event_orientation(
    conn: sqlite3.Connection,
    row: _WorkingRow,
    event: _EventState,
    alias_provider: str,
    as_of: str,
) -> tuple[bool, bool, str]:
    away_kind = _team_match_kind(
        conn,
        raw_name=row.raw_away_team,
        team_id=event.away_team_id,
        sport_code=event.sport_code,
        league_season=event.league_season,
        alias_provider=alias_provider,
        as_of=as_of,
    )
    home_kind = _team_match_kind(
        conn,
        raw_name=row.raw_home_team,
        team_id=event.home_team_id,
        sport_code=event.sport_code,
        league_season=event.league_season,
        alias_provider=alias_provider,
        as_of=as_of,
    )
    reverse_away = _team_match_kind(
        conn,
        raw_name=row.raw_away_team,
        team_id=event.home_team_id,
        sport_code=event.sport_code,
        league_season=event.league_season,
        alias_provider=alias_provider,
        as_of=as_of,
    )
    reverse_home = _team_match_kind(
        conn,
        raw_name=row.raw_home_team,
        team_id=event.away_team_id,
        sport_code=event.sport_code,
        league_season=event.league_season,
        alias_provider=alias_provider,
        as_of=as_of,
    )
    exact = away_kind is not None and home_kind is not None
    reversed_match = reverse_away is not None and reverse_home is not None
    method = (
        "PROVIDER_ALIAS"
        if "PROVIDER_ALIAS" in (away_kind, home_kind)
        else "CANONICAL_TEAM_PAIR"
    )
    return exact, reversed_match, method


def _source_id_events(
    conn: sqlite3.Connection,
    *,
    provider: str,
    provider_event_id: str,
    as_of: str,
    by_id: dict[int, _EventState],
) -> list[_EventState]:
    sql = (
        "SELECT event_id FROM football_provider_event_ids "
        "WHERE provider = ? AND provider_event_id = ? "
        "AND julianday(observed_at) <= julianday(?)"
    )
    params: list[object] = [provider, provider_event_id, as_of]
    result: list[_EventState] = []
    for (event_id,) in conn.execute(sql, tuple(params)):
        event = by_id.get(int(event_id))
        if event is not None:
            result.append(event)
    return result


def _resolve_row(
    conn: sqlite3.Connection,
    row: _WorkingRow,
    *,
    events: tuple[_EventState, ...],
    start: str,
    end: str,
    as_of: str,
    source_event_provider: str | None,
    alias_provider: str,
) -> None:
    if row.errors:
        return
    by_id = {event.event_id: event for event in events}
    window_events = tuple(
        event for event in events if _event_in_window(event, start, end)
    )
    source_event_id = row.raw_source_event_id.strip()
    if source_event_id:
        if source_event_provider is None:
            row.errors.append("SOURCE_EVENT_PROVIDER_REQUIRED")
            return
        candidates = _source_id_events(
            conn,
            provider=source_event_provider,
            provider_event_id=source_event_id,
            as_of=as_of,
            by_id=by_id,
        )
        if not candidates:
            row.errors.append("SOURCE_EVENT_ID_UNRESOLVED")
            return
        if len(candidates) > 1:
            row.errors.append("SOURCE_EVENT_ID_AMBIGUOUS")
            return
        event = candidates[0]
        if not _event_in_window(event, start, end):
            row.errors.append("EVENT_OUTSIDE_RESOLUTION_WINDOW")
            return
        exact, reversed_match, _ = _event_orientation(
            conn, row, event, alias_provider, as_of
        )
        if reversed_match and not exact:
            row.errors.append("REVERSED_HOME_AWAY")
            return
        if not exact:
            row.errors.append("TEAM_IDENTITY_CONFLICT")
            return
        if row.sport_hint is not None and row.sport_hint != event.sport_code:
            row.errors.append("SPORT_MISMATCH")
            return
        if (
            row.parsed_kickoff_at is not None
            and row.parsed_kickoff_at != event.kickoff_at
        ):
            row.errors.append("KICKOFF_CONFLICT")
            return
        row.event = event
        row.sport_code = event.sport_code
        row.resolution_method = "PROVIDER_EVENT_ID"
        row.evidence = {
            "provider": source_event_provider,
            "provider_event_id": source_event_id,
        }
    else:
        away_ids = _candidate_team_ids(
            conn,
            raw_name=row.raw_away_team,
            events=window_events,
            sport_hint=row.sport_hint,
            alias_provider=alias_provider,
            as_of=as_of,
        )
        home_ids = _candidate_team_ids(
            conn,
            raw_name=row.raw_home_team,
            events=window_events,
            sport_hint=row.sport_hint,
            alias_provider=alias_provider,
            as_of=as_of,
        )
        if not away_ids or not home_ids:
            row.errors.append("UNKNOWN_TEAM")
            return
        if len(away_ids) > 1 or len(home_ids) > 1:
            row.errors.append("AMBIGUOUS_TEAM")
            return
        exact_candidates: list[tuple[_EventState, str]] = []
        reversed_candidates: list[_EventState] = []
        for event in window_events:
            if row.sport_hint is not None and event.sport_code != row.sport_hint:
                continue
            exact, reversed_match, method = _event_orientation(
                conn, row, event, alias_provider, as_of
            )
            if exact:
                exact_candidates.append((event, method))
            if reversed_match:
                reversed_candidates.append(event)
        if row.parsed_kickoff_at is not None:
            kickoff_candidates = [
                candidate
                for candidate in exact_candidates
                if candidate[0].kickoff_at == row.parsed_kickoff_at
            ]
            if not kickoff_candidates and exact_candidates:
                row.errors.append("KICKOFF_CONFLICT")
                return
            exact_candidates = kickoff_candidates
        if not exact_candidates:
            row.errors.append(
                "REVERSED_HOME_AWAY" if reversed_candidates else "UNRESOLVED_EVENT"
            )
            return
        if len(exact_candidates) > 1:
            row.errors.append(
                "KICKOFF_REQUIRED_FOR_UNIQUE_RESOLUTION"
                if row.parsed_kickoff_at is None
                else "AMBIGUOUS_EVENT"
            )
            return
        event, method = exact_candidates[0]
        row.event = event
        row.sport_code = event.sport_code
        row.resolution_method = method
        row.evidence = {
            "alias_provider": alias_provider,
            "resolution_window_end_at": end,
            "resolution_window_start_at": start,
        }

    if row.event is not None:
        _, _, row.canonical_home_team_name = _team_record(
            conn, row.event.home_team_id
        )
        _, _, row.canonical_away_team_name = _team_record(
            conn, row.event.away_team_id
        )


def _parse_working_row(
    source: SourceRow,
    *,
    header_errors: tuple[str, ...],
) -> _WorkingRow:
    row = _WorkingRow(source=source)
    values = source.values
    row.raw_away_team = values.get("away_team", "")
    row.raw_home_team = values.get("home_team", "")
    row.raw_spread_text = values.get("spread", "")
    row.raw_spread_side = values.get("spread_side", "")
    row.raw_sport_hint = values.get("sport", "")
    row.raw_kickoff = values.get("kickoff", "")
    row.raw_source_event_id = values.get("source_event_id", "")
    row.raw_notes = values.get("notes", "")
    row.errors.extend(header_errors)
    if source.formula_present:
        row.errors.append("FORMULA_CELL_UNTRUSTED")
    if not row.raw_away_team.strip():
        row.errors.append("AWAY_TEAM_MISSING")
    if not row.raw_home_team.strip():
        row.errors.append("HOME_TEAM_MISSING")
    if (
        row.raw_away_team
        and row.raw_home_team
        and row.raw_away_team.strip().casefold()
        == row.raw_home_team.strip().casefold()
    ):
        row.errors.append("HOME_AWAY_IDENTICAL")
    if not row.raw_spread_text.strip():
        row.errors.append("SPREAD_MISSING")
    if not row.raw_spread_side.strip():
        row.errors.append("SPREAD_SIDE_MISSING")
    if not row.errors:
        try:
            spread = normalize_spread(
                row.raw_spread_text,
                row.raw_spread_side,
                row.raw_away_team,
                row.raw_home_team,
            )
            row.normalized_spread_side = spread.normalized_side
            row.displayed_spread_millipoints = spread.displayed_millipoints
            row.home_spread_millipoints = spread.home_millipoints
        except SpreadsheetContractError as exc:
            row.errors.append(str(exc))
    try:
        row.sport_hint = normalize_sport_hint(row.raw_sport_hint)
    except SpreadsheetContractError as exc:
        row.errors.append(str(exc))
    try:
        row.parsed_kickoff_at = normalize_kickoff(row.raw_kickoff)
    except SpreadsheetContractError as exc:
        row.errors.append(str(exc))
    row.errors = sorted(set(row.errors))
    return row


def _mark_duplicates(rows: list[_WorkingRow]) -> None:
    def mark(group: list[_WorkingRow], code: str) -> None:
        if len(group) > 1:
            for item in group:
                item.errors.append(code)

    by_raw_values: dict[tuple[str, ...], list[_WorkingRow]] = {}
    by_matchup: dict[tuple[str, str], list[_WorkingRow]] = {}
    by_source_id: dict[str, list[_WorkingRow]] = {}
    by_event: dict[int, list[_WorkingRow]] = {}
    for row in rows:
        raw_values = tuple(cell.strip() for cell in row.source.raw_cells)
        by_raw_values.setdefault(raw_values, []).append(row)
        raw_matchup = (
            row.raw_away_team.strip().casefold(),
            row.raw_home_team.strip().casefold(),
        )
        by_matchup.setdefault(raw_matchup, []).append(row)
        source_event_id = row.raw_source_event_id.strip()
        if source_event_id:
            by_source_id.setdefault(source_event_id, []).append(row)
        if row.event is not None:
            by_event.setdefault(row.event.event_id, []).append(row)
    for group in by_raw_values.values():
        mark(group, "DUPLICATE_RAW_ROW")
    for group in by_matchup.values():
        if len(group) > 1:
            spreads = {item.home_spread_millipoints for item in group}
            mark(
                group,
                "DUPLICATE_RAW_MATCHUP"
                if len(spreads) == 1
                else "CONFLICTING_RAW_MATCHUP_SPREAD",
            )
    for group in by_source_id.values():
        event_ids = {item.event.event_id for item in group if item.event is not None}
        if len(event_ids) > 1:
            mark(group, "SOURCE_EVENT_ID_CONFLICT")
    for group in by_event.values():
        if len(group) > 1:
            spreads = {item.home_spread_millipoints for item in group}
            mark(group, "DUPLICATE_CANONICAL_EVENT")
            if len(spreads) > 1:
                mark(group, "CONFLICTING_EVENT_SPREAD")
    for row in rows:
        row.errors = sorted(set(row.errors))
        if not row.errors and row.event is not None:
            row.resolution_state = "ACCEPTED"
        elif any(code in _AMBIGUOUS_CODES for code in row.errors):
            row.resolution_state = "AMBIGUOUS"
        elif any("UNRESOLVED" in code or code == "UNKNOWN_TEAM" for code in row.errors):
            row.resolution_state = "UNRESOLVED"
        else:
            row.resolution_state = "REJECTED"


def _canonical_row_payload(row: _WorkingRow) -> dict[str, object]:
    event = row.event
    return {
        "canonical_away_team_id": None if event is None else event.away_team_id,
        "canonical_away_team_name": row.canonical_away_team_name,
        "canonical_event_id": None if event is None else event.event_id,
        "canonical_home_team_id": None if event is None else event.home_team_id,
        "canonical_home_team_name": row.canonical_home_team_name,
        "canonical_kickoff_at": None if event is None else event.kickoff_at,
        "error_codes": row.errors,
        "event_revision_id": None if event is None else event.event_revision_id,
        "home_spread_millipoints": row.home_spread_millipoints,
        "raw_away_team": row.raw_away_team,
        "raw_home_team": row.raw_home_team,
        "raw_spread_side": row.raw_spread_side,
        "raw_spread_text": row.raw_spread_text,
        "resolution_evidence": row.evidence,
        "resolution_method": row.resolution_method,
        "resolution_state": row.resolution_state,
        "source_order": row.source.source_order,
        "source_row_number": row.source.source_row_number,
        "source_row_sha256": row.source.row_sha256,
        "sport_code": row.sport_code,
        "warning_codes": row.warnings,
    }


def _event_evidence_payload(row: _WorkingRow) -> dict[str, object]:
    if row.event is None:
        raise MixedPickemCustodyError("deadline evidence requires an accepted event")
    return {
        "event_id": row.event.event_id,
        "event_revision_id": row.event.event_revision_id,
        "home_team_id": row.event.home_team_id,
        "away_team_id": row.event.away_team_id,
        "kickoff_at": row.event.kickoff_at,
        "source_order": row.source.source_order,
        "sport_code": row.event.sport_code,
    }


def _validate_request(request: ManifestBuildRequest) -> tuple[str, str, str, str, str]:
    try:
        require_key(request.import_key, "import_key")
        actor = require_text(request.actor, "actor")
        provenance = require_text(request.provenance, "provenance")
        alias_provider = require_text(request.alias_provider, "alias_provider")
        received = utc_datetime(request.received_at, "received_at")
        imported = utc_datetime(request.imported_at, "imported_at")
        generated = utc_datetime(request.generated_at, "generated_at")
        start = utc_datetime(
            request.resolution_window_start_at, "resolution_window_start_at"
        )
        end = utc_datetime(
            request.resolution_window_end_at, "resolution_window_end_at"
        )
    except MixedPickemValidationError as exc:
        raise MixedPickemCustodyError(str(exc)) from exc
    if not received <= imported <= generated:
        raise MixedPickemCustodyError(
            "received_at, imported_at, and generated_at must be ordered"
        )
    if start >= end:
        raise MixedPickemCustodyError("resolution window must have positive duration")
    if request.expected_source_row_count is not None:
        _positive_integer(request.expected_source_row_count, "expected_source_row_count")
    source_provider = None
    if request.source_event_provider is not None:
        try:
            source_provider = require_text(
                request.source_event_provider, "source_event_provider"
            )
        except MixedPickemValidationError as exc:
            raise MixedPickemCustodyError(str(exc)) from exc
    return (
        received.isoformat(),
        imported.isoformat(),
        generated.isoformat(),
        start.isoformat(),
        end.isoformat(),
    )


def _insert_import_state(
    conn: sqlite3.Connection,
    *,
    import_id: int,
    sequence: int,
    state: str,
    recorded_at: str,
    actor: str,
    detail: str,
    provenance: str,
    prior_id: int | None,
) -> int:
    cursor = conn.execute(
        "INSERT INTO mixed_slate_import_states "
        "(import_id, sequence, state, supersedes_state_id, recorded_at, actor, "
        "detail, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            import_id,
            sequence,
            state,
            prior_id,
            recorded_at,
            actor,
            detail,
            provenance,
        ),
    )
    return int(cursor.lastrowid)


def build_manifest(
    conn: sqlite3.Connection,
    request: ManifestBuildRequest,
) -> ManifestBuildResult:
    """Custody every row and build a reviewable manifest; never approve or lock."""
    round_id = _positive_integer(request.contest_round_id, "contest_round_id")
    received, imported, generated, start, end = _validate_request(request)
    product_id, season_id, round_id, season_key, round_number = _scope(conn, round_id)
    latest = _latest_round_state(conn, round_id)
    accepts_import = latest is not None and latest[2] in (
        "OPEN", "NEEDS_REVIEW", "AMBIGUOUS", "REJECTED"
    )
    stale_rebuild = (
        latest is not None
        and latest[2] in ("MANIFEST_READY", "OWNER_APPROVED")
        and _stale_manifest_for_round_state(
            conn,
            state_id=latest[0],
            state=latest[2],
            as_of=received,
        )
    )
    if not accepts_import and not stale_rebuild:
        raise MixedPickemCustodyError(
            "contest round cannot accept another import in its current lifecycle state"
        )
    try:
        source = read_source(
            request.source_path,
            media_type=request.media_type,
            worksheet=request.worksheet,
        )
    except SpreadsheetContractError as exc:
        raise MixedPickemCustodyError(str(exc)) from exc

    rows = [
        _parse_working_row(item, header_errors=source.header_errors)
        for item in source.rows
    ]
    events = _effective_events(conn, as_of=generated)
    for row in rows:
        _resolve_row(
            conn,
            row,
            events=events,
            start=start,
            end=end,
            as_of=generated,
            source_event_provider=request.source_event_provider,
            alias_provider=request.alias_provider,
        )
    _mark_duplicates(rows)
    for row in rows:
        row.canonical_row_sha256 = sha256_text(
            canonical_json(_canonical_row_payload(row))
        )

    source_count = len(rows)
    expected_count = request.expected_source_row_count or source_count
    accepted_count = sum(row.resolution_state == "ACCEPTED" for row in rows)
    ambiguous_count = sum(row.resolution_state == "AMBIGUOUS" for row in rows)
    rejected_count = source_count - accepted_count - ambiguous_count
    duplicate_count = sum(
        any(code in _DUPLICATE_CODES for code in row.errors) for row in rows
    )
    count_mismatch = expected_count != source_count
    if ambiguous_count:
        import_status = "AMBIGUOUS"
    elif rejected_count or count_mismatch:
        import_status = "NEEDS_REVIEW"
    else:
        import_status = "RESOLVED"
    manifest_state = (
        "MANIFEST_READY"
        if import_status == "RESOLVED"
        else "AMBIGUOUS"
        if import_status == "AMBIGUOUS"
        else "NEEDS_REVIEW"
    )
    ordered_row_hash = sha256_text(
        canonical_json([row.canonical_row_sha256 for row in rows])
    )
    manifest_payload = {
        "accepted_count": accepted_count,
        "ambiguous_count": ambiguous_count,
        "duplicate_count": duplicate_count,
        "expected_source_row_count": expected_count,
        "lifecycle_state": manifest_state,
        "ordered_canonical_row_set_sha256": ordered_row_hash,
        "parser_version": PARSER_VERSION,
        "product_key": "mixed_pickem",
        "rejected_count": rejected_count,
        "round_number": round_number,
        "rows": [row.canonical_row_sha256 for row in rows],
        "season_key": season_key,
        "source_row_count": source_count,
        "source_sha256": source.source_sha256,
    }
    manifest_sha = sha256_text(canonical_json(manifest_payload))

    try:
        with _atomic(conn):
            cursor = conn.execute(
                "INSERT INTO mixed_slate_imports "
                "(import_key, product_id, contest_season_id, contest_round_id, "
                "source_media_type, original_filename, source_sha256, parser_version, "
                "selected_worksheet, resolution_window_start_at, "
                "resolution_window_end_at, expected_source_row_count, received_at, "
                "imported_at, actor, provenance, overall_status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    request.import_key,
                    product_id,
                    season_id,
                    round_id,
                    source.media_type,
                    source.original_filename,
                    source.source_sha256,
                    PARSER_VERSION,
                    source.selected_worksheet,
                    start,
                    end,
                    request.expected_source_row_count,
                    received,
                    imported,
                    request.actor.strip(),
                    request.provenance.strip(),
                    import_status,
                ),
            )
            import_id = int(cursor.lastrowid)
            import_row_ids: dict[int, int] = {}
            for row in rows:
                parse_state = (
                    "PARSED"
                    if not any(
                        code.startswith(("SPREAD_", "KICKOFF_", "SPORT_HINT_"))
                        or code.endswith(("_MISSING", "_INVALID", "_UNTRUSTED"))
                        or "HEADER" in code
                        for code in row.errors
                    )
                    else "NEEDS_REVIEW"
                )
                raw_cursor = conn.execute(
                    "INSERT INTO mixed_slate_import_rows "
                    "(import_id, source_row_number, source_order, raw_row_json, "
                    "raw_away_team, raw_home_team, raw_spread_text, raw_spread_side, "
                    "normalized_spread_side, parsed_displayed_spread_millipoints, "
                    "raw_sport_hint, raw_kickoff, parsed_kickoff_at, "
                    "raw_source_event_id, raw_notes, row_sha256, parse_state, "
                    "error_codes_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "?, ?, ?, ?, ?, ?)",
                    (
                        import_id,
                        row.source.source_row_number,
                        row.source.source_order,
                        row.source.raw_row_json,
                        row.raw_away_team or None,
                        row.raw_home_team or None,
                        row.raw_spread_text or None,
                        row.raw_spread_side or None,
                        row.normalized_spread_side,
                        row.displayed_spread_millipoints,
                        row.raw_sport_hint or None,
                        row.raw_kickoff or None,
                        row.parsed_kickoff_at,
                        row.raw_source_event_id or None,
                        row.raw_notes or None,
                        row.source.row_sha256,
                        parse_state,
                        canonical_json(row.errors),
                    ),
                )
                import_row_ids[row.source.source_order] = int(raw_cursor.lastrowid)

            state_1 = _insert_import_state(
                conn,
                import_id=import_id,
                sequence=1,
                state="RECEIVED",
                recorded_at=received,
                actor=request.actor,
                detail="Source bytes accepted into immutable custody.",
                provenance=request.provenance,
                prior_id=None,
            )
            state_2 = _insert_import_state(
                conn,
                import_id=import_id,
                sequence=2,
                state="PARSED",
                recorded_at=imported,
                actor=request.actor,
                detail=f"Represented {source_count} nonblank source game row(s).",
                provenance=request.provenance,
                prior_id=state_1,
            )
            _insert_import_state(
                conn,
                import_id=import_id,
                sequence=3,
                state=import_status,
                recorded_at=generated,
                actor=request.actor,
                detail=(
                    f"accepted={accepted_count}; rejected={rejected_count}; "
                    f"ambiguous={ambiguous_count}; duplicates={duplicate_count}"
                ),
                provenance=request.provenance,
                prior_id=state_2,
            )
            _append_round_state(
                conn,
                round_id=round_id,
                state="RECEIVED",
                recorded_at=received,
                actor=request.actor,
                reason="Authoritative weekly source received.",
                provenance=request.provenance,
                import_id=import_id,
            )
            _append_round_state(
                conn,
                round_id=round_id,
                state="PARSED",
                recorded_at=imported,
                actor=request.actor,
                reason="Every nonblank game row entered raw-row custody.",
                provenance=request.provenance,
                import_id=import_id,
            )
            _append_round_state(
                conn,
                round_id=round_id,
                state=import_status,
                recorded_at=generated,
                actor=request.actor,
                reason="Canonical event resolution completed without approval.",
                provenance=request.provenance,
                import_id=import_id,
            )

            manifest_cursor = conn.execute(
                "INSERT INTO mixed_slate_manifests "
                "(import_id, sequence, supersedes_manifest_id, product_id, "
                "contest_season_id, contest_round_id, source_sha256, parser_version, "
                "expected_source_row_count, source_row_count, accepted_count, "
                "rejected_count, ambiguous_count, duplicate_count, "
                "ordered_canonical_row_set_sha256, manifest_sha256, lifecycle_state, "
                "generated_at, provenance) VALUES (?, 1, NULL, ?, ?, ?, ?, ?, ?, ?, "
                "?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    import_id,
                    product_id,
                    season_id,
                    round_id,
                    source.source_sha256,
                    PARSER_VERSION,
                    expected_count,
                    source_count,
                    accepted_count,
                    rejected_count,
                    ambiguous_count,
                    duplicate_count,
                    ordered_row_hash,
                    manifest_sha,
                    manifest_state,
                    generated,
                    request.provenance,
                ),
            )
            manifest_id = int(manifest_cursor.lastrowid)
            manifest_row_ids: dict[int, int] = {}
            for row in rows:
                event = row.event
                manifest_row_cursor = conn.execute(
                    "INSERT INTO mixed_slate_manifest_rows "
                    "(manifest_id, import_row_id, source_order, raw_away_team, "
                    "raw_home_team, raw_spread_text, raw_spread_side, sport_code, "
                    "football_event_id, canonical_home_team_id, canonical_away_team_id, "
                    "canonical_home_team_name, canonical_away_team_name, "
                    "canonical_kickoff_at, event_revision_id, home_spread_millipoints, "
                    "resolution_state, resolution_method, resolution_evidence_json, "
                    "warning_codes_json, error_codes_json, source_row_sha256, "
                    "canonical_row_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        manifest_id,
                        import_row_ids[row.source.source_order],
                        row.source.source_order,
                        row.raw_away_team or None,
                        row.raw_home_team or None,
                        row.raw_spread_text or None,
                        row.raw_spread_side or None,
                        row.sport_code,
                        None if event is None else event.event_id,
                        None if event is None else event.home_team_id,
                        None if event is None else event.away_team_id,
                        row.canonical_home_team_name,
                        row.canonical_away_team_name,
                        None if event is None else event.kickoff_at,
                        None if event is None else event.event_revision_id,
                        row.home_spread_millipoints,
                        row.resolution_state,
                        row.resolution_method,
                        canonical_json(row.evidence),
                        canonical_json(row.warnings),
                        canonical_json(row.errors),
                        row.source.row_sha256,
                        row.canonical_row_sha256,
                    ),
                )
                manifest_row_ids[row.source.source_order] = int(
                    manifest_row_cursor.lastrowid
                )

            deadline_id = None
            event_set_hash = None
            earliest = None
            if manifest_state == "MANIFEST_READY":
                evidence_payloads = [_event_evidence_payload(row) for row in rows]
                event_set_hash = sha256_text(canonical_json(evidence_payloads))
                earliest = min(str(item["kickoff_at"]) for item in evidence_payloads)
                deadline_cursor = conn.execute(
                    "INSERT INTO mixed_deadline_derivations "
                    "(manifest_id, ordered_event_kickoff_set_sha256, "
                    "earliest_kickoff_at, deadline_policy_version, calculated_at, "
                    "actor, provenance) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        manifest_id,
                        event_set_hash,
                        earliest,
                        DEADLINE_POLICY_VERSION,
                        generated,
                        request.actor,
                        request.provenance,
                    ),
                )
                deadline_id = int(deadline_cursor.lastrowid)
                for row, payload in zip(rows, evidence_payloads, strict=True):
                    event = row.event
                    assert event is not None
                    conn.execute(
                        "INSERT INTO mixed_deadline_events "
                        "(deadline_derivation_id, manifest_row_id, source_order, "
                        "football_event_id, sport_code, kickoff_at, event_revision_id, "
                        "evidence_sha256) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            deadline_id,
                            manifest_row_ids[row.source.source_order],
                            row.source.source_order,
                            event.event_id,
                            event.sport_code,
                            event.kickoff_at,
                            event.event_revision_id,
                            sha256_text(canonical_json(payload)),
                        ),
                    )
                _append_round_state(
                    conn,
                    round_id=round_id,
                    state="MANIFEST_READY",
                    recorded_at=generated,
                    actor=request.actor,
                    reason="Complete manifest and earliest-kickoff evidence are ready for review.",
                    provenance=request.provenance,
                    manifest_id=manifest_id,
                )

            review = inspect_manifest(conn, manifest_id)
            return ManifestBuildResult(
                import_id=import_id,
                manifest_id=manifest_id,
                deadline_derivation_id=deadline_id,
                import_status=import_status,
                manifest_state=manifest_state,
                source_row_count=source_count,
                accepted_count=accepted_count,
                rejected_count=rejected_count,
                ambiguous_count=ambiguous_count,
                duplicate_count=duplicate_count,
                source_sha256=source.source_sha256,
                ordered_row_set_sha256=ordered_row_hash,
                manifest_sha256=manifest_sha,
                event_kickoff_set_sha256=event_set_hash,
                earliest_kickoff_at=earliest,
                review=review,
            )
    except sqlite3.IntegrityError as exc:
        raise MixedPickemCustodyError(f"manifest build was rejected: {exc}") from exc


def inspect_manifest(conn: sqlite3.Connection, manifest_id: int) -> dict[str, object]:
    """Return deterministic human-review JSON showing every represented row."""
    manifest_id = _positive_integer(manifest_id, "manifest_id")
    manifest = conn.execute(
        "SELECT manifest.id, product.product_key, season.season_key, round.round_number, "
        "import.original_filename, import.source_media_type, import.selected_worksheet, "
        "manifest.source_sha256, manifest.parser_version, "
        "manifest.expected_source_row_count, manifest.source_row_count, "
        "manifest.accepted_count, manifest.rejected_count, manifest.ambiguous_count, "
        "manifest.duplicate_count, manifest.ordered_canonical_row_set_sha256, "
        "manifest.manifest_sha256, manifest.lifecycle_state, manifest.generated_at "
        "FROM mixed_slate_manifests AS manifest "
        "JOIN mixed_slate_imports AS import ON import.id = manifest.import_id "
        "JOIN mixed_contest_products AS product ON product.id = manifest.product_id "
        "JOIN mixed_contest_seasons AS season ON season.id = manifest.contest_season_id "
        "JOIN mixed_contest_rounds AS round ON round.id = manifest.contest_round_id "
        "WHERE manifest.id = ?",
        (manifest_id,),
    ).fetchone()
    if manifest is None:
        raise MixedPickemCustodyError("manifest does not exist")
    rows = []
    for row in conn.execute(
        "SELECT source.source_row_number, row.source_order, row.raw_away_team, "
        "row.raw_home_team, row.raw_spread_text, row.raw_spread_side, row.sport_code, "
        "row.football_event_id, row.canonical_away_team_name, "
        "row.canonical_home_team_name, row.canonical_kickoff_at, "
        "row.home_spread_millipoints, row.resolution_state, row.resolution_method, "
        "row.resolution_evidence_json, row.warning_codes_json, row.error_codes_json, "
        "row.source_row_sha256, row.canonical_row_sha256 "
        "FROM mixed_slate_manifest_rows AS row "
        "JOIN mixed_slate_import_rows AS source ON source.id = row.import_row_id "
        "WHERE row.manifest_id = ? ORDER BY row.source_order",
        (manifest_id,),
    ):
        rows.append(
            {
                "canonical_away_team": row[8],
                "canonical_event_id": row[7],
                "canonical_home_team": row[9],
                "canonical_kickoff_at": row[10],
                "canonical_row_sha256": row[18],
                "error_codes": json.loads(str(row[16])),
                "home_spread_millipoints": row[11],
                "raw_away_team": row[2],
                "raw_home_team": row[3],
                "raw_spread_side": row[5],
                "raw_spread_text": row[4],
                "resolution_evidence": json.loads(str(row[14])),
                "resolution_method": row[13],
                "resolution_state": row[12],
                "source_order": row[1],
                "source_row_number": row[0],
                "source_row_sha256": row[17],
                "sport_code": row[6],
                "warning_codes": json.loads(str(row[15])),
            }
        )
    deadline = conn.execute(
        "SELECT id, ordered_event_kickoff_set_sha256, earliest_kickoff_at, "
        "deadline_policy_version, calculated_at FROM mixed_deadline_derivations "
        "WHERE manifest_id = ?",
        (manifest_id,),
    ).fetchone()
    return {
        "accepted_count": manifest[11],
        "ambiguous_count": manifest[13],
        "deadline": None
        if deadline is None
        else {
            "calculated_at": deadline[4],
            "deadline_derivation_id": deadline[0],
            "deadline_policy_version": deadline[3],
            "earliest_kickoff_at": deadline[2],
            "ordered_event_kickoff_set_sha256": deadline[1],
        },
        "duplicate_count": manifest[14],
        "expected_source_row_count": manifest[9],
        "generated_at": manifest[18],
        "lifecycle_state": manifest[17],
        "manifest_id": manifest[0],
        "manifest_sha256": manifest[16],
        "ordered_canonical_row_set_sha256": manifest[15],
        "original_filename": manifest[4],
        "parser_version": manifest[8],
        "product_key": manifest[1],
        "rejected_count": manifest[12],
        "round_number": manifest[3],
        "rows": rows,
        "season_key": manifest[2],
        "selected_worksheet": manifest[6],
        "source_media_type": manifest[5],
        "source_row_count": manifest[10],
        "source_sha256": manifest[7],
    }


def _current_event_set_for_manifest(
    conn: sqlite3.Connection,
    manifest_id: int,
    as_of: str,
) -> tuple[str, list[dict[str, object]]]:
    states = {event.event_id: event for event in _effective_events(conn, as_of=as_of)}
    payloads: list[dict[str, object]] = []
    rows = conn.execute(
        "SELECT source_order, football_event_id FROM mixed_slate_manifest_rows "
        "WHERE manifest_id = ? AND resolution_state = 'ACCEPTED' ORDER BY source_order",
        (manifest_id,),
    ).fetchall()
    for source_order, event_id in rows:
        event = states.get(int(event_id))
        if event is None:
            raise MixedPickemCustodyError("approved event is unavailable at the requested as_of")
        payloads.append(
            {
                "event_id": event.event_id,
                "event_revision_id": event.event_revision_id,
                "home_team_id": event.home_team_id,
                "away_team_id": event.away_team_id,
                "kickoff_at": event.kickoff_at,
                "source_order": int(source_order),
                "sport_code": event.sport_code,
            }
        )
    return sha256_text(canonical_json(payloads)), payloads


def approve_manifest(
    conn: sqlite3.Connection,
    *,
    manifest_id: int,
    approval_key: str,
    expected_source_sha256: str,
    expected_manifest_sha256: str,
    expected_row_count: int,
    reviewer: str,
    approved_at: datetime,
    provenance: str,
) -> ApprovalResult:
    """Bind immutable owner approval to one exact complete, current manifest."""
    manifest_id = _positive_integer(manifest_id, "manifest_id")
    expected_row_count = _positive_integer(expected_row_count, "expected_row_count")
    try:
        approval_key = require_key(approval_key, "approval_key")
        expected_source_sha256 = require_sha256(
            expected_source_sha256, "expected_source_sha256"
        )
        expected_manifest_sha256 = require_sha256(
            expected_manifest_sha256, "expected_manifest_sha256"
        )
        reviewer = require_text(reviewer, "reviewer")
        provenance = require_text(provenance, "provenance")
        approved = utc_text(approved_at, "approved_at")
    except MixedPickemValidationError as exc:
        raise MixedPickemCustodyError(str(exc)) from exc
    row = conn.execute(
        "SELECT manifest.product_id, manifest.contest_season_id, "
        "manifest.contest_round_id, manifest.source_sha256, manifest.manifest_sha256, "
        "manifest.source_row_count, manifest.lifecycle_state, deadline.id, "
        "deadline.ordered_event_kickoff_set_sha256, deadline.earliest_kickoff_at "
        "FROM mixed_slate_manifests AS manifest "
        "LEFT JOIN mixed_deadline_derivations AS deadline "
        "ON deadline.manifest_id = manifest.id WHERE manifest.id = ?",
        (manifest_id,),
    ).fetchone()
    if row is None or row[7] is None:
        raise MixedPickemCustodyError("manifest is not deadline-complete")
    if row[6] != "MANIFEST_READY":
        raise MixedPickemCustodyError("manifest is not ready for owner approval")
    if (row[3], row[4], int(row[5])) != (
        expected_source_sha256,
        expected_manifest_sha256,
        expected_row_count,
    ):
        raise MixedPickemCustodyError("approval checksum or row count does not match")
    current_hash, _ = _current_event_set_for_manifest(conn, manifest_id, approved)
    if current_hash != row[8]:
        raise MixedPickemCustodyError(
            "deadline derivation is stale after canonical event correction"
        )
    if datetime.fromisoformat(approved) >= datetime.fromisoformat(str(row[9])):
        raise MixedPickemCustodyError("manifest approval must precede the earliest kickoff")
    try:
        with _atomic(conn):
            cursor = conn.execute(
                "INSERT INTO mixed_slate_approvals "
                "(approval_key, manifest_id, deadline_derivation_id, product_id, "
                "contest_season_id, contest_round_id, source_sha256, manifest_sha256, "
                "event_kickoff_set_sha256, approved_row_count, reviewer, approved_at, "
                "provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    approval_key,
                    manifest_id,
                    int(row[7]),
                    int(row[0]),
                    int(row[1]),
                    int(row[2]),
                    expected_source_sha256,
                    expected_manifest_sha256,
                    current_hash,
                    expected_row_count,
                    reviewer,
                    approved,
                    provenance,
                ),
            )
            approval_id = int(cursor.lastrowid)
            _append_round_state(
                conn,
                round_id=int(row[2]),
                state="OWNER_APPROVED",
                recorded_at=approved,
                actor=reviewer,
                reason="Owner approved the exact complete manifest checksums and row count.",
                provenance=provenance,
                approval_id=approval_id,
            )
            return ApprovalResult(
                approval_id=approval_id,
                manifest_id=manifest_id,
                deadline_derivation_id=int(row[7]),
                manifest_sha256=expected_manifest_sha256,
                approved_row_count=expected_row_count,
                approved_at=approved,
            )
    except sqlite3.IntegrityError as exc:
        raise MixedPickemCustodyError(f"manifest approval was rejected: {exc}") from exc


def _line_payload(
    *,
    product_key: str,
    season_key: str,
    round_number: int,
    row: sqlite3.Row | tuple[object, ...],
    source_sha256: str,
    manifest_sha256: str,
    locked_at: str,
) -> dict[str, object]:
    return {
        "canonical_away_team_id": row[8],
        "canonical_away_team_name": row[10],
        "canonical_event_id": row[5],
        "canonical_home_team_id": row[7],
        "canonical_home_team_name": row[9],
        "home_spread_millipoints": row[13],
        "locked_at": locked_at,
        "manifest_sha256": manifest_sha256,
        "product_key": product_key,
        "raw_away_team": row[2],
        "raw_home_team": row[3],
        "raw_spread_text": row[12],
        "round_number": round_number,
        "season_key": season_key,
        "source_order": row[0],
        "source_row_sha256": row[14],
        "source_sha256": source_sha256,
        "sport_code": row[6],
    }


def lock_approved_manifest(
    conn: sqlite3.Connection,
    *,
    approval_id: int,
    lock_key: str,
    expected_manifest_sha256: str,
    expected_line_count: int,
    actor: str,
    locked_at: datetime,
    provenance: str,
    lock_policy_version: str = LOCK_POLICY_VERSION,
) -> LockResult:
    """Atomically lock every approved row or roll back the entire batch."""
    approval_id = _positive_integer(approval_id, "approval_id")
    expected_line_count = _positive_integer(expected_line_count, "expected_line_count")
    try:
        lock_key = require_key(lock_key, "lock_key")
        expected_manifest_sha256 = require_sha256(
            expected_manifest_sha256, "expected_manifest_sha256"
        )
        actor = require_text(actor, "actor")
        provenance = require_text(provenance, "provenance")
        lock_policy_version = require_text(lock_policy_version, "lock_policy_version")
        locked = utc_text(locked_at, "locked_at")
    except MixedPickemValidationError as exc:
        raise MixedPickemCustodyError(str(exc)) from exc
    approval = conn.execute(
        "SELECT approval.manifest_id, approval.product_id, "
        "approval.contest_season_id, approval.contest_round_id, "
        "approval.source_sha256, approval.manifest_sha256, "
        "approval.event_kickoff_set_sha256, approval.approved_row_count, "
        "approval.approved_at, deadline.earliest_kickoff_at, product.product_key, "
        "season.season_key, round.round_number "
        "FROM mixed_slate_approvals AS approval "
        "JOIN mixed_deadline_derivations AS deadline "
        "ON deadline.id = approval.deadline_derivation_id "
        "JOIN mixed_contest_products AS product ON product.id = approval.product_id "
        "JOIN mixed_contest_seasons AS season ON season.id = approval.contest_season_id "
        "JOIN mixed_contest_rounds AS round ON round.id = approval.contest_round_id "
        "WHERE approval.id = ?",
        (approval_id,),
    ).fetchone()
    if approval is None:
        raise MixedPickemCustodyError("approval does not exist")
    if (approval[5], int(approval[7])) != (
        expected_manifest_sha256,
        expected_line_count,
    ):
        raise MixedPickemCustodyError("lock checksum or expected line count does not match")
    if datetime.fromisoformat(locked) < datetime.fromisoformat(str(approval[8])):
        raise MixedPickemCustodyError("line lock cannot precede owner approval")
    if datetime.fromisoformat(locked) >= datetime.fromisoformat(str(approval[9])):
        raise MixedPickemCustodyError("line lock must complete before the earliest kickoff")
    current_hash, _ = _current_event_set_for_manifest(
        conn, int(approval[0]), locked
    )
    if current_hash != approval[6]:
        raise MixedPickemCustodyError(
            "deadline derivation is stale after canonical event correction"
        )
    manifest_rows = conn.execute(
        "SELECT row.source_order, row.import_row_id, row.raw_away_team, "
        "row.raw_home_team, row.id, row.football_event_id, row.sport_code, "
        "row.canonical_home_team_id, row.canonical_away_team_id, "
        "row.canonical_home_team_name, row.canonical_away_team_name, "
        "row.canonical_kickoff_at, row.raw_spread_text, "
        "row.home_spread_millipoints, row.source_row_sha256 "
        "FROM mixed_slate_manifest_rows AS row "
        "WHERE row.manifest_id = ? AND row.resolution_state = 'ACCEPTED' "
        "ORDER BY row.source_order",
        (int(approval[0]),),
    ).fetchall()
    if len(manifest_rows) != expected_line_count:
        raise MixedPickemCustodyError("approved manifest row count changed")
    line_payloads = [
        _line_payload(
            product_key=str(approval[10]),
            season_key=str(approval[11]),
            round_number=int(approval[12]),
            row=row,
            source_sha256=str(approval[4]),
            manifest_sha256=str(approval[5]),
            locked_at=locked,
        )
        for row in manifest_rows
    ]
    line_hashes = [sha256_text(canonical_json(payload)) for payload in line_payloads]
    line_set_hash = sha256_text(canonical_json(line_hashes))
    try:
        with _atomic(conn):
            batch_cursor = conn.execute(
                "INSERT INTO mixed_line_lock_batches "
                "(lock_key, approval_id, product_id, contest_season_id, "
                "contest_round_id, expected_line_count, locked_line_count, "
                "ordered_line_set_sha256, locked_at, actor, lock_policy_version, "
                "provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    lock_key,
                    approval_id,
                    int(approval[1]),
                    int(approval[2]),
                    int(approval[3]),
                    expected_line_count,
                    expected_line_count,
                    line_set_hash,
                    locked,
                    actor,
                    lock_policy_version,
                    provenance,
                ),
            )
            batch_id = int(batch_cursor.lastrowid)
            for row, line_hash in zip(manifest_rows, line_hashes, strict=True):
                conn.execute(
                    "INSERT INTO mixed_contest_lines "
                    "(lock_batch_id, product_id, contest_round_id, football_event_id, "
                    "sport_code, import_row_id, manifest_row_id, raw_away_team, "
                    "raw_home_team, canonical_away_team_id, canonical_home_team_id, "
                    "canonical_away_team_name, canonical_home_team_name, "
                    "raw_spread_text, home_spread_millipoints, locked_at, "
                    "source_sha256, source_row_sha256, manifest_sha256, line_sha256, "
                    "provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "?, ?, ?, ?, ?, ?, ?)",
                    (
                        batch_id,
                        int(approval[1]),
                        int(approval[3]),
                        int(row[5]),
                        str(row[6]),
                        int(row[1]),
                        int(row[4]),
                        str(row[2]),
                        str(row[3]),
                        int(row[8]),
                        int(row[7]),
                        str(row[10]),
                        str(row[9]),
                        str(row[12]),
                        int(row[13]),
                        locked,
                        str(approval[4]),
                        str(row[14]),
                        str(approval[5]),
                        line_hash,
                        provenance,
                    ),
                )
            persisted_hashes = [
                item[0]
                for item in conn.execute(
                    "SELECT line.line_sha256 FROM mixed_contest_lines AS line "
                    "JOIN mixed_slate_manifest_rows AS row "
                    "ON row.id = line.manifest_row_id "
                    "WHERE line.lock_batch_id = ? ORDER BY row.source_order",
                    (batch_id,),
                )
            ]
            if sha256_text(canonical_json(persisted_hashes)) != line_set_hash:
                raise MixedPickemCustodyError("persisted line-set hash differs")
            completion_cursor = conn.execute(
                "INSERT INTO mixed_line_lock_completions "
                "(lock_batch_id, line_count, ordered_line_set_sha256, completed_at, "
                "actor, provenance) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    expected_line_count,
                    line_set_hash,
                    locked,
                    actor,
                    provenance,
                ),
            )
            completion_id = int(completion_cursor.lastrowid)
            _append_round_state(
                conn,
                round_id=int(approval[3]),
                state="LOCKED",
                recorded_at=locked,
                actor=actor,
                reason="Every owner-approved manifest row was atomically locked.",
                provenance=provenance,
                lock_completion_id=completion_id,
            )
            return LockResult(
                lock_batch_id=batch_id,
                completion_id=completion_id,
                contest_round_id=int(approval[3]),
                line_count=expected_line_count,
                ordered_line_set_sha256=line_set_hash,
                locked_at=locked,
            )
    except sqlite3.IntegrityError as exc:
        raise MixedPickemCustodyError(f"atomic line lock was rejected: {exc}") from exc
