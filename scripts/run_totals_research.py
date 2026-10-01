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
    build_totals_research_dataset,
    run_totals_rolling_origin,
)


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
        dataset = build_totals_research_dataset(
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
    }
    if args.include_predictions:
        payload["predictions"] = [asdict(item) for item in result.predictions]
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
