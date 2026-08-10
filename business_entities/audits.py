"""Append-only outcome audits for contest picks."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from business_entities.cards import get_contest_pick
from business_entities.common import (
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    choice,
    integer,
    optional_integer,
    optional_number,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)


@dataclass(frozen=True)
class PickAudit:
    id: int
    audit_key: str
    contest_pick_id: int
    sequence: int
    supersedes_audit_id: int | None
    audit_status: str
    result: str
    final_home_points: int | None
    final_away_points: int | None
    closing_market_line_id: int | None
    clv_points: float | None
    policy_version: str
    source: str
    audited_at: str
    provenance: str


_COLUMNS = (
    "id, audit_key, contest_pick_id, sequence, supersedes_audit_id, audit_status, "
    "result, final_home_points, final_away_points, closing_market_line_id, "
    "clv_points, policy_version, source, audited_at, provenance"
)


def get_pick_audit(conn: sqlite3.Connection, audit_id: int) -> PickAudit:
    row = conn.execute(
        f"SELECT {_COLUMNS} FROM pick_audits WHERE id = ?", (audit_id,)
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"pick audit does not exist: {audit_id}")
    return PickAudit(*row)


def list_pick_audits(
    conn: sqlite3.Connection, contest_pick_id: int
) -> tuple[PickAudit, ...]:
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM pick_audits "
        "WHERE contest_pick_id = ? ORDER BY sequence",
        (contest_pick_id,),
    ).fetchall()
    return tuple(PickAudit(*row) for row in rows)


def record_pick_audit(
    conn: sqlite3.Connection,
    *,
    audit_key: str,
    contest_pick_id: int,
    audit_status: str,
    result: str,
    policy_version: str,
    source: str,
    provenance: str,
    final_home_points: int | None = None,
    final_away_points: int | None = None,
    closing_market_line_id: int | None = None,
    clv_points: float | int | None = None,
    audited_at: datetime | None = None,
) -> PickAudit:
    """Append an audit state; corrections supersede rather than overwrite."""
    audit_key = required_text(audit_key, "audit_key")
    contest_pick_id = integer(contest_pick_id, "contest_pick_id", 1)
    audit_status = choice(audit_status, "audit_status", ("pending", "final"))
    result = choice(result, "result", ("pending", "win", "loss", "push"))
    final_home_points = optional_integer(final_home_points, "final_home_points", 0)
    final_away_points = optional_integer(final_away_points, "final_away_points", 0)
    closing_market_line_id = optional_integer(
        closing_market_line_id, "closing_market_line_id", 1
    )
    clv_points = optional_number(clv_points, "clv_points")
    policy_version = required_text(policy_version, "policy_version")
    source = required_text(source, "source")
    provenance = required_text(provenance, "provenance")
    if audit_status == "pending" and (
        result != "pending" or final_home_points is not None or final_away_points is not None
    ):
        raise BusinessEntityError("pending audits cannot contain a result or final score")
    if audit_status == "final" and (
        result == "pending" or final_home_points is None or final_away_points is None
    ):
        raise BusinessEntityError("final audits require a result and both final scores")
    audited_at_value = utc_timestamp(audited_at, "audited_at")

    try:
        with atomic(conn):
            pick = get_contest_pick(conn, contest_pick_id)
            if closing_market_line_id is not None:
                if pick.model_prediction_id is None:
                    raise BusinessEntityError(
                        "closing market lines require a model-backed contest pick"
                    )
                row = conn.execute(
                    "SELECT line.game_id, prediction.game_id, line.line_type, line.fetched_at "
                    "FROM betting_lines AS line, model_predictions AS prediction "
                    "WHERE line.id = ? AND prediction.id = ?",
                    (closing_market_line_id, pick.model_prediction_id),
                ).fetchone()
                if row is None or row[0] != row[1]:
                    raise BusinessEntityError(
                        "closing market line and contest pick must refer to one game"
                    )
                if row[2] != "closing":
                    raise BusinessEntityError(
                        "pick audits require a closing market line"
                    )
                if not timestamp_on_or_before(conn, row[3], audited_at_value):
                    raise BusinessEntityError(
                        "closing market line must be captured before the audit"
                    )
            row = conn.execute(
                f"SELECT {_COLUMNS} FROM pick_audits WHERE audit_key = ?",
                (audit_key,),
            ).fetchone()
            if row is not None:
                existing = PickAudit(*row)
                requested_existing = (
                    audit_key,
                    contest_pick_id,
                    existing.sequence,
                    existing.supersedes_audit_id,
                    audit_status,
                    result,
                    final_home_points,
                    final_away_points,
                    closing_market_line_id,
                    clv_points,
                    policy_version,
                    source,
                    provenance,
                )
                recorded = (
                    existing.audit_key,
                    existing.contest_pick_id,
                    existing.sequence,
                    existing.supersedes_audit_id,
                    existing.audit_status,
                    existing.result,
                    existing.final_home_points,
                    existing.final_away_points,
                    existing.closing_market_line_id,
                    existing.clv_points,
                    existing.policy_version,
                    existing.source,
                    existing.provenance,
                )
                if recorded != requested_existing:
                    raise BusinessEntityConflictError(
                        "audit key already has different immutable values"
                    )
                return existing
            latest = conn.execute(
                "SELECT id, sequence FROM pick_audits "
                "WHERE contest_pick_id = ? ORDER BY sequence DESC LIMIT 1",
                (contest_pick_id,),
            ).fetchone()
            supersedes_id = latest[0] if latest is not None else None
            sequence = latest[1] + 1 if latest is not None else 1
            cursor = conn.execute(
                "INSERT INTO pick_audits "
                "(audit_key, contest_pick_id, sequence, supersedes_audit_id, "
                "audit_status, result, final_home_points, final_away_points, "
                "closing_market_line_id, clv_points, policy_version, source, "
                "audited_at, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    audit_key,
                    contest_pick_id,
                    sequence,
                    supersedes_id,
                    audit_status,
                    result,
                    final_home_points,
                    final_away_points,
                    closing_market_line_id,
                    clv_points,
                    policy_version,
                    source,
                    audited_at_value,
                    provenance,
                ),
            )
            return get_pick_audit(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("pick audit", exc) from exc
