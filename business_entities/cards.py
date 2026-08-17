"""Typed append-only storage for contest-card snapshots and selections."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from contest_lines import get_contest, get_effective_locked_line_as_of

from business_entities.common import (
    SHA256,
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    checksum,
    choice,
    integer,
    optional_integer,
    optional_text,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)
from business_entities.modeling import get_model_prediction, get_model_run


@dataclass(frozen=True)
class ContestCard:
    id: int
    card_key: str
    contest_id: int
    model_run_id: int | None
    version: int
    status: str
    policy_version: str
    locked_line_snapshot_sha256: str
    generated_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class ContestPick:
    id: int
    pick_key: str
    card_id: int
    locked_line_id: int
    model_prediction_id: int | None
    selected_side: str
    confidence: int | None
    rank: int | None
    is_top_five: bool
    fallback_code: str | None
    generated_at: str
    provenance: str


@dataclass(frozen=True)
class CardRevision:
    id: int
    revision_key: str
    prior_card_id: int
    revised_card_id: int
    change_type: str
    reason: str
    author: str
    revised_at: str
    provenance: str


_CARD_COLUMNS = (
    "id, card_key, contest_id, model_run_id, version, status, policy_version, "
    "locked_line_snapshot_sha256, generated_at, created_by, provenance"
)
_PICK_COLUMNS = (
    "id, pick_key, card_id, locked_line_id, model_prediction_id, selected_side, "
    "confidence, rank, is_top_five, fallback_code, generated_at, provenance"
)
_REVISION_COLUMNS = (
    "id, revision_key, prior_card_id, revised_card_id, change_type, reason, "
    "author, revised_at, provenance"
)


def get_contest_card(conn: sqlite3.Connection, card_id: int) -> ContestCard:
    row = conn.execute(
        f"SELECT {_CARD_COLUMNS} FROM contest_cards WHERE id = ?", (card_id,)
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"contest card does not exist: {card_id}")
    return ContestCard(*row)


def create_contest_card(
    conn: sqlite3.Connection,
    *,
    card_key: str,
    contest_id: int,
    version: int,
    status: str,
    policy_version: str,
    locked_line_snapshot_sha256: str,
    created_by: str,
    provenance: str,
    model_run_id: int | None = None,
    generated_at: datetime | None = None,
) -> ContestCard:
    """Create one immutable card snapshot; changes require a new version."""
    card_key = required_text(card_key, "card_key")
    contest_id = integer(contest_id, "contest_id", 1)
    model_run_id = optional_integer(model_run_id, "model_run_id", 1)
    version = integer(version, "version", 1)
    status = choice(status, "status", ("draft", "official"))
    if status == "official":
        raise BusinessEntityError(
            "official cards require the validated publication service"
        )
    values = (
        contest_id,
        model_run_id,
        version,
        status,
        required_text(policy_version, "policy_version"),
        checksum(
            locked_line_snapshot_sha256,
            "locked_line_snapshot_sha256",
            SHA256,
        ),
        required_text(created_by, "created_by"),
        required_text(provenance, "provenance"),
    )
    generated_at_value = utc_timestamp(generated_at, "generated_at")

    try:
        with atomic(conn):
            get_contest(conn, contest_id)
            if (
                model_run_id is not None
                and get_model_run(conn, model_run_id).status != "completed"
            ):
                raise BusinessEntityError("contest cards require a completed model run")
            row = conn.execute(
                f"SELECT {_CARD_COLUMNS} FROM contest_cards "
                "WHERE card_key = ? OR (contest_id = ? AND version = ?) "
                "ORDER BY card_key = ? DESC LIMIT 1",
                (card_key, contest_id, version, card_key),
            ).fetchone()
            requested = (card_key, *values)
            if row is not None:
                existing = ContestCard(*row)
                recorded = (
                    existing.card_key,
                    existing.contest_id,
                    existing.model_run_id,
                    existing.version,
                    existing.status,
                    existing.policy_version,
                    existing.locked_line_snapshot_sha256,
                    existing.created_by,
                    existing.provenance,
                )
                if recorded != requested:
                    raise BusinessEntityConflictError(
                        "card key or contest/version already has different immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO contest_cards "
                "(card_key, contest_id, model_run_id, version, status, policy_version, "
                "locked_line_snapshot_sha256, generated_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*requested[:7], generated_at_value, *requested[7:]),
            )
            return get_contest_card(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("contest card", exc) from exc


def get_contest_pick(conn: sqlite3.Connection, pick_id: int) -> ContestPick:
    row = conn.execute(
        f"SELECT {_PICK_COLUMNS} FROM contest_picks WHERE id = ?", (pick_id,)
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"contest pick does not exist: {pick_id}")
    values = list(row)
    values[8] = bool(values[8])
    return ContestPick(*values)


def list_contest_picks(
    conn: sqlite3.Connection, card_id: int
) -> tuple[ContestPick, ...]:
    """Return a card's immutable selections in locked-line order."""
    rows = conn.execute(
        f"SELECT {_PICK_COLUMNS} FROM contest_picks "
        "WHERE card_id = ? ORDER BY locked_line_id, id",
        (card_id,),
    ).fetchall()
    picks: list[ContestPick] = []
    for row in rows:
        values = list(row)
        values[8] = bool(values[8])
        picks.append(ContestPick(*values))
    return tuple(picks)


def add_contest_pick(
    conn: sqlite3.Connection,
    *,
    pick_key: str,
    card_id: int,
    locked_line_id: int,
    selected_side: str,
    provenance: str,
    model_prediction_id: int | None = None,
    confidence: int | None = None,
    rank: int | None = None,
    is_top_five: bool = False,
    fallback_code: str | None = None,
    generated_at: datetime | None = None,
) -> ContestPick:
    """Add one contest selection without creating sportsbook advice."""
    pick_key = required_text(pick_key, "pick_key")
    card_id = integer(card_id, "card_id", 1)
    locked_line_id = integer(locked_line_id, "locked_line_id", 1)
    model_prediction_id = optional_integer(
        model_prediction_id, "model_prediction_id", 1
    )
    selected_side = choice(selected_side, "selected_side", ("home", "away", "pass"))
    confidence = optional_integer(confidence, "confidence", 1)
    if confidence is not None and confidence > 5:
        raise BusinessEntityError("confidence cannot exceed 5")
    rank = optional_integer(rank, "rank", 1)
    if not isinstance(is_top_five, bool):
        raise BusinessEntityError("is_top_five must be boolean")
    fallback_code = optional_text(fallback_code, "fallback_code")
    provenance = required_text(provenance, "provenance")
    if selected_side == "pass" and (
        confidence is not None or rank is not None or is_top_five
    ):
        raise BusinessEntityError("pass selections cannot be ranked or assigned confidence")
    if model_prediction_id is None and fallback_code is None:
        raise BusinessEntityError("picks without a model prediction require fallback_code")
    if (
        model_prediction_id is not None
        and fallback_code is not None
        and fallback_code not in ("model_tie_home", "model_tie_away")
    ):
        raise BusinessEntityError(
            "model-backed picks may use only an explicit model-tie fallback"
        )
    generated_at_value = utc_timestamp(generated_at, "generated_at")
    generated_at_moment = datetime.fromisoformat(generated_at_value)

    try:
        with atomic(conn):
            card = get_contest_card(conn, card_id)
            line = get_effective_locked_line_as_of(
                conn, locked_line_id, generated_at_moment
            )
            if line.contest_id != card.contest_id:
                raise BusinessEntityError("locked line does not belong to the card contest")
            if not timestamp_on_or_before(conn, line.effective_at, generated_at_value):
                raise BusinessEntityError(
                    "locked line must be effective before pick generation"
                )
            if model_prediction_id is not None:
                prediction = get_model_prediction(conn, model_prediction_id)
                if line.game_id is None or prediction.game_id != line.game_id:
                    raise BusinessEntityError(
                        "model prediction and locked line must identify the same game"
                    )
                if card.model_run_id is not None and prediction.model_run_id != card.model_run_id:
                    raise BusinessEntityError(
                        "model prediction must come from the card model run"
                    )
            row = conn.execute(
                f"SELECT {_PICK_COLUMNS} FROM contest_picks "
                "WHERE pick_key = ? OR (card_id = ? AND locked_line_id = ?) "
                "ORDER BY pick_key = ? DESC LIMIT 1",
                (pick_key, card_id, locked_line_id, pick_key),
            ).fetchone()
            requested = (
                pick_key,
                card_id,
                locked_line_id,
                model_prediction_id,
                selected_side,
                confidence,
                rank,
                is_top_five,
                fallback_code,
                provenance,
            )
            if row is not None:
                existing = get_contest_pick(conn, row[0])
                recorded = (
                    existing.pick_key,
                    existing.card_id,
                    existing.locked_line_id,
                    existing.model_prediction_id,
                    existing.selected_side,
                    existing.confidence,
                    existing.rank,
                    existing.is_top_five,
                    existing.fallback_code,
                    existing.provenance,
                )
                if recorded != requested:
                    raise BusinessEntityConflictError(
                        "pick key or card/line already has different immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO contest_picks "
                "(pick_key, card_id, locked_line_id, model_prediction_id, selected_side, "
                "confidence, rank, is_top_five, fallback_code, generated_at, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*requested[:9], generated_at_value, provenance),
            )
            return get_contest_pick(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("contest pick", exc) from exc


def get_card_revision(conn: sqlite3.Connection, revision_id: int) -> CardRevision:
    row = conn.execute(
        f"SELECT {_REVISION_COLUMNS} FROM card_revisions WHERE id = ?",
        (revision_id,),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"card revision does not exist: {revision_id}")
    return CardRevision(*row)


def record_card_revision(
    conn: sqlite3.Connection,
    *,
    revision_key: str,
    prior_card_id: int,
    revised_card_id: int,
    change_type: str,
    reason: str,
    author: str,
    provenance: str,
    revised_at: datetime | None = None,
) -> CardRevision:
    """Link consecutive immutable card snapshots with an explicit reason."""
    revision_key = required_text(revision_key, "revision_key")
    prior_card_id = integer(prior_card_id, "prior_card_id", 1)
    revised_card_id = integer(revised_card_id, "revised_card_id", 1)
    values = (
        prior_card_id,
        revised_card_id,
        choice(
            change_type,
            "change_type",
            ("data_refresh", "contextual_adjustment", "bug_fix", "data_correction"),
        ),
        required_text(reason, "reason"),
        required_text(author, "author"),
    )
    provenance = required_text(provenance, "provenance")
    revised_at_value = (
        utc_timestamp(revised_at, "revised_at")
        if revised_at is not None
        else None
    )
    try:
        with atomic(conn):
            prior = get_contest_card(conn, prior_card_id)
            revised = get_contest_card(conn, revised_card_id)
            if prior.contest_id != revised.contest_id or revised.version != prior.version + 1:
                raise BusinessEntityError(
                    "card revision must link consecutive versions of one contest"
                )
            row = conn.execute(
                f"SELECT {_REVISION_COLUMNS} FROM card_revisions "
                "WHERE revision_key = ? OR revised_card_id = ? "
                "ORDER BY revision_key = ? DESC LIMIT 1",
                (revision_key, revised_card_id, revision_key),
            ).fetchone()
            if row is not None:
                existing = CardRevision(*row)
                requested = (
                    revision_key,
                    *values,
                    revised_at_value or existing.revised_at,
                    provenance,
                )
                recorded = (
                    existing.revision_key,
                    existing.prior_card_id,
                    existing.revised_card_id,
                    existing.change_type,
                    existing.reason,
                    existing.author,
                    existing.revised_at,
                    existing.provenance,
                )
                if recorded != requested:
                    raise BusinessEntityConflictError(
                        "revision key or revised card already has different "
                        "immutable values"
                    )
                return existing
            requested = (
                revision_key,
                *values,
                revised_at_value or utc_timestamp(None, "revised_at"),
                provenance,
            )
            cursor = conn.execute(
                "INSERT INTO card_revisions "
                "(revision_key, prior_card_id, revised_card_id, change_type, reason, "
                "author, revised_at, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            return get_card_revision(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("card revision", exc) from exc
