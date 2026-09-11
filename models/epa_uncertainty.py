"""Governed predictive uncertainty for the frozen EPA-only ATS baseline.

The production margin model remains unchanged.  This module supplies the
reliability input that the existing Confidence and Top-5 policies expect.  Its
scale comes exclusively from genuine rolling-origin prediction residuals; the
per-game support term is the standard one-feature prediction-leverage term.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


MODEL_NAME = "epa_only"
MODEL_VERSION = "epa-only-linear-v1"
FEATURE_SCHEMA_VERSION = "epa-differential-v1"
CONFIGURATION_VERSION = "walk-forward-prior-seasons-v1"
UNCERTAINTY_POLICY_VERSION = "epa-oos-predictive-uncertainty-v1"
FORMULA_VERSION = "oos-rmse-one-feature-prediction-leverage-v1"
DEFAULT_ARTIFACT_PATH = (
    Path(__file__).resolve().parents[1]
    / "config"
    / "epa-only-oos-uncertainty-v1.json"
)


class EpaUncertaintyError(ValueError):
    """Raised when governed EPA uncertainty custody is missing or invalid."""


@dataclass(frozen=True)
class EpaUncertaintyArtifact:
    artifact_version: str
    model_name: str
    model_version: str
    feature_schema_version: str
    configuration_version: str
    formula_version: str
    baseline_code_commit_sha: str
    outcome_cutoff_season: int
    evaluation_seasons: tuple[int, ...]
    eligible_predictions: int
    skipped_predictions: int
    residual_rmse_points: float
    residual_bias_points: float
    feature_mean: float
    feature_sxx: float
    ledger_sha256: str
    generated_at: str
    provenance: str
    artifact_payload_sha256: str

    def uncertainty_points(self, feature_value: float) -> float:
        """Return predictive SD; no market line, edge, or target outcome enters."""
        x = _finite_number(feature_value, "feature_value")
        leverage = (
            1.0
            + 1.0 / self.eligible_predictions
            + (x - self.feature_mean) ** 2 / self.feature_sxx
        )
        return self.residual_rmse_points * math.sqrt(leverage)


def _finite_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise EpaUncertaintyError(f"{name} must be numeric")
    converted = float(value)
    if not math.isfinite(converted):
        raise EpaUncertaintyError(f"{name} must be finite")
    return converted


def _sha256(value: str) -> str:
    normalized = value.casefold()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise EpaUncertaintyError("artifact hashes must be lowercase SHA-256")
    return normalized


def _sha1(value: str) -> str:
    normalized = value.casefold()
    if len(normalized) != 40 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise EpaUncertaintyError("baseline code commit must be lowercase SHA-1")
    return normalized


def _canonical_payload(payload: Mapping[str, Any]) -> str:
    governed = dict(payload)
    governed.pop("artifact_payload_sha256", None)
    return json.dumps(governed, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def artifact_payload_sha256(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_payload(payload).encode("utf-8")).hexdigest()


def artifact_from_mapping(payload: Mapping[str, Any]) -> EpaUncertaintyArtifact:
    expected_hash = _sha256(str(payload.get("artifact_payload_sha256", "")))
    actual_hash = artifact_payload_sha256(payload)
    if actual_hash != expected_hash:
        raise EpaUncertaintyError("EPA uncertainty artifact checksum mismatch")
    expected_identity = {
        "artifact_version": UNCERTAINTY_POLICY_VERSION,
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "configuration_version": CONFIGURATION_VERSION,
        "formula_version": FORMULA_VERSION,
    }
    for field_name, expected in expected_identity.items():
        if payload.get(field_name) != expected:
            raise EpaUncertaintyError(
                f"EPA uncertainty artifact {field_name} does not match {expected}"
            )
    seasons_value = payload.get("evaluation_seasons")
    if not isinstance(seasons_value, list) or not seasons_value:
        raise EpaUncertaintyError("evaluation_seasons must be a non-empty list")
    seasons = tuple(int(item) for item in seasons_value)
    if tuple(sorted(set(seasons))) != seasons:
        raise EpaUncertaintyError("evaluation_seasons must be unique and ordered")
    outcome_cutoff = int(payload.get("outcome_cutoff_season", 0))
    if outcome_cutoff != seasons[-1]:
        raise EpaUncertaintyError("outcome cutoff must equal the last evaluation season")
    eligible = int(payload.get("eligible_predictions", 0))
    skipped = int(payload.get("skipped_predictions", -1))
    if eligible < 2 or skipped < 0:
        raise EpaUncertaintyError("artifact prediction counts are invalid")
    rmse = _finite_number(payload.get("residual_rmse_points"), "residual_rmse_points")
    feature_sxx = _finite_number(payload.get("feature_sxx"), "feature_sxx")
    if rmse <= 0 or feature_sxx <= 0:
        raise EpaUncertaintyError("artifact residual scale and feature support must be positive")
    generated_at = str(payload.get("generated_at", "")).strip()
    provenance = str(payload.get("provenance", "")).strip()
    if not generated_at or not provenance:
        raise EpaUncertaintyError("artifact timestamp and provenance are required")
    return EpaUncertaintyArtifact(
        artifact_version=UNCERTAINTY_POLICY_VERSION,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        feature_schema_version=FEATURE_SCHEMA_VERSION,
        configuration_version=CONFIGURATION_VERSION,
        formula_version=FORMULA_VERSION,
        baseline_code_commit_sha=_sha1(
            str(payload.get("baseline_code_commit_sha", ""))
        ),
        outcome_cutoff_season=outcome_cutoff,
        evaluation_seasons=seasons,
        eligible_predictions=eligible,
        skipped_predictions=skipped,
        residual_rmse_points=rmse,
        residual_bias_points=_finite_number(
            payload.get("residual_bias_points"), "residual_bias_points"
        ),
        feature_mean=_finite_number(payload.get("feature_mean"), "feature_mean"),
        feature_sxx=feature_sxx,
        ledger_sha256=_sha256(str(payload.get("ledger_sha256", ""))),
        generated_at=generated_at,
        provenance=provenance,
        artifact_payload_sha256=expected_hash,
    )


def load_uncertainty_artifact(
    path: Path = DEFAULT_ARTIFACT_PATH,
) -> EpaUncertaintyArtifact:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EpaUncertaintyError("governed EPA uncertainty artifact is unavailable") from exc
    if not isinstance(payload, dict):
        raise EpaUncertaintyError("EPA uncertainty artifact must be a JSON object")
    return artifact_from_mapping(payload)


def derive_oos_statistics(
    conn: Any,
    evaluation_seasons: tuple[int, ...],
) -> dict[str, object]:
    """Rebuild the frozen rolling-origin residual ledger from SQLite.

    This intentionally mirrors ``run_walk_forward`` without its presentation
    rounding so the residual artifact reflects exact model forecasts.
    """
    from models import backtest_harness as harness
    from models import baseline_epa

    ledger: list[dict[str, object]] = []
    skipped = 0
    season_fits: dict[str, dict[str, object]] = {}
    for season in evaluation_seasons:
        training_seasons = harness.available_seasons_before(conn, season)
        rows, targets = harness.build_training_set(
            conn, baseline_epa.epa_differential, training_seasons
        )
        intercept, coefficients = harness.fit_multilinear(rows, targets)
        season_fits[str(season)] = {
            "training_seasons": training_seasons,
            "training_rows": len(rows),
            "intercept": intercept,
            "coefficients": list(coefficients),
        }
        for week in harness.list_weeks(conn, season):
            for (
                game_id,
                home_team,
                away_team,
                home_points,
                away_points,
                start_date,
            ) in harness.list_games(conn, season, week):
                package, reason = harness.build_feature_package(
                    conn,
                    game_id,
                    season,
                    week,
                    home_team,
                    away_team,
                    start_date,
                )
                if package is None or reason is not None:
                    skipped += 1
                    continue
                feature_value = baseline_epa.epa_differential(package)[0]
                predicted_margin = baseline_epa.predict_margin(
                    package, intercept, coefficients
                )
                actual_margin = home_points - away_points
                ledger.append(
                    {
                        "actual_home_margin": actual_margin,
                        "game_id": game_id,
                        "predicted_home_margin": predicted_margin,
                        "residual": actual_margin - predicted_margin,
                        "season": season,
                        "week": week,
                        "x": feature_value,
                    }
                )
    if len(ledger) < 2:
        raise EpaUncertaintyError("OOS residual ledger has insufficient predictions")
    residuals = [float(row["residual"]) for row in ledger]
    features = [float(row["x"]) for row in ledger]
    feature_mean = sum(features) / len(features)
    feature_sxx = sum((value - feature_mean) ** 2 for value in features)
    if feature_sxx <= 0:
        raise EpaUncertaintyError("OOS feature support is singular")
    ledger_json = json.dumps(
        ledger, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return {
        "eligible_predictions": len(ledger),
        "skipped_predictions": skipped,
        "residual_rmse_points": math.sqrt(
            sum(value * value for value in residuals) / len(residuals)
        ),
        "residual_bias_points": sum(residuals) / len(residuals),
        "feature_mean": feature_mean,
        "feature_sxx": feature_sxx,
        "ledger_sha256": hashlib.sha256(ledger_json.encode("utf-8")).hexdigest(),
        "season_fits": season_fits,
    }
