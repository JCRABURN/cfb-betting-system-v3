"""Complete, versioned, immutable postgame audits for contest cards."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime
from collections.abc import Mapping

from contest_lines import get_effective_locked_line_as_of

from business_entities.audits import record_pick_audit
from business_entities.cards import ContestPick, get_contest_card, list_contest_picks
from business_entities.common import (
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    choice,
    integer,
    optional_text,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)
from business_entities.contextual_adjustments import get_pick_adjustment_snapshot


ATS_METHOD = "locked_home_spread"
CLV_METHOD = "selected_side_locked_to_close"
HOOK_METHOD = "half_point_decision"
KEY_NUMBER_METHOD = "absolute_margin_and_line_crossing"
SPREAD_BUCKET_METHOD = "absolute_locked_spread_v1"
MANUAL_ADJUSTMENT_METHOD = "frozen_card_adjustment_snapshot"
BACKDOOR_METHOD = "scoring_sequence_evidence_only"

KEY_NUMBERS = (3.0, 7.0, 10.0, 14.0)
SPREAD_BUCKETS = (
    ("pickem", "Locked spread is exactly pick'em."),
    ("under_3", "Absolute locked spread is below 3."),
    ("3_to_6_5", "Absolute locked spread is at least 3 and below 7."),
    ("7_to_9_5", "Absolute locked spread is at least 7 and below 10."),
    ("10_to_13_5", "Absolute locked spread is at least 10 and below 14."),
    ("14_plus", "Absolute locked spread is at least 14."),
)
FAILURE_TAXONOMY = (
    ("no_failure", "The contest pick won against the locked line."),
    ("push", "The contest pick pushed against the locked line."),
    ("model_backed_loss", "A model-backed contest pick lost."),
    ("fallback_loss", "A fallback contest pick lost."),
    ("hook_loss", "The contest pick lost by the half-point hook."),
    ("key_number_loss", "The final margin landed on a configured key number."),
    (
        "manual_adjustment_harmed",
        "A manual margin adjustment flipped the side and worsened its ATS result.",
    ),
)

_BACKDOOR_OUTCOMES = (
    "not_evaluated",
    "confirmed_backdoor_cover",
    "confirmed_not_backdoor",
)


@dataclass(frozen=True)
class PostgameAuditPolicy:
    policy_version: str
    effective_at: datetime
    created_by: str
    provenance: str


@dataclass(frozen=True)
class RecordedPostgameAuditPolicy:
    id: int
    policy_version: str
    ats_method: str
    clv_method: str
    hook_method: str
    key_number_method: str
    spread_bucket_method: str
    manual_adjustment_method: str
    backdoor_method: str
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class PostgameAuditRequest:
    closing_market_line_id: int
    backdoor_outcome: str = "not_evaluated"
    scoring_sequence_evidence: str | None = None


@dataclass(frozen=True)
class CardPostgameAuditRun:
    id: int
    audit_run_key: str
    card_id: int
    audit_policy_id: int
    sequence: int
    supersedes_run_id: int | None
    expected_pick_count: int
    audited_at: str
    source: str
    provenance: str


@dataclass(frozen=True)
class PickAuditDetail:
    audit_id: int
    audit_run_id: int
    audit_policy_id: int
    contest_pick_id: int
    game_id: int
    locked_line_id: int
    locked_line_correction_id: int | None
    locked_home_spread: float
    closing_market_line_id: int
    closing_home_spread: float
    closing_book: str
    final_home_points: int
    final_away_points: int
    actual_home_margin: int
    selected_side: str
    covered_margin: float
    ats_result: str
    clv_points: float
    hook_outcome: str
    landed_key_number: float | None
    key_number_outcome: str
    favorite_status: str
    location_status: str
    spread_bucket_code: str
    confidence: int
    rank: int | None
    is_top_five: bool
    raw_model_margin: float | None
    adjusted_model_margin: float | None
    raw_selected_side: str | None
    raw_ats_result: str | None
    manual_adjustment_count: int
    manual_margin_adjustment_total: float
    manual_confidence_adjustment_total: int
    manual_adjustment_effect: str
    backdoor_outcome: str
    scoring_sequence_evidence: str | None
    audited_at: str
    source: str
    provenance: str


@dataclass(frozen=True)
class PickAuditKeyNumberCrossing:
    audit_id: int
    audit_policy_id: int
    key_number: float
    direction: str


@dataclass(frozen=True)
class PickAuditFailure:
    audit_id: int
    audit_policy_id: int
    priority: int
    failure_code: str
    evidence: str


@dataclass(frozen=True)
class CardPostgameAuditCompletion:
    audit_run_id: int
    audit_count: int
    win_count: int
    loss_count: int
    push_count: int
    ledger_sha256: str
    completed_at: str
    provenance: str


@dataclass(frozen=True)
class PostgameAuditReport:
    audit_run_id: int
    expected_pick_count: int
    audit_count: int
    missing_pick_ids: tuple[int, ...]
    unexpected_pick_ids: tuple[int, ...]
    win_count: int
    loss_count: int
    push_count: int
    key_crossing_count: int
    failure_record_count: int
    ledger_sha256: str
    recorded_ledger_sha256: str | None

    @property
    def complete(self) -> bool:
        return (
            self.audit_count == self.expected_pick_count
            and not self.missing_pick_ids
            and not self.unexpected_pick_ids
            and self.audit_count == self.win_count + self.loss_count + self.push_count
            and self.recorded_ledger_sha256 == self.ledger_sha256
        )


@dataclass(frozen=True)
class CardPostgameAuditResult:
    run: CardPostgameAuditRun
    details: tuple[PickAuditDetail, ...]
    crossings: tuple[PickAuditKeyNumberCrossing, ...]
    failures: tuple[PickAuditFailure, ...]
    completion: CardPostgameAuditCompletion
    report: PostgameAuditReport


_POLICY_COLUMNS = (
    "id, policy_version, ats_method, clv_method, hook_method, "
    "key_number_method, spread_bucket_method, manual_adjustment_method, "
    "backdoor_method, effective_at, created_by, provenance"
)
_RUN_COLUMNS = (
    "id, audit_run_key, card_id, audit_policy_id, sequence, supersedes_run_id, "
    "expected_pick_count, audited_at, source, provenance"
)
_DETAIL_COLUMNS = (
    "audit_id, audit_run_id, audit_policy_id, contest_pick_id, game_id, "
    "locked_line_id, locked_line_correction_id, locked_home_spread, "
    "closing_market_line_id, closing_home_spread, closing_book, "
    "final_home_points, final_away_points, actual_home_margin, selected_side, "
    "covered_margin, ats_result, clv_points, hook_outcome, landed_key_number, "
    "key_number_outcome, favorite_status, location_status, spread_bucket_code, "
    "confidence, rank, is_top_five, raw_model_margin, adjusted_model_margin, "
    "raw_selected_side, raw_ats_result, manual_adjustment_count, "
    "manual_margin_adjustment_total, manual_confidence_adjustment_total, "
    "manual_adjustment_effect, backdoor_outcome, scoring_sequence_evidence, "
    "audited_at, source, provenance"
)
_DETAIL_PLACEHOLDERS = ", ".join("?" for _ in _DETAIL_COLUMNS.split(","))
_CROSSING_COLUMNS = "audit_id, audit_policy_id, key_number, direction"
_QUALIFIED_CROSSING_COLUMNS = ", ".join(
    f"crossing.{column.strip()}" for column in _CROSSING_COLUMNS.split(",")
)
_FAILURE_COLUMNS = "audit_id, audit_policy_id, priority, failure_code, evidence"
_QUALIFIED_FAILURE_COLUMNS = ", ".join(
    f"failure.{column.strip()}" for column in _FAILURE_COLUMNS.split(",")
)
_COMPLETION_COLUMNS = (
    "audit_run_id, audit_count, win_count, loss_count, push_count, "
    "ledger_sha256, completed_at, provenance"
)


def _validated_policy(policy: PostgameAuditPolicy) -> PostgameAuditPolicy:
    if not isinstance(policy, PostgameAuditPolicy):
        raise BusinessEntityError("audit_policy must be a PostgameAuditPolicy")
    return PostgameAuditPolicy(
        policy_version=required_text(policy.policy_version, "audit_policy.policy_version"),
        effective_at=datetime.fromisoformat(
            utc_timestamp(policy.effective_at, "audit_policy.effective_at")
        ),
        created_by=required_text(policy.created_by, "audit_policy.created_by"),
        provenance=required_text(policy.provenance, "audit_policy.provenance"),
    )


def get_postgame_audit_policy(
    conn: sqlite3.Connection, audit_policy_id: int
) -> RecordedPostgameAuditPolicy:
    row = conn.execute(
        f"SELECT {_POLICY_COLUMNS} FROM postgame_audit_policies WHERE id = ?",
        (integer(audit_policy_id, "audit_policy_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"postgame audit policy does not exist: {audit_policy_id}")
    return RecordedPostgameAuditPolicy(*row)


def register_postgame_audit_policy(
    conn: sqlite3.Connection, policy: PostgameAuditPolicy
) -> RecordedPostgameAuditPolicy:
    policy = _validated_policy(policy)
    requested = (
        policy.policy_version,
        ATS_METHOD,
        CLV_METHOD,
        HOOK_METHOD,
        KEY_NUMBER_METHOD,
        SPREAD_BUCKET_METHOD,
        MANUAL_ADJUSTMENT_METHOD,
        BACKDOOR_METHOD,
        policy.effective_at.isoformat(),
        policy.created_by,
        policy.provenance,
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM postgame_audit_policies "
                "WHERE policy_version = ?",
                (policy.policy_version,),
            ).fetchone()
            if row is not None:
                existing = RecordedPostgameAuditPolicy(*row)
                if tuple(row[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "postgame audit policy version has different immutable values"
                    )
                _assert_policy_definitions(conn, existing.id)
                return existing
            cursor = conn.execute(
                "INSERT INTO postgame_audit_policies "
                "(policy_version, ats_method, clv_method, hook_method, "
                "key_number_method, spread_bucket_method, manual_adjustment_method, "
                "backdoor_method, effective_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            policy_id = cursor.lastrowid
            conn.executemany(
                "INSERT INTO postgame_audit_key_numbers "
                "(audit_policy_id, priority, key_number) VALUES (?, ?, ?)",
                ((policy_id, priority, value) for priority, value in enumerate(KEY_NUMBERS, 1)),
            )
            conn.executemany(
                "INSERT INTO postgame_audit_spread_buckets "
                "(audit_policy_id, priority, bucket_code, description) VALUES (?, ?, ?, ?)",
                (
                    (policy_id, priority, code, description)
                    for priority, (code, description) in enumerate(SPREAD_BUCKETS, 1)
                ),
            )
            conn.executemany(
                "INSERT INTO postgame_audit_failure_taxonomy "
                "(audit_policy_id, priority, failure_code, description) VALUES (?, ?, ?, ?)",
                (
                    (policy_id, priority, code, description)
                    for priority, (code, description) in enumerate(FAILURE_TAXONOMY, 1)
                ),
            )
            return get_postgame_audit_policy(conn, policy_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("postgame audit policy", exc) from exc


def _assert_policy_definitions(conn: sqlite3.Connection, policy_id: int) -> None:
    key_numbers = tuple(
        row[0]
        for row in conn.execute(
            "SELECT key_number FROM postgame_audit_key_numbers "
            "WHERE audit_policy_id = ? ORDER BY priority",
            (policy_id,),
        )
    )
    buckets = tuple(
        tuple(row)
        for row in conn.execute(
            "SELECT bucket_code, description FROM postgame_audit_spread_buckets "
            "WHERE audit_policy_id = ? ORDER BY priority",
            (policy_id,),
        )
    )
    failures = tuple(
        tuple(row)
        for row in conn.execute(
            "SELECT failure_code, description FROM postgame_audit_failure_taxonomy "
            "WHERE audit_policy_id = ? ORDER BY priority",
            (policy_id,),
        )
    )
    if key_numbers != KEY_NUMBERS or buckets != SPREAD_BUCKETS or failures != FAILURE_TAXONOMY:
        raise BusinessEntityConflictError("postgame audit policy definitions changed")


def get_card_postgame_audit_run(
    conn: sqlite3.Connection, audit_run_id: int
) -> CardPostgameAuditRun:
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM card_postgame_audit_runs WHERE id = ?",
        (integer(audit_run_id, "audit_run_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"postgame audit run does not exist: {audit_run_id}")
    return CardPostgameAuditRun(*row)


def list_pick_audit_details(
    conn: sqlite3.Connection, audit_run_id: int
) -> tuple[PickAuditDetail, ...]:
    rows = conn.execute(
        f"SELECT {_DETAIL_COLUMNS} FROM pick_audit_details "
        "WHERE audit_run_id = ? ORDER BY contest_pick_id",
        (integer(audit_run_id, "audit_run_id", 1),),
    ).fetchall()
    details = []
    for row in rows:
        values = list(row)
        values[26] = bool(values[26])
        details.append(PickAuditDetail(*values))
    return tuple(details)


def list_pick_audit_key_number_crossings(
    conn: sqlite3.Connection, audit_run_id: int
) -> tuple[PickAuditKeyNumberCrossing, ...]:
    rows = conn.execute(
        f"SELECT {_QUALIFIED_CROSSING_COLUMNS} "
        "FROM pick_audit_key_number_crossings AS crossing "
        "JOIN pick_audit_details AS detail ON detail.audit_id = crossing.audit_id "
        "WHERE detail.audit_run_id = ? ORDER BY crossing.audit_id, crossing.key_number",
        (integer(audit_run_id, "audit_run_id", 1),),
    ).fetchall()
    return tuple(PickAuditKeyNumberCrossing(*row) for row in rows)


def list_pick_audit_failures(
    conn: sqlite3.Connection, audit_run_id: int
) -> tuple[PickAuditFailure, ...]:
    rows = conn.execute(
        f"SELECT {_QUALIFIED_FAILURE_COLUMNS} FROM pick_audit_failures AS failure "
        "JOIN pick_audit_details AS detail ON detail.audit_id = failure.audit_id "
        "WHERE detail.audit_run_id = ? ORDER BY failure.audit_id, failure.priority",
        (integer(audit_run_id, "audit_run_id", 1),),
    ).fetchall()
    return tuple(PickAuditFailure(*row) for row in rows)


def get_card_postgame_audit_completion(
    conn: sqlite3.Connection, audit_run_id: int
) -> CardPostgameAuditCompletion:
    row = conn.execute(
        f"SELECT {_COMPLETION_COLUMNS} FROM card_postgame_audit_completions "
        "WHERE audit_run_id = ?",
        (integer(audit_run_id, "audit_run_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"postgame audit run is incomplete: {audit_run_id}")
    return CardPostgameAuditCompletion(*row)


def _request(value: PostgameAuditRequest) -> PostgameAuditRequest:
    if not isinstance(value, PostgameAuditRequest):
        raise BusinessEntityError("audit requests must be PostgameAuditRequest values")
    closing_id = integer(value.closing_market_line_id, "closing_market_line_id", 1)
    backdoor = choice(value.backdoor_outcome, "backdoor_outcome", _BACKDOOR_OUTCOMES)
    evidence = optional_text(value.scoring_sequence_evidence, "scoring_sequence_evidence")
    if (backdoor == "not_evaluated") != (evidence is None):
        raise BusinessEntityError(
            "backdoor outcomes require scoring-sequence evidence and cannot be inferred"
        )
    return PostgameAuditRequest(closing_id, backdoor, evidence)


def _ats_result(selected_side: str, actual_margin: int, home_spread: float) -> tuple[float, str]:
    covered = actual_margin + home_spread
    if selected_side == "away":
        covered = -covered
    result = "win" if covered > 0 else "loss" if covered < 0 else "push"
    return covered, result


def _spread_bucket(home_spread: float) -> str:
    absolute = abs(home_spread)
    if absolute == 0:
        return "pickem"
    if absolute < 3:
        return "under_3"
    if absolute < 7:
        return "3_to_6_5"
    if absolute < 10:
        return "7_to_9_5"
    if absolute < 14:
        return "10_to_13_5"
    return "14_plus"


def _raw_side(raw_margin: float, home_spread: float) -> str:
    edge = raw_margin + home_spread
    return "home" if edge > 0 else "away" if edge < 0 else "tie"


def _manual_effect(
    *,
    adjustment_count: int,
    margin_total: float,
    confidence_total: int,
    raw_side: str,
    selected_side: str,
    raw_result: str | None,
    selected_result: str,
) -> str:
    if adjustment_count == 0:
        return "no_adjustment"
    if margin_total == 0 and confidence_total == 0:
        return "net_zero"
    if margin_total == 0:
        return "confidence_only"
    if raw_side == selected_side:
        return "side_unchanged"
    if raw_side == "tie":
        return "raw_tie_resolved"
    scores = {"loss": -1, "push": 0, "win": 1}
    delta = scores[selected_result] - scores[raw_result or "push"]
    if delta > 0:
        return "side_flip_helped"
    if delta < 0:
        return "side_flip_harmed"
    return "side_flip_neutral"


def _detail_values(
    conn: sqlite3.Connection,
    *,
    run: CardPostgameAuditRun,
    pick: ContestPick,
    request: PostgameAuditRequest,
) -> tuple[tuple[object, ...], tuple[float, ...], tuple[tuple[str, str], ...]]:
    line = get_effective_locked_line_as_of(
        conn, pick.locked_line_id, datetime.fromisoformat(pick.generated_at)
    )
    if line.game_id is None:
        raise BusinessEntityError(f"locked line {line.locked_line_id} has no game identity")
    game = conn.execute(
        "SELECT start_date, home_points, away_points, completed, neutral_site "
        "FROM games WHERE game_id = ?",
        (line.game_id,),
    ).fetchone()
    if (
        game is None
        or game[3] != 1
        or game[1] is None
        or game[2] is None
        or not timestamp_on_or_before(conn, game[0], run.audited_at)
    ):
        raise BusinessEntityError(f"game {line.game_id} is not complete as of the audit")
    closing = conn.execute(
        "SELECT game_id, home_spread, book, line_type, fetched_at "
        "FROM betting_lines WHERE id = ?",
        (request.closing_market_line_id,),
    ).fetchone()
    if (
        closing is None
        or closing[0] != line.game_id
        or closing[1] is None
        or closing[3] != "closing"
        or not timestamp_on_or_before(conn, pick.generated_at, closing[4])
        or not timestamp_on_or_before(conn, closing[4], game[0])
    ):
        raise BusinessEntityError(
            f"closing line {request.closing_market_line_id} is not a "
            f"pre-kickoff closing line for game {line.game_id}"
        )
    home_points = integer(game[1], "home_points", 0)
    away_points = integer(game[2], "away_points", 0)
    actual_margin = home_points - away_points
    covered_margin, ats_result = _ats_result(pick.selected_side, actual_margin, line.home_spread)
    closing_spread = float(closing[1])
    clv = round(
        line.home_spread - closing_spread
        if pick.selected_side == "home"
        else closing_spread - line.home_spread,
        2,
    )
    half_point = abs(line.home_spread * 2) % 2 == 1
    hook = (
        "won_by_hook" if half_point and abs(covered_margin) == 0.5 and ats_result == "win"
        else "lost_by_hook" if half_point and abs(covered_margin) == 0.5 and ats_result == "loss"
        else "not_hook"
    )
    landed_key = float(abs(actual_margin)) if float(abs(actual_margin)) in KEY_NUMBERS else None
    key_outcome = "not_key_number" if landed_key is None else f"key_number_{ats_result}"
    favorite = (
        "pickem" if line.home_spread == 0
        else "favorite" if (line.home_spread < 0) == (pick.selected_side == "home")
        else "underdog"
    )
    location = "neutral" if game[4] == 1 else pick.selected_side

    raw_margin = adjusted_margin = None
    raw_selected_side = raw_result = None
    adjustment_count = confidence_total = 0
    margin_total = 0.0
    manual_effect = "no_adjustment"
    if pick.model_prediction_id is not None:
        snapshot = get_pick_adjustment_snapshot(conn, pick.id)
        if snapshot.model_prediction_id != pick.model_prediction_id:
            raise BusinessEntityError("adjustment snapshot and pick prediction differ")
        raw_margin = snapshot.raw_model_margin
        adjusted_margin = snapshot.adjusted_model_margin
        adjustment_count = snapshot.adjustment_count
        margin_total = snapshot.margin_adjustment_total
        confidence_total = snapshot.confidence_adjustment_total
        raw_selected_side = _raw_side(raw_margin, line.home_spread)
        if raw_selected_side != "tie":
            _, raw_result = _ats_result(raw_selected_side, actual_margin, line.home_spread)
        manual_effect = _manual_effect(
            adjustment_count=adjustment_count,
            margin_total=margin_total,
            confidence_total=confidence_total,
            raw_side=raw_selected_side,
            selected_side=pick.selected_side,
            raw_result=raw_result,
            selected_result=ats_result,
        )

    values = (
        run.id,
        run.audit_policy_id,
        pick.id,
        line.game_id,
        line.locked_line_id,
        line.correction_id,
        line.home_spread,
        request.closing_market_line_id,
        closing_spread,
        closing[2],
        home_points,
        away_points,
        actual_margin,
        pick.selected_side,
        covered_margin,
        ats_result,
        clv,
        hook,
        landed_key,
        key_outcome,
        favorite,
        location,
        _spread_bucket(line.home_spread),
        pick.confidence,
        pick.rank,
        int(pick.is_top_five),
        raw_margin,
        adjusted_margin,
        raw_selected_side,
        raw_result,
        adjustment_count,
        margin_total,
        confidence_total,
        manual_effect,
        request.backdoor_outcome,
        request.scoring_sequence_evidence,
        run.audited_at,
        run.source,
        run.provenance,
    )
    low, high = sorted((abs(line.home_spread), abs(closing_spread)))
    crossings = tuple(
        key for key in KEY_NUMBERS if low <= key <= high and low != high and clv != 0
    )
    primary = (
        "no_failure" if ats_result == "win"
        else "push" if ats_result == "push"
        else "fallback_loss" if pick.model_prediction_id is None
        else "model_backed_loss"
    )
    failures = [(primary, f"ats_result={ats_result};covered_margin={covered_margin}")]
    if hook == "lost_by_hook":
        failures.append(
            (
                "hook_loss",
                f"locked_home_spread={line.home_spread};"
                f"covered_margin={covered_margin}",
            )
        )
    if key_outcome == "key_number_loss":
        failures.append(
            (
                "key_number_loss",
                f"actual_home_margin={actual_margin};key_number={landed_key}",
            )
        )
    if manual_effect == "side_flip_harmed":
        failures.append(
            (
                "manual_adjustment_harmed",
                f"raw_result={raw_result};adjusted_result={ats_result};"
                f"margin_adjustment={margin_total}",
            )
        )
    return values, crossings, tuple(failures)


def _ledger_sha256(
    details: tuple[PickAuditDetail, ...],
    crossings: tuple[PickAuditKeyNumberCrossing, ...],
    failures: tuple[PickAuditFailure, ...],
) -> str:
    canonical = json.dumps(
        {
            "details": [asdict(item) for item in details],
            "key_number_crossings": [asdict(item) for item in crossings],
            "failures": [asdict(item) for item in failures],
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def inspect_postgame_audit_run(
    conn: sqlite3.Connection, audit_run_id: int
) -> PostgameAuditReport:
    run = get_card_postgame_audit_run(conn, audit_run_id)
    details = list_pick_audit_details(conn, run.id)
    crossings = list_pick_audit_key_number_crossings(conn, run.id)
    failures = list_pick_audit_failures(conn, run.id)
    expected = {
        row[0]
        for row in conn.execute("SELECT id FROM contest_picks WHERE card_id = ?", (run.card_id,))
    }
    actual = {detail.contest_pick_id for detail in details}
    try:
        completion = get_card_postgame_audit_completion(conn, run.id)
        recorded_hash = completion.ledger_sha256
    except BusinessEntityError:
        recorded_hash = None
    return PostgameAuditReport(
        audit_run_id=run.id,
        expected_pick_count=run.expected_pick_count,
        audit_count=len(details),
        missing_pick_ids=tuple(sorted(expected - actual)),
        unexpected_pick_ids=tuple(sorted(actual - expected)),
        win_count=sum(item.ats_result == "win" for item in details),
        loss_count=sum(item.ats_result == "loss" for item in details),
        push_count=sum(item.ats_result == "push" for item in details),
        key_crossing_count=len(crossings),
        failure_record_count=len(failures),
        ledger_sha256=_ledger_sha256(details, crossings, failures),
        recorded_ledger_sha256=recorded_hash,
    )


def validate_postgame_audit_run(
    conn: sqlite3.Connection, audit_run_id: int
) -> PostgameAuditReport:
    report = inspect_postgame_audit_run(conn, audit_run_id)
    if not report.complete:
        raise BusinessEntityError(
            "postgame audit is incomplete or its immutable ledger does not match"
        )
    return report


def _load_result(conn: sqlite3.Connection, run_id: int) -> CardPostgameAuditResult:
    run = get_card_postgame_audit_run(conn, run_id)
    details = list_pick_audit_details(conn, run.id)
    crossings = list_pick_audit_key_number_crossings(conn, run.id)
    failures = list_pick_audit_failures(conn, run.id)
    completion = get_card_postgame_audit_completion(conn, run.id)
    report = validate_postgame_audit_run(conn, run.id)
    return CardPostgameAuditResult(run, details, crossings, failures, completion, report)


def audit_contest_card(
    conn: sqlite3.Connection,
    *,
    audit_run_key: str,
    card_id: int,
    audit_policy: PostgameAuditPolicy,
    requests_by_locked_line_id: Mapping[int, PostgameAuditRequest],
    source: str,
    provenance: str,
    audited_at: datetime | None = None,
) -> CardPostgameAuditResult:
    """Grade every pick atomically and seal a reproducible audit ledger."""
    audit_run_key = required_text(audit_run_key, "audit_run_key")
    card_id = integer(card_id, "card_id", 1)
    audit_policy = _validated_policy(audit_policy)
    source = required_text(source, "source")
    provenance = required_text(provenance, "provenance")
    card = get_contest_card(conn, card_id)
    picks = list_contest_picks(conn, card_id)
    if not picks:
        raise BusinessEntityError("postgame audits require a card with picks")
    locked_line_ids = {
        row[0]
        for row in conn.execute(
            "SELECT id FROM contest_locked_lines "
            "WHERE contest_id = ? "
            "AND julianday(locked_at) <= julianday(?)",
            (card.contest_id, card.generated_at),
        )
    }
    pick_line_ids = {pick.locked_line_id for pick in picks}
    expected_top_five = min(5, len(picks))
    recorded_ranks = {pick.rank for pick in picks if pick.is_top_five}
    if (
        pick_line_ids != locked_line_ids
        or sum(pick.is_top_five for pick in picks) != expected_top_five
        or recorded_ranks != set(range(1, expected_top_five + 1))
    ):
        raise BusinessEntityError(
            "postgame audits require a complete card with exact Top 5 ranks"
        )
    if any(pick.selected_side not in ("home", "away") or pick.confidence is None for pick in picks):
        raise BusinessEntityError("postgame audits require a side and Confidence for every pick")
    expected_ids = {pick.locked_line_id for pick in picks}
    if not isinstance(requests_by_locked_line_id, Mapping):
        raise BusinessEntityError("requests_by_locked_line_id must be a mapping")
    requested_ids = {
        integer(line_id, "requests_by_locked_line_id key", 1)
        for line_id in requests_by_locked_line_id
    }
    if requested_ids != expected_ids:
        raise BusinessEntityError(
            "audit requests must cover every locked line exactly; "
            f"missing={sorted(expected_ids - requested_ids)}, "
            f"unexpected={sorted(requested_ids - expected_ids)}"
        )
    requests = {line_id: _request(requests_by_locked_line_id[line_id]) for line_id in expected_ids}

    existing_row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM card_postgame_audit_runs WHERE audit_run_key = ?",
        (audit_run_key,),
    ).fetchone()
    if existing_row is not None:
        existing = CardPostgameAuditRun(*existing_row)
        recorded_policy = get_postgame_audit_policy(conn, existing.audit_policy_id)
        requested_time = (
            existing.audited_at
            if audited_at is None
            else utc_timestamp(audited_at, "audited_at")
        )
        if (
            existing.card_id != card_id
            or existing.expected_pick_count != len(picks)
            or existing.audited_at != requested_time
            or existing.source != source
            or existing.provenance != provenance
            or recorded_policy.policy_version != audit_policy.policy_version
        ):
            raise BusinessEntityConflictError("audit run key has different immutable values")
        replay_policy = register_postgame_audit_policy(conn, audit_policy)
        if replay_policy.id != recorded_policy.id:
            raise BusinessEntityConflictError(
                "audit run replay has a different immutable policy"
            )
        details = {
            detail.contest_pick_id: detail
            for detail in list_pick_audit_details(conn, existing.id)
        }
        for pick in picks:
            detail = details.get(pick.id)
            request = requests[pick.locked_line_id]
            if detail is None or (
                detail.closing_market_line_id,
                detail.backdoor_outcome,
                detail.scoring_sequence_evidence,
            ) != (
                request.closing_market_line_id,
                request.backdoor_outcome,
                request.scoring_sequence_evidence,
            ):
                raise BusinessEntityConflictError(
                    "audit run replay has different immutable requests"
                )
        return _load_result(conn, existing.id)

    audited_at_value = utc_timestamp(audited_at, "audited_at")
    try:
        with atomic(conn):
            recorded_policy = register_postgame_audit_policy(conn, audit_policy)
            if not timestamp_on_or_before(conn, recorded_policy.effective_at, audited_at_value):
                raise BusinessEntityError("postgame audit policy is not yet effective")
            latest = conn.execute(
                "SELECT id, sequence FROM card_postgame_audit_runs "
                "WHERE card_id = ? ORDER BY sequence DESC LIMIT 1",
                (card_id,),
            ).fetchone()
            supersedes = latest[0] if latest is not None else None
            sequence = latest[1] + 1 if latest is not None else 1
            cursor = conn.execute(
                "INSERT INTO card_postgame_audit_runs "
                "(audit_run_key, card_id, audit_policy_id, sequence, supersedes_run_id, "
                "expected_pick_count, audited_at, source, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    audit_run_key,
                    card_id,
                    recorded_policy.id,
                    sequence,
                    supersedes,
                    len(picks),
                    audited_at_value,
                    source,
                    provenance,
                ),
            )
            run = get_card_postgame_audit_run(conn, cursor.lastrowid)
            for pick in picks:
                values, crossing_keys, failure_values = _detail_values(
                    conn, run=run, pick=pick, request=requests[pick.locked_line_id]
                )
                base_closing_id = values[7] if pick.model_prediction_id is not None else None
                base_clv = values[16] if pick.model_prediction_id is not None else None
                base = record_pick_audit(
                    conn,
                    audit_key=f"{audit_run_key}:pick:{pick.id}",
                    contest_pick_id=pick.id,
                    audit_status="final",
                    result=values[15],
                    final_home_points=values[10],
                    final_away_points=values[11],
                    closing_market_line_id=base_closing_id,
                    clv_points=base_clv,
                    policy_version=recorded_policy.policy_version,
                    source=source,
                    provenance=provenance,
                    audited_at=datetime.fromisoformat(run.audited_at),
                )
                conn.execute(
                    "INSERT INTO pick_audit_details "
                    f"({_DETAIL_COLUMNS}) VALUES ({_DETAIL_PLACEHOLDERS})",
                    (base.id, *values),
                )
                for key_number in crossing_keys:
                    conn.execute(
                        "INSERT INTO pick_audit_key_number_crossings "
                        "(audit_id, audit_policy_id, key_number, direction) VALUES (?, ?, ?, ?)",
                        (
                            base.id,
                            recorded_policy.id,
                            key_number,
                            "favorable" if values[16] > 0 else "adverse",
                        ),
                    )
                for priority, (failure_code, evidence) in enumerate(failure_values, 1):
                    conn.execute(
                        "INSERT INTO pick_audit_failures "
                        "(audit_id, audit_policy_id, priority, failure_code, "
                        "evidence) VALUES (?, ?, ?, ?, ?)",
                        (base.id, recorded_policy.id, priority, failure_code, evidence),
                    )
            details = list_pick_audit_details(conn, run.id)
            crossings = list_pick_audit_key_number_crossings(conn, run.id)
            failures = list_pick_audit_failures(conn, run.id)
            counts = {
                result: sum(detail.ats_result == result for detail in details)
                for result in ("win", "loss", "push")
            }
            ledger_hash = _ledger_sha256(details, crossings, failures)
            conn.execute(
                "INSERT INTO card_postgame_audit_completions "
                "(audit_run_id, audit_count, win_count, loss_count, push_count, "
                "ledger_sha256, completed_at, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.id,
                    len(details),
                    counts["win"],
                    counts["loss"],
                    counts["push"],
                    ledger_hash,
                    run.audited_at,
                    provenance,
                ),
            )
            return _load_result(conn, run.id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("complete postgame audit", exc) from exc
