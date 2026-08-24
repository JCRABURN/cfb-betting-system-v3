"""Immutable settlement, CLV, and coverage audits for sportsbook decisions."""

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
from business_entities.live_sportsbook import (
    SportsbookRecommendationEvaluation,
    get_sportsbook_recommendation_policy,
)


SETTLEMENT_METHOD = "selected_side_offered_spread_v1"
CLV_METHOD = "selected_side_offered_to_same_book_close_v1"


@dataclass(frozen=True)
class SportsbookPostgameAuditRun:
    id: int
    audit_run_key: str
    season: int
    week: int
    policy_id: int
    policy_version: str
    sequence: int
    supersedes_run_id: int | None
    expected_evaluation_count: int
    expected_bet_count: int
    audited_at: str
    source: str
    provenance: str


@dataclass(frozen=True)
class SportsbookPostgameAuditDetail:
    id: int
    audit_run_id: int
    evaluation_id: int
    recommendation_id: int
    market_offer_id: int
    game_id: int
    decision: str
    lifecycle_state: str
    selected_side: str
    bookmaker: str
    offered_spread: float
    offered_price: int
    stake_units: float
    final_home_points: int
    final_away_points: int
    actual_home_margin: int
    covered_margin: float
    ats_result: str
    realized_profit_units: float
    closing_designation_id: int | None
    closing_evidence_status: str
    closing_selected_spread: float | None
    closing_selected_price: int | None
    clv_points: float | None
    clv_evidence_status: str
    graded_at: str
    source: str
    provenance: str


@dataclass(frozen=True)
class SportsbookPostgameAuditCompletion:
    audit_run_id: int
    audit_count: int
    bet_count: int
    no_bet_count: int
    win_count: int
    loss_count: int
    push_count: int
    clv_graded_count: int
    missing_clv_count: int
    total_staked_units: float
    realized_profit_units: float
    roi_percent: float | None
    average_clv_points: float | None
    ledger_sha256: str
    completed_at: str
    provenance: str


@dataclass(frozen=True)
class SportsbookPostgameAuditReport:
    audit_run_id: int
    expected_evaluation_count: int
    expected_bet_count: int
    audit_count: int
    missing_evaluation_ids: tuple[int, ...]
    unexpected_evaluation_ids: tuple[int, ...]
    bet_count: int
    no_bet_count: int
    clv_graded_count: int
    missing_clv_count: int
    ledger_sha256: str
    recorded_ledger_sha256: str | None

    @property
    def complete(self) -> bool:
        return (
            self.audit_count == self.expected_evaluation_count
            and self.bet_count == self.expected_bet_count
            and self.audit_count == self.bet_count + self.no_bet_count
            and not self.missing_evaluation_ids
            and not self.unexpected_evaluation_ids
            and self.audit_count == self.clv_graded_count + self.missing_clv_count
            and self.ledger_sha256 == self.recorded_ledger_sha256
        )

    @property
    def all_clv_available(self) -> bool:
        return self.complete and self.missing_clv_count == 0


@dataclass(frozen=True)
class SportsbookPostgameAuditResult:
    run: SportsbookPostgameAuditRun
    details: tuple[SportsbookPostgameAuditDetail, ...]
    completion: SportsbookPostgameAuditCompletion
    report: SportsbookPostgameAuditReport


_RUN_COLUMNS = (
    "id, audit_run_key, season, week, policy_id, policy_version, sequence, "
    "supersedes_run_id, expected_evaluation_count, expected_bet_count, "
    "audited_at, source, provenance"
)
_DETAIL_COLUMNS = (
    "id, audit_run_id, evaluation_id, recommendation_id, market_offer_id, "
    "game_id, decision, lifecycle_state, selected_side, bookmaker, "
    "offered_spread, offered_price, stake_units, final_home_points, "
    "final_away_points, actual_home_margin, covered_margin, ats_result, "
    "realized_profit_units, closing_designation_id, closing_evidence_status, "
    "closing_selected_spread, closing_selected_price, clv_points, "
    "clv_evidence_status, graded_at, source, provenance"
)
_COMPLETION_COLUMNS = (
    "audit_run_id, audit_count, bet_count, no_bet_count, win_count, loss_count, "
    "push_count, clv_graded_count, missing_clv_count, total_staked_units, "
    "realized_profit_units, roi_percent, average_clv_points, ledger_sha256, "
    "completed_at, provenance"
)
_EVALUATION_COLUMNS = (
    "evaluation.id, evaluation.evaluation_key, evaluation.recommendation_id, "
    "evaluation.policy_id, evaluation.policy_version, evaluation.market_offer_id, "
    "evaluation.model_prediction_id, evaluation.supersedes_evaluation_id, "
    "evaluation.lifecycle_state, evaluation.decision, evaluation.selected_side, "
    "evaluation.selected_team, evaluation.bookmaker, evaluation.offered_spread, "
    "evaluation.offered_price, evaluation.captured_at, evaluation.event_start_at, "
    "evaluation.model_fair_spread, evaluation.spread_edge_points, "
    "evaluation.estimated_cover_probability, evaluation.break_even_probability, "
    "evaluation.expected_value, evaluation.stake_units, evaluation.reason_code, "
    "evaluation.evaluated_at, evaluation.provenance"
)


def get_sportsbook_postgame_audit_run(
    conn: sqlite3.Connection, audit_run_id: int
) -> SportsbookPostgameAuditRun:
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM sportsbook_postgame_audit_runs WHERE id = ?",
        (integer(audit_run_id, "audit_run_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"sportsbook postgame audit run does not exist: {audit_run_id}"
        )
    return SportsbookPostgameAuditRun(*row)


def list_sportsbook_postgame_audit_details(
    conn: sqlite3.Connection, audit_run_id: int
) -> tuple[SportsbookPostgameAuditDetail, ...]:
    rows = conn.execute(
        f"SELECT {_DETAIL_COLUMNS} FROM sportsbook_postgame_audit_details "
        "WHERE audit_run_id = ? ORDER BY evaluation_id",
        (integer(audit_run_id, "audit_run_id", 1),),
    ).fetchall()
    return tuple(SportsbookPostgameAuditDetail(*row) for row in rows)


def get_sportsbook_postgame_audit_completion(
    conn: sqlite3.Connection, audit_run_id: int
) -> SportsbookPostgameAuditCompletion:
    row = conn.execute(
        f"SELECT {_COMPLETION_COLUMNS} FROM sportsbook_postgame_audit_completions "
        "WHERE audit_run_id = ?",
        (integer(audit_run_id, "audit_run_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"sportsbook postgame audit run is incomplete: {audit_run_id}"
        )
    return SportsbookPostgameAuditCompletion(*row)


def _eligible_evaluations(
    conn: sqlite3.Connection,
    *,
    season: int,
    week: int,
    policy_id: int,
    audited_at: str,
) -> tuple[SportsbookRecommendationEvaluation, ...]:
    rows = conn.execute(
        f"SELECT {_EVALUATION_COLUMNS} "
        "FROM sportsbook_recommendation_evaluations AS evaluation "
        "JOIN sportsbook_market_offers AS offer "
        "ON offer.id = evaluation.market_offer_id "
        "JOIN games AS game ON game.game_id = offer.game_id "
        "WHERE game.season = ? AND game.week = ? AND evaluation.policy_id = ? "
        "AND julianday(evaluation.evaluated_at) <= julianday(?) "
        "ORDER BY evaluation.id",
        (season, week, policy_id, audited_at),
    ).fetchall()
    return tuple(SportsbookRecommendationEvaluation(*row) for row in rows)


def _closing_offer(
    conn: sqlite3.Connection, evaluation: SportsbookRecommendationEvaluation
) -> tuple[int, float, int] | None:
    row = conn.execute(
        "SELECT designation.id, "
        "CASE ? WHEN 'home' THEN closing.home_spread ELSE closing.away_spread END, "
        "CASE ? WHEN 'home' THEN closing.home_price ELSE closing.away_price END "
        "FROM sportsbook_market_offers AS opening "
        "JOIN sportsbook_closing_designations AS designation "
        "ON designation.game_id = opening.game_id "
        "AND designation.bookmaker = opening.bookmaker "
        "JOIN sportsbook_market_offers AS closing "
        "ON closing.id = designation.market_offer_id "
        "WHERE opening.id = ? "
        "ORDER BY designation.id DESC LIMIT 1",
        (evaluation.selected_side, evaluation.selected_side, evaluation.market_offer_id),
    ).fetchone()
    return None if row is None else (int(row[0]), float(row[1]), int(row[2]))


def _result(selected_side: str, offered_spread: float, actual_margin: int) -> tuple[float, str]:
    covered = (
        actual_margin + offered_spread
        if selected_side == "home"
        else -actual_margin + offered_spread
    )
    return covered, "win" if covered > 0 else "loss" if covered < 0 else "push"


def _profit(evaluation: SportsbookRecommendationEvaluation, result: str) -> float:
    if evaluation.decision == "no_bet" or result == "push":
        return 0.0
    if result == "loss":
        return -evaluation.stake_units
    multiplier = (
        100 / abs(evaluation.offered_price)
        if evaluation.offered_price < 0
        else evaluation.offered_price / 100
    )
    return evaluation.stake_units * multiplier


def _detail_values(
    conn: sqlite3.Connection,
    *,
    run: SportsbookPostgameAuditRun,
    evaluation: SportsbookRecommendationEvaluation,
) -> tuple[object, ...]:
    game = conn.execute(
        "SELECT offer.game_id, game.start_date, game.home_points, game.away_points, "
        "game.completed FROM sportsbook_market_offers AS offer "
        "JOIN games AS game ON game.game_id = offer.game_id WHERE offer.id = ?",
        (evaluation.market_offer_id,),
    ).fetchone()
    if (
        game is None
        or game[4] != 1
        or game[2] is None
        or game[3] is None
        or not timestamp_on_or_before(conn, game[1], run.audited_at)
    ):
        raise BusinessEntityError(
            f"sportsbook evaluation {evaluation.id} game is not complete as of the audit"
        )
    home_points = integer(game[2], "final_home_points", 0)
    away_points = integer(game[3], "final_away_points", 0)
    actual_margin = home_points - away_points
    covered, ats_result = _result(
        evaluation.selected_side, evaluation.offered_spread, actual_margin
    )
    realized = _profit(evaluation, ats_result)
    closing = _closing_offer(conn, evaluation)
    if closing is None:
        closing_values: tuple[object, ...] = (None, "missing", None, None, None, "missing")
    else:
        closing_id, closing_spread, closing_price = closing
        closing_values = (
            closing_id,
            "available",
            closing_spread,
            closing_price,
            round(evaluation.offered_spread - closing_spread, 6),
            "available",
        )
    return (
        run.id,
        evaluation.id,
        evaluation.recommendation_id,
        evaluation.market_offer_id,
        int(game[0]),
        evaluation.decision,
        evaluation.lifecycle_state,
        evaluation.selected_side,
        evaluation.bookmaker,
        evaluation.offered_spread,
        evaluation.offered_price,
        evaluation.stake_units,
        home_points,
        away_points,
        actual_margin,
        covered,
        ats_result,
        realized,
        *closing_values,
        run.audited_at,
        run.source,
        run.provenance,
    )


def _ledger_sha256(details: tuple[SportsbookPostgameAuditDetail, ...]) -> str:
    canonical = json.dumps(
        [asdict(detail) for detail in details],
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def inspect_sportsbook_postgame_audit(
    conn: sqlite3.Connection, audit_run_id: int
) -> SportsbookPostgameAuditReport:
    run = get_sportsbook_postgame_audit_run(conn, audit_run_id)
    details = list_sportsbook_postgame_audit_details(conn, run.id)
    expected = {
        evaluation.id
        for evaluation in _eligible_evaluations(
            conn,
            season=run.season,
            week=run.week,
            policy_id=run.policy_id,
            audited_at=run.audited_at,
        )
    }
    actual = {detail.evaluation_id for detail in details}
    try:
        completion = get_sportsbook_postgame_audit_completion(conn, run.id)
        recorded_hash = completion.ledger_sha256
    except BusinessEntityError:
        recorded_hash = None
    return SportsbookPostgameAuditReport(
        audit_run_id=run.id,
        expected_evaluation_count=run.expected_evaluation_count,
        expected_bet_count=run.expected_bet_count,
        audit_count=len(details),
        missing_evaluation_ids=tuple(sorted(expected - actual)),
        unexpected_evaluation_ids=tuple(sorted(actual - expected)),
        bet_count=sum(detail.decision == "bet" for detail in details),
        no_bet_count=sum(detail.decision == "no_bet" for detail in details),
        clv_graded_count=sum(detail.clv_evidence_status == "available" for detail in details),
        missing_clv_count=sum(detail.clv_evidence_status == "missing" for detail in details),
        ledger_sha256=_ledger_sha256(details),
        recorded_ledger_sha256=recorded_hash,
    )


def validate_sportsbook_postgame_audit(
    conn: sqlite3.Connection, audit_run_id: int
) -> SportsbookPostgameAuditReport:
    report = inspect_sportsbook_postgame_audit(conn, audit_run_id)
    if not report.complete:
        raise BusinessEntityError(
            "sportsbook postgame audit is incomplete or its immutable ledger differs"
        )
    return report


def _load_result(
    conn: sqlite3.Connection, audit_run_id: int
) -> SportsbookPostgameAuditResult:
    run = get_sportsbook_postgame_audit_run(conn, audit_run_id)
    details = list_sportsbook_postgame_audit_details(conn, audit_run_id)
    completion = get_sportsbook_postgame_audit_completion(conn, audit_run_id)
    report = validate_sportsbook_postgame_audit(conn, audit_run_id)
    return SportsbookPostgameAuditResult(run, details, completion, report)


def audit_sportsbook_recommendations(
    conn: sqlite3.Connection,
    *,
    audit_run_key: str,
    season: int,
    week: int,
    policy_id: int,
    source: str,
    provenance: str,
    audited_at: datetime | None = None,
) -> SportsbookPostgameAuditResult:
    """Grade every governed BET/NO BET evaluation and seal one audit ledger."""
    audit_run_key = required_text(audit_run_key, "audit_run_key")
    season = integer(season, "season", 1869)
    week = integer(week, "week", 0)
    if week > 20:
        raise BusinessEntityError("week must be between 0 and 20")
    policy_id = integer(policy_id, "policy_id", 1)
    source = required_text(source, "source")
    provenance = required_text(provenance, "provenance")
    audited_at_value = utc_timestamp(audited_at, "audited_at")
    policy = get_sportsbook_recommendation_policy(conn, policy_id)
    if not timestamp_on_or_before(conn, policy.effective_at, audited_at_value):
        raise BusinessEntityError("sportsbook policy is not effective at audit time")
    evaluations = _eligible_evaluations(
        conn,
        season=season,
        week=week,
        policy_id=policy_id,
        audited_at=audited_at_value,
    )
    expected_bets = sum(item.decision == "bet" for item in evaluations)
    existing = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM sportsbook_postgame_audit_runs "
        "WHERE audit_run_key = ?",
        (audit_run_key,),
    ).fetchone()
    if existing is not None:
        run = SportsbookPostgameAuditRun(*existing)
        if (
            (run.season, run.week, run.policy_id)
            != (season, week, policy_id)
            or run.policy_version != policy.policy_version
            or run.expected_evaluation_count != len(evaluations)
            or run.expected_bet_count != expected_bets
            or run.audited_at != audited_at_value
            or run.source != source
            or run.provenance != provenance
        ):
            raise BusinessEntityConflictError(
                "sportsbook audit run key has different immutable values"
            )
        return _load_result(conn, run.id)

    try:
        with atomic(conn):
            latest = conn.execute(
                "SELECT id, sequence FROM sportsbook_postgame_audit_runs "
                "WHERE season = ? AND week = ? AND policy_id = ? "
                "ORDER BY sequence DESC LIMIT 1",
                (season, week, policy_id),
            ).fetchone()
            supersedes = None if latest is None else int(latest[0])
            sequence = 1 if latest is None else int(latest[1]) + 1
            run_id = conn.execute(
                "INSERT INTO sportsbook_postgame_audit_runs "
                "(audit_run_key, season, week, policy_id, policy_version, sequence, "
                "supersedes_run_id, expected_evaluation_count, expected_bet_count, "
                "audited_at, source, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    audit_run_key,
                    season,
                    week,
                    policy_id,
                    policy.policy_version,
                    sequence,
                    supersedes,
                    len(evaluations),
                    expected_bets,
                    audited_at_value,
                    source,
                    provenance,
                ),
            ).lastrowid
            run = get_sportsbook_postgame_audit_run(conn, run_id)
            placeholders = ", ".join("?" for _ in range(27))
            for evaluation in evaluations:
                conn.execute(
                    "INSERT INTO sportsbook_postgame_audit_details "
                    "(audit_run_id, evaluation_id, recommendation_id, market_offer_id, "
                    "game_id, decision, lifecycle_state, selected_side, bookmaker, "
                    "offered_spread, offered_price, stake_units, final_home_points, "
                    "final_away_points, actual_home_margin, covered_margin, ats_result, "
                    "realized_profit_units, closing_designation_id, "
                    "closing_evidence_status, closing_selected_spread, "
                    "closing_selected_price, clv_points, clv_evidence_status, "
                    f"graded_at, source, provenance) VALUES ({placeholders})",
                    _detail_values(conn, run=run, evaluation=evaluation),
                )
            details = list_sportsbook_postgame_audit_details(conn, run.id)
            counts = {
                result: sum(detail.ats_result == result for detail in details)
                for result in ("win", "loss", "push")
            }
            total_staked = sum(
                detail.stake_units for detail in details if detail.decision == "bet"
            )
            realized = sum(detail.realized_profit_units for detail in details)
            clv_values = [
                detail.clv_points
                for detail in details
                if detail.clv_evidence_status == "available"
                and detail.clv_points is not None
            ]
            conn.execute(
                "INSERT INTO sportsbook_postgame_audit_completions "
                "(audit_run_id, audit_count, bet_count, no_bet_count, win_count, "
                "loss_count, push_count, clv_graded_count, missing_clv_count, "
                "total_staked_units, realized_profit_units, roi_percent, "
                "average_clv_points, ledger_sha256, completed_at, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.id,
                    len(details),
                    sum(detail.decision == "bet" for detail in details),
                    sum(detail.decision == "no_bet" for detail in details),
                    counts["win"],
                    counts["loss"],
                    counts["push"],
                    len(clv_values),
                    len(details) - len(clv_values),
                    total_staked,
                    realized,
                    None if total_staked == 0 else realized / total_staked * 100,
                    None if not clv_values else sum(clv_values) / len(clv_values),
                    _ledger_sha256(details),
                    run.audited_at,
                    run.provenance,
                ),
            )
            return _load_result(conn, run.id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("sportsbook postgame audit", exc) from exc
