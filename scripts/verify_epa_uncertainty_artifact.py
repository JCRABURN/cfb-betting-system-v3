"""Rebuild and verify the governed EPA-only OOS uncertainty artifact."""

from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path

from models.epa_uncertainty import (
    DEFAULT_ARTIFACT_PATH,
    derive_oos_statistics,
    load_uncertainty_artifact,
)


ROOT = Path(__file__).resolve().parents[1]


def verify_artifact(database: Path, artifact_path: Path) -> dict[str, object]:
    artifact = load_uncertainty_artifact(artifact_path)
    uri = f"file:{database.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute("PRAGMA query_only = ON")
    try:
        derived = derive_oos_statistics(conn, artifact.evaluation_seasons)
    finally:
        conn.close()
    comparisons = {
        "eligible_predictions": artifact.eligible_predictions,
        "skipped_predictions": artifact.skipped_predictions,
        "residual_rmse_points": artifact.residual_rmse_points,
        "residual_bias_points": artifact.residual_bias_points,
        "feature_mean": artifact.feature_mean,
        "feature_sxx": artifact.feature_sxx,
        "ledger_sha256": artifact.ledger_sha256,
    }
    mismatches = {
        name: {"artifact": expected, "derived": derived[name]}
        for name, expected in comparisons.items()
        if derived[name] != expected
    }
    if mismatches:
        raise RuntimeError(
            "governed EPA uncertainty artifact is not reproducible: "
            + json.dumps(mismatches, sort_keys=True)
        )
    return {
        "artifact_version": artifact.artifact_version,
        "artifact_payload_sha256": artifact.artifact_payload_sha256,
        "evaluation_seasons": list(artifact.evaluation_seasons),
        **comparisons,
        "season_fits": derived["season_fits"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "cfb.db")
    parser.add_argument("--artifact", type=Path, default=DEFAULT_ARTIFACT_PATH)
    args = parser.parse_args()
    print(json.dumps(verify_artifact(args.database, args.artifact), indent=2, sort_keys=True))
    print("Governed EPA uncertainty artifact verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
