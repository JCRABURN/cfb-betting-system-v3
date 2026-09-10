"""Run the governed 2026 Week 2 official ATS and limited totals shadow card."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from business_entities import (
    AtsShadowCalibrationPolicy,
    ConfidenceRankingPolicy,
    ContestLineInput,
    FreshnessFallbackDecision,
    FullCardPolicy,
    ManualAdjustmentPolicy,
    RequiredSourcePolicy,
    TotalReliabilityPolicy,
    TuesdayCardRequest,
    WeeklyControllerPolicy,
    generate_ats_shadow_calibrations,
    generate_total_shadow_card,
    get_total_score_component_prediction,
    register_ats_shadow_calibration_policy,
    register_total_reliability_policy,
    run_component_totals_shadow_model,
    run_tuesday_controller,
)
from business_entities.modeling import get_model_prediction
from contest_lines import list_effective_locked_lines
from migrations.runner import apply_migrations
from models import backtest_harness as harness
from models.totals_component_research import build_totals_component_dataset
from models.totals_research import (
    EMPIRICALLY_CALIBRATED_PROBABILITY_STATUS,
    FEATURE_NAMES,
    PROBABILITY_STATUS,
)
from operations.splashsports import (
    OWNER_MODEL_IMPORT_FORMAT,
    SplashSportsImportRequest,
    build_splashsports_manifest,
    ingest_owner_reviewed_schedule,
)
from operations.providers import ingest_provider_bundle, load_provider_bundle


ROOT = Path(__file__).resolve().parents[1]
POLICY_EFFECTIVE_AT = datetime(2026, 8, 1, tzinfo=timezone.utc)
SERVICE_ACADEMIES = frozenset(("Army", "Navy", "Air Force"))
TOTAL_DISAGREEMENT_QUARANTINE = 15.0
INITIAL_LOCK_OVERRIDE_REASON = (
    "Repository owner authorized the immutable owner-reviewed Week 2 lock after "
    "the normal Tuesday initial-card window."
)
PROVENANCE = "owner-reviewed://2026-week2/ats-official-totals-limited-shadow-v1"
APPROVED_PRODUCTION_POLICY_PROVENANCE = (
    "proposed-v3-production-policy-registration-requires-owner-approval"
)
SOURCE_RULES = tuple(
    RequiredSourcePolicy(data_type, provider, fallback)
    for data_type, provider, fallback in (
        ("odds", "the_odds_api", "odds_documented_fallback_v1"),
        ("injuries", "espn", "injuries_documented_fallback_v1"),
        ("weather", "open_meteo", "weather_documented_fallback_v1"),
        (
            "game_status",
            "collegefootballdata",
            "game_status_documented_fallback_v1",
        ),
        (
            "contextual",
            "collegefootballdata",
            "contextual_documented_fallback_v1",
        ),
    )
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: str) -> datetime:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _edge_context(
    disagreement: float, diagnostic: dict[str, object]
) -> dict[str, object]:
    buckets = diagnostic["edge_buckets"]
    assert isinstance(buckets, list)
    for item in buckets:
        assert isinstance(item, dict)
        lower = float(item["lower"])
        upper = item["upper_exclusive"]
        if disagreement >= lower and (
            upper is None or disagreement < float(upper)
        ):
            return dict(item)
    raise RuntimeError(f"no historical edge bucket covers {disagreement}")


def _target_feature_custody(
    conn: sqlite3.Connection,
    *,
    season: int,
    week: int,
    lines: tuple[object, ...],
) -> tuple[dict[str, dict[str, float]], dict[int, dict[str, object]], int, str]:
    seasons = tuple(
        sorted(set(harness.available_seasons_before(conn, season)) | {season})
    )
    dataset, component_observations = build_totals_component_dataset(
        conn, seasons=seasons
    )
    training = tuple(
        item for item in component_observations if item.base.fold_key < (season, week)
    )
    if not training:
        raise RuntimeError("totals shadow training set is empty")
    ranges = {
        feature_name: {
            "minimum": min(item.base.features[index] for item in training),
            "maximum": max(item.base.features[index] for item in training),
        }
        for index, feature_name in enumerate(FEATURE_NAMES)
    }
    custody: dict[int, dict[str, object]] = {}
    for line in lines:
        game_id = getattr(line, "game_id")
        if game_id is None:
            continue
        game = conn.execute(
            "SELECT home_team, away_team, start_date FROM games WHERE game_id = ?",
            (game_id,),
        ).fetchone()
        if game is None or game[2] is None:
            continue
        package = harness.get_pregame_stats(
            conn, game[0], game[1], season, week, game[2]
        )
        if package is None:
            continue
        raw_features = (
            package["home_stats"].get("offense_epa_play"),
            package["home_stats"].get("defense_epa_play"),
            package["away_stats"].get("offense_epa_play"),
            package["away_stats"].get("defense_epa_play"),
        )
        if not all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in raw_features
        ):
            continue
        features = tuple(float(value) for value in raw_features)
        feature_values = dict(zip(FEATURE_NAMES, features))
        extrapolated = tuple(
            feature_name
            for feature_name, value in feature_values.items()
            if value < ranges[feature_name]["minimum"]
            or value > ranges[feature_name]["maximum"]
        )
        custody[int(game_id)] = {
            "values": feature_values,
            "home_stats_as_of": [
                package["home_stats"]["as_of_season"],
                package["home_stats"]["as_of_week"],
            ],
            "away_stats_as_of": [
                package["away_stats"]["as_of_season"],
                package["away_stats"]["as_of_week"],
            ],
            "extrapolated_features": list(extrapolated),
        }
    return ranges, custody, len(training), dataset.dataset_sha256


def _official_ats_rows(
    conn: sqlite3.Connection, result: object
) -> list[dict[str, object]]:
    card_result = getattr(result, "card")
    rows = []
    for pick in card_result.picks:
        line = conn.execute(
            "SELECT game_id, normalized_away_team, normalized_home_team, "
            "home_spread, total FROM contest_locked_lines WHERE id = ?",
            (pick.locked_line_id,),
        ).fetchone()
        assert line is not None
        prediction = (
            None
            if pick.model_prediction_id is None
            else get_model_prediction(conn, pick.model_prediction_id)
        )
        home_edge = (
            None
            if prediction is None
            else prediction.predicted_home_margin + float(line[3])
        )
        selected_spread = (
            float(line[3]) if pick.selected_side == "home" else -float(line[3])
        )
        rows.append(
            {
                "game_id": int(line[0]),
                "away": line[1],
                "home": line[2],
                "locked_home_spread": float(line[3]),
                "locked_total": float(line[4]),
                "projected_home_margin": (
                    None if prediction is None else prediction.predicted_home_margin
                ),
                "ats_selected_side": pick.selected_side,
                "ats_selected_team": line[2] if pick.selected_side == "home" else line[1],
                "selected_spread": selected_spread,
                "ats_edge_magnitude": None if home_edge is None else abs(home_edge),
                "model_uncertainty_points": (
                    None if prediction is None else prediction.uncertainty_points
                ),
                "confidence": pick.confidence,
                "official_rank": pick.rank,
                "official_top_five": pick.is_top_five,
                "fallback_code": pick.fallback_code,
                "contest_pick_id": pick.id,
                "model_prediction_id": pick.model_prediction_id,
            }
        )
    return sorted(rows, key=lambda item: int(item["game_id"]))


def _totals_rows(
    conn: sqlite3.Connection,
    *,
    total_card: object,
    lines: tuple[object, ...],
    features: dict[int, dict[str, object]],
    diagnostic: dict[str, object],
) -> list[dict[str, object]]:
    candidates = {
        item.locked_line_id: item for item in getattr(total_card, "candidates")
    }
    skips = {item.locked_line_id: item for item in getattr(total_card, "skips")}
    direction_context = diagnostic["direction"]
    assert isinstance(direction_context, dict)
    rows = []
    for line in lines:
        game = conn.execute(
            "SELECT away_team, home_team FROM games WHERE game_id = ?",
            (line.game_id,),
        ).fetchone()
        assert game is not None
        option_style = bool(SERVICE_ACADEMIES.intersection(game))
        candidate = candidates.get(line.locked_line_id)
        if candidate is None:
            skip = skips[line.locked_line_id]
            flags = ["PIT_FEATURE_CUSTODY_INCOMPLETE"]
            if option_style:
                flags.append("OPTION_STYLE_PACE_RISK")
            rows.append(
                {
                    "game_id": line.game_id,
                    "away": game[0],
                    "home": game[1],
                    "locked_total": line.total,
                    "record_type": "explicit_skip",
                    "projected_total": None,
                    "projected_home_points": None,
                    "projected_away_points": None,
                    "selected_direction": None,
                    "raw_disagreement_points": None,
                    "uncertainty_points": None,
                    "raw_model_probability": None,
                    "raw_probability_status": PROBABILITY_STATUS,
                    "empirically_calibrated_probability": (
                        EMPIRICALLY_CALIBRATED_PROBABILITY_STATUS
                    ),
                    "shadow_confidence": None,
                    "feature_custody": features.get(int(line.game_id)),
                    "eligibility": "QUARANTINED_SHADOW",
                    "data_quality_flags": flags,
                    "skip_reason": skip.reason_code,
                    "historical_edge_context": None,
                    "historical_direction_context": None,
                    "primary_model_risk": "PIT feature custody is incomplete.",
                }
            )
            continue
        component = get_total_score_component_prediction(
            conn, candidate.total_model_prediction_id
        )
        disagreement = abs(candidate.projected_total - candidate.exact_locked_total)
        feature_custody = features.get(candidate.game_id)
        extrapolated = (
            []
            if feature_custody is None
            else list(feature_custody["extrapolated_features"])
        )
        flags = []
        if disagreement >= TOTAL_DISAGREEMENT_QUARANTINE:
            flags.append("EXTREME_DISAGREEMENT_15_PLUS")
        if extrapolated:
            flags.append("FEATURE_EXTRAPOLATION")
        if feature_custody is None:
            flags.append("PIT_FEATURE_CUSTODY_INCOMPLETE")
        if option_style:
            flags.append("OPTION_STYLE_PACE_RISK")
        eligibility = "QUARANTINED_SHADOW" if any(
            flag
            in (
                "EXTREME_DISAGREEMENT_15_PLUS",
                "FEATURE_EXTRAPOLATION",
                "PIT_FEATURE_CUSTODY_INCOMPLETE",
            )
            for flag in flags
        ) else "SHADOW_REVIEW"
        raw_selected_probability = (
            candidate.raw_over_probability
            if candidate.selected_direction == "over"
            else 1.0 - candidate.raw_over_probability
        )
        if "PIT_FEATURE_CUSTODY_INCOMPLETE" in flags:
            primary_risk = "PIT feature custody is incomplete."
        elif "FEATURE_EXTRAPOLATION" in flags:
            primary_risk = "One or more EPA inputs are outside the historical training range."
        elif "EXTREME_DISAGREEMENT_15_PLUS" in flags:
            primary_risk = "The model-total disagreement is in the audited unsafe tail."
        elif "OPTION_STYLE_PACE_RISK" in flags:
            primary_risk = "The feature set lacks an explicit option-style pace mechanism."
        else:
            primary_risk = "Raw normal-residual probability is not empirically calibrated."
        rows.append(
            {
                "game_id": candidate.game_id,
                "away": game[0],
                "home": game[1],
                "locked_total": candidate.exact_locked_total,
                "record_type": "shadow_prediction",
                "projected_total": candidate.projected_total,
                "projected_home_points": component.projected_home_points,
                "projected_away_points": component.projected_away_points,
                "selected_direction": candidate.selected_direction.upper(),
                "raw_disagreement_points": disagreement,
                "uncertainty_points": candidate.uncertainty_points,
                "raw_model_probability": raw_selected_probability,
                "raw_probability_status": PROBABILITY_STATUS,
                "empirically_calibrated_probability": (
                    EMPIRICALLY_CALIBRATED_PROBABILITY_STATUS
                ),
                "shadow_confidence": candidate.confidence,
                "feature_custody": feature_custody,
                "eligibility": eligibility,
                "data_quality_flags": flags,
                "skip_reason": None,
                "historical_edge_context": _edge_context(disagreement, diagnostic),
                "historical_direction_context": direction_context[
                    candidate.selected_direction.title()
                ],
                "primary_model_risk": primary_risk,
                "total_card_candidate_id": candidate.id,
            }
        )
    return rows


def _experimental_combined_top_five(
    *,
    ats_rows: list[dict[str, object]],
    ats_evaluations: tuple[object, ...],
    totals_rows: list[dict[str, object]],
) -> list[dict[str, object]]:
    ats_by_pick = {int(row["contest_pick_id"]): row for row in ats_rows}
    pool = []
    for evaluation in ats_evaluations:
        row = ats_by_pick[evaluation.contest_pick_id]
        pool.append(
            {
                "market_type": "ATS",
                "game_id": evaluation.game_id,
                "selection": (
                    f"{row['ats_selected_team']} {float(row['selected_spread']):+g}"
                ),
                "display_probability": (
                    evaluation.calibrated_selected_side_probability
                ),
                "probability_status": "CONSERVATIVE_SHADOW_NOT_EMPIRICALLY_VALIDATED",
                "reliability_policy_version": evaluation.reliability_policy_version,
                "source_id": evaluation.id,
            }
        )
    for row in totals_rows:
        if row["eligibility"] != "SHADOW_REVIEW":
            continue
        pool.append(
            {
                "market_type": "TOTAL",
                "game_id": row["game_id"],
                "selection": (
                    f"{row['selected_direction']} {float(row['locked_total']):g} "
                    f"({row['away']} @ {row['home']})"
                ),
                "display_probability": row["raw_model_probability"],
                "probability_status": PROBABILITY_STATUS,
                "reliability_policy_version": "total-reliability-raw-shadow-v1",
                "source_id": row["total_card_candidate_id"],
            }
        )
    ordered = sorted(
        pool,
        key=lambda item: (
            -float(item["display_probability"]),
            str(item["market_type"]),
            int(item["source_id"]),
        ),
    )
    distinct = []
    seen_games = set()
    for item in ordered:
        if item["game_id"] in seen_games:
            continue
        seen_games.add(item["game_id"])
        distinct.append(item)
        if len(distinct) == 5:
            break
    return [dict(item, rank=index) for index, item in enumerate(distinct, start=1)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/cfb.db"))
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("production-weeks/2026-week2-splashsports-manifest.json"),
    )
    parser.add_argument(
        "--diagnostic",
        type=Path,
        default=Path("outputs/totals-historical-custody-correction-2026-09-09.json"),
    )
    parser.add_argument(
        "--provider-bundle",
        type=Path,
        default=Path(
            "production-weeks/evidence/2026-week2/"
            "cfbd-week1-stats-replay-bundle.json"
        ),
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--code-commit-sha", required=True)
    parser.add_argument("--generated-at", type=_utc, required=True)
    args = parser.parse_args(argv)

    database = args.database.resolve()
    manifest_path = args.manifest.resolve()
    diagnostic_path = args.diagnostic.resolve()
    provider_bundle_path = args.provider_bundle.resolve()
    output = args.output.resolve()
    for path, field in (
        (database, "database"),
        (manifest_path, "manifest"),
        (diagnostic_path, "diagnostic"),
        (provider_bundle_path, "provider_bundle"),
        (output, "output"),
    ):
        if not path.is_relative_to(ROOT):
            parser.error(f"{field} must remain inside this repository worktree")
    if output.exists():
        parser.error("output already exists; governed reports are immutable")
    if not output.parent.is_dir():
        parser.error("output parent directory does not exist")
    if any(
        database.with_name(database.name + suffix).exists()
        for suffix in ("-wal", "-journal")
    ):
        parser.error("database has an active SQLite sidecar")

    database_before_sha256 = _sha256(database)
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    diagnostic = json.loads(diagnostic_path.read_text(encoding="utf-8"))
    if manifest.get("season") != 2026 or manifest.get("week") != 2:
        raise RuntimeError("manifest is not the governed 2026 Week 2 slate")
    if manifest.get("expected_lined_game_count") != 49 or len(manifest["lines"]) != 49:
        raise RuntimeError("Week 2 manifest must contain exactly 49 lines")
    if diagnostic.get("corrected_ledger_sha256") != (
        "7aef0a7184c78d277fcd7a171f2be96a435daaf570d96155d6e04de487f1874b"
    ):
        raise RuntimeError("historical diagnostic ledger identity is not approved")
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    input_reference = Path(manifest["input_custody"]["source_path"])
    input_path = (
        input_reference
        if input_reference.is_absolute()
        else (ROOT / input_reference).resolve()
    )
    captured_at = _utc(manifest["input_custody"]["captured_at"])
    if _sha256(input_path) != manifest["input_custody"]["source_sha256"]:
        raise RuntimeError("owner input hash does not match the governed manifest")

    import_request = SplashSportsImportRequest(
        source_path=input_path,
        input_format=OWNER_MODEL_IMPORT_FORMAT,
        season=2026,
        week=2,
        contest_key=manifest["contest_key"],
        contest_name=manifest["contest_name"],
        source_contest_id=manifest["source_contest_id"],
        expected_lined_game_count=49,
        captured_at=captured_at,
        imported_by=manifest["input_custody"]["imported_by"],
        provenance=manifest["input_custody"]["provenance"],
    )
    conn = sqlite3.connect(database)
    conn.execute("PRAGMA foreign_keys = ON")
    payload: dict[str, object]
    try:
        migrations = apply_migrations(conn)
        provider_bundle = load_provider_bundle(
            provider_bundle_path,
            repository_root=ROOT,
            season=2026,
            week=2,
        )
        provider_summaries = ingest_provider_bundle(conn, provider_bundle)
        if (
            len(provider_summaries) != 1
            or provider_summaries[0].status != "completed"
            or provider_summaries[0].rows_received != 138
            or provider_summaries[0].rows_accepted != 138
            or provider_summaries[0].rows_rejected != 0
        ):
            raise RuntimeError("Week 1 EPA replay did not complete cleanly")
        schedule = ingest_owner_reviewed_schedule(
            conn, import_request, imported_at=args.generated_at
        )
        rebuilt = build_splashsports_manifest(conn, import_request)
        if rebuilt.canonical_json.encode("utf-8") != manifest_bytes:
            raise RuntimeError("rebuilt Week 2 manifest differs from committed custody")
        lines = tuple(
            ContestLineInput(
                raw_home_team=item["raw_home_team"],
                raw_away_team=item["raw_away_team"],
                home_spread=item["home_spread"],
                source_line_id=item["source_line_id"],
                total=item["total"],
                game_id=item["game_id"],
                normalized_home_team=item["normalized_home_team"],
                normalized_away_team=item["normalized_away_team"],
            )
            for item in manifest["lines"]
        )
        fallbacks = tuple(
            FreshnessFallbackDecision(
                data_type=source.data_type,
                fallback_code=source.permitted_fallback_code,
                reason=(
                    "No live provider/API call was authorized for this governed Week 2 "
                    "execution; the explicit documented fallback is recorded."
                ),
                evidence=f"owner-reviewed://2026-week2/no-live-{source.data_type}",
                provenance=PROVENANCE,
            )
            for source in SOURCE_RULES
        )
        official = run_tuesday_controller(
            conn,
            TuesdayCardRequest(
                run_key="splashsports-2026-week-2:official-initial-owner-lock-v1",
                publication_key="splashsports-2026-week-2:official:v1",
                contest_key=manifest["contest_key"],
                contest_name=manifest["contest_name"],
                source_contest_id=manifest["source_contest_id"],
                season=2026,
                week=2,
                expected_lined_game_count=49,
                line_payload_sha256=manifest_sha256,
                raw_payload_reference=(
                    "repo://production-weeks/2026-week2-splashsports-manifest.json"
                ),
                lines=lines,
                model_run_key="splashsports-2026-week-2:epa-only:v1",
                code_commit_sha=args.code_commit_sha,
                controller_policy=WeeklyControllerPolicy(
                    policy_version="production-controller-v2",
                    authorized_contest_source="SplashSports",
                    required_sources=SOURCE_RULES,
                    effective_at=POLICY_EFFECTIVE_AT,
                    created_by="repository-owner",
                    provenance=APPROVED_PRODUCTION_POLICY_PROVENANCE,
                ),
                selection_policy=FullCardPolicy(
                    version="production-selection-v1",
                    market_books=(),
                    model_tie_side="away",
                    pickem_tiebreak_side="home",
                ),
                confidence_policy=ConfidenceRankingPolicy(
                    policy_key="production-confidence-ranking-v1",
                    confidence_policy_version="production-confidence-v1",
                    ranking_policy_version="production-ranking-v1",
                    confidence_5_max_uncertainty=2.0,
                    confidence_4_max_uncertainty=4.0,
                    confidence_3_max_uncertainty=6.0,
                    confidence_2_max_uncertainty=8.0,
                    effective_at=POLICY_EFFECTIVE_AT,
                    created_by="repository-owner",
                    provenance=APPROVED_PRODUCTION_POLICY_PROVENANCE,
                ),
                adjustment_policy=ManualAdjustmentPolicy(
                    policy_version="production-adjustment-v1",
                    effective_at=POLICY_EFFECTIVE_AT,
                    created_by="repository-owner",
                    provenance=APPROVED_PRODUCTION_POLICY_PROVENANCE,
                ),
                freshness_fallbacks=fallbacks,
                contextual_adjustments=(),
                sportsbook_recommendations=(),
                generated_at=args.generated_at,
                actor="repository-owner",
                provenance=PROVENANCE,
                line_captured_at=captured_at,
                initial_lock_window_override_reason=(
                    None
                    if args.generated_at.isoweekday() == 2
                    else INITIAL_LOCK_OVERRIDE_REASON
                ),
            ),
        )
        locked_lines = list_effective_locked_lines(
            conn, official.publication.contest_id, as_of=args.generated_at
        )
        training_ranges, target_features, training_count, training_hash = (
            _target_feature_custody(
                conn,
                season=2026,
                week=2,
                lines=locked_lines,
            )
        )
        total_run = run_component_totals_shadow_model(
            conn,
            contest_id=official.publication.contest_id,
            model_run_key="splashsports-2026-week-2:component-totals-shadow:v1",
            code_commit_sha=args.code_commit_sha,
            generated_at=args.generated_at,
            provenance=PROVENANCE,
        )
        total_policy = register_total_reliability_policy(
            conn,
            TotalReliabilityPolicy(
                policy_key="total-reliability-raw-shadow-v1",
                reliability_policy_version="total-reliability-raw-shadow-v1",
                probability_model_version="normal-total-residual-v1",
                calibration_slope=1.0,
                confidence_2_min_probability=0.55,
                confidence_3_min_probability=0.60,
                confidence_4_min_probability=0.70,
                confidence_5_min_probability=0.80,
                forecast_tie_direction="under",
                effective_at=POLICY_EFFECTIVE_AT,
                created_by="repository-owner",
                provenance=(
                    f"{PROVENANCE};identity_transform_is_raw_not_empirical;"
                    "confidence_is_shadow_display_only"
                ),
            ),
        )
        total_card = generate_total_shadow_card(
            conn,
            card_key="splashsports-2026-week-2:totals-shadow:v1",
            contest_id=official.publication.contest_id,
            total_model_run_id=total_run.id,
            total_reliability_policy_id=total_policy.id,
            version=1,
            generated_at=args.generated_at,
            created_by="repository-owner",
            provenance=PROVENANCE,
        )
        ats_policy = register_ats_shadow_calibration_policy(
            conn,
            AtsShadowCalibrationPolicy(
                policy_key="ats-shadow-conservative-policy-v1",
                reliability_policy_version="ats-shadow-conservative-v1",
                probability_method_version="conservative-selected-margin-v1",
                required_model_name="epa_only",
                required_model_version="epa-only-linear-v1",
                probability_per_margin_point=0.005,
                maximum_selected_probability=0.60,
                effective_at=POLICY_EFFECTIVE_AT,
                created_by="repository-owner",
                provenance=(
                    f"{PROVENANCE};not_empirically_validated;shadow_only"
                ),
            ),
        )
        ats_shadow = generate_ats_shadow_calibrations(
            conn,
            run_key="splashsports-2026-week-2:ats-shadow-calibration:v1",
            contest_card_id=official.card.card.id,
            ats_shadow_calibration_policy_id=ats_policy.id,
            generated_at=args.generated_at,
            created_by="repository-owner",
            provenance=PROVENANCE,
        )
        ats_rows = _official_ats_rows(conn, official)
        totals_rows = _totals_rows(
            conn,
            total_card=total_card,
            lines=locked_lines,
            features=target_features,
            diagnostic=diagnostic,
        )
        watchlist = [
            dict(row)
            for row in sorted(
                (
                    row
                    for row in totals_rows
                    if row["eligibility"] == "SHADOW_REVIEW"
                ),
                key=lambda row: (
                    -float(row["raw_model_probability"]),
                    int(row["game_id"]),
                ),
            )
        ]
        for rank, row in enumerate(watchlist, start=1):
            row["watchlist_rank"] = rank
        combined = _experimental_combined_top_five(
            ats_rows=ats_rows,
            ats_evaluations=ats_shadow.evaluations,
            totals_rows=totals_rows,
        )
        over_count = sum(
            row["selected_direction"] == "OVER" for row in totals_rows
        )
        under_count = sum(
            row["selected_direction"] == "UNDER" for row in totals_rows
        )
        signed_total_disagreement_mean = (
            sum(
                float(row["projected_total"]) - float(row["locked_total"])
                for row in totals_rows
                if row["projected_total"] is not None
            )
            / max(over_count + under_count, 1)
        )
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = len(conn.execute("PRAGMA foreign_key_check").fetchall())
        payload = {
            "artifact_version": "week2-ats-official-totals-limited-shadow-v1",
            "generated_at": args.generated_at.isoformat(),
            "code_commit_sha": args.code_commit_sha,
            "database_sha256_before": database_before_sha256,
            "database_sha256_after": None,
            "manifest_sha256": manifest_sha256,
            "source_csv_sha256": schedule.source_sha256,
            "week1_epa_provider_bundle_sha256": provider_bundle.sha256,
            "locked_line_snapshot_sha256": (
                official.line_batch.locked_line_snapshot_sha256
            ),
            "ingestion_audit": {
                "requested_games": schedule.requested_count,
                "inserted_games": schedule.inserted_count,
                "existing_games": schedule.existing_count,
                "manifest_lines": rebuilt.parsed_line_count,
                "locked_spreads": sum(item.home_spread is not None for item in locked_lines),
                "locked_totals": sum(item.total is not None for item in locked_lines),
                "duplicate_matchups": 0,
                "unresolved_identities": 0,
            },
            "migrations_applied": [item.version for item in migrations],
            "week1_epa_replay": [asdict(item) for item in provider_summaries],
            "sqlite_integrity_check": integrity,
            "sqlite_foreign_key_error_count": foreign_key_errors,
            "official_ats": {
                "status": "OFFICIAL",
                "controller_policy_version": "production-controller-v2",
                "model_name": "epa_only",
                "model_version": "epa-only-linear-v1",
                "feature_schema_version": "epa-differential-v1",
                "configuration_version": "walk-forward-prior-seasons-v1",
                "selection_policy_version": "production-selection-v1",
                "confidence_policy_version": "production-confidence-v1",
                "ranking_policy_version": "production-ranking-v1",
                "adjustment_policy_version": "production-adjustment-v1",
                "publication_id": official.publication.id,
                "card_id": official.card.card.id,
                "pick_count": len(ats_rows),
                "fallback_pick_count": sum(
                    row["fallback_code"] is not None for row in ats_rows
                ),
                "top_five_count": sum(row["official_top_five"] for row in ats_rows),
                "freshness_fallbacks": [asdict(item) for item in official.freshness],
                "full_card": ats_rows,
                "top_five": [
                    row
                    for row in sorted(
                        ats_rows,
                        key=lambda item: -int(item["official_rank"] or 0),
                    )
                    if row["official_top_five"]
                ],
            },
            "totals_shadow": {
                "status": "LIMITED_SHADOW_ONLY",
                "production_eligible": False,
                "model_name": total_run.model_name,
                "model_version": total_run.model_version,
                "feature_schema_version": total_run.feature_schema_version,
                "configuration_version": total_run.configuration_version,
                "raw_probability_status": PROBABILITY_STATUS,
                "empirically_calibrated_probability": (
                    EMPIRICALLY_CALIBRATED_PROBABILITY_STATUS
                ),
                "training_count": training_count,
                "training_dataset_sha256": training_hash,
                "training_feature_ranges": training_ranges,
                "locked_line_count": total_card.completion.locked_line_count,
                "prediction_count": total_card.completion.candidate_count,
                "explicit_skip_count": total_card.completion.skip_count,
                "shadow_review_count": sum(
                    row["eligibility"] == "SHADOW_REVIEW" for row in totals_rows
                ),
                "quarantined_count": sum(
                    row["eligibility"] == "QUARANTINED_SHADOW"
                    for row in totals_rows
                ),
                "over_count": over_count,
                "under_count": under_count,
                "mean_signed_model_minus_locked_total": signed_total_disagreement_mean,
                "continues_known_upward_total_bias": (
                    signed_total_disagreement_mean > 0
                ),
                "full_ledger": totals_rows,
                "quarantine_report": [
                    row
                    for row in totals_rows
                    if row["eligibility"] == "QUARANTINED_SHADOW"
                    or "OPTION_STYLE_PACE_RISK" in row["data_quality_flags"]
                ],
                "watchlist": watchlist,
            },
            "ats_shadow_calibration": {
                "status": "SHADOW_ONLY_NOT_EMPIRICALLY_VALIDATED",
                "policy_version": ats_policy.reliability_policy_version,
                "probability_method_version": ats_policy.probability_method_version,
                "evaluation_count": len(ats_shadow.evaluations),
                "ledger_sha256": ats_shadow.completion.ledger_sha256,
            },
            "experimental_combined_top_five": {
                "status": "SHADOW_NOT_OFFICIAL",
                "ranking_method": (
                    "eligible-total-raw-probability-vs-conservative-ats-shadow-"
                    "probability-one-candidate-per-game-v1"
                ),
                "evidence_compatibility_warning": (
                    "ATS and totals probabilities do not share an empirically validated "
                    "calibration basis; this display is experimental only."
                ),
                "raw_point_edge_used_for_ranking": False,
                "quarantined_totals_excluded": True,
                "candidates": combined,
            },
            "historical_diagnostic_reference": {
                "artifact": diagnostic_path.relative_to(ROOT).as_posix(),
                "corrected_ledger_sha256": diagnostic["corrected_ledger_sha256"],
                "decision_count": diagnostic["corrected"]["decision_count"],
                "conclusion_survives": True,
            },
            "current_totals_conclusion": "CONTINUE SHADOW",
            "totals_production_eligible": "NO",
        }
        if integrity != "ok" or foreign_key_errors:
            raise RuntimeError("post-run SQLite integrity validation failed")
        if len(ats_rows) != 49 or len(totals_rows) != 49:
            raise RuntimeError("Week 2 execution did not produce complete ledgers")
        if sum(row["official_top_five"] for row in ats_rows) != 5:
            raise RuntimeError("official ATS Top 5 is incomplete")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    payload["database_sha256_after"] = _sha256(database)
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(f"output={output}")
    print(f"source_csv_sha256={payload['source_csv_sha256']}")
    print(f"manifest_sha256={payload['manifest_sha256']}")
    print(f"locked_line_snapshot_sha256={payload['locked_line_snapshot_sha256']}")
    print(f"official_ats_picks={payload['official_ats']['pick_count']}")
    print(f"official_ats_top_five={payload['official_ats']['top_five_count']}")
    print(f"totals_predictions={payload['totals_shadow']['prediction_count']}")
    print(f"totals_skips={payload['totals_shadow']['explicit_skip_count']}")
    print(f"totals_review={payload['totals_shadow']['shadow_review_count']}")
    print(f"totals_quarantined={payload['totals_shadow']['quarantined_count']}")
    print("TOTALS PRODUCTION ELIGIBLE: NO")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
