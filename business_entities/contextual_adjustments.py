"""Versioned application of sourced manual context to immutable predictions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, astuple, dataclass
from datetime import datetime

from business_entities.adjustments import ManualAdjustment, list_manual_adjustments
from business_entities.cards import ContestPick, get_contest_card, get_contest_pick
from business_entities.common import (
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    integer,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)
from business_entities.modeling import ModelPrediction, get_model_prediction


MARGIN_METHOD = "additive_home_margin"
CONFIDENCE_METHOD = "additive_clamped_1_5"
CONFIDENCE_MIN = 1
CONFIDENCE_MAX = 5


@dataclass(frozen=True)
class ManualAdjustmentPolicy:
    policy_version: str
    effective_at: datetime
    created_by: str
    provenance: str


@dataclass(frozen=True)
class RecordedManualAdjustmentPolicy:
    id: int
    policy_version: str
    margin_method: str
    confidence_method: str
    confidence_min: int
    confidence_max: int
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class CardAdjustmentPolicyAssignment:
    card_id: int
    adjustment_policy_id: int
    assigned_at: str
    provenance: str


@dataclass(frozen=True)
class AdjustmentImpact:
    model_prediction: ModelPrediction
    adjustments: tuple[ManualAdjustment, ...]
    margin_adjustment_total: float
    adjusted_model_margin: float
    confidence_adjustment_total: int
    adjustment_history_sha256: str


@dataclass(frozen=True)
class PickAdjustmentItem:
    contest_pick_id: int
    adjustment_id: int
    history_order: int


@dataclass(frozen=True)
class PickAdjustmentSnapshot:
    contest_pick_id: int
    adjustment_policy_id: int
    model_prediction_id: int
    raw_model_margin: float
    margin_adjustment_total: float
    adjusted_model_margin: float
    raw_confidence: int
    confidence_adjustment_total: int
    adjusted_confidence: int
    adjustment_count: int
    adjustment_history_sha256: str
    generated_at: str
    provenance: str


_POLICY_COLUMNS = (
    "id, policy_version, margin_method, confidence_method, confidence_min, "
    "confidence_max, effective_at, created_by, provenance"
)
_ASSIGNMENT_COLUMNS = (
    "card_id, adjustment_policy_id, assigned_at, provenance"
)
_ITEM_COLUMNS = "contest_pick_id, adjustment_id, history_order"
_SNAPSHOT_COLUMNS = (
    "contest_pick_id, adjustment_policy_id, model_prediction_id, raw_model_margin, "
    "margin_adjustment_total, adjusted_model_margin, raw_confidence, "
    "confidence_adjustment_total, adjusted_confidence, adjustment_count, "
    "adjustment_history_sha256, generated_at, provenance"
)
_QUALIFIED_SNAPSHOT_COLUMNS = ", ".join(
    f"snapshot.{column.strip()}" for column in _SNAPSHOT_COLUMNS.split(",")
)


def validate_manual_adjustment_policy(
    policy: ManualAdjustmentPolicy,
) -> ManualAdjustmentPolicy:
    if not isinstance(policy, ManualAdjustmentPolicy):
        raise BusinessEntityError(
            "adjustment_policy must be a ManualAdjustmentPolicy"
        )
    return ManualAdjustmentPolicy(
        policy_version=required_text(
            policy.policy_version, "adjustment_policy.policy_version"
        ),
        effective_at=datetime.fromisoformat(
            utc_timestamp(policy.effective_at, "adjustment_policy.effective_at")
        ),
        created_by=required_text(
            policy.created_by, "adjustment_policy.created_by"
        ),
        provenance=required_text(
            policy.provenance, "adjustment_policy.provenance"
        ),
    )


def get_manual_adjustment_policy(
    conn: sqlite3.Connection, adjustment_policy_id: int
) -> RecordedManualAdjustmentPolicy:
    row = conn.execute(
        f"SELECT {_POLICY_COLUMNS} FROM manual_adjustment_policies WHERE id = ?",
        (integer(adjustment_policy_id, "adjustment_policy_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"manual adjustment policy does not exist: {adjustment_policy_id}"
        )
    return RecordedManualAdjustmentPolicy(*row)


def register_manual_adjustment_policy(
    conn: sqlite3.Connection, policy: ManualAdjustmentPolicy
) -> RecordedManualAdjustmentPolicy:
    policy = validate_manual_adjustment_policy(policy)
    requested = (
        policy.policy_version,
        MARGIN_METHOD,
        CONFIDENCE_METHOD,
        CONFIDENCE_MIN,
        CONFIDENCE_MAX,
        policy.effective_at.isoformat(),
        policy.created_by,
        policy.provenance,
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM manual_adjustment_policies "
                "WHERE policy_version = ?",
                (policy.policy_version,),
            ).fetchone()
            if row is not None:
                existing = RecordedManualAdjustmentPolicy(*row)
                if tuple(row[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "manual adjustment policy version has different immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO manual_adjustment_policies "
                "(policy_version, margin_method, confidence_method, confidence_min, "
                "confidence_max, effective_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            return get_manual_adjustment_policy(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("manual adjustment policy", exc) from exc


def recorded_manual_adjustment_policy_matches(
    recorded: RecordedManualAdjustmentPolicy,
    requested: ManualAdjustmentPolicy,
) -> bool:
    requested = validate_manual_adjustment_policy(requested)
    return (
        recorded.policy_version,
        recorded.margin_method,
        recorded.confidence_method,
        recorded.confidence_min,
        recorded.confidence_max,
        recorded.effective_at,
        recorded.created_by,
        recorded.provenance,
    ) == (
        requested.policy_version,
        MARGIN_METHOD,
        CONFIDENCE_METHOD,
        CONFIDENCE_MIN,
        CONFIDENCE_MAX,
        requested.effective_at.isoformat(),
        requested.created_by,
        requested.provenance,
    )


def get_card_adjustment_policy_assignment(
    conn: sqlite3.Connection, card_id: int
) -> CardAdjustmentPolicyAssignment:
    row = conn.execute(
        f"SELECT {_ASSIGNMENT_COLUMNS} FROM card_adjustment_policy_assignments "
        "WHERE card_id = ?",
        (integer(card_id, "card_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"contest card has no manual adjustment policy: {card_id}"
        )
    return CardAdjustmentPolicyAssignment(*row)


def get_card_adjustment_policy(
    conn: sqlite3.Connection, card_id: int
) -> RecordedManualAdjustmentPolicy:
    assignment = get_card_adjustment_policy_assignment(conn, card_id)
    return get_manual_adjustment_policy(conn, assignment.adjustment_policy_id)


def adjustment_policy_from_card(
    conn: sqlite3.Connection, card_id: int
) -> ManualAdjustmentPolicy:
    recorded = get_card_adjustment_policy(conn, card_id)
    return ManualAdjustmentPolicy(
        policy_version=recorded.policy_version,
        effective_at=datetime.fromisoformat(recorded.effective_at),
        created_by=recorded.created_by,
        provenance=recorded.provenance,
    )


def assign_card_adjustment_policy(
    conn: sqlite3.Connection,
    *,
    card_id: int,
    adjustment_policy_id: int,
    assigned_at: datetime,
    provenance: str,
) -> CardAdjustmentPolicyAssignment:
    card_id = integer(card_id, "card_id", 1)
    adjustment_policy_id = integer(
        adjustment_policy_id, "adjustment_policy_id", 1
    )
    assigned_at_value = utc_timestamp(assigned_at, "assigned_at")
    provenance = required_text(provenance, "provenance")
    requested = (
        card_id,
        adjustment_policy_id,
        assigned_at_value,
        provenance,
    )
    try:
        with atomic(conn):
            card = get_contest_card(conn, card_id)
            policy = get_manual_adjustment_policy(conn, adjustment_policy_id)
            if assigned_at_value != card.generated_at or not timestamp_on_or_before(
                conn, policy.effective_at, card.generated_at
            ):
                raise BusinessEntityError(
                    "card adjustment policy must be effective at generation"
                )
            row = conn.execute(
                f"SELECT {_ASSIGNMENT_COLUMNS} "
                "FROM card_adjustment_policy_assignments WHERE card_id = ?",
                (card_id,),
            ).fetchone()
            if row is not None:
                existing = CardAdjustmentPolicyAssignment(*row)
                if tuple(row) != requested:
                    raise BusinessEntityConflictError(
                        "card already has a different adjustment policy"
                    )
                return existing
            conn.execute(
                "INSERT INTO card_adjustment_policy_assignments "
                "(card_id, adjustment_policy_id, assigned_at, provenance) "
                "VALUES (?, ?, ?, ?)",
                requested,
            )
            return get_card_adjustment_policy_assignment(conn, card_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("card adjustment policy assignment", exc) from exc


def adjustment_history_sha256(
    adjustments: tuple[ManualAdjustment, ...],
) -> str:
    canonical = json.dumps(
        [asdict(adjustment) for adjustment in adjustments],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def adjustment_impact(
    conn: sqlite3.Connection,
    *,
    model_prediction_id: int,
    as_of: datetime | str,
) -> AdjustmentImpact:
    prediction = get_model_prediction(
        conn, integer(model_prediction_id, "model_prediction_id", 1)
    )
    if isinstance(as_of, datetime):
        as_of_value = utc_timestamp(as_of, "as_of")
    else:
        try:
            as_of_datetime = datetime.fromisoformat(required_text(as_of, "as_of"))
        except ValueError as exc:
            raise BusinessEntityError(
                "as_of must be a timezone-aware datetime"
            ) from exc
        as_of_value = utc_timestamp(as_of_datetime, "as_of")
    adjustments = tuple(
        adjustment
        for adjustment in list_manual_adjustments(conn, prediction.id)
        if timestamp_on_or_before(conn, adjustment.recorded_at, as_of_value)
    )
    margin_total = sum(
        adjustment.margin_adjustment for adjustment in adjustments
    )
    confidence_total = sum(
        adjustment.confidence_adjustment for adjustment in adjustments
    )
    return AdjustmentImpact(
        model_prediction=prediction,
        adjustments=adjustments,
        margin_adjustment_total=margin_total,
        adjusted_model_margin=prediction.predicted_home_margin + margin_total,
        confidence_adjustment_total=confidence_total,
        adjustment_history_sha256=adjustment_history_sha256(adjustments),
    )


def adjusted_confidence(raw_confidence: int, adjustment_total: int) -> int:
    raw_confidence = integer(raw_confidence, "raw_confidence", CONFIDENCE_MIN)
    adjustment_total = integer(adjustment_total, "adjustment_total")
    if raw_confidence > CONFIDENCE_MAX:
        raise BusinessEntityError("raw_confidence must be between 1 and 5")
    return max(
        CONFIDENCE_MIN,
        min(CONFIDENCE_MAX, raw_confidence + adjustment_total),
    )


def get_pick_adjustment_snapshot(
    conn: sqlite3.Connection, contest_pick_id: int
) -> PickAdjustmentSnapshot:
    row = conn.execute(
        f"SELECT {_SNAPSHOT_COLUMNS} FROM contest_pick_adjustment_snapshots "
        "WHERE contest_pick_id = ?",
        (integer(contest_pick_id, "contest_pick_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"contest pick has no adjustment snapshot: {contest_pick_id}"
        )
    return PickAdjustmentSnapshot(*row)


def list_pick_adjustment_items(
    conn: sqlite3.Connection, contest_pick_id: int
) -> tuple[PickAdjustmentItem, ...]:
    rows = conn.execute(
        f"SELECT {_ITEM_COLUMNS} FROM contest_pick_adjustment_items "
        "WHERE contest_pick_id = ? ORDER BY history_order",
        (integer(contest_pick_id, "contest_pick_id", 1),),
    ).fetchall()
    return tuple(PickAdjustmentItem(*row) for row in rows)


def list_card_adjustment_snapshots(
    conn: sqlite3.Connection, card_id: int
) -> tuple[PickAdjustmentSnapshot, ...]:
    rows = conn.execute(
        f"SELECT {_QUALIFIED_SNAPSHOT_COLUMNS} "
        "FROM contest_pick_adjustment_snapshots AS snapshot "
        "JOIN contest_picks AS pick ON pick.id = snapshot.contest_pick_id "
        "WHERE pick.card_id = ? ORDER BY pick.locked_line_id",
        (integer(card_id, "card_id", 1),),
    ).fetchall()
    return tuple(PickAdjustmentSnapshot(*row) for row in rows)


def _snapshot_values(
    pick: ContestPick,
    policy_id: int,
    raw_confidence: int,
    impact: AdjustmentImpact,
    provenance: str,
) -> tuple[object, ...]:
    final_confidence = adjusted_confidence(
        raw_confidence, impact.confidence_adjustment_total
    )
    return (
        pick.id,
        policy_id,
        impact.model_prediction.id,
        impact.model_prediction.predicted_home_margin,
        impact.margin_adjustment_total,
        impact.adjusted_model_margin,
        raw_confidence,
        impact.confidence_adjustment_total,
        final_confidence,
        len(impact.adjustments),
        impact.adjustment_history_sha256,
        pick.generated_at,
        provenance,
    )


def record_pick_adjustment_snapshot(
    conn: sqlite3.Connection,
    *,
    contest_pick_id: int,
    raw_confidence: int,
    provenance: str,
) -> PickAdjustmentSnapshot:
    pick = get_contest_pick(
        conn, integer(contest_pick_id, "contest_pick_id", 1)
    )
    if pick.model_prediction_id is None:
        raise BusinessEntityError(
            "adjustment snapshots require a model-backed contest pick"
        )
    assignment = get_card_adjustment_policy_assignment(conn, pick.card_id)
    impact = adjustment_impact(
        conn,
        model_prediction_id=pick.model_prediction_id,
        as_of=pick.generated_at,
    )
    provenance = required_text(provenance, "provenance")
    requested = _snapshot_values(
        pick,
        assignment.adjustment_policy_id,
        raw_confidence,
        impact,
        provenance,
    )
    if pick.confidence != requested[8]:
        raise BusinessEntityError(
            "pick Confidence does not match the contextual adjustment ledger"
        )
    try:
        with atomic(conn):
            existing_row = conn.execute(
                f"SELECT {_SNAPSHOT_COLUMNS} "
                "FROM contest_pick_adjustment_snapshots WHERE contest_pick_id = ?",
                (pick.id,),
            ).fetchone()
            if existing_row is not None:
                if tuple(existing_row) != requested:
                    raise BusinessEntityConflictError(
                        "pick adjustment snapshot has different immutable values"
                    )
                return PickAdjustmentSnapshot(*existing_row)
            for adjustment in impact.adjustments:
                item = (pick.id, adjustment.id, adjustment.sequence)
                row = conn.execute(
                    f"SELECT {_ITEM_COLUMNS} FROM contest_pick_adjustment_items "
                    "WHERE contest_pick_id = ? AND "
                    "(adjustment_id = ? OR history_order = ?)",
                    item,
                ).fetchone()
                if row is not None:
                    if tuple(row) != item:
                        raise BusinessEntityConflictError(
                            "pick adjustment item has different immutable values"
                        )
                    continue
                conn.execute(
                    "INSERT INTO contest_pick_adjustment_items "
                    "(contest_pick_id, adjustment_id, history_order) "
                    "VALUES (?, ?, ?)",
                    item,
                )
            conn.execute(
                "INSERT INTO contest_pick_adjustment_snapshots "
                f"({_SNAPSHOT_COLUMNS}) VALUES "
                f"({', '.join('?' for _ in requested)})",
                requested,
            )
            return get_pick_adjustment_snapshot(conn, pick.id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("pick adjustment snapshot", exc) from exc


def pick_adjustment_snapshot_matches(
    conn: sqlite3.Connection,
    *,
    pick: ContestPick,
    raw_confidence: int,
    policy: ManualAdjustmentPolicy,
) -> bool:
    try:
        recorded_policy = get_card_adjustment_policy(conn, pick.card_id)
        snapshot = get_pick_adjustment_snapshot(conn, pick.id)
        assignment = get_card_adjustment_policy_assignment(conn, pick.card_id)
        impact = adjustment_impact(
            conn,
            model_prediction_id=pick.model_prediction_id,
            as_of=pick.generated_at,
        )
        expected = _snapshot_values(
            pick,
            assignment.adjustment_policy_id,
            raw_confidence,
            impact,
            snapshot.provenance,
        )
        items = list_pick_adjustment_items(conn, pick.id)
        expected_items = tuple(
            PickAdjustmentItem(pick.id, item.id, item.sequence)
            for item in impact.adjustments
        )
        return (
            recorded_manual_adjustment_policy_matches(recorded_policy, policy)
            and astuple(snapshot) == expected
            and items == expected_items
        )
    except (BusinessEntityError, sqlite3.DatabaseError, ValueError):
        return False
