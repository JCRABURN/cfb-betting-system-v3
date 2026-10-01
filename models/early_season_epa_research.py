"""Historical Weeks 2-4 support research for the frozen EPA-only ATS model."""

from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Iterable

from models import backtest_harness as harness
from models import baseline_epa


FIXED_CURRENT_WEIGHTS = (0.25, 0.50, 0.75)
TARGET_WEEKS = (2, 3, 4)


def _finite_epa(stats: dict[str, object] | None) -> bool:
    if stats is None:
        return False
    return all(
        isinstance(stats.get(field), (int, float))
        and not isinstance(stats.get(field), bool)
        and math.isfinite(float(stats[field]))
        for field in ("offense_epa_play", "defense_epa_play")
    )


def _blend_stats(
    current: dict[str, object],
    prior: dict[str, object] | None,
    current_weight: float,
) -> tuple[dict[str, object], str]:
    if not _finite_epa(prior):
        return current, "current_only_missing_prior"
    result = dict(current)
    for field in ("offense_epa_play", "defense_epa_play"):
        result[field] = (
            current_weight * float(current[field])
            + (1.0 - current_weight) * float(prior[field])
        )
    return result, "fixed_prior_blend"


def _prior_opponent_type(
    conn: Any,
    *,
    team: str,
    season: int,
    target_start_date: str,
) -> str:
    fbs = conn.execute(
        "SELECT start_date FROM games "
        "WHERE season = ? AND completed = 1 "
        "AND (home_team = ? OR away_team = ?) AND start_date < ? "
        "ORDER BY start_date DESC LIMIT 1",
        (season, team, team, target_start_date),
    ).fetchone()
    supplemental = conn.execute(
        "SELECT start_date FROM supplemental_game_dates "
        "WHERE season = ? AND team = ? AND start_date < ? "
        "ORDER BY start_date DESC LIMIT 1",
        (season, team, target_start_date),
    ).fetchone()
    fbs_date = None if fbs is None else str(fbs[0])
    fcs_date = None if supplemental is None else str(supplemental[0])
    if fbs_date is None and fcs_date is None:
        return "unknown"
    if fcs_date is not None and (fbs_date is None or fcs_date > fbs_date):
        return "FCS"
    return "FBS"


def _game_prior_bucket(home_type: str, away_type: str) -> str:
    if "FCS" in (home_type, away_type):
        return "FCS"
    if home_type == away_type == "FBS":
        return "FBS"
    return "unknown"


def _candidate_key(current_weight: float | None) -> str:
    if current_weight is None:
        return "current_production"
    return f"fixed_prior_{int(current_weight * 100)}_{int((1-current_weight) * 100)}"


def build_early_season_rows(
    conn: Any,
    *,
    seasons: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024, 2025),
    target_weeks: tuple[int, ...] = TARGET_WEEKS,
) -> tuple[dict[str, object], ...]:
    """Return comparable OOS forecasts; candidates share the baseline fit."""
    rows: list[dict[str, object]] = []
    for season in seasons:
        training_seasons = harness.available_seasons_before(conn, season)
        training_rows, training_targets = harness.build_training_set(
            conn, baseline_epa.epa_differential, training_seasons
        )
        if len(training_rows) < 2:
            continue
        intercept, coefficients = harness.fit_multilinear(
            training_rows, training_targets
        )
        training_x = [float(item[0]) for item in training_rows]
        training_mean = sum(training_x) / len(training_x)
        training_sd = math.sqrt(
            sum((value - training_mean) ** 2 for value in training_x)
            / len(training_x)
        )
        if training_sd <= 0:
            continue
        for week in target_weeks:
            for (
                game_id,
                home_team,
                away_team,
                home_points,
                away_points,
                start_date,
            ) in harness.list_games(conn, season, week):
                current = harness.get_pregame_stats(
                    conn, home_team, away_team, season, week, start_date
                )
                if current is None:
                    continue
                home_current = current["home_stats"]
                away_current = current["away_stats"]
                if not _finite_epa(home_current) or not _finite_epa(away_current):
                    continue
                home_prior = harness.get_prior_season_final_stats(
                    conn, home_team, season
                )
                away_prior = harness.get_prior_season_final_stats(
                    conn, away_team, season
                )
                opening = harness.get_opening_line(conn, game_id)
                home_prior_type = _prior_opponent_type(
                    conn,
                    team=home_team,
                    season=season,
                    target_start_date=start_date,
                )
                away_prior_type = _prior_opponent_type(
                    conn,
                    team=away_team,
                    season=season,
                    target_start_date=start_date,
                )
                for current_weight in (None, *FIXED_CURRENT_WEIGHTS):
                    if current_weight is None:
                        home_stats = home_current
                        away_stats = away_current
                        home_fallback = "current_production"
                        away_fallback = "current_production"
                    else:
                        home_stats, home_fallback = _blend_stats(
                            home_current, home_prior, current_weight
                        )
                        away_stats, away_fallback = _blend_stats(
                            away_current, away_prior, current_weight
                        )
                    package = {"home_stats": home_stats, "away_stats": away_stats}
                    feature_x = float(baseline_epa.epa_differential(package)[0])
                    projected_margin = float(
                        baseline_epa.predict_margin(package, intercept, coefficients)
                    )
                    actual_margin = float(home_points - away_points)
                    error = projected_margin - actual_margin
                    opening_spread = (
                        None if opening is None else float(opening["home_spread"])
                    )
                    selected_side = None
                    ats_result = None
                    if opening_spread is not None:
                        home_edge = projected_margin + opening_spread
                        selected_side = home_team if home_edge > 0 else away_team
                        ats_result = harness.grade_ats(
                            selected_side,
                            home_team,
                            away_team,
                            opening_spread,
                            home_points,
                            away_points,
                        )
                    rows.append(
                        {
                            "candidate": _candidate_key(current_weight),
                            "current_weight": current_weight,
                            "season": season,
                            "week": week,
                            "game_id": game_id,
                            "home_team": home_team,
                            "away_team": away_team,
                            "home_current_offense_epa": float(
                                home_current["offense_epa_play"]
                            ),
                            "home_current_defense_epa": float(
                                home_current["defense_epa_play"]
                            ),
                            "away_current_offense_epa": float(
                                away_current["offense_epa_play"]
                            ),
                            "away_current_defense_epa": float(
                                away_current["defense_epa_play"]
                            ),
                            "home_offensive_plays": None,
                            "home_defensive_plays": None,
                            "away_offensive_plays": None,
                            "away_defensive_plays": None,
                            "feature_x": feature_x,
                            "feature_z": (feature_x - training_mean) / training_sd,
                            "training_feature_mean": training_mean,
                            "training_feature_sd": training_sd,
                            "intercept": intercept,
                            "coefficient": float(coefficients[0]),
                            "projected_home_margin": projected_margin,
                            "actual_home_margin": actual_margin,
                            "prediction_error": error,
                            "absolute_error": abs(error),
                            "opening_home_spread": opening_spread,
                            "selected_side": selected_side,
                            "ats_result": ats_result,
                            "home_prior_fallback": home_fallback,
                            "away_prior_fallback": away_fallback,
                            "home_prior_opponent_type": home_prior_type,
                            "away_prior_opponent_type": away_prior_type,
                            "prior_opponent_bucket": _game_prior_bucket(
                                home_prior_type, away_prior_type
                            ),
                        }
                    )
    return tuple(rows)


def summarize_rows(rows: Iterable[dict[str, object]]) -> dict[str, object]:
    selected = tuple(rows)
    n = len(selected)
    ats = tuple(item for item in selected if item["ats_result"] is not None)
    wins = sum(item["ats_result"] == "win" for item in ats)
    losses = sum(item["ats_result"] == "loss" for item in ats)
    pushes = sum(item["ats_result"] == "push" for item in ats)
    decisions = wins + losses
    errors = [float(item["prediction_error"]) for item in selected]
    return {
        "n": n,
        "mae": None if not n else sum(abs(value) for value in errors) / n,
        "rmse": None
        if not n
        else math.sqrt(sum(value * value for value in errors) / n),
        "bias_prediction_minus_actual": None if not n else sum(errors) / n,
        "ats_n": len(ats),
        "ats_wins": wins,
        "ats_losses": losses,
        "ats_pushes": pushes,
        "ats_win_rate_excluding_pushes": None if not decisions else wins / decisions,
        "roi_at_minus_110": None
        if not ats
        else (wins * 0.909 - losses) / len(ats),
        "pct_abs_projected_margin_gt_30": None
        if not n
        else sum(abs(float(item["projected_home_margin"])) > 30 for item in selected)
        / n,
        "pct_abs_projected_margin_gt_40": None
        if not n
        else sum(abs(float(item["projected_home_margin"])) > 40 for item in selected)
        / n,
        "pct_abs_feature_z_gte_3": None
        if not n
        else sum(abs(float(item["feature_z"])) >= 3 for item in selected) / n,
        "calibration_status": (
            "UNAVAILABLE_NO_GOVERNED_SELECTED_SIDE_PROBABILITY_FOR_CANDIDATE"
        ),
    }


def grouped_summaries(
    rows: tuple[dict[str, object], ...]
) -> dict[str, object]:
    candidate_names = sorted({str(item["candidate"]) for item in rows})
    by_candidate: dict[str, object] = {}
    for candidate in candidate_names:
        subset = tuple(item for item in rows if item["candidate"] == candidate)
        by_candidate[candidate] = {
            "combined_weeks_2_4": summarize_rows(subset),
            "by_week": {
                str(week): summarize_rows(
                    item for item in subset if item["week"] == week
                )
                for week in TARGET_WEEKS
            },
            "by_season": {
                str(season): summarize_rows(
                    item for item in subset if item["season"] == season
                )
                for season in sorted({int(item["season"]) for item in subset})
            },
            "by_season_and_week": {
                f"{season}-W{week}": summarize_rows(
                    item
                    for item in subset
                    if item["season"] == season and item["week"] == week
                )
                for season in sorted({int(item["season"]) for item in subset})
                for week in TARGET_WEEKS
            },
        }
    return by_candidate


def extreme_and_opponent_summaries(
    rows: tuple[dict[str, object], ...]
) -> dict[str, object]:
    control = tuple(item for item in rows if item["candidate"] == "current_production")
    candidates = sorted({str(item["candidate"]) for item in rows})
    extreme: dict[str, object] = {}
    for candidate in candidates:
        subset = tuple(item for item in rows if item["candidate"] == candidate)
        extreme[candidate] = {
            f"abs_z_gte_{cut}": summarize_rows(
                item for item in subset if abs(float(item["feature_z"])) >= cut
            )
            for cut in (2, 3, 4)
        }
    opponent = {
        bucket: summarize_rows(
            item for item in control if item["prior_opponent_bucket"] == bucket
        )
        for bucket in ("FBS", "FCS", "unknown")
    }
    fallback_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for item in rows:
        candidate = str(item["candidate"])
        fallback_counts[candidate][str(item["home_prior_fallback"])] += 1
        fallback_counts[candidate][str(item["away_prior_fallback"])] += 1
    return {
        "feature_extremity": extreme,
        "prior_opponent_quality_control": opponent,
        "prior_fallback_team_observation_counts": {
            candidate: dict(counts) for candidate, counts in fallback_counts.items()
        },
    }


def paired_ats_comparisons(
    rows: tuple[dict[str, object], ...]
) -> dict[str, object]:
    """Compare predefined candidates with control on side-disagreement games."""
    indexed: dict[tuple[int, int, int], dict[str, dict[str, object]]] = defaultdict(dict)
    for item in rows:
        indexed[
            (int(item["season"]), int(item["week"]), int(item["game_id"]))
        ][str(item["candidate"])] = item
    comparisons: dict[str, object] = {}
    for candidate in sorted(
        name
        for name in {str(item["candidate"]) for item in rows}
        if name != "current_production"
    ):
        candidate_right = 0
        control_right = 0
        disagreement_pushes = 0
        for candidates in indexed.values():
            control = candidates.get("current_production")
            challenger = candidates.get(candidate)
            if (
                control is None
                or challenger is None
                or control["ats_result"] is None
                or challenger["ats_result"] is None
                or control["selected_side"] == challenger["selected_side"]
            ):
                continue
            if challenger["ats_result"] == "win":
                candidate_right += 1
            elif control["ats_result"] == "win":
                control_right += 1
            else:
                disagreement_pushes += 1
        chi_square, p_value = harness.mcnemar_test(candidate_right, control_right)
        comparisons[candidate] = {
            "side_disagreements": (
                candidate_right + control_right + disagreement_pushes
            ),
            "candidate_right": candidate_right,
            "control_right": control_right,
            "disagreement_pushes": disagreement_pushes,
            "mcnemar_chi_square": chi_square,
            "mcnemar_p_value": p_value,
        }
    return comparisons
