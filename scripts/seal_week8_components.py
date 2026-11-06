"""Reconstruct and seal exact point-in-time model inputs for Week 8 audit custody.

This read-only verification recomputes the unchanged model projections from the
disposable execution DB. It fails if any component does not match the recorded
pregame prediction; no result or future-week statistic is used.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from business_entities.totals_components import get_total_score_component_prediction
from contest_lines import EffectiveContestLine
from models import backtest_harness as harness, baseline_epa
from models.totals_component_research import (
    build_totals_component_dataset, fit_totals_component_model,
    predict_totals_component_score,
)
from models.totals_research import TotalsResearchPolicy


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def components(conn: sqlite3.Connection, *, lines: tuple[EffectiveContestLine, ...],
               ats_run_id: int, total_run_id: int, ats_card_id: int, total_card_id: int,
               card_generated_at: datetime) -> dict:
    if not lines or any((line.season, line.week) != (2026, 8) for line in lines):
        raise ValueError("raw component custody requires the complete Week 8 lock")
    ats_seasons = tuple(harness.available_seasons_before(conn, 2026))
    ats_training, ats_targets = harness.build_training_set(conn, baseline_epa.epa_differential, ats_seasons)
    ats_intercept, ats_coefficients = harness.fit_multilinear(ats_training, ats_targets)
    total_seasons = tuple(sorted(set(ats_seasons) | {2026}))
    total_dataset, total_observations = build_totals_component_dataset(conn, seasons=total_seasons)
    total_training = tuple(item for item in total_observations if item.base.fold_key < (2026, 8))
    total_fit = fit_totals_component_model(total_training, policy=TotalsResearchPolicy())
    ats_run = conn.execute("SELECT model_name,model_version,code_commit_sha,data_snapshot_sha256 FROM model_runs WHERE id=?",
                           (ats_run_id,)).fetchone()
    total_run = conn.execute("SELECT model_name,model_version,code_commit_sha,data_snapshot_sha256 FROM total_model_runs WHERE id=?",
                             (total_run_id,)).fetchone()
    if ats_run is None or total_run is None or ats_run[2] != total_run[2]:
        raise ValueError("model run identity/commit mismatch")
    games = []
    for line in lines:
        game = conn.execute("SELECT home_team,away_team,start_date FROM games WHERE game_id=?",
                            (line.game_id,)).fetchone()
        if game is None:
            raise ValueError(f"missing game for raw component custody: {line.game_id}")
        kickoff = datetime.fromisoformat(game[2].replace("Z", "+00:00")).astimezone(timezone.utc)
        if card_generated_at >= kickoff or datetime.now(timezone.utc) >= kickoff:
            raise ValueError(f"raw component custody reached kickoff: {line.game_id}")
        package = harness.get_pregame_stats(conn, game[0], game[1], 2026, 8, game[2])
        if package is None:
            raise ValueError(f"missing point-in-time EPA component package: {line.game_id}")
        feature = baseline_epa.epa_differential(package)[0]
        calculated_ats = baseline_epa.predict_margin(package, ats_intercept, ats_coefficients)
        ats_prediction = conn.execute(
            "SELECT id,predicted_home_margin,uncertainty_points,generated_at FROM model_predictions "
            "WHERE model_run_id=? AND game_id=?", (ats_run_id, line.game_id)).fetchone()
        if ats_prediction is None or not math.isclose(calculated_ats, ats_prediction[1], abs_tol=1e-8):
            raise ValueError(f"ATS component replay mismatch: {line.game_id}")
        selected = conn.execute("SELECT selected_side FROM contest_picks WHERE card_id=? AND locked_line_id=?",
                                (ats_card_id, line.locked_line_id)).fetchone()
        if selected is None or selected[0] not in ("home", "away"):
            raise ValueError(f"missing governed selected side: {line.game_id}")
        selected_side = selected[0]
        signed_edge = calculated_ats + line.home_spread
        selected_edge = max(0.0, signed_edge if selected_side == "home" else -signed_edge)
        ats_shadow = conn.execute(
            "SELECT selected_margin_advantage_points,calibrated_selected_side_probability "
            "FROM ats_shadow_calibrated_evaluations WHERE contest_card_id=? AND game_id=?",
            (ats_card_id, line.game_id)).fetchone()
        expected_ats_score = min(.60, .50+.005*selected_edge)
        if (ats_shadow is None
                or not math.isclose(ats_shadow[0], selected_edge, abs_tol=1e-8)
                or not math.isclose(ats_shadow[1], expected_ats_score, abs_tol=1e-8)):
            raise ValueError(f"ATS shadow score replay mismatch: {line.game_id}")
        total_prediction = conn.execute(
            "SELECT id,projected_total,uncertainty_points,feature_snapshot_sha256,generated_at "
            "FROM total_model_predictions WHERE total_model_run_id=? AND game_id=?",
            (total_run_id, line.game_id)).fetchone()
        total_record = None
        if line.total is not None:
            if total_prediction is None:
                raise ValueError(f"missing total model component prediction: {line.game_id}")
            features = tuple(float(package[side][key]) for side, key in
                             (("home_stats", "offense_epa_play"), ("home_stats", "defense_epa_play"),
                              ("away_stats", "offense_epa_play"), ("away_stats", "defense_epa_play")))
            home_points, away_points = predict_totals_component_score(features, total_fit)
            sealed_component = get_total_score_component_prediction(conn, total_prediction[0])
            if (not math.isclose(home_points, sealed_component.projected_home_points, abs_tol=1e-8)
                    or not math.isclose(away_points, sealed_component.projected_away_points, abs_tol=1e-8)
                    or not math.isclose(home_points+away_points, total_prediction[1], abs_tol=1e-8)
                    or not math.isclose(total_prediction[2], total_fit.uncertainty_points, abs_tol=1e-8)):
                raise ValueError(f"total component replay mismatch: {line.game_id}")
            snapshot = {"game_id": line.game_id, "features": features,
                        "home_stats_as_of": [package["home_stats"]["as_of_season"],
                                             package["home_stats"]["as_of_week"]],
                        "away_stats_as_of": [package["away_stats"]["as_of_season"],
                                             package["away_stats"]["as_of_week"]]}
            if canonical_sha(snapshot) != total_prediction[3]:
                raise ValueError(f"total feature hash mismatch: {line.game_id}")
            candidate = conn.execute(
                "SELECT selected_direction,raw_over_probability,calibrated_over_probability,selected_probability "
                "FROM total_card_candidates WHERE total_shadow_card_id=? AND locked_line_id=?",
                (total_card_id, line.locked_line_id)).fetchone()
            if candidate is None:
                raise ValueError(f"missing totals research card candidate: {line.game_id}")
            z_score = (total_prediction[1]-line.total)/total_prediction[2]
            raw_over = .5*(1+math.erf(z_score/math.sqrt(2)))
            expected_selected = raw_over if candidate[0] == "over" else 1-raw_over
            if (not math.isclose(raw_over, candidate[1], abs_tol=1e-10)
                    or not math.isclose(candidate[1], candidate[2], abs_tol=1e-10)
                    or not math.isclose(expected_selected, candidate[3], abs_tol=1e-10)):
                raise ValueError(f"totals shadow score replay mismatch: {line.game_id}")
            total_record = {"prediction_id": total_prediction[0], "features": features,
                            "feature_snapshot_sha256": total_prediction[3],
                            "projected_home_points": home_points, "projected_away_points": away_points,
                            "projected_total": total_prediction[1],
                            "residual_uncertainty_points": total_prediction[2],
                            "locked_total": line.total,
                            "z_score": z_score, "raw_over_probability_normal_assumption": raw_over,
                            "calibration_slope": 1.0, "selected_direction": candidate[0],
                            "shadow_selected_score_not_empirically_calibrated": candidate[3],
                            "prediction_generated_at": total_prediction[4]}
        elif total_prediction is not None:
            # It is possible for the model to forecast a game that lacks a contest total.
            total_record = {"status": "NO_LOCKED_TOTAL;NOT_A_TOTALS_SELECTION",
                            "prediction_id": total_prediction[0]}
        games.append({"game_id": line.game_id, "locked_line_id": line.locked_line_id,
                      "kickoff_utc": kickoff.isoformat(), "home": line.normalized_home_team,
                      "away": line.normalized_away_team, "locked_home_spread": line.home_spread,
                      "raw_point_in_time_package": package,
                      "ats": {"prediction_id": ats_prediction[0], "epa_differential": feature,
                              "intercept": ats_intercept, "coefficients": ats_coefficients,
                              "projected_home_margin": calculated_ats,
                              "governed_uncertainty_points": ats_prediction[2],
                              "governed_selected_side": selected_side,
                              "selected_margin_advantage_points": selected_edge,
                              "shadow_score_transform": "min(0.60,0.50+0.005*selected_margin_advantage_points)",
                              "shadow_score_not_empirically_calibrated": expected_ats_score,
                              "prediction_generated_at": ats_prediction[3]},
                      "totals": total_record,
                      "non_model_context": {kind: "NOT_USED_IN_RAW_MODEL;PENDING_SEPARATE_SOURCED_REVIEW"
                                            for kind in ("injury", "qb", "weather", "travel_rest", "coaching", "market")}})
    return {"status": "PREGAME_COMPONENT_REPLAY_VERIFIED", "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "card_generated_at_utc": card_generated_at.isoformat(),
            "code_commit_sha": ats_run[2],
            "ats_model": {"name": ats_run[0], "version": ats_run[1],
                          "data_snapshot_sha256": ats_run[3], "training_seasons": ats_seasons,
                          "training_rows": len(ats_training), "intercept": ats_intercept,
                          "coefficients": ats_coefficients},
            "totals_model": {"name": total_run[0], "version": total_run[1],
                             "data_snapshot_sha256": total_run[3],
                             "training_dataset_sha256": total_dataset.dataset_sha256,
                             "training_rows": len(total_training), "fitted": asdict(total_fit)},
            "games": games}


def seal(path: Path, payload: dict) -> str:
    if path.exists():
        raise ValueError("raw component artifact already exists; never overwrite")
    raw = (json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()
