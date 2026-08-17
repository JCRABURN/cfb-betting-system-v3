"""Run the versioned model-research suite against a SQLite snapshot.

The database is opened read-only/query-only. Results are canonical JSON on
stdout; the command never writes a model, policy, prediction, or database row.

Example::

    python -m models.run_research \
      --database data/cfb.db \
      --code-commit-sha 0123456789abcdef0123456789abcdef01234567
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from models import research_framework as research


FEATURE_SCHEMA = (
    "epa_differential",
    "success_rate_differential",
    "havoc_rate_differential",
    "rest_days_differential",
    "bye_flag_differential",
)


def _database_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as database_file:
        for block in iter(lambda: database_file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_only_connection(path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _models():
    baseline = research.epa_only_baseline()
    candidates = (
        research.ridge_candidate(
            model_key="ridge_complete_features",
            model_version="ridge-complete-features-v1",
            feature_names=FEATURE_SCHEMA,
            l2_penalty=10.0,
        ),
        research.dynamic_rating_candidate(
            model_key="dynamic_team_ratings",
            model_version="dynamic-team-ratings-v1",
            update_rate=0.10,
            carry_decay=0.25,
        ),
        research.gradient_boosted_candidate(
            model_key="gradient_boosted_stumps",
            model_version="gradient-boosted-stumps-v1",
            feature_names=FEATURE_SCHEMA,
            estimator_count=25,
            learning_rate=0.05,
            minimum_leaf_size=50,
        ),
    )
    return baseline, candidates


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Run weekly rolling-origin model research without database writes."
    )
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--code-commit-sha", required=True)
    parser.add_argument(
        "--seasons",
        nargs="+",
        type=int,
        default=[2021, 2022, 2023, 2024, 2025],
    )
    parser.add_argument(
        "--feature-schema-version",
        default="market-residual-features-v1",
    )
    parser.add_argument(
        "--configuration-version",
        default="model-research-suite-v1",
    )
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    database_path = args.database.resolve(strict=True)
    database_sha = _database_sha256(database_path)
    connection = _read_only_connection(database_path)
    try:
        dataset = research.build_research_dataset(
            connection,
            seasons=tuple(args.seasons),
            feature_names=FEATURE_SCHEMA,
        )
    finally:
        connection.close()
    baseline, candidates = _models()
    result = research.run_weekly_rolling_origin(
        dataset=dataset,
        baseline=baseline,
        candidates=candidates,
        policy=research.default_research_policy(),
        metadata=research.ResearchMetadata(
            code_commit_sha=args.code_commit_sha,
            data_snapshot_sha256=database_sha,
            feature_schema_version=args.feature_schema_version,
            configuration_version=args.configuration_version,
            generated_at=datetime.now(timezone.utc).isoformat(),
        ),
    )
    print(
        json.dumps(
            asdict(result),
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
