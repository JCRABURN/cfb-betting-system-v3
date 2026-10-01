"""Run the repaired Week 2 ATS replay and historical Weeks 2-4 research."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import shutil
import sqlite3
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from business_entities import ConfidenceRankingPolicy, FullCardPolicy, ManualAdjustmentPolicy
from business_entities.full_card import generate_full_card
from business_entities.modeling import get_model_prediction
from business_entities.weekly_controller import run_epa_only_model
from migrations.runner import apply_migrations
from models import backtest_harness as harness
from models import baseline_epa
from models.early_season_epa_research import (
    build_early_season_rows,
    extreme_and_opponent_summaries,
    grouped_summaries,
    paired_ats_comparisons,
)
from models.epa_uncertainty import load_uncertainty_artifact


ROOT = Path(__file__).resolve().parents[1]
GENERATED_AT = datetime(2026, 9, 10, 15, 38, 30, tzinfo=timezone.utc)
POLICY_AT = datetime(2026, 8, 1, tzinfo=timezone.utc)
POLICY_PROVENANCE = "proposed-v3-production-policy-registration-requires-owner-approval"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _prior_opponent(conn: sqlite3.Connection, team: str, kickoff: str) -> str:
    row = conn.execute(
        "SELECT home_team, away_team FROM games "
        "WHERE season = 2026 AND week < 2 AND start_date < ? "
        "AND (home_team = ? OR away_team = ?) ORDER BY start_date DESC LIMIT 1",
        (kickoff, team, team),
    ).fetchone()
    if row is None:
        return "unknown"
    opponent = row[1] if row[0] == team else row[0]
    is_fbs = conn.execute(
        "SELECT 1 FROM teams WHERE lower(trim(school)) = lower(trim(?)) LIMIT 1",
        (opponent,),
    ).fetchone()
    return "FBS" if is_fbs is not None else "FCS"


def _run_week2(
    source_database: Path,
    manifest: dict[str, object],
    code_commit_sha: str,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    with tempfile.TemporaryDirectory(prefix="week2-ats-reliability-") as temp_dir:
        database = Path(temp_dir) / "cfb.db"
        shutil.copy2(source_database, database)
        conn = sqlite3.connect(database)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            migrations = apply_migrations(conn)
            contest_row = conn.execute(
                "SELECT id FROM contests WHERE contest_key = ? AND season = 2026 "
                "AND week = 2",
                (manifest["contest_key"],),
            ).fetchone()
            if contest_row is None:
                raise RuntimeError("authoritative Week 2 contest is unavailable")
            contest_id = int(contest_row[0])
            run = run_epa_only_model(
                conn,
                contest_id=contest_id,
                model_run_key="splashsports-2026-week-2:provisional-uncertainty-v1:model",
                code_commit_sha=code_commit_sha,
                generated_at=GENERATED_AT,
                provenance="research://week2-ats-uncertainty-repair",
            )
            selection_policy = FullCardPolicy(
                version="production-selection-v1",
                market_books=(),
                model_tie_side="away",
                pickem_tiebreak_side="home",
            )
            confidence_policy = ConfidenceRankingPolicy(
                policy_key="production-confidence-ranking-v1",
                confidence_policy_version="production-confidence-v1",
                ranking_policy_version="production-ranking-v1",
                confidence_5_max_uncertainty=2.0,
                confidence_4_max_uncertainty=4.0,
                confidence_3_max_uncertainty=6.0,
                confidence_2_max_uncertainty=8.0,
                effective_at=POLICY_AT,
                created_by="repository-owner",
                provenance=POLICY_PROVENANCE,
            )
            card = generate_full_card(
                conn,
                card_key="splashsports-2026-week-2:provisional-uncertainty-v1:card",
                contest_id=contest_id,
                model_run_id=run.id,
                version=2,
                policy=selection_policy,
                confidence_policy=confidence_policy,
                adjustment_policy=ManualAdjustmentPolicy(
                    policy_version="production-adjustment-v1",
                    effective_at=POLICY_AT,
                    created_by="repository-owner",
                    provenance=POLICY_PROVENANCE,
                ),
                created_by="repository-owner",
                provenance="research://week2-ats-uncertainty-repair",
                generated_at=GENERATED_AT,
            )
            training_rows, training_targets = harness.build_training_set(
                conn,
                baseline_epa.epa_differential,
                harness.available_seasons_before(conn, 2026),
            )
            intercept, coefficients = harness.fit_multilinear(
                training_rows, training_targets
            )
            training_x = [float(item[0]) for item in training_rows]
            training_mean = sum(training_x) / len(training_x)
            training_sd = math.sqrt(
                sum((value - training_mean) ** 2 for value in training_x)
                / len(training_x)
            )
            results: list[dict[str, object]] = []
            for pick in card.picks:
                line = conn.execute(
                    "SELECT game_id, normalized_away_team, normalized_home_team, "
                    "home_spread FROM contest_locked_lines WHERE id = ?",
                    (pick.locked_line_id,),
                ).fetchone()
                assert line is not None and pick.model_prediction_id is not None
                game = conn.execute(
                    "SELECT start_date FROM games WHERE game_id = ?", (line[0],)
                ).fetchone()
                assert game is not None
                package = harness.get_pregame_stats(
                    conn, line[2], line[1], 2026, 2, game[0]
                )
                assert package is not None
                x = float(baseline_epa.epa_differential(package)[0])
                z = (x - training_mean) / training_sd
                prediction = get_model_prediction(conn, pick.model_prediction_id)
                home_edge = prediction.predicted_home_margin + float(line[3])
                selected_team = line[2] if pick.selected_side == "home" else line[1]
                selected_spread = (
                    float(line[3]) if pick.selected_side == "home" else -float(line[3])
                )
                prior_home = harness.get_prior_season_final_stats(conn, line[2], 2026)
                prior_away = harness.get_prior_season_final_stats(conn, line[1], 2026)
                fixed_prior: dict[str, object] = {}
                for current_weight in (0.25, 0.50, 0.75):
                    blended: dict[str, dict[str, object]] = {}
                    fallbacks: list[str] = []
                    for side, current_stats, prior_stats in (
                        ("home_stats", package["home_stats"], prior_home),
                        ("away_stats", package["away_stats"], prior_away),
                    ):
                        blended_stats = dict(current_stats)
                        if prior_stats is None:
                            fallbacks.append(f"{side}:current_only_missing_prior")
                        else:
                            for field in ("offense_epa_play", "defense_epa_play"):
                                blended_stats[field] = (
                                    current_weight * float(current_stats[field])
                                    + (1 - current_weight) * float(prior_stats[field])
                                )
                        blended[side] = blended_stats
                    candidate_x = float(baseline_epa.epa_differential(blended)[0])
                    fixed_prior[
                        f"{int(current_weight * 100)}_current_"
                        f"{int((1-current_weight) * 100)}_prior"
                    ] = {
                        "projected_home_margin": baseline_epa.predict_margin(
                            blended, intercept, coefficients
                        ),
                        "feature_x": candidate_x,
                        "feature_z": (candidate_x - training_mean) / training_sd,
                        "fallbacks": fallbacks,
                    }
                results.append(
                    {
                        "game_id": int(line[0]),
                        "away": line[1],
                        "home": line[2],
                        "locked_home_spread": float(line[3]),
                        "projected_home_margin": prediction.predicted_home_margin,
                        "selected_side": pick.selected_side,
                        "selected_team": selected_team,
                        "selected_spread": selected_spread,
                        "raw_ats_edge": abs(home_edge),
                        "feature_x": x,
                        "feature_z": z,
                        "home_offense_epa": package["home_stats"]["offense_epa_play"],
                        "home_defense_epa": package["home_stats"]["defense_epa_play"],
                        "away_offense_epa": package["away_stats"]["offense_epa_play"],
                        "away_defense_epa": package["away_stats"]["defense_epa_play"],
                        "home_stats_as_of": [
                            package["home_stats"]["as_of_season"],
                            package["home_stats"]["as_of_week"],
                        ],
                        "away_stats_as_of": [
                            package["away_stats"]["as_of_season"],
                            package["away_stats"]["as_of_week"],
                        ],
                        "home_prior_opponent_type": _prior_opponent(
                            conn, str(line[2]), str(game[0])
                        ),
                        "away_prior_opponent_type": _prior_opponent(
                            conn, str(line[1]), str(game[0])
                        ),
                        "play_count_support": "UNAVAILABLE_NOT_STORED",
                        "uncertainty_points": prediction.uncertainty_points,
                        "confidence": pick.confidence,
                        "ranking_sort_key_without_identity": [
                            -pick.confidence,
                            False,
                            prediction.uncertainty_points,
                        ],
                        "rank": pick.rank,
                        "is_top_five": pick.is_top_five,
                        "extreme_output_diagnostic": (
                            abs(prediction.predicted_home_margin) > 30 or abs(z) >= 3
                        ),
                        "research_only_fixed_prior_projections": fixed_prior,
                        "prediction_provenance": prediction.provenance,
                    }
                )
            metadata = {
                "migrations_applied_to_disposable_copy": [
                    migration.version for migration in migrations
                ],
                "training_rows": len(training_rows),
                "training_feature_min": min(training_x),
                "training_feature_max": max(training_x),
                "training_feature_mean": training_mean,
                "training_feature_sd": training_sd,
                "intercept": intercept,
                "coefficient": coefficients[0],
                "sqlite_integrity": conn.execute("PRAGMA integrity_check").fetchone()[0],
                "foreign_key_violations": len(
                    tuple(conn.execute("PRAGMA foreign_key_check"))
                ),
                "locked_line_snapshot_sha256": card.card.locked_line_snapshot_sha256,
            }
            return results, metadata
        finally:
            conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "cfb.db")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "production-weeks" / "2026-week2-splashsports-manifest.json",
    )
    parser.add_argument("--code-commit-sha", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dataset-output", type=Path, required=True)
    args = parser.parse_args(argv)
    database = args.database.resolve()
    output = args.output.resolve()
    dataset_output = args.dataset_output.resolve()
    for path in (database, args.manifest.resolve(), output, dataset_output):
        if not path.is_relative_to(ROOT):
            parser.error("all paths must remain inside the repository worktree")
    for path in (output, dataset_output):
        if path.exists():
            parser.error(f"output already exists: {path}")
    source_hash_before = _sha256(database)
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("season") != 2026 or manifest.get("week") != 2:
        raise RuntimeError("manifest is not the governed Week 2 slate")
    if len(manifest.get("lines", [])) != 49:
        raise RuntimeError("Week 2 manifest must have exactly 49 locked lines")
    card, card_metadata = _run_week2(database, manifest, args.code_commit_sha)
    source_conn = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
    source_conn.execute("PRAGMA query_only = ON")
    try:
        research_rows = build_early_season_rows(source_conn)
        historical_target_game_count = source_conn.execute(
            "SELECT COUNT(*) FROM games WHERE season BETWEEN 2020 AND 2025 "
            "AND week IN (2, 3, 4) AND completed = 1"
        ).fetchone()[0]
    finally:
        source_conn.close()
    dataset_payload = {
        "dataset_version": "epa-early-season-weeks2-4-oos-v1",
        "model_name": "epa_only",
        "model_version": "epa-only-linear-v1",
        "feature_schema_version": "epa-differential-v1",
        "configuration_version": "walk-forward-prior-seasons-v1",
        "target_weeks": [2, 3, 4],
        "seasons": [2020, 2021, 2022, 2023, 2024, 2025],
        "play_count_status": (
            "UNAVAILABLE: team_game_stats has no offensive/defensive play-count columns"
        ),
        "rows": research_rows,
    }
    dataset_sha = _canonical_sha256(dataset_payload)
    dataset_columns = (
        "candidate",
        "current_weight",
        "season",
        "week",
        "game_id",
        "away_team",
        "home_team",
        "home_current_offense_epa",
        "home_current_defense_epa",
        "away_current_offense_epa",
        "away_current_defense_epa",
        "home_offensive_plays",
        "home_defensive_plays",
        "away_offensive_plays",
        "away_defensive_plays",
        "feature_x",
        "feature_z",
        "training_feature_mean",
        "training_feature_sd",
        "intercept",
        "coefficient",
        "projected_home_margin",
        "actual_home_margin",
        "prediction_error",
        "absolute_error",
        "opening_home_spread",
        "selected_side",
        "ats_result",
        "home_prior_fallback",
        "away_prior_fallback",
        "home_prior_opponent_type",
        "away_prior_opponent_type",
        "prior_opponent_bucket",
    )
    dataset_buffer = io.StringIO(newline="")
    dataset_writer = csv.DictWriter(
        dataset_buffer,
        fieldnames=dataset_columns,
        extrasaction="ignore",
        lineterminator="\n",
    )
    dataset_writer.writeheader()
    dataset_writer.writerows(research_rows)
    dataset_csv = dataset_buffer.getvalue()
    dataset_file_sha = hashlib.sha256(dataset_csv.encode("utf-8")).hexdigest()
    artifact = load_uncertainty_artifact()
    week2_pathologies: dict[str, object] = {
        "current_production": {
            "abs_margin_gt_30": sum(
                abs(float(item["projected_home_margin"])) > 30 for item in card
            ),
            "abs_margin_gt_40": sum(
                abs(float(item["projected_home_margin"])) > 40 for item in card
            ),
            "abs_feature_z_gte_3": sum(
                abs(float(item["feature_z"])) >= 3 for item in card
            ),
        }
    }
    for label in (
        "25_current_75_prior",
        "50_current_50_prior",
        "75_current_25_prior",
    ):
        projections = [
            item["research_only_fixed_prior_projections"][label] for item in card
        ]
        week2_pathologies[label] = {
            "abs_margin_gt_30": sum(
                abs(float(item["projected_home_margin"])) > 30
                for item in projections
            ),
            "abs_margin_gt_40": sum(
                abs(float(item["projected_home_margin"])) > 40
                for item in projections
            ),
            "abs_feature_z_gte_3": sum(
                abs(float(item["feature_z"])) >= 3 for item in projections
            ),
        }
    report = {
        "report_version": "week2-ats-uncertainty-and-early-season-research-v1",
        "status": "PROVISIONAL_ATS_CARD_NOT_PUBLISHABLE",
        "source_database_sha256_before": source_hash_before,
        "source_database_sha256_after": _sha256(database),
        "source_database_unchanged": source_hash_before == _sha256(database),
        "code_commit_sha": args.code_commit_sha,
        "uncertainty_artifact": {
            "version": artifact.artifact_version,
            "formula_version": artifact.formula_version,
            "payload_sha256": artifact.artifact_payload_sha256,
            "residual_ledger_sha256": artifact.ledger_sha256,
            "residual_n": artifact.eligible_predictions,
            "residual_rmse_points": artifact.residual_rmse_points,
            "feature_mean": artifact.feature_mean,
            "feature_sxx": artifact.feature_sxx,
        },
        "week2_model": card_metadata,
        "week2_pathology_counts_research_only": week2_pathologies,
        "week2_card": card,
        "week2_top_ten": sorted(
            card,
            key=lambda item: (
                int(item["rank"] is None),
                -int(item["rank"] or 0),
                float(item["uncertainty_points"]),
            ),
        )[:10],
        "early_season_dataset": {
            "path": dataset_output.relative_to(ROOT).as_posix(),
            "file_sha256": dataset_file_sha,
            "semantic_ledger_sha256": dataset_sha,
            "candidate_row_count": len(research_rows),
            "eligible_game_count": len(
                {
                    (item["season"], item["week"], item["game_id"])
                    for item in research_rows
                }
            ),
            "completed_target_game_count": historical_target_game_count,
            "missing_pit_feature_game_count": (
                historical_target_game_count
                - len(
                    {
                        (item["season"], item["week"], item["game_id"])
                        for item in research_rows
                    }
                )
            ),
            "opening_line_eligible_game_count": sum(
                item["candidate"] == "current_production"
                and item["opening_home_spread"] is not None
                for item in research_rows
            ),
        },
        "candidate_results": grouped_summaries(research_rows),
        "paired_ats_comparisons": paired_ats_comparisons(research_rows),
        "support_diagnostics": extreme_and_opponent_summaries(research_rows),
        "sample_size_shrinkage": {
            f"K_{value}": {
                "status": "NOT_EVALUABLE",
                "reason": (
                    "offensive and defensive play counts are not stored in the "
                    "point-in-time feature schema; no proxy was manufactured"
                ),
            }
            for value in (50, 100, 200)
        },
    }
    if not report["source_database_unchanged"]:
        raise RuntimeError("authoritative database changed")
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    dataset_output.write_text(dataset_csv, encoding="utf-8", newline="")
    print(f"report={output}")
    print(f"dataset={dataset_output}")
    print(f"dataset_sha256={dataset_sha}")
    print(f"week2_picks={len(card)}")
    print(f"week2_top_five={sum(bool(item['is_top_five']) for item in card)}")
    print(f"source_database_unchanged={report['source_database_unchanged']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
