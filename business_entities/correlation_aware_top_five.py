"""Correlation-aware, calibrated-probability mixed Top-5 shadow ranking."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime

from business_entities.ats_shadow_calibration import (
    AtsShadowCalibratedEvaluation,
    get_ats_shadow_calibrated_evaluation,
    get_ats_shadow_calibration_result,
)
from business_entities.cards import get_contest_card
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
from business_entities.totals import (
    TotalCardCandidate,
    get_total_shadow_card_result,
)
from contest_lines import get_effective_locked_line_as_of
from models.cross_market_correlation import (
    EVIDENCE_METHOD,
    PENALTY_METHOD,
    RELATION_CODES,
    CrossMarketCorrelationResult,
)


TOP_FIVE_COUNT = 5
BASE_SCORE_METRIC = "calibrated_selection_probability"
ORDERING_METHOD = "greedy_probability_minus_same_game_covariance_v1"


@dataclass(frozen=True)
class CrossMarketCorrelationPolicy:
    policy_key: str
    policy_version: str
    effective_at: datetime
    created_by: str
    provenance: str


@dataclass(frozen=True)
class RecordedCrossMarketCorrelationPolicy:
    id: int
    policy_key: str
    policy_version: str
    evidence_method: str
    penalty_method: str
    status: str
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class CrossMarketCorrelationCell:
    id: int
    cross_market_correlation_policy_id: int
    relation_code: str
    sample_n: int
    phi_correlation: float | None
    fisher_lower_95: float | None
    fisher_upper_95: float | None
    positive_penalty_weight: float
    evidence_status: str
    dataset_sha256: str
    generated_at: str
    provenance: str


@dataclass(frozen=True)
class CorrelationAwareUnifiedPolicy:
    policy_key: str
    policy_version: str
    cross_market_correlation_policy_id: int
    effective_at: datetime
    created_by: str
    provenance: str


@dataclass(frozen=True)
class RecordedCorrelationAwareUnifiedPolicy:
    id: int
    policy_key: str
    policy_version: str
    cross_market_correlation_policy_id: int
    top_five_count: int
    base_score_metric: str
    ordering_method: str
    status: str
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class CorrelationAwareUnifiedRun:
    id: int
    run_key: str
    contest_card_id: int
    ats_shadow_calibration_run_id: int
    total_shadow_card_id: int
    correlation_aware_unified_policy_id: int
    candidate_input_sha256: str
    status: str
    generated_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class CorrelationAwareUnifiedCandidate:
    id: int
    candidate_key: str
    correlation_aware_unified_run_id: int
    market_type: str
    game_id: int
    contest_pick_id: int | None
    ats_shadow_calibrated_evaluation_id: int | None
    total_card_candidate_id: int | None
    same_game_predecessor_candidate_id: int | None
    correlation_cell_id: int | None
    correlation_relation_code: str | None
    calibrated_probability: float
    reliability_policy_version: str
    correlation_penalty: float
    adjusted_score: float
    correlation_status: str
    pool_rank: int
    top_five_rank: int | None
    is_top_five: bool
    generated_at: str
    provenance: str


@dataclass(frozen=True)
class CorrelationAwareUnifiedPairFlag:
    id: int
    correlation_aware_unified_run_id: int
    ats_candidate_id: int
    total_candidate_id: int
    game_id: int
    relation_code: str
    correlation_cell_id: int | None
    penalty_applied: float
    status: str
    generated_at: str
    provenance: str


@dataclass(frozen=True)
class CorrelationAwareUnifiedCompletion:
    correlation_aware_unified_run_id: int
    candidate_count: int
    selected_count: int
    same_game_top_five_pair_count: int
    rank_five_score: float | None
    rank_six_score: float | None
    cutoff_gap: float | None
    ledger_sha256: str
    completed_at: str


@dataclass(frozen=True)
class CorrelationAwareUnifiedResult:
    run: CorrelationAwareUnifiedRun
    candidates: tuple[CorrelationAwareUnifiedCandidate, ...]
    pair_flags: tuple[CorrelationAwareUnifiedPairFlag, ...]
    completion: CorrelationAwareUnifiedCompletion
    replayed: bool

    @property
    def top_five(self) -> tuple[CorrelationAwareUnifiedCandidate, ...]:
        return tuple(item for item in self.candidates if item.is_top_five)


@dataclass(frozen=True)
class _PoolItem:
    market_type: str
    source_id: int
    game_id: int
    contest_pick_id: int | None
    ats_evaluation_id: int | None
    total_candidate_id: int | None
    probability: float
    reliability_policy_version: str
    ats_market_status: str | None
    total_direction: str | None


@dataclass(frozen=True)
class _RankedItem:
    item: _PoolItem
    penalty: float
    adjusted_score: float
    status: str
    relation_code: str | None
    cell_id: int | None


_CORRELATION_POLICY_COLUMNS = (
    "id, policy_key, policy_version, evidence_method, penalty_method, status, "
    "effective_at, created_by, provenance"
)
_CELL_COLUMNS = (
    "id, cross_market_correlation_policy_id, relation_code, sample_n, "
    "phi_correlation, fisher_lower_95, fisher_upper_95, "
    "positive_penalty_weight, evidence_status, dataset_sha256, generated_at, provenance"
)
_POLICY_COLUMNS = (
    "id, policy_key, policy_version, cross_market_correlation_policy_id, "
    "top_five_count, base_score_metric, ordering_method, status, effective_at, "
    "created_by, provenance"
)
_RUN_COLUMNS = (
    "id, run_key, contest_card_id, ats_shadow_calibration_run_id, "
    "total_shadow_card_id, correlation_aware_unified_policy_id, "
    "candidate_input_sha256, status, generated_at, created_by, provenance"
)
_CANDIDATE_COLUMNS = (
    "id, candidate_key, correlation_aware_unified_run_id, market_type, game_id, "
    "contest_pick_id, ats_shadow_calibrated_evaluation_id, total_card_candidate_id, "
    "same_game_predecessor_candidate_id, correlation_cell_id, "
    "correlation_relation_code, calibrated_probability, "
    "reliability_policy_version, correlation_penalty, "
    "adjusted_score, correlation_status, pool_rank, top_five_rank, is_top_five, "
    "generated_at, provenance"
)
_PAIR_COLUMNS = (
    "id, correlation_aware_unified_run_id, ats_candidate_id, total_candidate_id, "
    "game_id, relation_code, correlation_cell_id, penalty_applied, status, "
    "generated_at, provenance"
)
_COMPLETION_COLUMNS = (
    "correlation_aware_unified_run_id, candidate_count, selected_count, "
    "same_game_top_five_pair_count, rank_five_score, rank_six_score, cutoff_gap, "
    "ledger_sha256, completed_at"
)


def _sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def register_cross_market_correlation_policy(
    conn: sqlite3.Connection,
    *,
    policy: CrossMarketCorrelationPolicy,
    evidence: CrossMarketCorrelationResult,
    generated_at: datetime,
) -> tuple[RecordedCrossMarketCorrelationPolicy, tuple[CrossMarketCorrelationCell, ...]]:
    if not isinstance(policy, CrossMarketCorrelationPolicy):
        raise BusinessEntityError("policy must be CrossMarketCorrelationPolicy")
    if evidence.evidence_method != EVIDENCE_METHOD or evidence.penalty_method != PENALTY_METHOD:
        raise BusinessEntityError("correlation evidence uses an unsupported method")
    generated = utc_timestamp(generated_at, "generated_at")
    if tuple(sorted(item.relation_code for item in evidence.estimates)) != tuple(
        sorted(RELATION_CODES)
    ):
        raise BusinessEntityError("correlation evidence must cover every relation once")
    requested = (
        required_text(policy.policy_key, "policy.policy_key"),
        required_text(policy.policy_version, "policy.policy_version"),
        EVIDENCE_METHOD,
        PENALTY_METHOD,
        "shadow",
        utc_timestamp(policy.effective_at, "policy.effective_at"),
        required_text(policy.created_by, "policy.created_by"),
        required_text(policy.provenance, "policy.provenance"),
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_CORRELATION_POLICY_COLUMNS} FROM cross_market_correlation_policies "
                "WHERE policy_key = ? OR policy_version = ? ORDER BY policy_key = ? DESC LIMIT 1",
                (requested[0], requested[1], requested[0]),
            ).fetchone()
            if row is None:
                cursor = conn.execute(
                    "INSERT INTO cross_market_correlation_policies "
                    "(policy_key, policy_version, evidence_method, penalty_method, "
                    "status, effective_at, created_by, provenance) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    requested,
                )
                policy_id = cursor.lastrowid
                for estimate in evidence.estimates:
                    conn.execute(
                        "INSERT INTO cross_market_correlation_cells "
                        "(cross_market_correlation_policy_id, relation_code, sample_n, "
                        "phi_correlation, fisher_lower_95, fisher_upper_95, "
                        "positive_penalty_weight, evidence_status, dataset_sha256, "
                        "generated_at, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            policy_id,
                            estimate.relation_code,
                            estimate.sample_n,
                            estimate.phi_correlation,
                            estimate.fisher_lower_95,
                            estimate.fisher_upper_95,
                            estimate.positive_penalty_weight,
                            estimate.evidence_status,
                            evidence.dataset_sha256,
                            generated,
                            policy.provenance,
                        ),
                    )
            else:
                if tuple(row[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "correlation policy key/version has different immutable values"
                    )
                policy_id = row[0]
            recorded = conn.execute(
                f"SELECT {_CORRELATION_POLICY_COLUMNS} FROM cross_market_correlation_policies "
                "WHERE id = ?",
                (policy_id,),
            ).fetchone()
            cells = tuple(
                CrossMarketCorrelationCell(*item)
                for item in conn.execute(
                    f"SELECT {_CELL_COLUMNS} FROM cross_market_correlation_cells "
                    "WHERE cross_market_correlation_policy_id = ? ORDER BY relation_code",
                    (policy_id,),
                )
            )
            expected_cells = {
                item.relation_code: (
                    item.sample_n,
                    item.phi_correlation,
                    item.fisher_lower_95,
                    item.fisher_upper_95,
                    item.positive_penalty_weight,
                    item.evidence_status,
                    evidence.dataset_sha256,
                    generated,
                    policy.provenance,
                )
                for item in evidence.estimates
            }
            if len(cells) != len(evidence.estimates) or any(
                (
                    cell.sample_n,
                    cell.phi_correlation,
                    cell.fisher_lower_95,
                    cell.fisher_upper_95,
                    cell.positive_penalty_weight,
                    cell.evidence_status,
                    cell.dataset_sha256,
                    cell.generated_at,
                    cell.provenance,
                )
                != expected_cells[cell.relation_code]
                for cell in cells
            ):
                raise BusinessEntityConflictError(
                    "correlation policy has different immutable evidence"
                )
            assert recorded is not None
            return RecordedCrossMarketCorrelationPolicy(*recorded), cells
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("cross-market correlation policy", exc) from exc


def register_correlation_aware_unified_policy(
    conn: sqlite3.Connection, policy: CorrelationAwareUnifiedPolicy
) -> RecordedCorrelationAwareUnifiedPolicy:
    if not isinstance(policy, CorrelationAwareUnifiedPolicy):
        raise BusinessEntityError("policy must be CorrelationAwareUnifiedPolicy")
    correlation_policy_id = integer(
        policy.cross_market_correlation_policy_id,
        "policy.cross_market_correlation_policy_id",
        1,
    )
    if conn.execute(
        "SELECT 1 FROM cross_market_correlation_policies WHERE id = ?",
        (correlation_policy_id,),
    ).fetchone() is None:
        raise BusinessEntityError("correlation policy does not exist")
    requested = (
        required_text(policy.policy_key, "policy.policy_key"),
        required_text(policy.policy_version, "policy.policy_version"),
        correlation_policy_id,
        TOP_FIVE_COUNT,
        BASE_SCORE_METRIC,
        ORDERING_METHOD,
        "shadow",
        utc_timestamp(policy.effective_at, "policy.effective_at"),
        required_text(policy.created_by, "policy.created_by"),
        required_text(policy.provenance, "policy.provenance"),
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM correlation_aware_unified_policies "
                "WHERE policy_key = ? OR policy_version = ? ORDER BY policy_key = ? DESC LIMIT 1",
                (requested[0], requested[1], requested[0]),
            ).fetchone()
            if row is not None:
                if tuple(row[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "correlation-aware policy key/version has different immutable values"
                    )
                return RecordedCorrelationAwareUnifiedPolicy(*row)
            cursor = conn.execute(
                "INSERT INTO correlation_aware_unified_policies "
                "(policy_key, policy_version, cross_market_correlation_policy_id, "
                "top_five_count, base_score_metric, ordering_method, status, "
                "effective_at, created_by, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM correlation_aware_unified_policies WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
            assert row is not None
            return RecordedCorrelationAwareUnifiedPolicy(*row)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("correlation-aware unified policy", exc) from exc


def _market_status(conn: sqlite3.Connection, evaluation: AtsShadowCalibratedEvaluation) -> str:
    moment = datetime.fromisoformat(evaluation.card_generated_at)
    line = get_effective_locked_line_as_of(conn, evaluation.locked_line_id, as_of=moment)
    if line.home_spread == 0:
        return "pickem"
    favorite_side = "home" if line.home_spread < 0 else "away"
    return "favorite" if evaluation.selected_side == favorite_side else "underdog"


def _penalty(
    item: _PoolItem,
    ranked: list[_RankedItem],
    cells: dict[str, CrossMarketCorrelationCell],
) -> tuple[float, str, str | None, int | None]:
    predecessor = next(
        (
            prior
            for prior in ranked
            if prior.item.game_id == item.game_id
            and prior.item.market_type != item.market_type
        ),
        None,
    )
    if predecessor is None:
        return 0.0, "no_same_game_predecessor", None, None
    ats = item if item.market_type == "ATS" else predecessor.item
    total = item if item.market_type == "TOTAL" else predecessor.item
    assert ats.ats_market_status is not None and total.total_direction is not None
    relation = f"{ats.ats_market_status}_{total.total_direction}"
    cell = cells.get(relation)
    if cell is None or cell.evidence_status != "estimated":
        return 0.0, "same_game_no_evidence", relation, None if cell is None else cell.id
    if cell.positive_penalty_weight <= 0:
        return 0.0, "same_game_not_empirically_positive", relation, cell.id
    covariance = cell.positive_penalty_weight * math.sqrt(
        item.probability
        * (1 - item.probability)
        * predecessor.item.probability
        * (1 - predecessor.item.probability)
    )
    return covariance, "penalized_positive_correlation", relation, cell.id


def _get_result(
    conn: sqlite3.Connection, run_id: int, *, replayed: bool = False
) -> CorrelationAwareUnifiedResult:
    run = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM correlation_aware_unified_runs WHERE id = ?",
        (integer(run_id, "run_id", 1),),
    ).fetchone()
    if run is None:
        raise BusinessEntityError(f"correlation-aware run does not exist: {run_id}")
    candidates = []
    for row in conn.execute(
        f"SELECT {_CANDIDATE_COLUMNS} FROM correlation_aware_unified_candidates "
        "WHERE correlation_aware_unified_run_id = ? ORDER BY pool_rank",
        (run_id,),
    ):
        values = list(row)
        values[18] = bool(values[18])
        candidates.append(CorrelationAwareUnifiedCandidate(*values))
    flags = tuple(
        CorrelationAwareUnifiedPairFlag(*row)
        for row in conn.execute(
            f"SELECT {_PAIR_COLUMNS} FROM correlation_aware_unified_pair_flags "
            "WHERE correlation_aware_unified_run_id = ? ORDER BY game_id",
            (run_id,),
        )
    )
    completion = conn.execute(
        f"SELECT {_COMPLETION_COLUMNS} FROM correlation_aware_unified_completions "
        "WHERE correlation_aware_unified_run_id = ?",
        (run_id,),
    ).fetchone()
    if completion is None:
        raise BusinessEntityError(f"correlation-aware run is incomplete: {run_id}")
    return CorrelationAwareUnifiedResult(
        CorrelationAwareUnifiedRun(*run),
        tuple(candidates),
        flags,
        CorrelationAwareUnifiedCompletion(*completion),
        replayed,
    )


def get_correlation_aware_unified_result(
    conn: sqlite3.Connection, run_id: int, *, replayed: bool = False
) -> CorrelationAwareUnifiedResult:
    return _get_result(conn, run_id, replayed=replayed)


def generate_correlation_aware_unified_top_five(
    conn: sqlite3.Connection,
    *,
    run_key: str,
    contest_card_id: int,
    total_shadow_card_id: int,
    correlation_aware_unified_policy_id: int,
    ats_calibrated_evaluation_ids: tuple[int, ...],
    generated_at: datetime,
    created_by: str,
    provenance: str,
) -> CorrelationAwareUnifiedResult:
    """Rank all ATS and total opportunities; same-game pairs remain eligible."""
    key = required_text(run_key, "run_key")
    contest_card_id = integer(contest_card_id, "contest_card_id", 1)
    total_card_id = integer(total_shadow_card_id, "total_shadow_card_id", 1)
    policy_id = integer(
        correlation_aware_unified_policy_id,
        "correlation_aware_unified_policy_id",
        1,
    )
    generated = utc_timestamp(generated_at, "generated_at")
    created_by = required_text(created_by, "created_by")
    provenance = required_text(provenance, "provenance")
    policy_row = conn.execute(
        f"SELECT {_POLICY_COLUMNS} FROM correlation_aware_unified_policies WHERE id = ?",
        (policy_id,),
    ).fetchone()
    if policy_row is None:
        raise BusinessEntityError(f"correlation-aware policy does not exist: {policy_id}")
    policy = RecordedCorrelationAwareUnifiedPolicy(*policy_row)
    if not timestamp_on_or_before(conn, policy.effective_at, generated):
        raise BusinessEntityError("correlation-aware policy is not yet effective")
    ats_card = get_contest_card(conn, contest_card_id)
    total_result = get_total_shadow_card_result(conn, total_card_id)
    if ats_card.contest_id != total_result.card.contest_id:
        raise BusinessEntityError("ATS and total cards belong to different contests")
    evaluation_ids = tuple(integer(item, "ATS evaluation id", 1) for item in ats_calibrated_evaluation_ids)
    if len(evaluation_ids) != len(set(evaluation_ids)) or not evaluation_ids:
        raise BusinessEntityError("ATS evaluation IDs must be non-empty and unique")
    evaluations = tuple(get_ats_shadow_calibrated_evaluation(conn, item) for item in evaluation_ids)
    ats_run_ids = {item.ats_shadow_calibration_run_id for item in evaluations}
    if len(ats_run_ids) != 1:
        raise BusinessEntityError("ATS evaluations must belong to one calibration run")
    ats_result = get_ats_shadow_calibration_result(conn, next(iter(ats_run_ids)))
    if ats_result.run.contest_card_id != contest_card_id or {
        item.id for item in ats_result.evaluations
    } != set(evaluation_ids):
        raise BusinessEntityError("ATS evaluation IDs must cover the exact card ledger")
    if not timestamp_on_or_before(conn, ats_result.run.generated_at, generated):
        raise BusinessEntityError("unified run cannot precede ATS calibration")
    pool = [
        _PoolItem(
            "ATS",
            item.id,
            item.game_id,
            item.contest_pick_id,
            item.id,
            None,
            item.calibrated_selected_side_probability,
            item.reliability_policy_version,
            _market_status(conn, item),
            None,
        )
        for item in evaluations
    ] + [
        _PoolItem(
            "TOTAL",
            item.id,
            item.game_id,
            None,
            None,
            item.id,
            item.selected_probability,
            item.reliability_policy_version,
            None,
            item.selected_direction,
        )
        for item in total_result.candidates
    ]
    for item in pool:
        kickoff = conn.execute(
            "SELECT start_date FROM games WHERE game_id = ?", (item.game_id,)
        ).fetchone()
        if kickoff is None or kickoff[0] is None or timestamp_on_or_before(conn, kickoff[0], generated):
            raise BusinessEntityError(
                f"correlation-aware ranking must precede kickoff for game {item.game_id}"
            )
    cells = {
        item.relation_code: item
        for item in (
            CrossMarketCorrelationCell(*row)
            for row in conn.execute(
                f"SELECT {_CELL_COLUMNS} FROM cross_market_correlation_cells "
                "WHERE cross_market_correlation_policy_id = ?",
                (policy.cross_market_correlation_policy_id,),
            )
        )
    }
    if len(cells) != 6:
        raise BusinessEntityError("correlation policy evidence ledger is incomplete")
    ranked: list[_RankedItem] = []
    remaining = list(pool)
    while remaining:
        scored = []
        for item in remaining:
            penalty, status, relation, cell_id = _penalty(item, ranked, cells)
            scored.append(
                _RankedItem(
                    item,
                    penalty,
                    max(item.probability - penalty, 0.0),
                    status,
                    relation,
                    cell_id,
                )
            )
        selected = min(
            scored,
            key=lambda item: (
                -item.adjusted_score,
                item.item.market_type,
                item.item.source_id,
            ),
        )
        ranked.append(selected)
        remaining.remove(selected.item)
    input_hash = _sha256(
        {
            "run_key": key,
            "contest_card_id": contest_card_id,
            "ats_ledger": ats_result.completion.ledger_sha256,
            "total_card_id": total_card_id,
            "total_ledger": total_result.completion.ledger_sha256,
            "policy_id": policy_id,
            "correlation_cells": [asdict(cells[key]) for key in sorted(cells)],
            "pool": [asdict(item) for item in pool],
            "generated_at": generated,
        }
    )
    requested_run = (
        key,
        contest_card_id,
        ats_result.run.id,
        total_card_id,
        policy_id,
        input_hash,
        "shadow",
        generated,
        created_by,
        provenance,
    )
    try:
        with atomic(conn):
            existing = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM correlation_aware_unified_runs WHERE run_key = ?",
                (key,),
            ).fetchone()
            if existing is not None:
                if tuple(existing[1:]) != requested_run:
                    raise BusinessEntityConflictError(
                        "correlation-aware run key has different immutable inputs"
                    )
                return _get_result(conn, existing[0], replayed=True)
            cursor = conn.execute(
                "INSERT INTO correlation_aware_unified_runs "
                "(run_key, contest_card_id, ats_shadow_calibration_run_id, "
                "total_shadow_card_id, correlation_aware_unified_policy_id, "
                "candidate_input_sha256, status, generated_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested_run,
            )
            run_id = cursor.lastrowid
            inserted_ids: dict[tuple[str, int], int] = {}
            for rank, item in enumerate(ranked, start=1):
                source = item.item
                opposite = "TOTAL" if source.market_type == "ATS" else "ATS"
                predecessor_id = inserted_ids.get((opposite, source.game_id))
                candidate_cursor = conn.execute(
                    "INSERT INTO correlation_aware_unified_candidates "
                    "(candidate_key, correlation_aware_unified_run_id, market_type, "
                    "game_id, contest_pick_id, ats_shadow_calibrated_evaluation_id, "
                    "total_card_candidate_id, same_game_predecessor_candidate_id, "
                    "correlation_cell_id, correlation_relation_code, calibrated_probability, "
                    "reliability_policy_version, correlation_penalty, adjusted_score, "
                    "correlation_status, pool_rank, top_five_rank, is_top_five, "
                    "generated_at, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{key}:{source.market_type}:{source.source_id}",
                        run_id,
                        source.market_type,
                        source.game_id,
                        source.contest_pick_id,
                        source.ats_evaluation_id,
                        source.total_candidate_id,
                        predecessor_id,
                        item.cell_id if predecessor_id is not None else None,
                        item.relation_code if predecessor_id is not None else None,
                        source.probability,
                        source.reliability_policy_version,
                        item.penalty,
                        item.adjusted_score,
                        item.status,
                        rank,
                        rank if rank <= TOP_FIVE_COUNT else None,
                        int(rank <= TOP_FIVE_COUNT),
                        generated,
                        provenance,
                    ),
                )
                inserted_ids[(source.market_type, source.game_id)] = candidate_cursor.lastrowid
            candidates = _candidate_rows(conn, run_id)
            inserted = {(item.market_type, item.game_id): item for item in candidates}
            top_games = {item.game_id for item in candidates if item.is_top_five}
            for game_id in sorted(top_games):
                ats = inserted.get(("ATS", game_id))
                total = inserted.get(("TOTAL", game_id))
                if ats is None or total is None or not ats.is_top_five or not total.is_top_five:
                    continue
                source_ranked = ranked[max(ats.pool_rank, total.pool_rank) - 1]
                relation = source_ranked.relation_code
                assert relation is not None
                cell = cells.get(relation)
                if cell is None or cell.evidence_status != "estimated":
                    flag_status = "no_evidence"
                    cell_id = None if cell is None else cell.id
                elif cell.positive_penalty_weight > 0:
                    flag_status = "penalized_positive_correlation"
                    cell_id = cell.id
                else:
                    flag_status = "not_empirically_positive"
                    cell_id = cell.id
                conn.execute(
                    "INSERT INTO correlation_aware_unified_pair_flags "
                    "(correlation_aware_unified_run_id, ats_candidate_id, "
                    "total_candidate_id, game_id, relation_code, correlation_cell_id, "
                    "penalty_applied, status, generated_at, provenance) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        ats.id,
                        total.id,
                        game_id,
                        relation,
                        cell_id,
                        source_ranked.penalty,
                        flag_status,
                        generated,
                        provenance,
                    ),
                )
            candidates = _candidate_rows(conn, run_id)
            flags = tuple(
                CorrelationAwareUnifiedPairFlag(*row)
                for row in conn.execute(
                    f"SELECT {_PAIR_COLUMNS} FROM correlation_aware_unified_pair_flags "
                    "WHERE correlation_aware_unified_run_id = ? ORDER BY game_id",
                    (run_id,),
                )
            )
            fifth = candidates[4].adjusted_score if len(candidates) >= 6 else None
            sixth = candidates[5].adjusted_score if len(candidates) >= 6 else None
            ledger_hash = _sha256(
                {
                    "run_id": run_id,
                    "candidates": [asdict(item) for item in candidates],
                    "pair_flags": [asdict(item) for item in flags],
                }
            )
            conn.execute(
                "INSERT INTO correlation_aware_unified_completions "
                "(correlation_aware_unified_run_id, candidate_count, selected_count, "
                "same_game_top_five_pair_count, rank_five_score, rank_six_score, "
                "cutoff_gap, ledger_sha256, completed_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run_id,
                    len(candidates),
                    min(len(candidates), TOP_FIVE_COUNT),
                    len(flags),
                    fifth,
                    sixth,
                    None if fifth is None else fifth - sixth,
                    ledger_hash,
                    generated,
                ),
            )
            return _get_result(conn, run_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("correlation-aware unified Top-5", exc) from exc


def _candidate_rows(
    conn: sqlite3.Connection, run_id: int
) -> tuple[CorrelationAwareUnifiedCandidate, ...]:
    output = []
    for row in conn.execute(
        f"SELECT {_CANDIDATE_COLUMNS} FROM correlation_aware_unified_candidates "
        "WHERE correlation_aware_unified_run_id = ? ORDER BY pool_rank",
        (run_id,),
    ):
        values = list(row)
        values[18] = bool(values[18])
        output.append(CorrelationAwareUnifiedCandidate(*values))
    return tuple(output)
