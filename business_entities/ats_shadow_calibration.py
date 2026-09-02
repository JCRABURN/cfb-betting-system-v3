"""Immutable shadow-only ATS probability custody for unified ranking.

The v1 method is deliberately conservative and is not represented as an
empirically calibrated betting model.  It converts the selected side's
nonnegative model-versus-locked-line margin advantage into a probability by a
versioned linear rate, caps the result at a conservative policy maximum, and
assigns exactly 0.50 when the contest pick has no model prediction.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime

from business_entities.cards import ContestPick, get_contest_card, list_contest_picks
from business_entities.common import (
    SHA256,
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    checksum,
    integer,
    number,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)
from business_entities.modeling import get_model_prediction, get_model_run
from contest_lines import get_effective_locked_line_as_of


CALIBRATION_METHOD = "conservative_linear_margin_v1"
EMPIRICAL_CALIBRATION_STATUS = "not_empirically_validated"
SHADOW_STATUS = "shadow"
MISSING_PREDICTION_PROBABILITY = 0.5


@dataclass(frozen=True)
class AtsShadowCalibrationPolicy:
    policy_key: str
    reliability_policy_version: str
    probability_method_version: str
    required_model_name: str
    required_model_version: str
    probability_per_margin_point: float
    maximum_selected_probability: float
    effective_at: datetime
    created_by: str
    provenance: str


@dataclass(frozen=True)
class RecordedAtsShadowCalibrationPolicy:
    id: int
    policy_key: str
    reliability_policy_version: str
    probability_method_version: str
    calibration_method: str
    required_model_name: str
    required_model_version: str
    probability_per_margin_point: float
    maximum_selected_probability: float
    missing_prediction_probability: float
    empirical_calibration_status: str
    status: str
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class AtsShadowCalibrationRun:
    id: int
    run_key: str
    contest_card_id: int
    ats_model_run_id: int
    ats_shadow_calibration_policy_id: int
    status: str
    input_sha256: str
    generated_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class AtsShadowCalibratedEvaluation:
    id: int
    evaluation_key: str
    ats_shadow_calibration_run_id: int
    contest_card_id: int
    contest_pick_id: int
    ats_model_run_id: int
    ats_model_prediction_id: int | None
    locked_line_id: int
    game_id: int
    selected_side: str
    ats_model_name: str
    ats_model_version: str
    reliability_policy_version: str
    probability_method_version: str
    selected_margin_advantage_points: float
    calibrated_selected_side_probability: float
    card_generated_at: str
    line_effective_at: str
    prediction_generated_at: str | None
    input_sha256: str
    generated_at: str
    provenance: str


@dataclass(frozen=True)
class AtsShadowCalibrationCompletion:
    ats_shadow_calibration_run_id: int
    evaluation_count: int
    ledger_sha256: str
    completed_at: str


@dataclass(frozen=True)
class AtsShadowCalibrationResult:
    run: AtsShadowCalibrationRun
    evaluations: tuple[AtsShadowCalibratedEvaluation, ...]
    completion: AtsShadowCalibrationCompletion
    replayed: bool


@dataclass(frozen=True)
class _EvaluationInput:
    contest_pick_id: int
    ats_model_prediction_id: int | None
    locked_line_id: int
    game_id: int
    selected_side: str
    selected_margin_advantage_points: float
    calibrated_selected_side_probability: float
    card_generated_at: str
    line_effective_at: str
    prediction_generated_at: str | None
    input_sha256: str


_POLICY_COLUMNS = (
    "id, policy_key, reliability_policy_version, probability_method_version, "
    "calibration_method, required_model_name, required_model_version, "
    "probability_per_margin_point, maximum_selected_probability, "
    "missing_prediction_probability, empirical_calibration_status, status, "
    "effective_at, created_by, provenance"
)
_RUN_COLUMNS = (
    "id, run_key, contest_card_id, ats_model_run_id, "
    "ats_shadow_calibration_policy_id, status, input_sha256, generated_at, "
    "created_by, provenance"
)
_EVALUATION_COLUMNS = (
    "id, evaluation_key, ats_shadow_calibration_run_id, contest_card_id, "
    "contest_pick_id, ats_model_run_id, ats_model_prediction_id, locked_line_id, "
    "game_id, selected_side, ats_model_name, ats_model_version, "
    "reliability_policy_version, probability_method_version, "
    "selected_margin_advantage_points, calibrated_selected_side_probability, "
    "card_generated_at, line_effective_at, prediction_generated_at, input_sha256, "
    "generated_at, provenance"
)
_COMPLETION_COLUMNS = (
    "ats_shadow_calibration_run_id, evaluation_count, ledger_sha256, completed_at"
)


def _canonical_sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _validate_policy(
    policy: AtsShadowCalibrationPolicy,
) -> AtsShadowCalibrationPolicy:
    if not isinstance(policy, AtsShadowCalibrationPolicy):
        raise BusinessEntityError("policy must be an AtsShadowCalibrationPolicy")
    rate = number(
        policy.probability_per_margin_point,
        "policy.probability_per_margin_point",
    )
    maximum = number(
        policy.maximum_selected_probability,
        "policy.maximum_selected_probability",
    )
    if not 0 < rate <= 0.01:
        raise BusinessEntityError(
            "shadow ATS probability rate must be within (0, 0.01]"
        )
    if not 0.5 < maximum <= 0.6:
        raise BusinessEntityError(
            "shadow ATS probability cap must be within (0.5, 0.6]"
        )
    return AtsShadowCalibrationPolicy(
        policy_key=required_text(policy.policy_key, "policy.policy_key"),
        reliability_policy_version=required_text(
            policy.reliability_policy_version,
            "policy.reliability_policy_version",
        ),
        probability_method_version=required_text(
            policy.probability_method_version,
            "policy.probability_method_version",
        ),
        required_model_name=required_text(
            policy.required_model_name, "policy.required_model_name"
        ),
        required_model_version=required_text(
            policy.required_model_version, "policy.required_model_version"
        ),
        probability_per_margin_point=rate,
        maximum_selected_probability=maximum,
        effective_at=datetime.fromisoformat(
            utc_timestamp(policy.effective_at, "policy.effective_at")
        ),
        created_by=required_text(policy.created_by, "policy.created_by"),
        provenance=required_text(policy.provenance, "policy.provenance"),
    )


def get_ats_shadow_calibration_policy(
    conn: sqlite3.Connection, policy_id: int
) -> RecordedAtsShadowCalibrationPolicy:
    row = conn.execute(
        f"SELECT {_POLICY_COLUMNS} FROM ats_shadow_calibration_policies WHERE id = ?",
        (integer(policy_id, "policy_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"ATS shadow calibration policy does not exist: {policy_id}"
        )
    return RecordedAtsShadowCalibrationPolicy(*row)


def register_ats_shadow_calibration_policy(
    conn: sqlite3.Connection, policy: AtsShadowCalibrationPolicy
) -> RecordedAtsShadowCalibrationPolicy:
    policy = _validate_policy(policy)
    requested = (
        policy.policy_key,
        policy.reliability_policy_version,
        policy.probability_method_version,
        CALIBRATION_METHOD,
        policy.required_model_name,
        policy.required_model_version,
        policy.probability_per_margin_point,
        policy.maximum_selected_probability,
        MISSING_PREDICTION_PROBABILITY,
        EMPIRICAL_CALIBRATION_STATUS,
        SHADOW_STATUS,
        policy.effective_at.isoformat(),
        policy.created_by,
        policy.provenance,
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM ats_shadow_calibration_policies "
                "WHERE policy_key = ? OR reliability_policy_version = ? "
                "ORDER BY policy_key = ? DESC LIMIT 1",
                (requested[0], requested[1], requested[0]),
            ).fetchone()
            if row is not None:
                if tuple(row[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "ATS shadow calibration policy key/version has different "
                        "immutable values"
                    )
                return get_ats_shadow_calibration_policy(conn, row[0])
            cursor = conn.execute(
                "INSERT INTO ats_shadow_calibration_policies "
                "(policy_key, reliability_policy_version, probability_method_version, "
                "calibration_method, required_model_name, required_model_version, "
                "probability_per_margin_point, maximum_selected_probability, "
                "missing_prediction_probability, empirical_calibration_status, status, "
                "effective_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            return get_ats_shadow_calibration_policy(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("ATS shadow calibration policy", exc) from exc


def _get_run(conn: sqlite3.Connection, run_id: int) -> AtsShadowCalibrationRun:
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM ats_shadow_calibration_runs WHERE id = ?",
        (integer(run_id, "run_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"ATS shadow calibration run does not exist: {run_id}")
    return AtsShadowCalibrationRun(*row)


def list_ats_shadow_calibrated_evaluations(
    conn: sqlite3.Connection, run_id: int
) -> tuple[AtsShadowCalibratedEvaluation, ...]:
    return tuple(
        AtsShadowCalibratedEvaluation(*row)
        for row in conn.execute(
            f"SELECT {_EVALUATION_COLUMNS} FROM ats_shadow_calibrated_evaluations "
            "WHERE ats_shadow_calibration_run_id = ? ORDER BY contest_pick_id",
            (integer(run_id, "run_id", 1),),
        )
    )


def get_ats_shadow_calibrated_evaluation(
    conn: sqlite3.Connection, evaluation_id: int
) -> AtsShadowCalibratedEvaluation:
    row = conn.execute(
        f"SELECT {_EVALUATION_COLUMNS} FROM ats_shadow_calibrated_evaluations "
        "WHERE id = ?",
        (integer(evaluation_id, "evaluation_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"ATS shadow calibrated evaluation does not exist: {evaluation_id}"
        )
    return AtsShadowCalibratedEvaluation(*row)


def _get_completion(
    conn: sqlite3.Connection, run_id: int
) -> AtsShadowCalibrationCompletion:
    row = conn.execute(
        f"SELECT {_COMPLETION_COLUMNS} FROM ats_shadow_calibration_completions "
        "WHERE ats_shadow_calibration_run_id = ?",
        (integer(run_id, "run_id", 1),),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"ATS shadow calibration run is not complete: {run_id}"
        )
    return AtsShadowCalibrationCompletion(*row)


def get_ats_shadow_calibration_result(
    conn: sqlite3.Connection, run_id: int, *, replayed: bool = False
) -> AtsShadowCalibrationResult:
    return AtsShadowCalibrationResult(
        run=_get_run(conn, run_id),
        evaluations=list_ats_shadow_calibrated_evaluations(conn, run_id),
        completion=_get_completion(conn, run_id),
        replayed=replayed,
    )


def _before_kickoff(
    conn: sqlite3.Connection, game_id: int, generated_at: str
) -> None:
    row = conn.execute(
        "SELECT start_date FROM games WHERE game_id = ?", (game_id,)
    ).fetchone()
    if row is None or row[0] is None or timestamp_on_or_before(
        conn, row[0], generated_at
    ):
        raise BusinessEntityError(
            f"ATS shadow calibration must be generated before kickoff for game {game_id}"
        )


def _evaluation_input(
    conn: sqlite3.Connection,
    *,
    pick: ContestPick,
    card_generated_at: datetime,
    model_run_id: int,
    policy: RecordedAtsShadowCalibrationPolicy,
    generated_at: str,
) -> _EvaluationInput:
    if pick.selected_side not in ("home", "away"):
        raise BusinessEntityError(
            "ATS shadow calibration requires a mandatory selected ATS side"
        )
    line = get_effective_locked_line_as_of(
        conn, pick.locked_line_id, card_generated_at
    )
    if line.game_id is None:
        raise BusinessEntityError("ATS shadow calibration requires game identity")
    _before_kickoff(conn, line.game_id, generated_at)

    prediction_generated_at: str | None = None
    prediction_id = pick.model_prediction_id
    advantage = 0.0
    if prediction_id is not None:
        prediction = get_model_prediction(conn, prediction_id)
        if prediction.model_run_id != model_run_id or prediction.game_id != line.game_id:
            raise BusinessEntityError(
                "ATS pick prediction does not belong to the calibrated model/game"
            )
        if prediction.entry_locked_line_id != pick.locked_line_id:
            raise BusinessEntityError(
                "ATS shadow calibration requires the pick's exact locked-line entry"
            )
        home_advantage = prediction.predicted_home_margin + line.home_spread
        signed_advantage = (
            home_advantage if pick.selected_side == "home" else -home_advantage
        )
        advantage = max(0.0, signed_advantage)
        prediction_generated_at = prediction.generated_at

    calibrated = min(
        policy.maximum_selected_probability,
        MISSING_PREDICTION_PROBABILITY
        + advantage * policy.probability_per_margin_point,
    )
    payload = {
        "contest_pick_id": pick.id,
        "ats_model_prediction_id": prediction_id,
        "locked_line_id": pick.locked_line_id,
        "game_id": line.game_id,
        "selected_side": pick.selected_side,
        "selected_margin_advantage_points": advantage,
        "calibrated_selected_side_probability": calibrated,
        "card_generated_at": card_generated_at.isoformat(),
        "line_effective_at": line.effective_at,
        "prediction_generated_at": prediction_generated_at,
        "reliability_policy_version": policy.reliability_policy_version,
        "probability_method_version": policy.probability_method_version,
    }
    return _EvaluationInput(
        contest_pick_id=pick.id,
        ats_model_prediction_id=prediction_id,
        locked_line_id=pick.locked_line_id,
        game_id=line.game_id,
        selected_side=pick.selected_side,
        selected_margin_advantage_points=advantage,
        calibrated_selected_side_probability=calibrated,
        card_generated_at=card_generated_at.isoformat(),
        line_effective_at=line.effective_at,
        prediction_generated_at=prediction_generated_at,
        input_sha256=_canonical_sha256(payload),
    )


def generate_ats_shadow_calibrations(
    conn: sqlite3.Connection,
    *,
    run_key: str,
    contest_card_id: int,
    ats_shadow_calibration_policy_id: int,
    generated_at: datetime,
    created_by: str,
    provenance: str,
) -> AtsShadowCalibrationResult:
    """Compute and seal one complete, conservative ATS shadow evaluation ledger."""
    run_key = required_text(run_key, "run_key")
    contest_card_id = integer(contest_card_id, "contest_card_id", 1)
    policy_id = integer(
        ats_shadow_calibration_policy_id,
        "ats_shadow_calibration_policy_id",
        1,
    )
    generated_at_value = utc_timestamp(generated_at, "generated_at")
    created_by = required_text(created_by, "created_by")
    provenance = required_text(provenance, "provenance")

    card = get_contest_card(conn, contest_card_id)
    if card.model_run_id is None:
        raise BusinessEntityError(
            "ATS shadow calibration requires the card's governed model run"
        )
    model_run = get_model_run(conn, card.model_run_id)
    policy = get_ats_shadow_calibration_policy(conn, policy_id)
    if model_run.status != "completed":
        raise BusinessEntityError("ATS shadow calibration requires a completed model run")
    if (model_run.model_name, model_run.model_version) != (
        policy.required_model_name,
        policy.required_model_version,
    ):
        raise BusinessEntityError(
            "ATS shadow calibration policy requires a different ATS model version"
        )
    if not timestamp_on_or_before(conn, card.generated_at, generated_at_value):
        raise BusinessEntityError("ATS calibration cannot precede its contest card")
    if not timestamp_on_or_before(conn, policy.effective_at, generated_at_value):
        raise BusinessEntityError("ATS calibration policy is not yet effective")

    card_generated_at = datetime.fromisoformat(card.generated_at)
    inputs = tuple(
        _evaluation_input(
            conn,
            pick=pick,
            card_generated_at=card_generated_at,
            model_run_id=model_run.id,
            policy=policy,
            generated_at=generated_at_value,
        )
        for pick in list_contest_picks(conn, contest_card_id)
    )
    input_hash = _canonical_sha256(
        {
            "run_key": run_key,
            "contest_card": asdict(card),
            "ats_model_run": asdict(model_run),
            "ats_shadow_calibration_policy": asdict(policy),
            "generated_at": generated_at_value,
            "evaluations": [asdict(item) for item in inputs],
        }
    )
    requested_run = (
        run_key,
        contest_card_id,
        model_run.id,
        policy.id,
        SHADOW_STATUS,
        checksum(input_hash, "input_sha256", SHA256),
        generated_at_value,
        created_by,
        provenance,
    )

    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM ats_shadow_calibration_runs "
                "WHERE run_key = ? OR (contest_card_id = ? AND "
                "ats_shadow_calibration_policy_id = ?) "
                "ORDER BY run_key = ? DESC LIMIT 1",
                (run_key, contest_card_id, policy.id, run_key),
            ).fetchone()
            if row is not None:
                if tuple(row[1:]) != requested_run:
                    raise BusinessEntityConflictError(
                        "ATS shadow calibration run identity has different immutable values"
                    )
                return get_ats_shadow_calibration_result(
                    conn, row[0], replayed=True
                )

            cursor = conn.execute(
                "INSERT INTO ats_shadow_calibration_runs "
                "(run_key, contest_card_id, ats_model_run_id, "
                "ats_shadow_calibration_policy_id, status, input_sha256, generated_at, "
                "created_by, provenance) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested_run,
            )
            run_id = cursor.lastrowid
            for item in inputs:
                conn.execute(
                    "INSERT INTO ats_shadow_calibrated_evaluations "
                    "(evaluation_key, ats_shadow_calibration_run_id, contest_card_id, "
                    "contest_pick_id, ats_model_run_id, ats_model_prediction_id, "
                    "locked_line_id, game_id, selected_side, ats_model_name, "
                    "ats_model_version, reliability_policy_version, "
                    "probability_method_version, selected_margin_advantage_points, "
                    "calibrated_selected_side_probability, card_generated_at, "
                    "line_effective_at, prediction_generated_at, input_sha256, "
                    "generated_at, provenance) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        f"{run_key}:pick:{item.contest_pick_id}",
                        run_id,
                        contest_card_id,
                        item.contest_pick_id,
                        model_run.id,
                        item.ats_model_prediction_id,
                        item.locked_line_id,
                        item.game_id,
                        item.selected_side,
                        model_run.model_name,
                        model_run.model_version,
                        policy.reliability_policy_version,
                        policy.probability_method_version,
                        item.selected_margin_advantage_points,
                        item.calibrated_selected_side_probability,
                        item.card_generated_at,
                        item.line_effective_at,
                        item.prediction_generated_at,
                        item.input_sha256,
                        generated_at_value,
                        provenance,
                    ),
                )
            evaluations = list_ats_shadow_calibrated_evaluations(conn, run_id)
            ledger_hash = _canonical_sha256(
                {"run_id": run_id, "evaluations": [asdict(x) for x in evaluations]}
            )
            conn.execute(
                "INSERT INTO ats_shadow_calibration_completions "
                "(ats_shadow_calibration_run_id, evaluation_count, ledger_sha256, "
                "completed_at) VALUES (?, ?, ?, ?)",
                (run_id, len(evaluations), ledger_hash, generated_at_value),
            )
            return get_ats_shadow_calibration_result(conn, run_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("ATS shadow calibration", exc) from exc
