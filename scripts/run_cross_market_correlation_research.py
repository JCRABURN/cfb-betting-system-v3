"""Join the exact ATS baseline and totals OOS ledgers for dependence evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path

from models import backtest_harness as harness
from models import baseline_epa
from models.cross_market_correlation import (
    estimate_cross_market_correlations,
    outcomes_from_prediction_ledgers,
)
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
        description="Run read-only OOS ATS/totals correlation research."
    )
    parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    parser.add_argument("--seasons", nargs="+", type=int, required=True)
    parser.add_argument("--minimum-training-examples", type=int, default=100)
    args = parser.parse_args()
    if len(args.seasons) < 2:
        parser.error("at least one training season and one evaluation season are required")
    database = args.database.resolve()
    before = _sha256(database)
    conn = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    try:
        totals_dataset = build_totals_research_dataset(
            conn, seasons=tuple(args.seasons)
        )
        totals_result = run_totals_rolling_origin(
            totals_dataset,
            policy=TotalsResearchPolicy(
                minimum_training_examples=args.minimum_training_examples
            ),
        )
        ats_records, _ = harness.run_walk_forward(
            conn,
            list(args.seasons[1:]),
            baseline_epa.epa_differential,
            baseline_epa.predict_margin,
        )
    finally:
        conn.close()
    outcomes = outcomes_from_prediction_ledgers(ats_records, totals_result.predictions)
    correlation = estimate_cross_market_correlations(outcomes)
    after = _sha256(database)
    if after != before:
        raise RuntimeError("authoritative database changed during correlation research")
    print(
        json.dumps(
            {
                "ats_model": "epa_only",
                "ats_model_version": "epa-only-linear-v1",
                "ats_feature_schema": "epa-differential-v1",
                "ats_configuration": "walk-forward-prior-seasons-v1",
                "totals_model": totals_result.model_name,
                "totals_model_version": totals_result.model_version,
                "joined_oos_game_count": len(outcomes),
                "database_sha256_before": before,
                "database_sha256_after": after,
                "database_unchanged": before == after,
                "correlation": asdict(correlation),
            },
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
