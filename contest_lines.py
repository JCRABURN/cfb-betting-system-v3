"""Transactional service for immutable contest-line locks and corrections.

Market opening/current/closing lines remain in ``betting_lines``. Contest
lines are locked exactly once in ``contest_locked_lines``. A correction never
updates that row; it appends a complete replacement snapshot to
``contest_line_corrections`` so the original and every superseded value remain
auditable.
"""

from __future__ import annotations

import itertools
import math
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator


_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")
_UNSET = object()
_SAVEPOINT_IDS = itertools.count(1)


class ContestLineError(RuntimeError):
    """Base error for invalid or conflicting contest-line operations."""


class ContestConflictError(ContestLineError):
    """Raised when an immutable contest definition conflicts with an existing one."""


class LineAlreadyLockedError(ContestLineError):
    """Raised when a matchup is relocked with different data."""


class LineCorrectionError(ContestLineError):
    """Raised when a requested correction is invalid or has no effect."""


@dataclass(frozen=True)
class Contest:
    id: int
    contest_key: str
    name: str
    season: int
    week: int
    source: str
    source_contest_id: str | None
    provenance: str
    created_at: str


@dataclass(frozen=True)
class LockedContestLine:
    id: int
    contest_id: int
    game_id: int | None
    season: int
    week: int
    raw_home_team: str
    raw_away_team: str
    normalized_home_team: str
    normalized_away_team: str
    home_spread: float
    total: float | None
    locked_at: str
    source: str
    source_line_id: str | None
    provenance: str
    payload_sha256: str


@dataclass(frozen=True)
class LockResult:
    line: LockedContestLine
    created: bool


@dataclass(frozen=True)
class ContestLineCorrection:
    id: int
    locked_line_id: int
    sequence: int
    supersedes_correction_id: int | None
    game_id: int | None
    raw_home_team: str
    raw_away_team: str
    normalized_home_team: str
    normalized_away_team: str
    home_spread: float
    total: float | None
    reason: str
    author: str
    corrected_at: str
    source: str
    source_line_id: str | None
    provenance: str
    payload_sha256: str


@dataclass(frozen=True)
class EffectiveContestLine:
    locked_line_id: int
    contest_id: int
    game_id: int | None
    season: int
    week: int
    raw_home_team: str
    raw_away_team: str
    normalized_home_team: str
    normalized_away_team: str
    home_spread: float
    total: float | None
    original_locked_at: str
    effective_at: str
    correction_id: int | None
    correction_sequence: int | None
    source: str
    source_line_id: str | None
    provenance: str
    payload_sha256: str


_CONTEST_COLUMNS = (
    "id, contest_key, name, season, week, source, source_contest_id, "
    "provenance, created_at"
)
_LOCKED_LINE_COLUMNS = (
    "id, contest_id, game_id, season, week, raw_home_team, raw_away_team, "
    "normalized_home_team, normalized_away_team, home_spread, total, locked_at, "
    "source, source_line_id, provenance, payload_sha256"
)
_CORRECTION_COLUMNS = (
    "id, locked_line_id, sequence, supersedes_correction_id, game_id, "
    "raw_home_team, raw_away_team, normalized_home_team, normalized_away_team, "
    "home_spread, total, reason, author, corrected_at, source, source_line_id, "
    "provenance, payload_sha256"
)


@contextmanager
def _atomic(conn: sqlite3.Connection) -> Iterator[None]:
    name = f"contest_lines_{next(_SAVEPOINT_IDS)}"
    conn.execute(f"SAVEPOINT {name}")
    try:
        yield
    except Exception:
        conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
        conn.execute(f"RELEASE SAVEPOINT {name}")
        raise
    else:
        conn.execute(f"RELEASE SAVEPOINT {name}")


def _required_text(value: str, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContestLineError(f"{field} must be non-empty text")
    return value


def _optional_text(value: str | None, field: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field)


def _integer(value: int, field: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ContestLineError(f"{field} must be an integer greater than or equal to {minimum}")
    return value


def _optional_game_id(value: int | None) -> int | None:
    if value is None:
        return None
    return _integer(value, "game_id", 1)


def _number(value: float | int, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContestLineError(f"{field} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ContestLineError(f"{field} must be a finite number")
    return result


def _optional_total(value: float | int | None) -> float | None:
    if value is None:
        return None
    result = _number(value, "total")
    if result < 0:
        raise ContestLineError("total must be greater than or equal to zero")
    return result


def _payload_checksum(value: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise ContestLineError("payload_sha256 must be exactly 64 hexadecimal characters")
    return value.lower()


def _utc_timestamp(value: datetime | None, field: str) -> str:
    moment = value or datetime.now(timezone.utc)
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise ContestLineError(f"{field} must be a timezone-aware datetime")
    return moment.astimezone(timezone.utc).isoformat()


def _validate_teams(
    raw_home_team: str,
    raw_away_team: str,
    normalized_home_team: str,
    normalized_away_team: str,
) -> tuple[str, str, str, str]:
    values = (
        _required_text(raw_home_team, "raw_home_team"),
        _required_text(raw_away_team, "raw_away_team"),
        _required_text(normalized_home_team, "normalized_home_team"),
        _required_text(normalized_away_team, "normalized_away_team"),
    )
    if values[2].strip().casefold() == values[3].strip().casefold():
        raise ContestLineError("normalized home and away teams must be different")
    return values


def _assert_game_matches(
    conn: sqlite3.Connection,
    game_id: int | None,
    season: int,
    week: int,
    normalized_home_team: str,
    normalized_away_team: str,
) -> None:
    if game_id is None:
        return
    row = conn.execute(
        "SELECT season, week, home_team, away_team FROM games WHERE game_id = ?",
        (game_id,),
    ).fetchone()
    expected = (season, week, normalized_home_team, normalized_away_team)
    if row != expected:
        raise ContestLineError(
            "game_id does not match the contest season, week, and normalized teams"
        )


def _contest_from_row(row: tuple[object, ...] | None) -> Contest | None:
    return Contest(*row) if row is not None else None


def _locked_line_from_row(row: tuple[object, ...] | None) -> LockedContestLine | None:
    return LockedContestLine(*row) if row is not None else None


def _correction_from_row(row: tuple[object, ...] | None) -> ContestLineCorrection | None:
    return ContestLineCorrection(*row) if row is not None else None


def get_contest(conn: sqlite3.Connection, contest_id: int) -> Contest:
    row = conn.execute(
        f"SELECT {_CONTEST_COLUMNS} FROM contests WHERE id = ?", (contest_id,)
    ).fetchone()
    contest = _contest_from_row(row)
    if contest is None:
        raise ContestLineError(f"contest does not exist: {contest_id}")
    return contest


def create_contest(
    conn: sqlite3.Connection,
    *,
    contest_key: str,
    name: str,
    season: int,
    week: int,
    source: str,
    provenance: str,
    source_contest_id: str | None = None,
    created_at: datetime | None = None,
) -> Contest:
    """Create an immutable weekly contest, or return an identical prior record."""
    contest_key = _required_text(contest_key, "contest_key")
    name = _required_text(name, "name")
    season = _integer(season, "season", 1869)
    week = _integer(week, "week", 0)
    source = _required_text(source, "source")
    provenance = _required_text(provenance, "provenance")
    source_contest_id = _optional_text(source_contest_id, "source_contest_id")
    created_at_value = _utc_timestamp(created_at, "created_at")

    try:
        with _atomic(conn):
            row = conn.execute(
                f"SELECT {_CONTEST_COLUMNS} FROM contests "
                "WHERE contest_key = ? AND season = ? AND week = ?",
                (contest_key, season, week),
            ).fetchone()
            existing = _contest_from_row(row)
            if existing is not None:
                immutable_values = (
                    existing.name,
                    existing.source,
                    existing.source_contest_id,
                    existing.provenance,
                )
                requested_values = (name, source, source_contest_id, provenance)
                if immutable_values != requested_values:
                    raise ContestConflictError(
                        "contest already exists with different immutable metadata"
                    )
                return existing

            cursor = conn.execute(
                "INSERT INTO contests "
                "(contest_key, name, season, week, source, source_contest_id, "
                "provenance, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    contest_key,
                    name,
                    season,
                    week,
                    source,
                    source_contest_id,
                    provenance,
                    created_at_value,
                ),
            )
            return get_contest(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise ContestConflictError(f"contest conflicts with an existing record: {exc}") from exc


def get_original_locked_line(
    conn: sqlite3.Connection, locked_line_id: int
) -> LockedContestLine:
    row = conn.execute(
        f"SELECT {_LOCKED_LINE_COLUMNS} FROM contest_locked_lines WHERE id = ?",
        (locked_line_id,),
    ).fetchone()
    line = _locked_line_from_row(row)
    if line is None:
        raise ContestLineError(f"locked contest line does not exist: {locked_line_id}")
    return line


def _find_matchup_lock(
    conn: sqlite3.Connection,
    contest_id: int,
    game_id: int | None,
    normalized_home_team: str,
    normalized_away_team: str,
) -> LockedContestLine | None:
    row = conn.execute(
        f"SELECT {_LOCKED_LINE_COLUMNS} FROM contest_locked_lines "
        "WHERE contest_id = ? AND ("
        "(? IS NOT NULL AND game_id = ?) OR ("
        "min(lower(trim(normalized_home_team)), lower(trim(normalized_away_team))) = "
        "min(lower(trim(?)), lower(trim(?))) AND "
        "max(lower(trim(normalized_home_team)), lower(trim(normalized_away_team))) = "
        "max(lower(trim(?)), lower(trim(?)))"
        ")) ORDER BY id LIMIT 1",
        (
            contest_id,
            game_id,
            game_id,
            normalized_home_team,
            normalized_away_team,
            normalized_home_team,
            normalized_away_team,
        ),
    ).fetchone()
    return _locked_line_from_row(row)


def lock_contest_line(
    conn: sqlite3.Connection,
    *,
    contest_id: int,
    raw_home_team: str,
    raw_away_team: str,
    normalized_home_team: str,
    normalized_away_team: str,
    home_spread: float | int,
    source: str,
    provenance: str,
    payload_sha256: str,
    game_id: int | None = None,
    total: float | int | None = None,
    source_line_id: str | None = None,
    locked_at: datetime | None = None,
) -> LockResult:
    """Lock one contest matchup once; an identical replay is idempotent."""
    contest_id = _integer(contest_id, "contest_id", 1)
    game_id = _optional_game_id(game_id)
    teams = _validate_teams(
        raw_home_team,
        raw_away_team,
        normalized_home_team,
        normalized_away_team,
    )
    home_spread = _number(home_spread, "home_spread")
    total = _optional_total(total)
    source = _required_text(source, "source")
    source_line_id = _optional_text(source_line_id, "source_line_id")
    provenance = _required_text(provenance, "provenance")
    payload_sha256 = _payload_checksum(payload_sha256)
    locked_at_value = _utc_timestamp(locked_at, "locked_at")

    try:
        with _atomic(conn):
            contest = get_contest(conn, contest_id)
            _assert_game_matches(
                conn, game_id, contest.season, contest.week, teams[2], teams[3]
            )
            existing = _find_matchup_lock(
                conn, contest_id, game_id, teams[2], teams[3]
            )
            if existing is not None:
                existing_values = (
                    existing.game_id,
                    existing.raw_home_team,
                    existing.raw_away_team,
                    existing.normalized_home_team,
                    existing.normalized_away_team,
                    existing.home_spread,
                    existing.total,
                    existing.source,
                    existing.source_line_id,
                    existing.provenance,
                    existing.payload_sha256,
                )
                requested_values = (
                    game_id,
                    *teams,
                    home_spread,
                    total,
                    source,
                    source_line_id,
                    provenance,
                    payload_sha256,
                )
                if existing_values == requested_values:
                    return LockResult(line=existing, created=False)
                raise LineAlreadyLockedError(
                    f"contest matchup is already locked as line {existing.id}; "
                    "record a correction instead"
                )

            cursor = conn.execute(
                "INSERT INTO contest_locked_lines "
                "(contest_id, game_id, season, week, raw_home_team, raw_away_team, "
                "normalized_home_team, normalized_away_team, home_spread, total, "
                "locked_at, source, source_line_id, provenance, payload_sha256) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    contest_id,
                    game_id,
                    contest.season,
                    contest.week,
                    *teams,
                    home_spread,
                    total,
                    locked_at_value,
                    source,
                    source_line_id,
                    provenance,
                    payload_sha256,
                ),
            )
            return LockResult(
                line=get_original_locked_line(conn, cursor.lastrowid), created=True
            )
    except sqlite3.IntegrityError as exc:
        raise LineAlreadyLockedError(f"contest line could not be locked: {exc}") from exc


def list_line_corrections(
    conn: sqlite3.Connection, locked_line_id: int
) -> tuple[ContestLineCorrection, ...]:
    rows = conn.execute(
        f"SELECT {_CORRECTION_COLUMNS} FROM contest_line_corrections "
        "WHERE locked_line_id = ? ORDER BY sequence",
        (locked_line_id,),
    ).fetchall()
    return tuple(ContestLineCorrection(*row) for row in rows)


def _latest_correction(
    conn: sqlite3.Connection, locked_line_id: int
) -> ContestLineCorrection | None:
    row = conn.execute(
        f"SELECT {_CORRECTION_COLUMNS} FROM contest_line_corrections "
        "WHERE locked_line_id = ? ORDER BY sequence DESC LIMIT 1",
        (locked_line_id,),
    ).fetchone()
    return _correction_from_row(row)


def _effective_line(
    original: LockedContestLine,
    correction: ContestLineCorrection | None,
) -> EffectiveContestLine:
    if correction is None:
        return EffectiveContestLine(
            locked_line_id=original.id,
            contest_id=original.contest_id,
            game_id=original.game_id,
            season=original.season,
            week=original.week,
            raw_home_team=original.raw_home_team,
            raw_away_team=original.raw_away_team,
            normalized_home_team=original.normalized_home_team,
            normalized_away_team=original.normalized_away_team,
            home_spread=original.home_spread,
            total=original.total,
            original_locked_at=original.locked_at,
            effective_at=original.locked_at,
            correction_id=None,
            correction_sequence=None,
            source=original.source,
            source_line_id=original.source_line_id,
            provenance=original.provenance,
            payload_sha256=original.payload_sha256,
        )
    return EffectiveContestLine(
        locked_line_id=original.id,
        contest_id=original.contest_id,
        game_id=correction.game_id,
        season=original.season,
        week=original.week,
        raw_home_team=correction.raw_home_team,
        raw_away_team=correction.raw_away_team,
        normalized_home_team=correction.normalized_home_team,
        normalized_away_team=correction.normalized_away_team,
        home_spread=correction.home_spread,
        total=correction.total,
        original_locked_at=original.locked_at,
        effective_at=correction.corrected_at,
        correction_id=correction.id,
        correction_sequence=correction.sequence,
        source=correction.source,
        source_line_id=correction.source_line_id,
        provenance=correction.provenance,
        payload_sha256=correction.payload_sha256,
    )


def get_effective_locked_line(
    conn: sqlite3.Connection, locked_line_id: int
) -> EffectiveContestLine:
    """Return the latest effective value while preserving the original lock."""
    original = get_original_locked_line(conn, locked_line_id)
    return _effective_line(original, _latest_correction(conn, locked_line_id))


def get_effective_locked_line_as_of(
    conn: sqlite3.Connection,
    locked_line_id: int,
    as_of: datetime,
) -> EffectiveContestLine:
    """Return the line state visible at one UTC instant, without lookahead."""
    as_of_value = _utc_timestamp(as_of, "as_of")
    original = get_original_locked_line(conn, locked_line_id)
    visible = conn.execute(
        "SELECT julianday(?) >= julianday(?)",
        (as_of_value, original.locked_at),
    ).fetchone()
    if visible is None or visible[0] != 1:
        raise ContestLineError(
            f"locked contest line {locked_line_id} was not available at as_of"
        )
    row = conn.execute(
        f"SELECT {_CORRECTION_COLUMNS} FROM contest_line_corrections "
        "WHERE locked_line_id = ? AND julianday(corrected_at) <= julianday(?) "
        "ORDER BY sequence DESC LIMIT 1",
        (locked_line_id, as_of_value),
    ).fetchone()
    return _effective_line(original, _correction_from_row(row))


def list_effective_locked_lines(
    conn: sqlite3.Connection,
    contest_id: int,
    *,
    as_of: datetime | None = None,
) -> tuple[EffectiveContestLine, ...]:
    """List every contest line in stable order, optionally point-in-time."""
    contest_id = _integer(contest_id, "contest_id", 1)
    get_contest(conn, contest_id)
    as_of_value = _utc_timestamp(as_of, "as_of") if as_of is not None else None
    line_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM contest_locked_lines WHERE contest_id = ? "
            "AND (? IS NULL OR julianday(locked_at) <= julianday(?)) ORDER BY id",
            (contest_id, as_of_value, as_of_value),
        )
    ]
    if as_of is None:
        return tuple(get_effective_locked_line(conn, line_id) for line_id in line_ids)
    return tuple(
        get_effective_locked_line_as_of(conn, line_id, as_of)
        for line_id in line_ids
    )


def correct_locked_line(
    conn: sqlite3.Connection,
    locked_line_id: int,
    *,
    reason: str,
    author: str,
    source: str,
    provenance: str,
    payload_sha256: str,
    source_line_id: str | None = None,
    corrected_at: datetime | None = None,
    game_id: int | None | object = _UNSET,
    raw_home_team: str | object = _UNSET,
    raw_away_team: str | object = _UNSET,
    normalized_home_team: str | object = _UNSET,
    normalized_away_team: str | object = _UNSET,
    home_spread: float | int | object = _UNSET,
    total: float | int | None | object = _UNSET,
) -> ContestLineCorrection:
    """Append a full corrected snapshot without changing the original lock."""
    locked_line_id = _integer(locked_line_id, "locked_line_id", 1)
    reason = _required_text(reason, "reason")
    author = _required_text(author, "author")
    source = _required_text(source, "source")
    provenance = _required_text(provenance, "provenance")
    payload_sha256 = _payload_checksum(payload_sha256)
    source_line_id = _optional_text(source_line_id, "source_line_id")
    corrected_at_value = _utc_timestamp(corrected_at, "corrected_at")

    try:
        with _atomic(conn):
            original = get_original_locked_line(conn, locked_line_id)
            latest = _latest_correction(conn, locked_line_id)
            base = latest or original

            corrected_game_id = (
                base.game_id if game_id is _UNSET else _optional_game_id(game_id)
            )
            corrected_teams = _validate_teams(
                base.raw_home_team if raw_home_team is _UNSET else raw_home_team,
                base.raw_away_team if raw_away_team is _UNSET else raw_away_team,
                base.normalized_home_team
                if normalized_home_team is _UNSET
                else normalized_home_team,
                base.normalized_away_team
                if normalized_away_team is _UNSET
                else normalized_away_team,
            )
            corrected_spread = (
                base.home_spread
                if home_spread is _UNSET
                else _number(home_spread, "home_spread")
            )
            corrected_total = (
                base.total if total is _UNSET else _optional_total(total)
            )
            before = (
                base.game_id,
                base.raw_home_team,
                base.raw_away_team,
                base.normalized_home_team,
                base.normalized_away_team,
                base.home_spread,
                base.total,
            )
            after = (
                corrected_game_id,
                *corrected_teams,
                corrected_spread,
                corrected_total,
            )
            if before == after:
                raise LineCorrectionError("correction must change at least one line field")

            prior_timestamp = latest.corrected_at if latest is not None else original.locked_at
            if datetime.fromisoformat(corrected_at_value) <= datetime.fromisoformat(
                prior_timestamp
            ):
                raise LineCorrectionError(
                    "correction timestamp must follow the prior recorded value"
                )

            _assert_game_matches(
                conn,
                corrected_game_id,
                original.season,
                original.week,
                corrected_teams[2],
                corrected_teams[3],
            )
            sequence = 1 if latest is None else latest.sequence + 1
            supersedes_id = None if latest is None else latest.id
            cursor = conn.execute(
                "INSERT INTO contest_line_corrections "
                "(locked_line_id, sequence, supersedes_correction_id, game_id, "
                "raw_home_team, raw_away_team, normalized_home_team, "
                "normalized_away_team, home_spread, total, reason, author, "
                "corrected_at, source, source_line_id, provenance, payload_sha256) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    locked_line_id,
                    sequence,
                    supersedes_id,
                    corrected_game_id,
                    *corrected_teams,
                    corrected_spread,
                    corrected_total,
                    reason,
                    author,
                    corrected_at_value,
                    source,
                    source_line_id,
                    provenance,
                    payload_sha256,
                ),
            )
            row = conn.execute(
                f"SELECT {_CORRECTION_COLUMNS} FROM contest_line_corrections WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            correction = _correction_from_row(row)
            if correction is None:  # pragma: no cover - guarded by the insert above
                raise LineCorrectionError("correction insert did not return a record")
            return correction
    except sqlite3.IntegrityError as exc:
        raise LineCorrectionError(f"contest line correction was rejected: {exc}") from exc
