"""Seal the local Week 5 ATS, totals, and unified shadow cards and export CSVs."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import subprocess
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from business_entities import ConfidenceRankingPolicy, FullCardPolicy, ManualAdjustmentPolicy
from business_entities.ats_shadow_calibration import (
    AtsShadowCalibrationPolicy, generate_ats_shadow_calibrations,
    register_ats_shadow_calibration_policy,
)
from business_entities.full_card import generate_full_card
from business_entities.totals import (
    TotalReliabilityPolicy, generate_total_shadow_card, register_total_reliability_policy,
)
from business_entities.unified_top_five import (
    UnifiedTopFivePolicy, generate_unified_top_five, register_unified_top_five_policy,
)
from contest_lines import list_effective_locked_lines
from models import backtest_harness, baseline_epa
from models.epa_uncertainty import load_uncertainty_artifact


ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = "owner-request://2026-week5-execution;isolated-local-rehearsal;not-cloud-publication"


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"refuse to write empty card: {path.name}")
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    database, output = args.database.resolve(), args.output.resolve()
    if not database.is_relative_to(ROOT) or database == ROOT / "data" / "cfb.db" or not output.is_relative_to(ROOT):
        parser.error("only isolated Week 5 paths are permitted")
    if not output.is_dir() or (output / "week5_ats_full_card.csv").exists():
        parser.error("output must be an existing, unfinalized Week 5 directory")
    policy_config = json.loads((ROOT / "config/production_policies.example.json").read_text(encoding="utf-8"))
    effective = datetime.fromisoformat(policy_config["effective_at"])
    versions = policy_config["versions"]
    confidence = policy_config["confidence"]
    now = datetime.now(timezone.utc)
    conn = sqlite3.connect(database)
    conn.execute("PRAGMA foreign_keys=ON")
    contest = conn.execute("SELECT id FROM contests WHERE contest_key='splashsports-cfb-2026-w05'").fetchone()
    if contest is None:
        raise ValueError("Week 5 contest is not locked")
    contest_id = contest[0]
    lines = list_effective_locked_lines(conn, contest_id, as_of=now)
    if len(lines) != 56:
        raise ValueError(f"expected 56 immutable locks, got {len(lines)}")
    ats_run = conn.execute("SELECT id FROM model_runs WHERE run_key='week5-20260930:epa'").fetchone()
    total_run = conn.execute("SELECT id FROM total_model_runs WHERE run_key='week5-20260930:component-totals'").fetchone()
    if ats_run is None or total_run is None:
        raise ValueError("both model runs must exist")
    selection = FullCardPolicy(
        version=versions["selection"], market_books=(),
        model_tie_side=policy_config["selection"]["model_tie_side"],
        pickem_tiebreak_side=policy_config["selection"]["pickem_tiebreak_side"],
    )
    ranking = ConfidenceRankingPolicy(
        policy_key=confidence["policy_key"],
        confidence_policy_version=versions["confidence"],
        ranking_policy_version=versions["ranking"],
        confidence_5_max_uncertainty=confidence["confidence_5_max_uncertainty"],
        confidence_4_max_uncertainty=confidence["confidence_4_max_uncertainty"],
        confidence_3_max_uncertainty=confidence["confidence_3_max_uncertainty"],
        confidence_2_max_uncertainty=confidence["confidence_2_max_uncertainty"],
        effective_at=effective, created_by=policy_config["created_by"],
        provenance=policy_config["provenance"],
    )
    adjustment = ManualAdjustmentPolicy(
        policy_version=versions["adjustment"], effective_at=effective,
        created_by=policy_config["created_by"], provenance=policy_config["provenance"],
    )
    ats_card = generate_full_card(
        conn, card_key="week5-20260930:ats-card", contest_id=contest_id,
        model_run_id=ats_run[0], version=1, policy=selection,
        confidence_policy=ranking, adjustment_policy=adjustment,
        created_by="Codex", provenance=PROVENANCE, generated_at=now,
    )
    total_policy = register_total_reliability_policy(conn, TotalReliabilityPolicy(
        policy_key="total-reliability-shadow-v1", reliability_policy_version="total-reliability-v1",
        probability_model_version="normal-total-residual-v1", calibration_slope=1.0,
        confidence_2_min_probability=0.55, confidence_3_min_probability=0.60,
        confidence_4_min_probability=0.70, confidence_5_min_probability=0.80,
        forecast_tie_direction="under", effective_at=effective, created_by="Codex",
        provenance="PR26 shadow defaults; unvalidated raw normal probability; local rehearsal",
    ))
    totals_card = generate_total_shadow_card(
        conn, card_key="week5-20260930:totals-card", contest_id=contest_id,
        total_model_run_id=total_run[0], total_reliability_policy_id=total_policy.id,
        version=1, generated_at=now, created_by="Codex", provenance=PROVENANCE,
    )
    ats_shadow_policy = register_ats_shadow_calibration_policy(conn, AtsShadowCalibrationPolicy(
        policy_key="ats-shadow-conservative-policy-v1", reliability_policy_version="ats-shadow-conservative-v1",
        probability_method_version="conservative-selected-margin-v1", required_model_name="epa_only",
        required_model_version="epa-only-linear-v1", probability_per_margin_point=0.005,
        maximum_selected_probability=0.6, effective_at=effective, created_by="Codex",
        provenance="PR26 conservative shadow transform; not empirically calibrated",
    ))
    ats_shadow = generate_ats_shadow_calibrations(
        conn, run_key="week5-20260930:ats-shadow", contest_card_id=ats_card.card.id,
        ats_shadow_calibration_policy_id=ats_shadow_policy.id,
        generated_at=now, created_by="Codex", provenance=PROVENANCE,
    )
    unified_policy = register_unified_top_five_policy(conn, UnifiedTopFivePolicy(
        policy_key="unified-shadow-top-five-v1", policy_version="unified-shadow-top-five-v1",
        allow_multiple_per_game=False, effective_at=effective, created_by="Codex",
        provenance="PR26 shadow one-selection-per-game probability ordering",
    ))
    unified = generate_unified_top_five(
        conn, run_key="week5-20260930:unified-shadow", contest_card_id=ats_card.card.id,
        total_shadow_card_id=totals_card.card.id, unified_top_five_policy_id=unified_policy.id,
        ats_calibrated_evaluation_ids=tuple(item.id for item in ats_shadow.evaluations),
        generated_at=now, created_by="Codex", provenance=PROVENANCE,
    )
    conn.commit()
    by_line = {line.locked_line_id: line for line in lines}
    uncertainty_artifact = load_uncertainty_artifact()
    shadow_uncertainty: dict[int, float] = {}
    for line in lines:
        game = conn.execute("SELECT home_team,away_team,start_date FROM games WHERE game_id=?", (line.game_id,)).fetchone()
        if game is None:
            raise ValueError(f"missing game for shadow uncertainty: {line.game_id}")
        package = backtest_harness.get_pregame_stats(conn, game[0], game[1], line.season, line.week, game[2])
        if package is None:
            raise ValueError(f"missing point-in-time features for shadow uncertainty: {line.game_id}")
        shadow_uncertainty[line.game_id] = uncertainty_artifact.uncertainty_points(baseline_epa.epa_differential(package)[0])
    ats_rows: list[dict] = []
    for pick in ats_card.picks:
        line = by_line[pick.locked_line_id]
        projection = conn.execute("SELECT predicted_home_margin,uncertainty_points FROM model_predictions WHERE id=?", (pick.model_prediction_id,)).fetchone() if pick.model_prediction_id else None
        edge = projection[0] + line.home_spread if projection else None
        ats_rows.append({
            "game_id": line.game_id, "away": line.normalized_away_team, "home": line.normalized_home_team,
            "locked_line_id": line.locked_line_id, "locked_home_spread": line.home_spread,
            "projected_home_margin": projection[0] if projection else None,
            "home_ats_edge": edge, "selected_side": pick.selected_side,
            "pick": line.normalized_home_team if pick.selected_side == "home" else line.normalized_away_team,
            "pick_spread": line.home_spread if pick.selected_side == "home" else -line.home_spread,
            "uncertainty_points": projection[1] if projection else None,
            "shadow_uncertainty_points": shadow_uncertainty[line.game_id],
            "confidence": pick.confidence, "rank": pick.rank, "top_five": bool(pick.is_top_five),
            "fallback_code": pick.fallback_code, "context_adjustment_points": 0,
            "adjusted_home_margin": projection[0] if projection else None,
            "data_quality": "WEEK4_PIT_EPA;INJURY_WEATHER_MARKET_UNVERIFIED",
        })
    totals_rows: list[dict] = []
    for candidate in totals_card.candidates:
        line = by_line[candidate.locked_line_id]
        totals_rows.append({
            "game_id": line.game_id, "away": line.normalized_away_team, "home": line.normalized_home_team,
            "locked_line_id": line.locked_line_id, "locked_total": candidate.exact_locked_total,
            "projected_total": candidate.projected_total,
            "raw_point_edge": candidate.projected_total-candidate.exact_locked_total,
            "pick": candidate.selected_direction, "uncertainty_points": candidate.uncertainty_points,
            "raw_selected_probability": candidate.selected_probability,
            "probability_status": "UNCALIBRATED_NORMAL_SHADOW", "confidence": candidate.confidence,
            "data_quality": "WEEK4_PIT_EPA;INJURY_WEATHER_MARKET_UNVERIFIED", "skip_reason": "",
        })
    for skip in totals_card.skips:
        line = by_line[skip.locked_line_id]
        totals_rows.append({
            "game_id": line.game_id, "away": line.normalized_away_team, "home": line.normalized_home_team,
            "locked_line_id": line.locked_line_id, "locked_total": line.total,
            "projected_total": "", "raw_point_edge": "", "pick": "", "uncertainty_points": "",
            "raw_selected_probability": "", "probability_status": "SKIPPED", "confidence": "",
            "data_quality": "EXPLICIT_SKIP", "skip_reason": skip.reason_code,
        })
    ats_rows.sort(key=lambda row: row["game_id"])
    totals_rows.sort(key=lambda row: row["game_id"])
    if len(ats_rows) != 56 or len(totals_rows) != 56:
        raise ValueError("card coverage failed")
    ats_top = sorted((row for row in ats_rows if row["top_five"]), key=lambda row: -row["rank"])
    shadow_ats_top = sorted(ats_rows, key=lambda row: (row["shadow_uncertainty_points"], row["locked_line_id"]))[:5]
    total_top = sorted((row for row in totals_rows if row["pick"]), key=lambda row: -row["raw_selected_probability"])[:5]
    ats_by_game = {row["game_id"]: row for row in ats_rows}
    totals_by_game = {row["game_id"]: row for row in totals_rows}
    combined_rows = []
    for item in unified.top_five:
        source = ats_by_game[item.game_id] if item.market_type == "ats" else totals_by_game[item.game_id]
        combined_rows.append({"rank": item.top_five_rank, "market": item.market_type,
                              "game_id": item.game_id, "away": source["away"], "home": source["home"],
                              "pick": source["pick"], "locked_line": source["locked_home_spread"] if item.market_type == "ats" else source["locked_total"],
                              "projection": source["projected_home_margin"] if item.market_type == "ats" else source["projected_total"],
                              "edge_points": source["home_ats_edge"] if item.market_type == "ats" else source["raw_point_edge"],
                              "shadow_probability_score": item.calibrated_probability,
                              "confidence": source["confidence"], "probability_status": "NOT_EMPIRICALLY_VALIDATED"})
    if len(ats_top) != 5 or len(total_top) != 5 or len(combined_rows) != 5 or len({row["game_id"] for row in combined_rows}) != 5:
        raise ValueError("Top 5 cardinality/uniqueness failed")
    write_csv(output / "week5_ats_full_card.csv", ats_rows)
    write_csv(output / "week5_totals_full_card.csv", totals_rows)
    write_csv(output / "week5_official_ats_top5.csv", ats_top)
    write_csv(output / "week5_shadow_ats_top5.csv", shadow_ats_top)
    write_csv(output / "week5_shadow_totals_top5.csv", total_top)
    write_csv(output / "week5_combined_top5.csv", combined_rows)
    (output / "week5_card_manifest.json").write_text(json.dumps({
        "status": "LOCAL_GOVERNED_DRAFT_NOT_CLOUD_OFFICIAL", "generated_at": now.isoformat(),
        "ats_card": asdict(ats_card.card), "ats_report": asdict(ats_card.report),
        "totals_card": asdict(totals_card.card), "totals_completion": asdict(totals_card.completion),
        "ats_shadow_completion": asdict(ats_shadow.completion),
        "unified_run": asdict(unified.run), "unified_completion": asdict(unified.completion),
        "policy_source": "config/production_policies.example.json; example/proposed, not owner-approved cutover",
        "ats_shadow_uncertainty_artifact_sha256": uncertainty_artifact.artifact_payload_sha256,
        "totals_production_eligible": False, "combined_empirically_validated": False,
    }, indent=2, default=str) + "\n", encoding="utf-8")
    model_rows = conn.execute(
        "SELECT model_name,model_version,feature_schema_version,configuration_version,"
        "code_commit_sha,data_snapshot_sha256 FROM model_runs WHERE id=?", (ats_run[0],)
    ).fetchone()
    total_rows = conn.execute(
        "SELECT model_name,model_version,feature_schema_version,configuration_version,"
        "code_commit_sha,data_snapshot_sha256 FROM total_model_runs WHERE id=?", (total_run[0],)
    ).fetchone()
    code_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if code_sha != model_rows[4] or code_sha != total_rows[4]:
        raise ValueError("code commit changed between prediction and card sealing")
    from business_entities.full_card import locked_line_snapshot_sha256
    manifest = {
        "generated_at_utc": now.isoformat(), "code_commit_sha": code_sha,
        "source_database_sha256": hashlib.sha256((ROOT / "data/cfb.db").read_bytes()).hexdigest(),
        "execution_database_sha256": hashlib.sha256(database.read_bytes()).hexdigest(),
        "locked_source_csv_sha256": hashlib.sha256((ROOT / "production-weeks/2026-week5-splashsports.csv").read_bytes().replace(b"\r\n", b"\n")).hexdigest(),
        "locked_line_snapshot_sha256": locked_line_snapshot_sha256(lines),
        "contest_key": "splashsports-cfb-2026-w05", "season": 2026, "week": 5,
        "ats": dict(zip(("name", "version", "feature_schema", "configuration", "code_commit_sha", "data_snapshot_sha256"), model_rows)),
        "ats_training_seasons": list(range(2019, 2026)),
        "ats_uncertainty_policy": "main-policy-null-uncertainty",
        "ats_shadow_uncertainty_policy": uncertainty_artifact.artifact_version,
        "ats_shadow_uncertainty_artifact_sha256": uncertainty_artifact.artifact_payload_sha256,
        "ats_selection_policy": selection.version,
        "ats_confidence_policy": ranking.confidence_policy_version,
        "ats_ranking_policy": ranking.ranking_policy_version,
        "adjustment_policy": adjustment.policy_version,
        "manual_adjustment_count": 0,
        "totals": dict(zip(("name", "version", "feature_schema", "configuration", "code_commit_sha", "data_snapshot_sha256"), total_rows)),
        "totals_reliability_policy": total_policy.reliability_policy_version,
        "ats_shadow_probability_policy": ats_shadow_policy.reliability_policy_version,
        "unified_shadow_policy": unified_policy.policy_version,
        "policy_configuration_sha256": hashlib.sha256((ROOT / "config/production_policies.example.json").read_bytes()).hexdigest(),
        "official_publication_status": "NOT_PUBLISHED;LOCAL_GOVERNED_DRAFT",
        "totals_and_unified_status": "SHADOW_NOT_PRODUCTION_ELIGIBLE",
    }
    (output / "week5_model_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"ats": len(ats_rows), "totals": len(totals_rows), "ats_top5": len(ats_top),
                      "total_top5": len(total_top), "combined_top5": len(combined_rows)}))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
