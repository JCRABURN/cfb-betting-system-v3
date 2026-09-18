"""Run the governed totals baseline against a read-only historical database."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from models.totals_research import (
    TotalsResearchPolicy,
    run_totals_rolling_origin,
)
from models.totals_component_research import (
    build_totals_component_dataset,
    run_totals_component_rolling_origin,
)
from models.totals_evaluation import evaluate_totals_research


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATABASE = ROOT / "data" / "cfb.db"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run point-in-time rolling-origin totals research."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--seasons", nargs="+", type=int, required=True)
    parser.add_argument("--minimum-training-examples", type=int, default=100)
    parser.add_argument("--include-predictions", action="store_true")
    args = parser.parse_args()

    database = args.database.resolve()
    before_hash = _sha256(database)
    connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    try:
        dataset, component_observations = build_totals_component_dataset(
            connection, seasons=tuple(args.seasons)
        )
    finally:
        connection.close()
    result = run_totals_rolling_origin(
        dataset,
        policy=TotalsResearchPolicy(
            minimum_training_examples=args.minimum_training_examples
        ),
    )
    component_result = run_totals_component_rolling_origin(
        dataset,
        component_observations,
        policy=result.policy,
    )
    evaluation = evaluate_totals_research(dataset, result)
    after_hash = _sha256(database)
    if after_hash != before_hash:
        raise RuntimeError("authoritative database changed during totals research")

    payload = {
        "database_sha256_before": before_hash,
        "database_sha256_after": after_hash,
        "database_unchanged": before_hash == after_hash,
        "dataset_observation_count": len(dataset.observations),
        "dataset_skip_count": len(dataset.skips),
        "dataset_skip_reasons": {
            reason: sum(item.reason == reason for item in dataset.skips)
            for reason in sorted({item.reason for item in dataset.skips})
        },
        "model_name": result.model_name,
        "model_version": result.model_version,
        "feature_schema_version": result.feature_schema_version,
        "target_version": result.target_version,
        "probability_model_version": result.probability_model_version,
        "probability_status": result.probability_status,
        "empirically_calibrated_probability": (
            result.empirically_calibrated_probability_status
        ),
        "selected_book_distribution": {
            book: sum(item.opening_book == book for item in dataset.observations)
            for book in sorted(
                {item.opening_book for item in dataset.observations if item.opening_book}
            )
        },
        "quote_time_custody_distribution": {
            status: sum(
                item.quote_time_custody_status == status
                for item in dataset.observations
            )
            for status in sorted(
                {
                    item.quote_time_custody_status
                    for item in dataset.observations
                    if item.quote_time_custody_status
                }
            )
        },
        "configuration_version": result.configuration_version,
        "policy": asdict(result.policy),
        "dataset_sha256": result.dataset_sha256,
        "fold_count": len(result.fold_audits),
        "skipped_fold_count": len(result.skipped_folds),
        "metrics": asdict(result.metrics),
        "ledger_sha256": result.ledger_sha256,
        "governance_status": result.governance_status,
        "production_eligible": result.production_eligible,
        "recommendation": result.recommendation,
        "component_score_model": {
            "model_name": component_result.model_name,
            "model_version": component_result.model_version,
            "target_version": component_result.target_version,
            "configuration_version": component_result.configuration_version,
            "home_mae": component_result.home_mae,
            "away_mae": component_result.away_mae,
            "total_mae": component_result.total_mae,
            "total_rmse": component_result.total_rmse,
            "ledger_sha256": component_result.ledger_sha256,
            "governance_status": component_result.governance_status,
            "production_eligible": component_result.production_eligible,
        },
        "comparative_evaluation": asdict(evaluation),
    }
    if args.include_predictions:
        payload["predictions"] = [asdict(item) for item in result.predictions]
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
