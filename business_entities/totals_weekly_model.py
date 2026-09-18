"""Manual shadow weekly runner for the independent component-score totals model."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict
from datetime import datetime

from business_entities.common import (
    SHA1,
    BusinessEntityError,
    atomic,
    checksum,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)
from business_entities.totals import (
    TotalModelRun,
    record_total_model_prediction,
    record_total_model_run,
)
from business_entities.totals_components import (
    record_total_score_component_prediction,
)
from contest_lines import get_contest, list_effective_locked_lines
from models import backtest_harness as harness
from models.totals_component_research import (
    CONFIGURATION_VERSION,
    MODEL_NAME,
    MODEL_VERSION,
    build_totals_component_dataset,
    fit_totals_component_model,
    predict_totals_component_score,
)
from models.totals_research import FEATURE_SCHEMA_VERSION, TotalsResearchPolicy


def _sha256(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def run_component_totals_shadow_model(
    conn: sqlite3.Connection,
    *,
    contest_id: int,
    model_run_key: str,
    code_commit_sha: str,
    generated_at: datetime,
    provenance: str,
    policy: TotalsResearchPolicy = TotalsResearchPolicy(),
) -> TotalModelRun:
    """Fit strict-prior folds and record PIT forecasts without changing ATS."""
    contest = get_contest(conn, contest_id)
    key = required_text(model_run_key, "model_run_key")
    commit = checksum(code_commit_sha, "code_commit_sha", SHA1)
    generated_value = utc_timestamp(generated_at, "generated_at")
    provenance = required_text(provenance, "provenance")
    lines = list_effective_locked_lines(conn, contest.id, as_of=generated_at)
    if not lines:
        raise BusinessEntityError("totals shadow model requires locked contest lines")
    if any((line.season, line.week) != (contest.season, contest.week) for line in lines):
        raise BusinessEntityError("contest lines do not share the contest fold")
    seasons = tuple(
        sorted(
            set(harness.available_seasons_before(conn, contest.season))
            | {contest.season}
        )
    )
    dataset, component_observations = build_totals_component_dataset(
        conn, seasons=seasons
    )
    training = tuple(
        item
        for item in component_observations
        if item.base.fold_key < (contest.season, contest.week)
    )
    fitted = fit_totals_component_model(training, policy=policy)
    targets = []
    for line in lines:
        if line.game_id is None:
            targets.append((line, None, "missing_game_identity"))
            continue
        game = conn.execute(
            "SELECT home_team, away_team, start_date FROM games WHERE game_id = ?",
            (line.game_id,),
        ).fetchone()
        if game is None or game[2] is None:
            targets.append((line, None, "missing_game_or_kickoff"))
            continue
        if timestamp_on_or_before(conn, game[2], generated_value):
            targets.append((line, None, "kickoff_not_in_future"))
            continue
        package = harness.get_pregame_stats(
            conn,
            game[0],
            game[1],
            contest.season,
            contest.week,
            game[2],
        )
        if package is None:
            targets.append((line, None, "missing_point_in_time_epa"))
            continue
        features = (
            package["home_stats"].get("offense_epa_play"),
            package["home_stats"].get("defense_epa_play"),
            package["away_stats"].get("offense_epa_play"),
            package["away_stats"].get("defense_epa_play"),
        )
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in features
        ):
            targets.append((line, None, "missing_point_in_time_epa"))
            continue
        targets.append((line, (package, tuple(float(value) for value in features)), None))
    data_hash = _sha256(
        {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "policy": asdict(policy),
            "training_dataset_sha256": dataset.dataset_sha256,
            "training_game_ids": [item.base.game_id for item in training],
            "target_fold": [contest.season, contest.week],
            "targets": [
                {
                    "locked_line_id": line.locked_line_id,
                    "game_id": line.game_id,
                    "sealed_input": sealed,
                    "skip_reason": skip,
                }
                for line, sealed, skip in targets
            ],
        }
    )
    try:
        with atomic(conn):
            run = record_total_model_run(
                conn,
                run_key=key,
                model_name=MODEL_NAME,
                model_version=MODEL_VERSION,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                configuration_version=CONFIGURATION_VERSION,
                code_commit_sha=commit,
                data_snapshot_sha256=data_hash,
                lifecycle_stage="shadow",
                status="completed",
                generated_at=generated_at,
                provenance=(
                    f"{provenance};training_count={len(training)};"
                    f"dataset_sha256={dataset.dataset_sha256};"
                    "skipped=" + (",".join(
                        f"{line.game_id}:{skip}"
                        for line, _, skip in targets if skip is not None
                    ) or "none") + ";"
                    "unavailable_inputs_are_explicit_prediction_omissions"
                ),
            )
            for line, sealed, skip_reason in targets:
                if sealed is None or skip_reason is not None or line.game_id is None:
                    continue
                package, features = sealed
                home, away = predict_totals_component_score(features, fitted)
                feature_hash = _sha256(
                    {
                        "game_id": line.game_id,
                        "features": features,
                        "home_stats_as_of": [
                            package["home_stats"]["as_of_season"],
                            package["home_stats"]["as_of_week"],
                        ],
                        "away_stats_as_of": [
                            package["away_stats"]["as_of_season"],
                            package["away_stats"]["as_of_week"],
                        ],
                    }
                )
                prediction = record_total_model_prediction(
                    conn,
                    prediction_key=f"{key}:game:{line.game_id}",
                    total_model_run_id=run.id,
                    game_id=line.game_id,
                    projected_total=home + away,
                    uncertainty_points=fitted.uncertainty_points,
                    home_stats_as_of_season=package["home_stats"]["as_of_season"],
                    home_stats_as_of_week=package["home_stats"]["as_of_week"],
                    away_stats_as_of_season=package["away_stats"]["as_of_season"],
                    away_stats_as_of_week=package["away_stats"]["as_of_week"],
                    features_as_of_at=generated_at,
                    feature_snapshot_sha256=feature_hash,
                    provenance=f"{provenance};locked_line_id={line.locked_line_id}",
                    generated_at=generated_at,
                )
                record_total_score_component_prediction(
                    conn,
                    total_model_prediction_id=prediction.id,
                    component_model_version=MODEL_VERSION,
                    projected_home_points=home,
                    projected_away_points=away,
                    generated_at=generated_at,
                    provenance=f"{provenance};component_scores",
                )
            return run
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("totals weekly shadow model", exc) from exc
