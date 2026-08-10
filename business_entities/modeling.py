"""Typed append-only storage for model executions and raw predictions."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from contest_lines import get_effective_locked_line

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
    optional_number,
    optional_text,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)


@dataclass(frozen=True)
class ModelRun:
    id: int
    run_key: str
    model_name: str
    model_version: str
    feature_schema_version: str
    configuration_version: str
    code_commit_sha: str
    data_snapshot_sha256: str
    status: str
    failure_reason: str | None
    generated_at: str
    provenance: str


@dataclass(frozen=True)
class ModelPrediction:
    id: int
    prediction_key: str
    model_run_id: int
    game_id: int
    predicted_home_margin: float
    home_win_probability: float | None
    uncertainty_points: float | None
    entry_market_line_id: int | None
    entry_locked_line_id: int | None
    generated_at: str
    provenance: str


_RUN_COLUMNS = (
    "id, run_key, model_name, model_version, feature_schema_version, "
    "configuration_version, code_commit_sha, data_snapshot_sha256, status, "
    "failure_reason, generated_at, provenance"
)
_PREDICTION_COLUMNS = (
    "id, prediction_key, model_run_id, game_id, predicted_home_margin, "
    "home_win_probability, uncertainty_points, entry_market_line_id, "
    "entry_locked_line_id, generated_at, provenance"
)


def get_model_run(conn: sqlite3.Connection, model_run_id: int) -> ModelRun:
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM model_runs WHERE id = ?", (model_run_id,)
    ).fetchone()
    if row is None:
        raise BusinessEntityError(f"model run does not exist: {model_run_id}")
    return ModelRun(*row)


def record_model_run(
    conn: sqlite3.Connection,
    *,
    run_key: str,
    model_name: str,
    model_version: str,
    feature_schema_version: str,
    configuration_version: str,
    code_commit_sha: str,
    data_snapshot_sha256: str,
    status: str,
    provenance: str,
    failure_reason: str | None = None,
    generated_at: datetime | None = None,
) -> ModelRun:
    """Record one completed or failed model execution; exact replay is idempotent."""
    run_key = required_text(run_key, "run_key")
    values = (
        required_text(model_name, "model_name"),
        required_text(model_version, "model_version"),
        required_text(feature_schema_version, "feature_schema_version"),
        required_text(configuration_version, "configuration_version"),
        checksum(code_commit_sha, "code_commit_sha", SHA1),
        checksum(data_snapshot_sha256, "data_snapshot_sha256", SHA256),
        choice(status, "status", ("completed", "failed")),
        optional_text(failure_reason, "failure_reason"),
        required_text(provenance, "provenance"),
    )
    if values[6] == "completed" and values[7] is not None:
        raise BusinessEntityError("completed model runs cannot have a failure_reason")
    if values[6] == "failed" and values[7] is None:
        raise BusinessEntityError("failed model runs require a failure_reason")
    generated_at_value = utc_timestamp(generated_at, "generated_at")

    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_RUN_COLUMNS} FROM model_runs WHERE run_key = ?", (run_key,)
            ).fetchone()
            if row is not None:
                existing = ModelRun(*row)
                recorded = (
                    existing.model_name,
                    existing.model_version,
                    existing.feature_schema_version,
                    existing.configuration_version,
                    existing.code_commit_sha,
                    existing.data_snapshot_sha256,
                    existing.status,
                    existing.failure_reason,
                    existing.provenance,
                )
                if recorded != values:
                    raise BusinessEntityConflictError(
                        "model run key already has different immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO model_runs "
                "(run_key, model_name, model_version, feature_schema_version, "
                "configuration_version, code_commit_sha, data_snapshot_sha256, "
                "status, failure_reason, generated_at, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_key, *values[:8], generated_at_value, values[8]),
            )
            return get_model_run(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("model run", exc) from exc


def get_model_prediction(
    conn: sqlite3.Connection, model_prediction_id: int
) -> ModelPrediction:
    row = conn.execute(
        f"SELECT {_PREDICTION_COLUMNS} FROM model_predictions WHERE id = ?",
        (model_prediction_id,),
    ).fetchone()
    if row is None:
        raise BusinessEntityError(
            f"model prediction does not exist: {model_prediction_id}"
        )
    return ModelPrediction(*row)


def record_model_prediction(
    conn: sqlite3.Connection,
    *,
    prediction_key: str,
    model_run_id: int,
    game_id: int,
    predicted_home_margin: float | int,
    provenance: str,
    home_win_probability: float | int | None = None,
    uncertainty_points: float | int | None = None,
    entry_market_line_id: int | None = None,
    entry_locked_line_id: int | None = None,
    generated_at: datetime | None = None,
) -> ModelPrediction:
    """Record a raw forecast without turning it into a pick or wager."""
    prediction_key = required_text(prediction_key, "prediction_key")
    model_run_id = integer(model_run_id, "model_run_id", 1)
    game_id = integer(game_id, "game_id", 1)
    margin = number(predicted_home_margin, "predicted_home_margin")
    probability = optional_number(home_win_probability, "home_win_probability")
    uncertainty = optional_number(uncertainty_points, "uncertainty_points")
    provenance = required_text(provenance, "provenance")
    if probability is not None and not 0 <= probability <= 1:
        raise BusinessEntityError("home_win_probability must be between 0 and 1")
    if uncertainty is not None and uncertainty < 0:
        raise BusinessEntityError("uncertainty_points cannot be negative")
    if entry_market_line_id is not None and entry_locked_line_id is not None:
        raise BusinessEntityError("a prediction can reference only one entry-line type")
    entry_market_line_id = (
        integer(entry_market_line_id, "entry_market_line_id", 1)
        if entry_market_line_id is not None
        else None
    )
    entry_locked_line_id = (
        integer(entry_locked_line_id, "entry_locked_line_id", 1)
        if entry_locked_line_id is not None
        else None
    )
    generated_at_value = utc_timestamp(generated_at, "generated_at")

    try:
        with atomic(conn):
            run = get_model_run(conn, model_run_id)
            if run.status != "completed":
                raise BusinessEntityError("predictions require a completed model run")
            if conn.execute(
                "SELECT 1 FROM games WHERE game_id = ?", (game_id,)
            ).fetchone() is None:
                raise BusinessEntityError(f"game does not exist: {game_id}")
            if entry_market_line_id is not None:
                row = conn.execute(
                    "SELECT game_id, line_type, fetched_at FROM betting_lines WHERE id = ?",
                    (entry_market_line_id,),
                ).fetchone()
                if row is None or row[0] != game_id:
                    raise BusinessEntityError(
                        "entry market line must belong to the predicted game"
                    )
                if row[1] not in ("opening", "current"):
                    raise BusinessEntityError(
                        "prediction entry requires an opening or current market line"
                    )
                if not timestamp_on_or_before(conn, row[2], generated_at_value):
                    raise BusinessEntityError(
                        "entry market line must be captured before prediction generation"
                    )
            if entry_locked_line_id is not None:
                line = get_effective_locked_line(conn, entry_locked_line_id)
                if line.game_id != game_id:
                    raise BusinessEntityError(
                        "entry locked line must identify the predicted game"
                    )
                if not timestamp_on_or_before(
                    conn, line.effective_at, generated_at_value
                ):
                    raise BusinessEntityError(
                        "entry locked line must be effective before prediction generation"
                    )

            row = conn.execute(
                f"SELECT {_PREDICTION_COLUMNS} FROM model_predictions "
                "WHERE prediction_key = ? OR (model_run_id = ? AND game_id = ?) "
                "ORDER BY prediction_key = ? DESC LIMIT 1",
                (prediction_key, model_run_id, game_id, prediction_key),
            ).fetchone()
            requested = (
                prediction_key,
                model_run_id,
                game_id,
                margin,
                probability,
                uncertainty,
                entry_market_line_id,
                entry_locked_line_id,
                provenance,
            )
            if row is not None:
                existing = ModelPrediction(*row)
                recorded = (
                    existing.prediction_key,
                    existing.model_run_id,
                    existing.game_id,
                    existing.predicted_home_margin,
                    existing.home_win_probability,
                    existing.uncertainty_points,
                    existing.entry_market_line_id,
                    existing.entry_locked_line_id,
                    existing.provenance,
                )
                if recorded != requested:
                    raise BusinessEntityConflictError(
                        "prediction key or run/game already has different immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO model_predictions "
                "(prediction_key, model_run_id, game_id, predicted_home_margin, "
                "home_win_probability, uncertainty_points, entry_market_line_id, "
                "entry_locked_line_id, generated_at, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*requested[:8], generated_at_value, provenance),
            )
            return get_model_prediction(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("model prediction", exc) from exc
