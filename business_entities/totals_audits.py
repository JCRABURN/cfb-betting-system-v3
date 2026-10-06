"""Complete immutable postgame audits for every shadow totals candidate."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from collections.abc import Mapping

from business_entities.common import (
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    choice,
    integer,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)
from business_entities.totals import get_total_shadow_card_result


GRADING_METHOD = "locked_total_comparison_v1"
CLV_METHOD = "selected_total_locked_to_close_v1"
PROJECTION_ERROR_METHOD = "projection_minus_actual_v1"
CONTEXT_EVIDENCE_METHOD = "explicit_evidence_only_v1"
_CONTEXT_STATUSES = ("not_evaluated", "observed", "not_observed")
_FAILURE_CODES = (
    "not_evaluated",
    "no_failure",
    "model_projection_failure",
    "pace_failure",
    "matchup_failure",
    "game_script_failure",
    "quarterback_failure",
    "offensive_line_failure",
    "defensive_personnel_failure",
    "weather_failure",
    "overtime_variance",
    "garbage_time_variance",
    "late_score_variance",
)


@dataclass(frozen=True)
class TotalPostgameAuditPolicy:
    policy_version: str
    effective_at: datetime
    created_by: str
    provenance: str


@dataclass(frozen=True)
class RecordedTotalPostgameAuditPolicy:
    id: int
    policy_version: str
    grading_method: str
    clv_method: str
    projection_error_method: str
    context_evidence_method: str
    status: str
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class TotalAuditContext:
    weather_impact_status: str = "not_evaluated"
    qb_injury_impact_status: str = "not_evaluated"
    overtime_impact_status: str = "not_evaluated"
    garbage_time_impact_status: str = "not_evaluated"
    late_score_impact_status: str = "not_evaluated"
    context_evidence: str | None = None
    logic_failure_code: str = "not_evaluated"


@dataclass(frozen=True)
class TotalPostgameAuditRun:
    id: int
    audit_run_key: str
    total_shadow_card_id: int
    total_postgame_audit_policy_id: int
    sequence: int
    supersedes_run_id: int | None
    expected_candidate_count: int
    input_sha256: str
    audited_at: str
    source: str
    provenance: str


@dataclass(frozen=True)
class TotalPostgameAuditDetail:
    id: int
    audit_key: str
    total_postgame_audit_run_id: int
    total_card_candidate_id: int
    game_id: int
    locked_line_id: int
    exact_locked_total: float
    closing_market_line_id: int | None
    closing_total: float | None
    closing_book: str | None
    closing_status: str
    final_home_points: int
    final_away_points: int
    actual_total: int
    selected_direction: str
    result: str
    unit_profit_at_minus_110: float
    clv_points: float | None
    projected_total: float
    projection_error: float
    raw_edge: float
    confidence: int
    weather_impact_status: str
    qb_injury_impact_status: str
    overtime_impact_status: str
    garbage_time_impact_status: str
    late_score_impact_status: str
    context_evidence: str | None
    logic_failure_code: str
    audited_at: str
    source: str
    provenance: str


@dataclass(frozen=True)
class TotalPostgameAuditCompletion:
    total_postgame_audit_run_id: int
    audit_count: int
    win_count: int
    loss_count: int
    push_count: int
    ledger_sha256: str
    completed_at: str


@dataclass(frozen=True)
class TotalPostgameAuditResult:
    run: TotalPostgameAuditRun
    details: tuple[TotalPostgameAuditDetail, ...]
    completion: TotalPostgameAuditCompletion
    replayed: bool


@dataclass(frozen=True)
class TotalAuditSegment:
    dimension: str
    value: str
    sample_n: int
    wins: int
    losses: int
    pushes: int
    win_rate_excluding_pushes: float | None
    roi_at_minus_110: float | None
    average_clv: float | None
    projection_mae: float
    projection_rmse: float


_POLICY_COLUMNS = (
    "id, policy_version, grading_method, clv_method, projection_error_method, "
    "context_evidence_method, status, effective_at, created_by, provenance"
)
_RUN_COLUMNS = (
    "id, audit_run_key, total_shadow_card_id, total_postgame_audit_policy_id, "
    "sequence, supersedes_run_id, expected_candidate_count, input_sha256, "
    "audited_at, source, provenance"
)
_DETAIL_COLUMNS = (
    "id, audit_key, total_postgame_audit_run_id, total_card_candidate_id, "
    "game_id, locked_line_id, exact_locked_total, closing_market_line_id, "
    "closing_total, closing_book, closing_status, final_home_points, "
    "final_away_points, actual_total, selected_direction, result, "
    "unit_profit_at_minus_110, clv_points, projected_total, projection_error, "
    "raw_edge, confidence, weather_impact_status, qb_injury_impact_status, "
    "overtime_impact_status, garbage_time_impact_status, late_score_impact_status, "
    "context_evidence, logic_failure_code, audited_at, source, provenance"
)
_COMPLETION_COLUMNS = (
    "total_postgame_audit_run_id, audit_count, win_count, loss_count, push_count, "
    "ledger_sha256, completed_at"
)


def _sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def register_total_postgame_audit_policy(
    conn: sqlite3.Connection, policy: TotalPostgameAuditPolicy
) -> RecordedTotalPostgameAuditPolicy:
    if not isinstance(policy, TotalPostgameAuditPolicy):
        raise BusinessEntityError("policy must be a TotalPostgameAuditPolicy")
    requested = (
        required_text(policy.policy_version, "policy.policy_version"),
        GRADING_METHOD,
        CLV_METHOD,
        PROJECTION_ERROR_METHOD,
        CONTEXT_EVIDENCE_METHOD,
        "shadow",
        utc_timestamp(policy.effective_at, "policy.effective_at"),
        required_text(policy.created_by, "policy.created_by"),
        required_text(policy.provenance, "policy.provenance"),
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM total_postgame_audit_policies "
                "WHERE policy_version = ?",
                (requested[0],),
            ).fetchone()
            if row is not None:
                if tuple(row[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "total audit policy version has different immutable values"
                    )
                return RecordedTotalPostgameAuditPolicy(*row)
            cursor = conn.execute(
                "INSERT INTO total_postgame_audit_policies "
                "(policy_version, grading_method, clv_method, "
                "projection_error_method, context_evidence_method, status, "
                "effective_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM total_postgame_audit_policies WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            assert row is not None
            return RecordedTotalPostgameAuditPolicy(*row)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("total postgame audit policy", exc) from exc


def _get_result(
    conn: sqlite3.Connection, run_id: int, *, replayed: bool = False
) -> TotalPostgameAuditResult:
    run_row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM total_postgame_audit_runs WHERE id = ?",
        (integer(run_id, "run_id", 1),),
    ).fetchone()
    if run_row is None:
        raise BusinessEntityError(f"total audit run does not exist: {run_id}")
    details = tuple(
        TotalPostgameAuditDetail(*row)
        for row in conn.execute(
            f"SELECT {_DETAIL_COLUMNS} FROM total_postgame_audit_details "
            "WHERE total_postgame_audit_run_id = ? ORDER BY total_card_candidate_id",
            (run_id,),
        )
    )
    completion_row = conn.execute(
        f"SELECT {_COMPLETION_COLUMNS} FROM total_postgame_audit_completions "
        "WHERE total_postgame_audit_run_id = ?",
        (run_id,),
    ).fetchone()
    if completion_row is None:
        raise BusinessEntityError(f"total audit run is incomplete: {run_id}")
    return TotalPostgameAuditResult(
        TotalPostgameAuditRun(*run_row),
        details,
        TotalPostgameAuditCompletion(*completion_row),
        replayed,
    )


def _validate_context(context: TotalAuditContext) -> TotalAuditContext:
    if not isinstance(context, TotalAuditContext):
        raise BusinessEntityError("audit context must be TotalAuditContext")
    values = (
        choice(context.weather_impact_status, "weather_impact_status", _CONTEXT_STATUSES),
        choice(context.qb_injury_impact_status, "qb_injury_impact_status", _CONTEXT_STATUSES),
        choice(context.overtime_impact_status, "overtime_impact_status", _CONTEXT_STATUSES),
        choice(context.garbage_time_impact_status, "garbage_time_impact_status", _CONTEXT_STATUSES),
        choice(context.late_score_impact_status, "late_score_impact_status", _CONTEXT_STATUSES),
    )
    failure = choice(context.logic_failure_code, "logic_failure_code", _FAILURE_CODES)
    evidence = (
        required_text(context.context_evidence, "context_evidence")
        if context.context_evidence is not None
        else None
    )
    if (any(item != "not_evaluated" for item in values) or failure != "not_evaluated") and evidence is None:
        raise BusinessEntityError("evaluated audit context requires explicit evidence")
    if all(item == "not_evaluated" for item in values) and failure == "not_evaluated" and evidence is not None:
        raise BusinessEntityError("unevaluated audit context cannot carry evidence")
    return TotalAuditContext(*values, evidence, failure)


def audit_total_shadow_card(
    conn: sqlite3.Connection,
    *,
    audit_run_key: str,
    total_shadow_card_id: int,
    total_postgame_audit_policy_id: int,
    audited_at: datetime,
    source: str,
    provenance: str,
    contexts: Mapping[int, TotalAuditContext] | None = None,
) -> TotalPostgameAuditResult:
    """Grade every candidate; closing totals are resolved, never caller asserted."""
    key = required_text(audit_run_key, "audit_run_key")
    card_id = integer(total_shadow_card_id, "total_shadow_card_id", 1)
    policy_id = integer(
        total_postgame_audit_policy_id, "total_postgame_audit_policy_id", 1
    )
    audited = utc_timestamp(audited_at, "audited_at")
    source = required_text(source, "source")
    provenance = required_text(provenance, "provenance")
    card = get_total_shadow_card_result(conn, card_id)
    policy = conn.execute(
        f"SELECT {_POLICY_COLUMNS} FROM total_postgame_audit_policies WHERE id = ?",
        (policy_id,),
    ).fetchone()
    if policy is None:
        raise BusinessEntityError(f"total audit policy does not exist: {policy_id}")
    if not timestamp_on_or_before(conn, policy[7], audited):
        raise BusinessEntityError("total audit policy is not yet effective")
    supplied = dict(contexts or {})
    expected_ids = {item.id for item in card.candidates}
    if not set(supplied).issubset(expected_ids):
        raise BusinessEntityError("audit contexts include a candidate outside the card")
    normalized = {
        candidate_id: _validate_context(
            supplied.get(candidate_id, TotalAuditContext())
        )
        for candidate_id in expected_ids
    }
    input_hash = _sha256(
        {
            "audit_run_key": key,
            "card_id": card_id,
            "policy_id": policy_id,
            "audited_at": audited,
            "source": source,
            "provenance": provenance,
            "contexts": {
                str(item_id): asdict(normalized[item_id])
                for item_id in sorted(normalized)
            },
        }
    )
    try:
        with atomic(conn):
            existing = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM total_postgame_audit_runs "
                "WHERE audit_run_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                requested_run = (
                    key,
                    card_id,
                    policy_id,
                    existing[4],
                    existing[5],
                    len(card.candidates),
                    input_hash,
                    audited,
                    source,
                    provenance,
                )
                if tuple(existing[1:]) != requested_run:
                    raise BusinessEntityConflictError(
                        "total audit run key has different immutable inputs"
                    )
                return _get_result(conn, existing[0], replayed=True)
            latest = conn.execute(
                "SELECT id, sequence FROM total_postgame_audit_runs "
                "WHERE total_shadow_card_id = ? ORDER BY sequence DESC LIMIT 1",
                (card_id,),
            ).fetchone()
            supersedes = latest[0] if latest is not None else None
            sequence = latest[1] + 1 if latest is not None else 1
            requested_run = (
                key,
                card_id,
                policy_id,
                sequence,
                supersedes,
                len(card.candidates),
                input_hash,
                audited,
                source,
                provenance,
            )
            cursor = conn.execute(
                "INSERT INTO total_postgame_audit_runs "
                "(audit_run_key, total_shadow_card_id, "
                "total_postgame_audit_policy_id, sequence, supersedes_run_id, "
                "expected_candidate_count, "
                "input_sha256, audited_at, source, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested_run,
            )
            run_id = cursor.lastrowid
            for candidate in card.candidates:
                game = conn.execute(
                    "SELECT start_date, home_points, away_points, completed "
                    "FROM games WHERE game_id = ?",
                    (candidate.game_id,),
                ).fetchone()
                if (
                    game is None
                    or game[3] != 1
                    or game[1] is None
                    or game[2] is None
                    or not timestamp_on_or_before(conn, game[0], audited)
                ):
                    raise BusinessEntityError(
                        f"completed result unavailable for totals game {candidate.game_id}"
                    )
                actual_total = int(game[1]) + int(game[2])
                if actual_total == candidate.exact_locked_total:
                    result = "push"
                else:
                    actual_direction = (
                        "over"
                        if actual_total > candidate.exact_locked_total
                        else "under"
                    )
                    result = (
                        "win"
                        if candidate.selected_direction == actual_direction
                        else "loss"
                    )
                unit_profit = (
                    100 / 110 if result == "win" else -1.0 if result == "loss" else 0.0
                )
                closing = conn.execute(
                    "SELECT id, total, book FROM betting_lines "
                    "WHERE game_id = ? AND line_type = 'closing' AND total IS NOT NULL "
                    "AND julianday(fetched_at) >= julianday(?) "
                    "AND julianday(fetched_at) <= julianday(?) "
                    "ORDER BY julianday(fetched_at) DESC, id DESC LIMIT 1",
                    (candidate.game_id, card.card.generated_at, game[0]),
                ).fetchone()
                if closing is None:
                    closing_values = (None, None, None, "missing_closing_total", None)
                else:
                    clv = (
                        float(closing[1]) - candidate.exact_locked_total
                        if candidate.selected_direction == "over"
                        else candidate.exact_locked_total - float(closing[1])
                    )
                    closing_values = (
                        int(closing[0]),
                        float(closing[1]),
                        str(closing[2]),
                        "captured",
                        clv,
                    )
                context = normalized[candidate.id]
                conn.execute(
                    "INSERT INTO total_postgame_audit_details "
                    "(audit_key, total_postgame_audit_run_id, total_card_candidate_id, "
                    "game_id, locked_line_id, exact_locked_total, closing_market_line_id, "
                    "closing_total, closing_book, closing_status, final_home_points, "
                    "final_away_points, actual_total, selected_direction, result, "
                    "unit_profit_at_minus_110, clv_points, projected_total, "
                    "projection_error, raw_edge, confidence, weather_impact_status, "
                    "qb_injury_impact_status, overtime_impact_status, "
                    "garbage_time_impact_status, late_score_impact_status, "
                    "context_evidence, logic_failure_code, audited_at, source, provenance) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    "?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{key}:candidate:{candidate.id}",
                        run_id,
                        candidate.id,
                        candidate.game_id,
                        candidate.locked_line_id,
                        candidate.exact_locked_total,
                        *closing_values[:4],
                        int(game[1]),
                        int(game[2]),
                        actual_total,
                        candidate.selected_direction,
                        result,
                        unit_profit,
                        closing_values[4],
                        candidate.projected_total,
                        candidate.projected_total - actual_total,
                        candidate.projected_total - candidate.exact_locked_total,
                        candidate.confidence,
                        context.weather_impact_status,
                        context.qb_injury_impact_status,
                        context.overtime_impact_status,
                        context.garbage_time_impact_status,
                        context.late_score_impact_status,
                        context.context_evidence,
                        context.logic_failure_code,
                        audited,
                        source,
                        provenance,
                    ),
                )
            details = tuple(
                TotalPostgameAuditDetail(*row)
                for row in conn.execute(
                    f"SELECT {_DETAIL_COLUMNS} FROM total_postgame_audit_details "
                    "WHERE total_postgame_audit_run_id = ? ORDER BY total_card_candidate_id",
                    (run_id,),
                )
            )
            ledger_hash = _sha256(
                {"run_id": run_id, "details": [asdict(item) for item in details]}
            )
            counts = {
                outcome: sum(item.result == outcome for item in details)
                for outcome in ("win", "loss", "push")
            }
            conn.execute(
                "INSERT INTO total_postgame_audit_completions "
                "(total_postgame_audit_run_id, audit_count, win_count, loss_count, "
                "push_count, ledger_sha256, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    len(details),
                    counts["win"],
                    counts["loss"],
                    counts["push"],
                    ledger_hash,
                    audited,
                ),
            )
            return _get_result(conn, run_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("total postgame audit", exc) from exc


def _edge_bucket(value: float) -> str:
    edge = abs(value)
    for upper, label in ((1.5, "under_1_5"), (3, "1_5_to_under_3"), (5, "3_to_under_5"), (8, "5_to_under_8"), (12, "8_to_under_12"), (20, "12_to_under_20")):
        if edge < upper:
            return label
    return "20_plus"


def _total_bucket(value: float) -> str:
    for upper, label in ((42, "under_42"), (49, "42_to_under_49"), (56, "49_to_under_56"), (63, "56_to_under_63"), (70, "63_to_under_70")):
        if value < upper:
            return label
    return "70_plus"


def summarize_total_postgame_audit(
    conn: sqlite3.Connection, total_postgame_audit_run_id: int
) -> tuple[TotalAuditSegment, ...]:
    """Return reproducible diagnostics; unavailable rich context stays explicit."""
    result = _get_result(conn, total_postgame_audit_run_id)
    groups: dict[tuple[str, str], list[TotalPostgameAuditDetail]] = {}
    for detail in result.details:
        values = (
            ("direction", detail.selected_direction),
            ("confidence", str(detail.confidence)),
            ("edge_bucket", _edge_bucket(detail.raw_edge)),
            ("total_line_bucket", _total_bucket(detail.exact_locked_total)),
            ("weather", detail.weather_impact_status),
            ("qb_change", detail.qb_injury_impact_status),
        )
        for key in values:
            groups.setdefault(key, []).append(detail)
    segments: list[TotalAuditSegment] = []
    for (dimension, value), items in sorted(groups.items()):
        wins = sum(item.result == "win" for item in items)
        losses = sum(item.result == "loss" for item in items)
        pushes = sum(item.result == "push" for item in items)
        decisions = wins + losses
        clv = [item.clv_points for item in items if item.clv_points is not None]
        segments.append(
            TotalAuditSegment(
                dimension,
                value,
                len(items),
                wins,
                losses,
                pushes,
                wins / decisions if decisions else None,
                sum(item.unit_profit_at_minus_110 for item in items) / len(items),
                sum(clv) / len(clv) if clv else None,
                sum(abs(item.projection_error) for item in items) / len(items),
                math.sqrt(
                    sum(item.projection_error**2 for item in items) / len(items)
                ),
            )
        )
    return tuple(segments)
