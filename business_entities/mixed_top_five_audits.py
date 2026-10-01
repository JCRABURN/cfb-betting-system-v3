"""Postgame audit for the correlation-aware shadow mixed Top 5."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime

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
from business_entities.correlation_aware_top_five import (
    get_correlation_aware_unified_result,
)


@dataclass(frozen=True)
class MixedTopFiveAuditRun:
    id: int
    audit_run_key: str
    correlation_aware_unified_run_id: int
    card_postgame_audit_run_id: int
    total_postgame_audit_run_id: int
    input_sha256: str
    audited_at: str
    provenance: str


@dataclass(frozen=True)
class MixedTopFiveAuditDetail:
    id: int
    mixed_top_five_audit_run_id: int
    unified_candidate_id: int
    market_type: str
    game_id: int
    pick_audit_detail_id: int | None
    total_postgame_audit_detail_id: int | None
    result: str
    unit_profit_at_minus_110: float
    clv_points: float | None
    expected_win_probability: float
    audited_at: str


@dataclass(frozen=True)
class MixedTopFiveAuditCompletion:
    mixed_top_five_audit_run_id: int
    audit_count: int
    ats_count: int
    total_count: int
    win_count: int
    loss_count: int
    push_count: int
    unit_profit_at_minus_110: float
    roi_at_minus_110: float | None
    average_clv: float | None
    expected_win_rate: float | None
    actual_win_rate: float | None
    ledger_sha256: str
    completed_at: str


@dataclass(frozen=True)
class MixedTopFiveAuditResult:
    run: MixedTopFiveAuditRun
    details: tuple[MixedTopFiveAuditDetail, ...]
    completion: MixedTopFiveAuditCompletion
    replayed: bool


_RUN_COLUMNS = (
    "id, audit_run_key, correlation_aware_unified_run_id, "
    "card_postgame_audit_run_id, total_postgame_audit_run_id, input_sha256, "
    "audited_at, provenance"
)
_DETAIL_COLUMNS = (
    "id, mixed_top_five_audit_run_id, unified_candidate_id, market_type, "
    "game_id, pick_audit_detail_id, total_postgame_audit_detail_id, result, "
    "unit_profit_at_minus_110, clv_points, expected_win_probability, audited_at"
)
_COMPLETION_COLUMNS = (
    "mixed_top_five_audit_run_id, audit_count, ats_count, total_count, win_count, "
    "loss_count, push_count, unit_profit_at_minus_110, roi_at_minus_110, "
    "average_clv, expected_win_rate, actual_win_rate, ledger_sha256, completed_at"
)


def _sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _result(
    conn: sqlite3.Connection, run_id: int, *, replayed: bool = False
) -> MixedTopFiveAuditResult:
    run = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM mixed_top_five_audit_runs WHERE id = ?",
        (integer(run_id, "run_id", 1),),
    ).fetchone()
    if run is None:
        raise BusinessEntityError(f"mixed Top-5 audit run does not exist: {run_id}")
    details = tuple(
        MixedTopFiveAuditDetail(*row)
        for row in conn.execute(
            f"SELECT {_DETAIL_COLUMNS} FROM mixed_top_five_audit_details "
            "WHERE mixed_top_five_audit_run_id = ? ORDER BY unified_candidate_id",
            (run_id,),
        )
    )
    completion = conn.execute(
        f"SELECT {_COMPLETION_COLUMNS} FROM mixed_top_five_audit_completions "
        "WHERE mixed_top_five_audit_run_id = ?",
        (run_id,),
    ).fetchone()
    if completion is None:
        raise BusinessEntityError(f"mixed Top-5 audit run is incomplete: {run_id}")
    return MixedTopFiveAuditResult(
        MixedTopFiveAuditRun(*run),
        details,
        MixedTopFiveAuditCompletion(*completion),
        replayed,
    )


def audit_mixed_top_five(
    conn: sqlite3.Connection,
    *,
    audit_run_key: str,
    correlation_aware_unified_run_id: int,
    card_postgame_audit_run_id: int,
    total_postgame_audit_run_id: int,
    audited_at: datetime,
    provenance: str,
) -> MixedTopFiveAuditResult:
    key = required_text(audit_run_key, "audit_run_key")
    unified_run_id = integer(
        correlation_aware_unified_run_id, "correlation_aware_unified_run_id", 1
    )
    ats_audit_id = integer(
        card_postgame_audit_run_id, "card_postgame_audit_run_id", 1
    )
    total_audit_id = integer(
        total_postgame_audit_run_id, "total_postgame_audit_run_id", 1
    )
    audited = utc_timestamp(audited_at, "audited_at")
    provenance = required_text(provenance, "provenance")
    unified = get_correlation_aware_unified_result(conn, unified_run_id)
    ats_run = conn.execute(
        "SELECT card_id, audited_at FROM card_postgame_audit_runs WHERE id = ?",
        (ats_audit_id,),
    ).fetchone()
    total_run = conn.execute(
        "SELECT total_shadow_card_id, audited_at FROM total_postgame_audit_runs WHERE id = ?",
        (total_audit_id,),
    ).fetchone()
    if ats_run is None or conn.execute(
        "SELECT 1 FROM card_postgame_audit_completions WHERE audit_run_id = ?",
        (ats_audit_id,),
    ).fetchone() is None:
        raise BusinessEntityError("ATS postgame audit is not complete")
    if total_run is None or conn.execute(
        "SELECT 1 FROM total_postgame_audit_completions "
        "WHERE total_postgame_audit_run_id = ?",
        (total_audit_id,),
    ).fetchone() is None:
        raise BusinessEntityError("totals postgame audit is not complete")
    if ats_run[0] != unified.run.contest_card_id or total_run[0] != unified.run.total_shadow_card_id:
        raise BusinessEntityError("mixed audit sub-audits belong to different cards")
    if not timestamp_on_or_before(conn, ats_run[1], audited) or not timestamp_on_or_before(conn, total_run[1], audited):
        raise BusinessEntityError("mixed audit cannot precede a sub-audit")
    input_hash = _sha256(
        {
            "audit_run_key": key,
            "unified_run_id": unified_run_id,
            "unified_ledger": unified.completion.ledger_sha256,
            "ats_audit_run_id": ats_audit_id,
            "total_audit_run_id": total_audit_id,
            "audited_at": audited,
            "provenance": provenance,
        }
    )
    requested = (
        key,
        unified_run_id,
        ats_audit_id,
        total_audit_id,
        input_hash,
        audited,
        provenance,
    )
    try:
        with atomic(conn):
            existing = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM mixed_top_five_audit_runs WHERE audit_run_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                if tuple(existing[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "mixed audit run key has different immutable inputs"
                    )
                return _result(conn, existing[0], replayed=True)
            cursor = conn.execute(
                "INSERT INTO mixed_top_five_audit_runs "
                "(audit_run_key, correlation_aware_unified_run_id, "
                "card_postgame_audit_run_id, total_postgame_audit_run_id, "
                "input_sha256, audited_at, provenance) VALUES (?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            run_id = cursor.lastrowid
            for candidate in unified.top_five:
                if candidate.market_type == "ATS":
                    source = conn.execute(
                        "SELECT audit_id, ats_result, clv_points FROM pick_audit_details "
                        "WHERE audit_run_id = ? AND contest_pick_id = ?",
                        (ats_audit_id, candidate.contest_pick_id),
                    ).fetchone()
                    if source is None:
                        raise BusinessEntityError(
                            f"missing ATS audit for unified candidate {candidate.id}"
                        )
                    pick_audit_id, total_detail_id = int(source[0]), None
                    result, clv = str(source[1]), float(source[2])
                else:
                    source = conn.execute(
                        "SELECT id, result, clv_points FROM total_postgame_audit_details "
                        "WHERE total_postgame_audit_run_id = ? "
                        "AND total_card_candidate_id = ?",
                        (total_audit_id, candidate.total_card_candidate_id),
                    ).fetchone()
                    if source is None:
                        raise BusinessEntityError(
                            f"missing totals audit for unified candidate {candidate.id}"
                        )
                    pick_audit_id, total_detail_id = None, int(source[0])
                    result = str(source[1])
                    clv = None if source[2] is None else float(source[2])
                profit = 100 / 110 if result == "win" else -1.0 if result == "loss" else 0.0
                conn.execute(
                    "INSERT INTO mixed_top_five_audit_details "
                    "(mixed_top_five_audit_run_id, unified_candidate_id, "
                    "market_type, game_id, pick_audit_detail_id, "
                    "total_postgame_audit_detail_id, result, unit_profit_at_minus_110, "
                    "clv_points, expected_win_probability, audited_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        candidate.id,
                        candidate.market_type,
                        candidate.game_id,
                        pick_audit_id,
                        total_detail_id,
                        result,
                        profit,
                        clv,
                        candidate.calibrated_probability,
                        audited,
                    ),
                )
            details = tuple(
                MixedTopFiveAuditDetail(*row)
                for row in conn.execute(
                    f"SELECT {_DETAIL_COLUMNS} FROM mixed_top_five_audit_details "
                    "WHERE mixed_top_five_audit_run_id = ? ORDER BY unified_candidate_id",
                    (run_id,),
                )
            )
            wins = sum(item.result == "win" for item in details)
            losses = sum(item.result == "loss" for item in details)
            pushes = sum(item.result == "push" for item in details)
            decisions = wins + losses
            profit = sum(item.unit_profit_at_minus_110 for item in details)
            clv = [item.clv_points for item in details if item.clv_points is not None]
            graded = [item for item in details if item.result != "push"]
            ledger = _sha256(
                {"run_id": run_id, "details": [asdict(item) for item in details]}
            )
            completion_values = (
                run_id,
                len(details),
                sum(item.market_type == "ATS" for item in details),
                sum(item.market_type == "TOTAL" for item in details),
                wins,
                losses,
                pushes,
                profit,
                profit / len(details) if details else None,
                sum(clv) / len(clv) if clv else None,
                (
                    sum(item.expected_win_probability for item in graded) / len(graded)
                    if graded
                    else None
                ),
                wins / decisions if decisions else None,
                ledger,
                audited,
            )
            conn.execute(
                "INSERT INTO mixed_top_five_audit_completions "
                "(mixed_top_five_audit_run_id, audit_count, ats_count, total_count, "
                "win_count, loss_count, push_count, unit_profit_at_minus_110, "
                "roi_at_minus_110, average_clv, expected_win_rate, actual_win_rate, "
                "ledger_sha256, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                completion_values,
            )
            return _result(conn, run_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("mixed Top-5 postgame audit", exc) from exc
