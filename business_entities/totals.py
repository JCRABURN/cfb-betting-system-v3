"""Append-only totals-model and complete shadow-card custody.

This module is deliberately isolated from the production ATS card path.  It
reads the effective immutable contest total as of the shadow generation time,
records either one O/U candidate or one explicit skip for every visible locked
line, and seals the resulting ledger.  It never writes ``contest_picks``.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime

from business_entities.common import (
    SHA1,
    SHA256,
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    checksum,
    choice,
    integer,
    number,
    optional_text,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)
from business_entities.full_card import locked_line_snapshot_sha256
from contest_lines import get_contest, list_effective_locked_lines


CALIBRATION_METHOD = "symmetric_logit_scale_v1"


@dataclass(frozen=True)
class TotalModelRun:
    id: int
    run_key: str
    model_name: str
    model_version: str
    feature_schema_version: str
    configuration_version: str
    code_commit_sha: str
    data_snapshot_sha256: str
    lifecycle_stage: str
    status: str
    failure_reason: str | None
    generated_at: str
    provenance: str


@dataclass(frozen=True)
class TotalModelPrediction:
    id: int
    prediction_key: str
    total_model_run_id: int
    game_id: int
    projected_total: float
    uncertainty_points: float
    home_stats_as_of_season: int
    home_stats_as_of_week: int
    away_stats_as_of_season: int
    away_stats_as_of_week: int
    features_as_of_at: str
    feature_snapshot_sha256: str
    generated_at: str
    provenance: str


@dataclass(frozen=True)
class TotalReliabilityPolicy:
    policy_key: str
    reliability_policy_version: str
    probability_model_version: str
    calibration_slope: float
    confidence_2_min_probability: float
    confidence_3_min_probability: float
    confidence_4_min_probability: float
    confidence_5_min_probability: float
    forecast_tie_direction: str
    effective_at: datetime
    created_by: str
    provenance: str


@dataclass(frozen=True)
class RecordedTotalReliabilityPolicy:
    id: int
    policy_key: str
    reliability_policy_version: str
    probability_model_version: str
    calibration_method: str
    calibration_slope: float
    confidence_2_min_probability: float
    confidence_3_min_probability: float
    confidence_4_min_probability: float
    confidence_5_min_probability: float
    forecast_tie_direction: str
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class TotalShadowCard:
    id: int
    card_key: str
    contest_id: int
    total_model_run_id: int
    total_reliability_policy_id: int
    version: int
    status: str
    locked_line_snapshot_sha256: str
    request_sha256: str
    generated_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class TotalCardCandidate:
    id: int
    candidate_key: str
    total_shadow_card_id: int
    locked_line_id: int
    total_model_prediction_id: int
    game_id: int
    exact_locked_total: float
    line_effective_at: str
    correction_id: int | None
    projected_total: float
    uncertainty_points: float
    selected_direction: str
    raw_over_probability: float
    calibrated_over_probability: float
    selected_probability: float
    confidence: int
    reliability_policy_version: str
    generated_at: str
    provenance: str


@dataclass(frozen=True)
class TotalCardSkip:
    id: int
    skip_key: str
    total_shadow_card_id: int
    locked_line_id: int
    game_id: int | None
    reason_code: str
    line_effective_at: str
    generated_at: str
    provenance: str


@dataclass(frozen=True)
class TotalShadowCardCompletion:
    total_shadow_card_id: int
    locked_line_count: int
    candidate_count: int
    skip_count: int
    ledger_sha256: str
    completed_at: str


@dataclass(frozen=True)
class TotalShadowCardResult:
    card: TotalShadowCard
    candidates: tuple[TotalCardCandidate, ...]
    skips: tuple[TotalCardSkip, ...]
    completion: TotalShadowCardCompletion
    replayed: bool


_RUN_COLUMNS = (
    "id, run_key, model_name, model_version, feature_schema_version, "
    "configuration_version, code_commit_sha, data_snapshot_sha256, "
    "lifecycle_stage, status, failure_reason, generated_at, provenance"
)
_PREDICTION_COLUMNS = (
    "id, prediction_key, total_model_run_id, game_id, projected_total, "
    "uncertainty_points, home_stats_as_of_season, home_stats_as_of_week, "
    "away_stats_as_of_season, away_stats_as_of_week, features_as_of_at, "
    "feature_snapshot_sha256, generated_at, provenance"
)
_POLICY_COLUMNS = (
    "id, policy_key, reliability_policy_version, probability_model_version, "
    "calibration_method, calibration_slope, confidence_2_min_probability, "
    "confidence_3_min_probability, confidence_4_min_probability, "
    "confidence_5_min_probability, forecast_tie_direction, effective_at, "
    "created_by, provenance"
)
_CARD_COLUMNS = (
    "id, card_key, contest_id, total_model_run_id, total_reliability_policy_id, "
    "version, status, locked_line_snapshot_sha256, request_sha256, generated_at, "
    "created_by, provenance"
)
_CANDIDATE_COLUMNS = (
    "id, candidate_key, total_shadow_card_id, locked_line_id, "
    "total_model_prediction_id, game_id, exact_locked_total, line_effective_at, "
    "correction_id, projected_total, uncertainty_points, selected_direction, "
    "raw_over_probability, calibrated_over_probability, selected_probability, "
    "confidence, reliability_policy_version, generated_at, provenance"
)
_SKIP_COLUMNS = (
    "id, skip_key, total_shadow_card_id, locked_line_id, game_id, reason_code, "
    "line_effective_at, generated_at, provenance"
)
_COMPLETION_COLUMNS = (
    "total_shadow_card_id, locked_line_count, candidate_count, skip_count, "
    "ledger_sha256, completed_at"
)


def _canonical_sha256(payload: object) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _moment(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BusinessEntityError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.utcoffset() is None:
        raise BusinessEntityError(f"{field} must include an offset")
    return parsed


def get_total_model_run(conn: sqlite3.Connection, run_id: int) -> TotalModelRun:
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM total_model_runs WHERE id = ?",
        (integer(run_id, "run_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"total model run does not exist: {run_id}")
    return TotalModelRun(*row)


def record_total_model_run(
    conn: sqlite3.Connection,
    *,
    run_key: str,
    model_name: str,
    model_version: str,
    feature_schema_version: str,
    configuration_version: str,
    code_commit_sha: str,
    data_snapshot_sha256: str,
    lifecycle_stage: str,
    status: str,
    provenance: str,
    failure_reason: str | None = None,
    generated_at: datetime | None = None,
) -> TotalModelRun:
    """Record a totals-specific run; production is not a permitted lifecycle."""
    run_key = required_text(run_key, "run_key")
    values = (
        required_text(model_name, "model_name"),
        required_text(model_version, "model_version"),
        required_text(feature_schema_version, "feature_schema_version"),
        required_text(configuration_version, "configuration_version"),
        checksum(code_commit_sha, "code_commit_sha", SHA1),
        checksum(data_snapshot_sha256, "data_snapshot_sha256", SHA256),
        choice(lifecycle_stage, "lifecycle_stage", ("research", "shadow")),
        choice(status, "status", ("completed", "failed")),
        optional_text(failure_reason, "failure_reason"),
        required_text(provenance, "provenance"),
    )
    if values[7] == "completed" and values[8] is not None:
        raise BusinessEntityError("completed total model runs cannot have a failure_reason")
    if values[7] == "failed" and values[8] is None:
        raise BusinessEntityError("failed total model runs require a failure_reason")
    generated_at_value = utc_timestamp(generated_at, "generated_at")
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM total_model_runs WHERE run_key = ?",
                (run_key,),
            ).fetchone()
            requested = (run_key, *values[:9], generated_at_value, values[9])
            if row is not None:
                existing = TotalModelRun(*row)
                recorded = tuple(row[1:])
                if recorded != requested:
                    raise BusinessEntityConflictError(
                        "total model run key has different immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO total_model_runs "
                "(run_key, model_name, model_version, feature_schema_version, "
                "configuration_version, code_commit_sha, data_snapshot_sha256, "
                "lifecycle_stage, status, failure_reason, generated_at, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            return get_total_model_run(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("total model run", exc) from exc


def get_total_model_prediction(
    conn: sqlite3.Connection, prediction_id: int
) -> TotalModelPrediction:
    row = conn.execute(
        f"SELECT {_PREDICTION_COLUMNS} FROM total_model_predictions WHERE id = ?",
        (integer(prediction_id, "prediction_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"total model prediction does not exist: {prediction_id}")
    return TotalModelPrediction(*row)


def record_total_model_prediction(
    conn: sqlite3.Connection,
    *,
    prediction_key: str,
    total_model_run_id: int,
    game_id: int,
    projected_total: float | int,
    uncertainty_points: float | int,
    home_stats_as_of_season: int,
    home_stats_as_of_week: int,
    away_stats_as_of_season: int,
    away_stats_as_of_week: int,
    features_as_of_at: datetime,
    feature_snapshot_sha256: str,
    provenance: str,
    generated_at: datetime | None = None,
) -> TotalModelPrediction:
    """Record one PIT-safe total forecast, separate from its O/U selection."""
    prediction_key = required_text(prediction_key, "prediction_key")
    total_model_run_id = integer(total_model_run_id, "total_model_run_id", 1)
    game_id = integer(game_id, "game_id", 1)
    projected = number(projected_total, "projected_total")
    uncertainty = number(uncertainty_points, "uncertainty_points")
    if projected < 0:
        raise BusinessEntityError("projected_total cannot be negative")
    if uncertainty <= 0:
        raise BusinessEntityError("uncertainty_points must be positive")
    home_season = integer(home_stats_as_of_season, "home_stats_as_of_season", 1869)
    home_week = integer(home_stats_as_of_week, "home_stats_as_of_week", 0)
    away_season = integer(away_stats_as_of_season, "away_stats_as_of_season", 1869)
    away_week = integer(away_stats_as_of_week, "away_stats_as_of_week", 0)
    features_at = utc_timestamp(features_as_of_at, "features_as_of_at")
    feature_hash = checksum(
        feature_snapshot_sha256, "feature_snapshot_sha256", SHA256
    )
    provenance = required_text(provenance, "provenance")
    generated_at_value = utc_timestamp(generated_at, "generated_at")

    try:
        with atomic(conn):
            run = get_total_model_run(conn, total_model_run_id)
            if run.status != "completed":
                raise BusinessEntityError("total predictions require a completed run")
            game = conn.execute(
                "SELECT season, week, start_date FROM games WHERE game_id = ?",
                (game_id,),
            ).fetchone()
            if game is None or game[2] is None:
                raise BusinessEntityError("total predictions require a scheduled game")
            target = (game[0], game[1])
            if (home_season, home_week) >= target or (away_season, away_week) >= target:
                raise BusinessEntityError(
                    "total prediction feature snapshots must precede the target week"
                )
            if not timestamp_on_or_before(conn, features_at, generated_at_value):
                raise BusinessEntityError("features_as_of_at cannot be in the future")
            if not timestamp_on_or_before(conn, run.generated_at, generated_at_value):
                raise BusinessEntityError("prediction cannot precede its model run")
            if timestamp_on_or_before(conn, game[2], generated_at_value):
                raise BusinessEntityError("total prediction must be generated before kickoff")

            requested = (
                prediction_key,
                total_model_run_id,
                game_id,
                projected,
                uncertainty,
                home_season,
                home_week,
                away_season,
                away_week,
                features_at,
                feature_hash,
                generated_at_value,
                provenance,
            )
            row = conn.execute(
                f"SELECT {_PREDICTION_COLUMNS} FROM total_model_predictions "
                "WHERE prediction_key = ? OR (total_model_run_id = ? AND game_id = ?) "
                "ORDER BY prediction_key = ? DESC LIMIT 1",
                (prediction_key, total_model_run_id, game_id, prediction_key),
            ).fetchone()
            if row is not None:
                existing = TotalModelPrediction(*row)
                if tuple(row[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "total prediction key or run/game has different immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO total_model_predictions "
                "(prediction_key, total_model_run_id, game_id, projected_total, "
                "uncertainty_points, home_stats_as_of_season, home_stats_as_of_week, "
                "away_stats_as_of_season, away_stats_as_of_week, features_as_of_at, "
                "feature_snapshot_sha256, generated_at, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            return get_total_model_prediction(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("total model prediction", exc) from exc


def validate_total_reliability_policy(
    policy: TotalReliabilityPolicy,
) -> TotalReliabilityPolicy:
    if not isinstance(policy, TotalReliabilityPolicy):
        raise BusinessEntityError("policy must be a TotalReliabilityPolicy")
    slope = number(policy.calibration_slope, "policy.calibration_slope")
    if slope <= 0:
        raise BusinessEntityError("calibration_slope must be positive")
    thresholds = tuple(
        number(value, field)
        for value, field in (
            (policy.confidence_2_min_probability, "confidence_2_min_probability"),
            (policy.confidence_3_min_probability, "confidence_3_min_probability"),
            (policy.confidence_4_min_probability, "confidence_4_min_probability"),
            (policy.confidence_5_min_probability, "confidence_5_min_probability"),
        )
    )
    if thresholds[0] <= 0.5 or thresholds[-1] > 1 or not all(
        lower < upper for lower, upper in zip(thresholds, thresholds[1:])
    ):
        raise BusinessEntityError(
            "total confidence thresholds must strictly increase within (0.5, 1]"
        )
    effective_at = datetime.fromisoformat(
        utc_timestamp(policy.effective_at, "policy.effective_at")
    )
    return TotalReliabilityPolicy(
        policy_key=required_text(policy.policy_key, "policy.policy_key"),
        reliability_policy_version=required_text(
            policy.reliability_policy_version, "policy.reliability_policy_version"
        ),
        probability_model_version=required_text(
            policy.probability_model_version, "policy.probability_model_version"
        ),
        calibration_slope=slope,
        confidence_2_min_probability=thresholds[0],
        confidence_3_min_probability=thresholds[1],
        confidence_4_min_probability=thresholds[2],
        confidence_5_min_probability=thresholds[3],
        forecast_tie_direction=choice(
            policy.forecast_tie_direction,
            "policy.forecast_tie_direction",
            ("over", "under"),
        ),
        effective_at=effective_at,
        created_by=required_text(policy.created_by, "policy.created_by"),
        provenance=required_text(policy.provenance, "policy.provenance"),
    )


def get_total_reliability_policy(
    conn: sqlite3.Connection, policy_id: int
) -> RecordedTotalReliabilityPolicy:
    row = conn.execute(
        f"SELECT {_POLICY_COLUMNS} FROM total_reliability_policies WHERE id = ?",
        (integer(policy_id, "policy_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"total reliability policy does not exist: {policy_id}")
    return RecordedTotalReliabilityPolicy(*row)


def register_total_reliability_policy(
    conn: sqlite3.Connection, policy: TotalReliabilityPolicy
) -> RecordedTotalReliabilityPolicy:
    policy = validate_total_reliability_policy(policy)
    requested = (
        policy.policy_key,
        policy.reliability_policy_version,
        policy.probability_model_version,
        CALIBRATION_METHOD,
        policy.calibration_slope,
        policy.confidence_2_min_probability,
        policy.confidence_3_min_probability,
        policy.confidence_4_min_probability,
        policy.confidence_5_min_probability,
        policy.forecast_tie_direction,
        policy.effective_at.isoformat(),
        policy.created_by,
        policy.provenance,
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM total_reliability_policies "
                "WHERE policy_key = ? OR reliability_policy_version = ? "
                "ORDER BY policy_key = ? DESC LIMIT 1",
                (
                    policy.policy_key,
                    policy.reliability_policy_version,
                    policy.policy_key,
                ),
            ).fetchone()
            if row is not None:
                existing = RecordedTotalReliabilityPolicy(*row)
                if tuple(row[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "total reliability policy key/version has different immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO total_reliability_policies "
                "(policy_key, reliability_policy_version, probability_model_version, "
                "calibration_method, calibration_slope, confidence_2_min_probability, "
                "confidence_3_min_probability, confidence_4_min_probability, "
                "confidence_5_min_probability, forecast_tie_direction, effective_at, "
                "created_by, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            return get_total_reliability_policy(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("total reliability policy", exc) from exc


def confidence_for_total_probability(
    policy: RecordedTotalReliabilityPolicy, selected_probability: float | int
) -> int:
    probability = number(selected_probability, "selected_probability")
    if not 0.5 <= probability <= 1:
        raise BusinessEntityError("selected_probability must be between 0.5 and 1")
    if probability >= policy.confidence_5_min_probability:
        return 5
    if probability >= policy.confidence_4_min_probability:
        return 4
    if probability >= policy.confidence_3_min_probability:
        return 3
    if probability >= policy.confidence_2_min_probability:
        return 2
    return 1


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _symmetric_calibration(probability: float, slope: float) -> float:
    bounded = min(max(probability, 1e-12), 1 - 1e-12)
    logit = math.log(bounded / (1 - bounded))
    scaled = min(max(slope * logit, -700.0), 700.0)
    calibrated = 1 / (1 + math.exp(-scaled))
    return min(max(calibrated, 0.0), 1.0)


def _get_total_shadow_card(conn: sqlite3.Connection, card_id: int) -> TotalShadowCard:
    row = conn.execute(
        f"SELECT {_CARD_COLUMNS} FROM total_shadow_cards WHERE id = ?",
        (integer(card_id, "card_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"total shadow card does not exist: {card_id}")
    return TotalShadowCard(*row)


def list_total_card_candidates(
    conn: sqlite3.Connection, card_id: int
) -> tuple[TotalCardCandidate, ...]:
    return tuple(
        TotalCardCandidate(*row)
        for row in conn.execute(
            f"SELECT {_CANDIDATE_COLUMNS} FROM total_card_candidates "
            "WHERE total_shadow_card_id = ? ORDER BY locked_line_id",
            (integer(card_id, "card_id", 1),),
        )
    )


def list_total_card_skips(
    conn: sqlite3.Connection, card_id: int
) -> tuple[TotalCardSkip, ...]:
    return tuple(
        TotalCardSkip(*row)
        for row in conn.execute(
            f"SELECT {_SKIP_COLUMNS} FROM total_card_skips "
            "WHERE total_shadow_card_id = ? ORDER BY locked_line_id",
            (integer(card_id, "card_id", 1),),
        )
    )


def get_total_shadow_card_completion(
    conn: sqlite3.Connection, card_id: int
) -> TotalShadowCardCompletion:
    row = conn.execute(
        f"SELECT {_COMPLETION_COLUMNS} FROM total_shadow_card_completions "
        "WHERE total_shadow_card_id = ?",
        (integer(card_id, "card_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"total shadow card is not complete: {card_id}")
    return TotalShadowCardCompletion(*row)


def get_total_shadow_card_result(
    conn: sqlite3.Connection, card_id: int, *, replayed: bool = False
) -> TotalShadowCardResult:
    return TotalShadowCardResult(
        card=_get_total_shadow_card(conn, card_id),
        candidates=list_total_card_candidates(conn, card_id),
        skips=list_total_card_skips(conn, card_id),
        completion=get_total_shadow_card_completion(conn, card_id),
        replayed=replayed,
    )


def _assert_before_kickoff(
    conn: sqlite3.Connection, game_id: int, generated_at: str
) -> None:
    row = conn.execute(
        "SELECT start_date FROM games WHERE game_id = ?", (game_id,)
    ).fetchone()
    if row is None or row[0] is None:
        raise BusinessEntityError(f"total shadow game lacks kickoff custody: {game_id}")
    if timestamp_on_or_before(conn, row[0], generated_at):
        raise BusinessEntityError(
            f"total shadow card must be generated before kickoff for game {game_id}"
        )


def generate_total_shadow_card(
    conn: sqlite3.Connection,
    *,
    card_key: str,
    contest_id: int,
    total_model_run_id: int,
    total_reliability_policy_id: int,
    version: int,
    generated_at: datetime,
    created_by: str,
    provenance: str,
) -> TotalShadowCardResult:
    """Generate and seal a complete shadow O/U candidate ledger.

    Missing totals and missing predictions are explicit skips.  The caller
    cannot supply a total: the service always resolves immutable contest-total
    custody as of ``generated_at``.
    """
    card_key = required_text(card_key, "card_key")
    contest_id = integer(contest_id, "contest_id", 1)
    total_model_run_id = integer(total_model_run_id, "total_model_run_id", 1)
    total_reliability_policy_id = integer(
        total_reliability_policy_id, "total_reliability_policy_id", 1
    )
    version = integer(version, "version", 1)
    generated_at_value = utc_timestamp(generated_at, "generated_at")
    generated_moment = _moment(generated_at_value, "generated_at")
    created_by = required_text(created_by, "created_by")
    provenance = required_text(provenance, "provenance")

    get_contest(conn, contest_id)
    run = get_total_model_run(conn, total_model_run_id)
    policy = get_total_reliability_policy(conn, total_reliability_policy_id)
    if run.status != "completed" or run.lifecycle_stage != "shadow":
        raise BusinessEntityError("total shadow cards require a completed shadow run")
    if not timestamp_on_or_before(conn, run.generated_at, generated_at_value):
        raise BusinessEntityError("total shadow card cannot precede its model run")
    if not timestamp_on_or_before(conn, policy.effective_at, generated_at_value):
        raise BusinessEntityError("total reliability policy is not yet effective")

    lines = list_effective_locked_lines(conn, contest_id, as_of=generated_moment)
    for line in lines:
        if line.game_id is not None:
            _assert_before_kickoff(conn, line.game_id, generated_at_value)
    locked_hash = locked_line_snapshot_sha256(lines)
    request_hash = _canonical_sha256(
        {
            "card_key": card_key,
            "contest_id": contest_id,
            "total_model_run_id": total_model_run_id,
            "total_reliability_policy_id": total_reliability_policy_id,
            "version": version,
            "generated_at": generated_at_value,
            "created_by": created_by,
            "provenance": provenance,
            "locked_line_snapshot_sha256": locked_hash,
        }
    )

    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_CARD_COLUMNS} FROM total_shadow_cards WHERE card_key = ?",
                (card_key,),
            ).fetchone()
            requested_card = (
                card_key,
                contest_id,
                total_model_run_id,
                total_reliability_policy_id,
                version,
                "shadow",
                locked_hash,
                request_hash,
                generated_at_value,
                created_by,
                provenance,
            )
            if row is not None:
                if tuple(row[1:]) != requested_card:
                    raise BusinessEntityConflictError(
                        "total shadow card key has different immutable values"
                    )
                return get_total_shadow_card_result(conn, row[0], replayed=True)

            cursor = conn.execute(
                "INSERT INTO total_shadow_cards "
                "(card_key, contest_id, total_model_run_id, "
                "total_reliability_policy_id, version, status, locked_line_snapshot_sha256, "
                "request_sha256, generated_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested_card,
            )
            card_id = cursor.lastrowid
            predictions = {
                row[3]: TotalModelPrediction(*row)
                for row in conn.execute(
                    f"SELECT {_PREDICTION_COLUMNS} FROM total_model_predictions "
                    "WHERE total_model_run_id = ? ORDER BY game_id",
                    (total_model_run_id,),
                )
            }

            for line in lines:
                skip_reason: str | None = None
                prediction: TotalModelPrediction | None = None
                if line.total is None:
                    skip_reason = "missing_locked_total"
                elif line.game_id is None:
                    skip_reason = "missing_game_identity"
                else:
                    prediction = predictions.get(line.game_id)
                    if prediction is None or not timestamp_on_or_before(
                        conn, prediction.generated_at, generated_at_value
                    ):
                        skip_reason = "missing_total_prediction"

                if skip_reason is not None:
                    conn.execute(
                        "INSERT INTO total_card_skips "
                        "(skip_key, total_shadow_card_id, locked_line_id, game_id, "
                        "reason_code, line_effective_at, generated_at, provenance) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            f"{card_key}:skip:{line.locked_line_id}",
                            card_id,
                            line.locked_line_id,
                            line.game_id,
                            skip_reason,
                            line.effective_at,
                            generated_at_value,
                            provenance,
                        ),
                    )
                    continue

                assert prediction is not None and line.total is not None
                z_score = (
                    prediction.projected_total - line.total
                ) / prediction.uncertainty_points
                raw_over = _normal_cdf(z_score)
                calibrated_over = _symmetric_calibration(
                    raw_over, policy.calibration_slope
                )
                if prediction.projected_total > line.total:
                    direction = "over"
                elif prediction.projected_total < line.total:
                    direction = "under"
                else:
                    direction = policy.forecast_tie_direction
                selected_probability = (
                    calibrated_over if direction == "over" else 1 - calibrated_over
                )
                selected_probability = max(selected_probability, 0.5)
                confidence = confidence_for_total_probability(
                    policy, selected_probability
                )
                conn.execute(
                    "INSERT INTO total_card_candidates "
                    "(candidate_key, total_shadow_card_id, locked_line_id, "
                    "total_model_prediction_id, game_id, exact_locked_total, "
                    "line_effective_at, correction_id, projected_total, "
                    "uncertainty_points, selected_direction, raw_over_probability, "
                    "calibrated_over_probability, selected_probability, confidence, "
                    "reliability_policy_version, generated_at, provenance) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{card_key}:total:{line.locked_line_id}",
                        card_id,
                        line.locked_line_id,
                        prediction.id,
                        line.game_id,
                        line.total,
                        line.effective_at,
                        line.correction_id,
                        prediction.projected_total,
                        prediction.uncertainty_points,
                        direction,
                        raw_over,
                        calibrated_over,
                        selected_probability,
                        confidence,
                        policy.reliability_policy_version,
                        generated_at_value,
                        provenance,
                    ),
                )

            candidates = list_total_card_candidates(conn, card_id)
            skips = list_total_card_skips(conn, card_id)
            ledger_hash = _canonical_sha256(
                {
                    "card_id": card_id,
                    "candidates": [asdict(item) for item in candidates],
                    "skips": [asdict(item) for item in skips],
                }
            )
            conn.execute(
                "INSERT INTO total_shadow_card_completions "
                "(total_shadow_card_id, locked_line_count, candidate_count, "
                "skip_count, ledger_sha256, completed_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    card_id,
                    len(lines),
                    len(candidates),
                    len(skips),
                    ledger_hash,
                    generated_at_value,
                ),
            )
            return get_total_shadow_card_result(conn, card_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("total shadow card", exc) from exc
