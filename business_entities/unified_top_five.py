"""Shadow-only cross-market Top-5 candidate ranking.

ATS pick identity remains in ``contest_picks``.  Totals identity remains in
``total_card_candidates``.  This module records typed references to either
market and compares only calibrated selection probabilities—never raw point
edges from unlike markets.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime

from business_entities.cards import get_contest_card, list_contest_picks
from business_entities.common import (
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    integer,
    number,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)
from business_entities.totals import (
    TotalCardCandidate,
    get_total_shadow_card_result,
    list_total_card_candidates,
)
from contest_lines import get_effective_locked_line_as_of


TOP_FIVE_COUNT = 5
CANDIDATE_SCORE_METRIC = "calibrated_selection_probability"
ORDERING_METHOD = "score_desc_market_type_asc_source_id_asc"


@dataclass(frozen=True)
class UnifiedTopFivePolicy:
    policy_key: str
    policy_version: str
    effective_at: datetime
    created_by: str
    provenance: str
    allow_multiple_per_game: bool = False


@dataclass(frozen=True)
class RecordedUnifiedTopFivePolicy:
    id: int
    policy_key: str
    policy_version: str
    top_five_count: int
    allow_multiple_per_game: bool
    candidate_score_metric: str
    ordering_method: str
    status: str
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class AtsUnifiedCandidateInput:
    contest_pick_id: int
    calibrated_probability: float
    reliability_policy_version: str


@dataclass(frozen=True)
class UnifiedTopFiveRun:
    id: int
    run_key: str
    contest_card_id: int
    total_shadow_card_id: int
    unified_top_five_policy_id: int
    status: str
    candidate_input_sha256: str
    generated_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class UnifiedTopFiveCandidate:
    id: int
    candidate_key: str
    unified_top_five_run_id: int
    market_type: str
    game_id: int
    contest_pick_id: int | None
    total_card_candidate_id: int | None
    calibrated_probability: float
    candidate_score: float
    reliability_policy_version: str
    pool_rank: int
    top_five_rank: int | None
    is_top_five: bool
    generated_at: str
    provenance: str


@dataclass(frozen=True)
class UnifiedTopFiveCompletion:
    unified_top_five_run_id: int
    candidate_count: int
    selected_count: int
    ledger_sha256: str
    completed_at: str


@dataclass(frozen=True)
class UnifiedTopFiveResult:
    run: UnifiedTopFiveRun
    candidates: tuple[UnifiedTopFiveCandidate, ...]
    completion: UnifiedTopFiveCompletion
    replayed: bool

    @property
    def top_five(self) -> tuple[UnifiedTopFiveCandidate, ...]:
        return tuple(
            sorted(
                (item for item in self.candidates if item.is_top_five),
                key=lambda item: item.top_five_rank or 0,
            )
        )


@dataclass(frozen=True)
class _PoolInput:
    market_type: str
    game_id: int
    source_id: int
    contest_pick_id: int | None
    total_card_candidate_id: int | None
    calibrated_probability: float
    reliability_policy_version: str


_POLICY_COLUMNS = (
    "id, policy_key, policy_version, top_five_count, allow_multiple_per_game, "
    "candidate_score_metric, ordering_method, status, effective_at, created_by, "
    "provenance"
)
_RUN_COLUMNS = (
    "id, run_key, contest_card_id, total_shadow_card_id, "
    "unified_top_five_policy_id, status, candidate_input_sha256, generated_at, "
    "created_by, provenance"
)
_CANDIDATE_COLUMNS = (
    "id, candidate_key, unified_top_five_run_id, market_type, game_id, "
    "contest_pick_id, total_card_candidate_id, calibrated_probability, "
    "candidate_score, reliability_policy_version, pool_rank, top_five_rank, "
    "is_top_five, generated_at, provenance"
)
_COMPLETION_COLUMNS = (
    "unified_top_five_run_id, candidate_count, selected_count, ledger_sha256, "
    "completed_at"
)


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def get_unified_top_five_policy(
    conn: sqlite3.Connection, policy_id: int
) -> RecordedUnifiedTopFivePolicy:
    row = conn.execute(
        f"SELECT {_POLICY_COLUMNS} FROM unified_top_five_policies WHERE id = ?",
        (integer(policy_id, "policy_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"unified Top-5 policy does not exist: {policy_id}")
    values = list(row)
    values[4] = bool(values[4])
    return RecordedUnifiedTopFivePolicy(*values)


def register_unified_top_five_policy(
    conn: sqlite3.Connection, policy: UnifiedTopFivePolicy
) -> RecordedUnifiedTopFivePolicy:
    if not isinstance(policy, UnifiedTopFivePolicy):
        raise BusinessEntityError("policy must be a UnifiedTopFivePolicy")
    if not isinstance(policy.allow_multiple_per_game, bool):
        raise BusinessEntityError("allow_multiple_per_game must be boolean")
    requested = (
        required_text(policy.policy_key, "policy.policy_key"),
        required_text(policy.policy_version, "policy.policy_version"),
        TOP_FIVE_COUNT,
        int(policy.allow_multiple_per_game),
        CANDIDATE_SCORE_METRIC,
        ORDERING_METHOD,
        "shadow",
        utc_timestamp(policy.effective_at, "policy.effective_at"),
        required_text(policy.created_by, "policy.created_by"),
        required_text(policy.provenance, "policy.provenance"),
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM unified_top_five_policies "
                "WHERE policy_key = ? OR policy_version = ? "
                "ORDER BY policy_key = ? DESC LIMIT 1",
                (requested[0], requested[1], requested[0]),
            ).fetchone()
            if row is not None:
                if tuple(row[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "unified Top-5 policy key/version has different immutable values"
                    )
                return get_unified_top_five_policy(conn, row[0])
            cursor = conn.execute(
                "INSERT INTO unified_top_five_policies "
                "(policy_key, policy_version, top_five_count, "
                "allow_multiple_per_game, candidate_score_metric, ordering_method, "
                "status, effective_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            return get_unified_top_five_policy(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("unified Top-5 policy", exc) from exc


def _get_run(conn: sqlite3.Connection, run_id: int) -> UnifiedTopFiveRun:
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM unified_top_five_runs WHERE id = ?",
        (integer(run_id, "run_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"unified Top-5 run does not exist: {run_id}")
    return UnifiedTopFiveRun(*row)


def list_unified_top_five_candidates(
    conn: sqlite3.Connection, run_id: int
) -> tuple[UnifiedTopFiveCandidate, ...]:
    result: list[UnifiedTopFiveCandidate] = []
    for row in conn.execute(
        f"SELECT {_CANDIDATE_COLUMNS} FROM unified_top_five_candidates "
        "WHERE unified_top_five_run_id = ? ORDER BY pool_rank",
        (integer(run_id, "run_id", 1),),
    ):
        values = list(row)
        values[12] = bool(values[12])
        result.append(UnifiedTopFiveCandidate(*values))
    return tuple(result)


def _get_completion(
    conn: sqlite3.Connection, run_id: int
) -> UnifiedTopFiveCompletion:
    row = conn.execute(
        f"SELECT {_COMPLETION_COLUMNS} FROM unified_top_five_completions "
        "WHERE unified_top_five_run_id = ?",
        (integer(run_id, "run_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"unified Top-5 run is not complete: {run_id}")
    return UnifiedTopFiveCompletion(*row)


def get_unified_top_five_result(
    conn: sqlite3.Connection, run_id: int, *, replayed: bool = False
) -> UnifiedTopFiveResult:
    return UnifiedTopFiveResult(
        run=_get_run(conn, run_id),
        candidates=list_unified_top_five_candidates(conn, run_id),
        completion=_get_completion(conn, run_id),
        replayed=replayed,
    )


def _probability(value: float | int, field: str) -> float:
    probability = number(value, field)
    if not 0.5 <= probability <= 1:
        raise BusinessEntityError(f"{field} must be between 0.5 and 1")
    return probability


def _ats_pool(
    conn: sqlite3.Connection,
    contest_card_id: int,
    inputs: tuple[AtsUnifiedCandidateInput, ...],
) -> tuple[_PoolInput, ...]:
    card = get_contest_card(conn, contest_card_id)
    picks = list_contest_picks(conn, contest_card_id)
    by_id: dict[int, AtsUnifiedCandidateInput] = {}
    for item in inputs:
        if not isinstance(item, AtsUnifiedCandidateInput):
            raise BusinessEntityError("ATS candidates must be AtsUnifiedCandidateInput")
        pick_id = integer(item.contest_pick_id, "contest_pick_id", 1)
        if pick_id in by_id:
            raise BusinessEntityError("duplicate ATS candidate identity")
        by_id[pick_id] = item
    expected_ids = {pick.id for pick in picks}
    if set(by_id) != expected_ids:
        missing = sorted(expected_ids - set(by_id))
        unknown = sorted(set(by_id) - expected_ids)
        raise BusinessEntityError(
            f"ATS calibrated inputs must cover every card pick; missing={missing}, "
            f"unknown={unknown}"
        )

    generated_at = datetime.fromisoformat(card.generated_at)
    pool: list[_PoolInput] = []
    for pick in picks:
        if pick.selected_side not in ("home", "away"):
            raise BusinessEntityError("unified Top-5 ATS candidates require a selected side")
        line = get_effective_locked_line_as_of(conn, pick.locked_line_id, generated_at)
        if line.game_id is None:
            raise BusinessEntityError("unified ATS candidate lacks game identity")
        item = by_id[pick.id]
        pool.append(
            _PoolInput(
                market_type="ATS",
                game_id=line.game_id,
                source_id=pick.id,
                contest_pick_id=pick.id,
                total_card_candidate_id=None,
                calibrated_probability=_probability(
                    item.calibrated_probability,
                    f"ATS pick {pick.id} calibrated_probability",
                ),
                reliability_policy_version=required_text(
                    item.reliability_policy_version,
                    f"ATS pick {pick.id} reliability_policy_version",
                ),
            )
        )
    return tuple(pool)


def _total_pool(candidates: tuple[TotalCardCandidate, ...]) -> tuple[_PoolInput, ...]:
    return tuple(
        _PoolInput(
            market_type="TOTAL",
            game_id=item.game_id,
            source_id=item.id,
            contest_pick_id=None,
            total_card_candidate_id=item.id,
            calibrated_probability=_probability(
                item.selected_probability,
                f"total candidate {item.id} selected_probability",
            ),
            reliability_policy_version=item.reliability_policy_version,
        )
        for item in candidates
    )


def _assert_before_kickoff(
    conn: sqlite3.Connection, game_id: int, generated_at: str
) -> None:
    row = conn.execute(
        "SELECT start_date FROM games WHERE game_id = ?", (game_id,)
    ).fetchone()
    if row is None or row[0] is None or timestamp_on_or_before(
        conn, row[0], generated_at
    ):
        raise BusinessEntityError(
            f"unified Top-5 must be generated before kickoff for game {game_id}"
        )


def generate_unified_top_five(
    conn: sqlite3.Connection,
    *,
    run_key: str,
    contest_card_id: int,
    total_shadow_card_id: int,
    unified_top_five_policy_id: int,
    ats_candidates: tuple[AtsUnifiedCandidateInput, ...],
    generated_at: datetime,
    created_by: str,
    provenance: str,
) -> UnifiedTopFiveResult:
    """Build a deterministic mixed-market Top-5 candidate pool in shadow only."""
    run_key = required_text(run_key, "run_key")
    contest_card_id = integer(contest_card_id, "contest_card_id", 1)
    total_shadow_card_id = integer(total_shadow_card_id, "total_shadow_card_id", 1)
    unified_top_five_policy_id = integer(
        unified_top_five_policy_id, "unified_top_five_policy_id", 1
    )
    generated_at_value = utc_timestamp(generated_at, "generated_at")
    created_by = required_text(created_by, "created_by")
    provenance = required_text(provenance, "provenance")

    ats_card = get_contest_card(conn, contest_card_id)
    total_result = get_total_shadow_card_result(conn, total_shadow_card_id)
    policy = get_unified_top_five_policy(conn, unified_top_five_policy_id)
    if ats_card.contest_id != total_result.card.contest_id:
        raise BusinessEntityError("ATS and totals cards must belong to the same contest")
    if not timestamp_on_or_before(conn, ats_card.generated_at, generated_at_value):
        raise BusinessEntityError("unified run cannot precede the ATS card")
    if not timestamp_on_or_before(
        conn, total_result.card.generated_at, generated_at_value
    ):
        raise BusinessEntityError("unified run cannot precede the totals card")
    if not timestamp_on_or_before(conn, policy.effective_at, generated_at_value):
        raise BusinessEntityError("unified Top-5 policy is not yet effective")

    pool = _ats_pool(conn, contest_card_id, ats_candidates) + _total_pool(
        total_result.candidates
    )
    for item in pool:
        _assert_before_kickoff(conn, item.game_id, generated_at_value)
    ordered = tuple(
        sorted(
            pool,
            key=lambda item: (
                -item.calibrated_probability,
                item.market_type,
                item.source_id,
            ),
        )
    )

    selected: list[_PoolInput] = []
    selected_games: set[int] = set()
    for item in ordered:
        if len(selected) == TOP_FIVE_COUNT:
            break
        if not policy.allow_multiple_per_game and item.game_id in selected_games:
            continue
        selected.append(item)
        selected_games.add(item.game_id)
    top_rank = {
        (item.market_type, item.source_id): index
        for index, item in enumerate(selected, start=1)
    }
    input_hash = _canonical_sha256(
        {
            "run_key": run_key,
            "contest_card_id": contest_card_id,
            "total_shadow_card_id": total_shadow_card_id,
            "total_ledger_sha256": total_result.completion.ledger_sha256,
            "unified_top_five_policy_id": unified_top_five_policy_id,
            "generated_at": generated_at_value,
            "ats_candidates": [asdict(item) for item in ats_candidates],
            "ordered_candidate_inputs": [asdict(item) for item in ordered],
        }
    )

    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM unified_top_five_runs WHERE run_key = ?",
                (run_key,),
            ).fetchone()
            requested_run = (
                run_key,
                contest_card_id,
                total_shadow_card_id,
                unified_top_five_policy_id,
                "shadow",
                input_hash,
                generated_at_value,
                created_by,
                provenance,
            )
            if row is not None:
                if tuple(row[1:]) != requested_run:
                    raise BusinessEntityConflictError(
                        "unified Top-5 run key has different immutable values"
                    )
                return get_unified_top_five_result(conn, row[0], replayed=True)

            cursor = conn.execute(
                "INSERT INTO unified_top_five_runs "
                "(run_key, contest_card_id, total_shadow_card_id, "
                "unified_top_five_policy_id, status, candidate_input_sha256, "
                "generated_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested_run,
            )
            run_id = cursor.lastrowid
            for pool_rank, item in enumerate(ordered, start=1):
                selected_rank = top_rank.get((item.market_type, item.source_id))
                conn.execute(
                    "INSERT INTO unified_top_five_candidates "
                    "(candidate_key, unified_top_five_run_id, market_type, game_id, "
                    "contest_pick_id, total_card_candidate_id, calibrated_probability, "
                    "candidate_score, reliability_policy_version, pool_rank, "
                    "top_five_rank, is_top_five, generated_at, provenance) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{run_key}:{item.market_type}:{item.source_id}",
                        run_id,
                        item.market_type,
                        item.game_id,
                        item.contest_pick_id,
                        item.total_card_candidate_id,
                        item.calibrated_probability,
                        item.calibrated_probability,
                        item.reliability_policy_version,
                        pool_rank,
                        selected_rank,
                        int(selected_rank is not None),
                        generated_at_value,
                        provenance,
                    ),
                )
            candidates = list_unified_top_five_candidates(conn, run_id)
            ledger_hash = _canonical_sha256(
                {
                    "run_id": run_id,
                    "candidates": [asdict(item) for item in candidates],
                }
            )
            conn.execute(
                "INSERT INTO unified_top_five_completions "
                "(unified_top_five_run_id, candidate_count, selected_count, "
                "ledger_sha256, completed_at) VALUES (?, ?, ?, ?, ?)",
                (
                    run_id,
                    len(candidates),
                    len(selected),
                    ledger_hash,
                    generated_at_value,
                ),
            )
            return get_unified_top_five_result(conn, run_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("unified Top-5 run", exc) from exc
