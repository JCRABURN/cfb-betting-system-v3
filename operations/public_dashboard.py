"""Sanitized, deterministic static publication for the V3 owner dashboard."""

from __future__ import annotations

import json
import math
import os
import re
import shutil
import sqlite3
import tempfile
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from business_entities.live_sportsbook import DRAFTKINGS_BOOKMAKER
from business_entities.weekly_controller import inspect_official_card
from operations.execution import ProductionExecutionResult
from operations.weekly_config import WeeklyOperationConfiguration


PUBLIC_DASHBOARD_SCHEMA_VERSION = "v3-public-dashboard-v1"
PUBLIC_DASHBOARD_URL = "https://jcraburn.github.io/cfb-betting-system-v3/"
PUBLIC_DASHBOARD_ASSETS = ("index.html", "styles.css", "dashboard.js")
_BLOCKED_KEY_PARTS = (
    "api_key",
    "credential",
    "database_url",
    "endpoint",
    "evidence",
    "payload",
    "provenance",
    "raw_",
    "secret",
    "token",
)
_BLOCKED_TEXT_PATTERNS = (
    re.compile(r"(?i)\b(?:postgres|postgresql)://"),
    re.compile(r"(?i)\b(?:api[_-]?key|authorization|bearer|client[_-]?secret)\b"),
    re.compile(r"(?i)\bCFB_V3_DATABASE_URL\b"),
    re.compile(r"(?i)\b(?:CFBD|ODDS)_API_KEY\b"),
)


class PublicDashboardError(RuntimeError):
    """Raised when public output would be incomplete, ambiguous, or unsafe."""


@dataclass(frozen=True)
class PublicDashboardContext:
    season: int
    week: int
    contest_key: str
    expected_lined_game_count: int
    display_timezone: str
    sportsbook_policy_version: str
    generated_at: str
    operation: str
    execution_profile: str = "production"
    draftkings_rows: tuple[Mapping[str, object], ...] = ()
    next_scheduled_refresh: str | None = None


def _row_dicts(cursor: sqlite3.Cursor) -> list[dict[str, object]]:
    columns = tuple(item[0] for item in cursor.description or ())
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _one(cursor: sqlite3.Cursor, message: str) -> dict[str, object]:
    rows = _row_dicts(cursor)
    if len(rows) != 1:
        raise PublicDashboardError(message)
    return rows[0]


def _finite(value: object, field: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PublicDashboardError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise PublicDashboardError(f"{field} must be finite")
    return result


def _integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PublicDashboardError(f"{field} must be an integer")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PublicDashboardError(f"{field} must be non-empty text")
    return value.strip()


def _selected_values(row: Mapping[str, object]) -> tuple[str, float]:
    side = _text(row["selected_side"], "selected_side")
    if side not in ("home", "away"):
        raise PublicDashboardError("official contest picks must select home or away")
    home_spread = _finite(row["locked_home_spread"], "locked_home_spread")
    assert home_spread is not None
    if side == "home":
        return _text(row["home_team"], "home_team"), home_spread
    return _text(row["away_team"], "away_team"), -home_spread


def _card_change(row: Mapping[str, object]) -> tuple[str, tuple[str, ...]]:
    labels: list[str] = []
    if row.get("side_changed") == 1:
        labels.append("SIDE FLIP")
    if row.get("confidence_changed") == 1:
        labels.append("CONFIDENCE")
    if row.get("top_five_changed") == 1:
        labels.append("TOP 5")
    if row.get("rank_changed") == 1:
        labels.append("RANK")
    if row.get("model_prediction_changed") == 1:
        labels.append("MODEL REFRESH")
    if row.get("fallback_changed") == 1:
        labels.append("FALLBACK")
    return (" · ".join(labels) if labels else "No material pick change", tuple(labels))


def _latest_publication(
    conn: sqlite3.Connection, context: PublicDashboardContext
) -> dict[str, object]:
    publication = _one(
        conn.execute(
            "SELECT publication.id AS publication_id, publication.card_id, "
            "publication.contest_id, publication.card_version, publication.published_at, "
            "publication.expected_locked_line_count, publication.pick_count, "
            "publication.top_five_count, publication.fallback_pick_count, "
            "contest.name AS contest_name, contest.source AS contest_source, "
            "card.generated_at AS card_generated_at, batch.captured_at AS locked_at, "
            "run.completed_at AS controller_completed_at "
            "FROM official_card_publications AS publication "
            "JOIN contests AS contest ON contest.id = publication.contest_id "
            "JOIN contest_cards AS card ON card.id = publication.card_id "
            "JOIN contest_line_lock_batches AS batch ON batch.contest_id = contest.id "
            "JOIN weekly_controller_runs AS run ON run.id = publication.controller_run_id "
            "WHERE contest.contest_key = ? AND contest.season = ? AND contest.week = ? "
            "ORDER BY publication.card_version DESC, publication.id DESC LIMIT 1",
            (context.contest_key, context.season, context.week),
        ),
        "the configured week has no unique official publication",
    )
    if publication["contest_source"] != "SplashSports":
        raise PublicDashboardError("official dashboard source must be SplashSports")
    inspection = inspect_official_card(
        conn, publication_id=int(publication["publication_id"])
    )
    if not inspection.valid or not inspection.is_latest_official_version:
        raise PublicDashboardError("latest official publication failed read-only inspection")
    return publication


def _latest_refresh(conn: sqlite3.Connection, context: PublicDashboardContext) -> str | None:
    row = conn.execute(
        "SELECT recorded_at FROM provider_ingestion_runs "
        "WHERE status IN ('completed', 'partial', 'empty') "
        "AND json_extract(request_parameters, '$.season') = ? "
        "AND json_extract(request_parameters, '$.week') = ? "
        "ORDER BY julianday(recorded_at) DESC, id DESC LIMIT 1",
        (context.season, context.week),
    ).fetchone()
    return None if row is None else str(row[0])


def _freshness(
    conn: sqlite3.Connection, card_id: int
) -> tuple[list[dict[str, object]], str]:
    rows = _row_dicts(
        conn.execute(
            "SELECT data_type, provider, state, observed_at, expires_at, fallback_code "
            "FROM card_source_freshness WHERE card_id = ? "
            "ORDER BY CASE data_type WHEN 'odds' THEN 1 WHEN 'injuries' THEN 2 "
            "WHEN 'weather' THEN 3 WHEN 'game_status' THEN 4 ELSE 5 END",
            (card_id,),
        )
    )
    safe = [
        {
            "data_type": row["data_type"],
            "provider": row["provider"],
            "state": str(row["state"]).upper(),
            "observed_at": row["observed_at"],
            "expires_at": row["expires_at"],
            "fallback_code": row["fallback_code"],
        }
        for row in rows
    ]
    states = {str(row["state"]).casefold() for row in rows}
    if states.intersection({"stale", "missing"}):
        return safe, "STALE"
    if "partial" in states:
        return safe, "PARTIAL"
    return safe, "CURRENT"


def _card_games(
    conn: sqlite3.Connection, publication: Mapping[str, object]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    card_id = int(publication["card_id"])
    rows = _row_dicts(
        conn.execute(
            "SELECT pick.id AS pick_id, pick.locked_line_id, locked.game_id, "
            "game.away_team, game.home_team, game.start_date, pick.selected_side, "
            "pick.confidence, pick.rank, pick.is_top_five, pick.fallback_code, "
            "COALESCE((SELECT correction.home_spread FROM contest_line_corrections AS correction "
            "WHERE correction.locked_line_id = locked.id "
            "AND julianday(correction.corrected_at) <= julianday(card.generated_at) "
            "ORDER BY correction.sequence DESC LIMIT 1), locked.home_spread) "
            "AS locked_home_spread, locked.home_spread AS original_locked_home_spread, "
            "prediction.predicted_home_margin, snapshot.adjusted_model_margin, "
            "change.side_changed, change.confidence_changed, change.rank_changed, "
            "change.top_five_changed, change.model_prediction_changed, "
            "change.fallback_changed "
            "FROM contest_picks AS pick "
            "JOIN contest_cards AS card ON card.id = pick.card_id "
            "JOIN contest_locked_lines AS locked ON locked.id = pick.locked_line_id "
            "JOIN games AS game ON game.game_id = locked.game_id "
            "LEFT JOIN model_predictions AS prediction ON prediction.id = pick.model_prediction_id "
            "LEFT JOIN contest_pick_adjustment_snapshots AS snapshot "
            "ON snapshot.contest_pick_id = pick.id "
            "LEFT JOIN card_revisions AS revision ON revision.revised_card_id = card.id "
            "LEFT JOIN card_revision_pick_changes AS change "
            "ON change.revision_id = revision.id AND change.locked_line_id = locked.id "
            "WHERE pick.card_id = ? ORDER BY game.start_date, locked.id",
            (card_id,),
        )
    )
    adjustments = _row_dicts(
        conn.execute(
            "SELECT item.contest_pick_id, adjustment.category, adjustment.affected_side, "
            "adjustment.reason, adjustment.recorded_at "
            "FROM contest_pick_adjustment_items AS item "
            "JOIN manual_adjustments AS adjustment ON adjustment.id = item.adjustment_id "
            "JOIN contest_picks AS pick ON pick.id = item.contest_pick_id "
            "WHERE pick.card_id = ? ORDER BY item.contest_pick_id, item.history_order",
            (card_id,),
        )
    )
    by_pick: dict[int, list[dict[str, object]]] = {}
    for adjustment in adjustments:
        by_pick.setdefault(int(adjustment["contest_pick_id"]), []).append(adjustment)

    games: list[dict[str, object]] = []
    changes: list[dict[str, object]] = []
    for row in rows:
        team, selected_spread = _selected_values(row)
        change_label, change_codes = _card_change(row)
        item_adjustments = by_pick.get(int(row["pick_id"]), [])
        categories = tuple(dict.fromkeys(str(item["category"]).upper() for item in item_adjustments))
        fallback = row["fallback_code"]
        context_label = (
            ", ".join(categories)
            if categories
            else (f"Fallback: {fallback}" if fallback else "EPA baseline")
        )
        confidence = _integer(row["confidence"], "confidence")
        if confidence is None or not 1 <= confidence <= 5:
            raise PublicDashboardError("every official pick requires Confidence 1-5")
        game = {
            "game_id": int(row["game_id"]),
            "matchup": f"{row['away_team']} at {row['home_team']}",
            "kickoff": row["start_date"],
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "locked_line_source": "SplashSports",
            "locked_home_spread": _finite(row["locked_home_spread"], "locked_home_spread"),
            "original_locked_home_spread": _finite(
                row["original_locked_home_spread"], "original_locked_home_spread"
            ),
            "selected_team": team,
            "selected_side": row["selected_side"],
            "selected_locked_spread": selected_spread,
            "confidence": confidence,
            "top_five_rank": int(row["rank"]) if row["is_top_five"] else None,
            "is_top_five": bool(row["is_top_five"]),
            "model_projected_home_margin": _finite(
                row["predicted_home_margin"], "predicted_home_margin"
            ),
            "adjusted_projected_home_margin": _finite(
                row["adjusted_model_margin"], "adjusted_model_margin"
            ),
            "change": change_label,
            "context": context_label,
            "fallback_code": fallback,
        }
        games.append(game)
        for code in change_codes:
            changes.append(
                {
                    "category": "CONTEST",
                    "matchup": game["matchup"],
                    "change": code,
                    "observed_at": publication["published_at"],
                }
            )
        for adjustment in item_adjustments:
            changes.append(
                {
                    "category": "CONTEXT",
                    "matchup": game["matchup"],
                    "change": (
                        f"{str(adjustment['category']).upper()} adjustment "
                        f"({adjustment['affected_side']}): {adjustment['reason']}"
                    ),
                    "observed_at": adjustment["recorded_at"],
                }
            )
    return games, changes


def _terminal_draftkings_rows(
    conn: sqlite3.Connection,
    *,
    publication: Mapping[str, object],
    context: PublicDashboardContext,
) -> tuple[Mapping[str, object], ...]:
    policy = _one(
        conn.execute(
            "SELECT id FROM sportsbook_recommendation_policies WHERE policy_version = ?",
            (context.sportsbook_policy_version,),
        ),
        "configured sportsbook policy is not registered",
    )
    if context.draftkings_rows:
        return context.draftkings_rows
    games = conn.execute(
        "SELECT locked.game_id, game.away_team, game.home_team "
        "FROM contest_locked_lines AS locked "
        "JOIN games AS game ON game.game_id = locked.game_id "
        "WHERE locked.contest_id = ? ORDER BY game.start_date, locked.id",
        (int(publication["contest_id"]),),
    ).fetchall()
    terminal: list[Mapping[str, object]] = []
    for game_id_value, away_team, home_team in games:
        game_id = int(game_id_value)
        row = conn.execute(
            "SELECT evaluation.id, evaluation.lifecycle_state, evaluation.decision, "
            "evaluation.selected_side, evaluation.selected_team, "
            "evaluation.offered_spread, evaluation.offered_price, "
            "evaluation.captured_at, evaluation.model_fair_spread, "
            "evaluation.spread_edge_points, evaluation.estimated_cover_probability, "
            "evaluation.break_even_probability, evaluation.expected_value, "
            "evaluation.stake_units, evaluation.policy_version, evaluation.reason_code "
            "FROM sportsbook_recommendation_evaluations AS evaluation "
            "JOIN sportsbook_market_offers AS offer ON offer.id = evaluation.market_offer_id "
            "WHERE evaluation.policy_id = ? AND offer.game_id = ? "
            "AND lower(trim(evaluation.bookmaker)) = ? "
            "AND NOT EXISTS (SELECT 1 FROM sportsbook_recommendation_evaluations AS newer "
            "WHERE newer.supersedes_evaluation_id = evaluation.id) "
            "ORDER BY evaluation.id DESC LIMIT 1",
            (int(policy["id"]), game_id, DRAFTKINGS_BOOKMAKER),
        ).fetchone()
        matchup = f"{away_team} at {home_team}"
        if row is None:
            terminal.append(
                {
                    "game_id": game_id,
                    "game": matchup,
                    "selected_team": None,
                    "selected_side": None,
                    "decision": "DRAFTKINGS_UNAVAILABLE",
                    "bookmaker": "DraftKings",
                    "offered_spread": None,
                    "offered_price": None,
                    "offer_captured_at": None,
                    "observation_timestamp": "NOT_ATTEMPTED",
                    "model_fair_spread": None,
                    "spread_edge_points": None,
                    "estimated_cover_probability": None,
                    "break_even_probability": None,
                    "expected_value": None,
                    "stake_units": 0.0,
                    "reason_code": "DRAFTKINGS_EVALUATION_NOT_RECORDED",
                    "freshness": "UNAVAILABLE",
                    "availability_state": "EVALUATION_MISSING",
                    "evaluation_id": None,
                }
            )
            continue
        lifecycle = str(row[1])
        settled_stage = context.operation in ("postgame_grading", "weekly_audit")
        terminal.append(
            {
                "game_id": game_id,
                "game": matchup,
                "selected_team": row[4],
                "selected_side": row[3],
                "decision": str(row[2]).upper(),
                "bookmaker": "DraftKings",
                "offered_spread": row[5],
                "offered_price": row[6],
                "offer_captured_at": row[7],
                "observation_timestamp": row[7],
                "model_fair_spread": row[8],
                "spread_edge_points": row[9],
                "estimated_cover_probability": row[10],
                "break_even_probability": row[11],
                "expected_value": row[12],
                "stake_units": row[13],
                "policy_version": row[14],
                "reason_code": row[15],
                "freshness": (
                    "STALE" if lifecycle == "expired" or settled_stage else "CURRENT"
                ),
                "availability_state": "AVAILABLE",
                "evaluation_id": int(row[0]),
            }
        )
    return tuple(terminal)


def _draftkings_board(
    conn: sqlite3.Connection,
    *,
    publication: Mapping[str, object],
    context: PublicDashboardContext,
) -> tuple[list[dict[str, object]], list[dict[str, object]], str | None]:
    rows = _terminal_draftkings_rows(conn, publication=publication, context=context)
    safe_rows: list[dict[str, object]] = []
    changes: list[dict[str, object]] = []
    latest_timestamp: str | None = None
    for raw in rows:
        bookmaker = _text(raw.get("bookmaker"), "bookmaker")
        if bookmaker.casefold() != DRAFTKINGS_BOOKMAKER:
            raise PublicDashboardError("another sportsbook cannot masquerade as DraftKings")
        decision = _text(raw.get("decision"), "decision").upper().replace("_", " ")
        if decision not in ("BET", "NO BET", "DRAFTKINGS UNAVAILABLE"):
            raise PublicDashboardError("DraftKings decision is invalid")
        evaluation_id = _integer(raw.get("evaluation_id"), "evaluation_id")
        prior = None
        if evaluation_id is not None:
            prior_row = conn.execute(
                "SELECT prior.decision, prior.offered_spread, prior.offered_price "
                "FROM sportsbook_recommendation_evaluations AS current "
                "JOIN sportsbook_recommendation_evaluations AS prior "
                "ON prior.id = current.supersedes_evaluation_id WHERE current.id = ?",
                (evaluation_id,),
            ).fetchone()
            if prior_row is not None:
                prior = {
                    "decision": str(prior_row[0]).upper().replace("_", " "),
                    "spread": float(prior_row[1]),
                    "price": int(prior_row[2]),
                }
        change_parts: list[str] = []
        if prior is not None:
            if prior["decision"] != decision:
                change_parts.append(f"{prior['decision']} → {decision}")
            offered_spread = _finite(raw.get("offered_spread"), "offered_spread")
            offered_price = _integer(raw.get("offered_price"), "offered_price")
            if offered_spread != prior["spread"]:
                change_parts.append(f"spread {prior['spread']:+g} → {offered_spread:+g}")
            if offered_price != prior["price"]:
                change_parts.append(f"price {prior['price']:+d} → {offered_price:+d}")
        observation = _text(raw.get("observation_timestamp"), "observation_timestamp")
        if observation != "NOT_ATTEMPTED" and (
            latest_timestamp is None or observation > latest_timestamp
        ):
            latest_timestamp = observation
        change = " · ".join(change_parts) if change_parts else "No material change"
        safe = {
            "game_id": int(raw["game_id"]),
            "matchup": _text(raw.get("game"), "game"),
            "bookmaker": "DraftKings",
            "decision": decision,
            "selected_team": raw.get("selected_team"),
            "selected_side": raw.get("selected_side"),
            "offered_spread": _finite(raw.get("offered_spread"), "offered_spread"),
            "offered_price": _integer(raw.get("offered_price"), "offered_price"),
            "model_fair_spread": _finite(raw.get("model_fair_spread"), "model_fair_spread"),
            "spread_edge_points": _finite(
                raw.get("spread_edge_points"), "spread_edge_points"
            ),
            "estimated_cover_probability": _finite(
                raw.get("estimated_cover_probability"), "estimated_cover_probability"
            ),
            "break_even_probability": _finite(
                raw.get("break_even_probability"), "break_even_probability"
            ),
            "expected_value": _finite(raw.get("expected_value"), "expected_value"),
            "suggested_units": _finite(raw.get("stake_units"), "stake_units"),
            "offer_captured_at": raw.get("offer_captured_at"),
            "observation_timestamp": observation,
            "reason": _text(raw.get("reason_code"), "reason_code"),
            "freshness": _text(raw.get("freshness"), "freshness").upper(),
            "availability": _text(
                raw.get("availability_state"), "availability_state"
            ).upper(),
            "changed_since_prior": bool(change_parts),
            "change": change,
        }
        if decision == "DRAFTKINGS UNAVAILABLE" and any(
            safe[field] is not None
            for field in (
                "selected_team",
                "selected_side",
                "offered_spread",
                "offered_price",
                "model_fair_spread",
            )
        ):
            raise PublicDashboardError("unavailable DraftKings rows cannot fabricate an offer")
        safe_rows.append(safe)
        if change_parts:
            changes.append(
                {
                    "category": "DRAFTKINGS",
                    "matchup": safe["matchup"],
                    "change": change,
                    "observed_at": observation,
                }
            )
    return safe_rows, changes, latest_timestamp


def _market_comparison(
    conn: sqlite3.Connection, *, season: int, week: int
) -> list[dict[str, object]]:
    rows = _row_dicts(
        conn.execute(
            "SELECT offer.game_id, game.away_team, game.home_team, offer.bookmaker, "
            "offer.home_spread, offer.home_price, offer.away_spread, offer.away_price, "
            "offer.observed_at FROM sportsbook_market_offers AS offer "
            "JOIN games AS game ON game.game_id = offer.game_id "
            "WHERE game.season = ? AND game.week = ? "
            "AND offer.line_type IN ('opening', 'current') "
            "AND lower(trim(offer.bookmaker)) != ? "
            "ORDER BY offer.game_id, lower(offer.bookmaker), "
            "julianday(offer.observed_at) DESC, offer.id DESC",
            (season, week, DRAFTKINGS_BOOKMAKER),
        )
    )
    groups: dict[tuple[int, str], list[dict[str, object]]] = {}
    for row in rows:
        key = (int(row["game_id"]), str(row["bookmaker"]).casefold())
        groups.setdefault(key, []).append(row)
    result: list[dict[str, object]] = []
    for values in groups.values():
        current = values[0]
        prior = values[1] if len(values) > 1 else None
        current_home = float(current["home_spread"])
        result.append(
            {
                "game_id": int(current["game_id"]),
                "matchup": f"{current['away_team']} at {current['home_team']}",
                "bookmaker": current["bookmaker"],
                "home_spread": current_home,
                "home_price": int(current["home_price"]),
                "away_spread": float(current["away_spread"]),
                "away_price": int(current["away_price"]),
                "observed_at": current["observed_at"],
                "home_spread_movement": (
                    None if prior is None else current_home - float(prior["home_spread"])
                ),
                "context_only": True,
            }
        )
    return result


def _results(
    conn: sqlite3.Connection,
    *,
    publication: Mapping[str, object],
    context: PublicDashboardContext,
) -> dict[str, object]:
    audit_run = conn.execute(
        "SELECT run.id FROM card_postgame_audit_runs AS run "
        "JOIN card_postgame_audit_completions AS completion "
        "ON completion.audit_run_id = run.id WHERE run.card_id = ? "
        "ORDER BY run.sequence DESC, run.id DESC LIMIT 1",
        (int(publication["card_id"]),),
    ).fetchone()
    if audit_run is None:
        return {
            "available": False,
            "games": [],
            "weekly_summary": None,
            "profitability_note": "No profitability claim; grading is not complete.",
        }
    audit_run_id = int(audit_run[0])
    rows = _row_dicts(
        conn.execute(
            "SELECT detail.game_id, game.away_team, game.home_team, "
            "detail.final_away_points, detail.final_home_points, detail.ats_result, "
            "detail.is_top_five, detail.confidence, detail.closing_home_spread, "
            "detail.closing_book, detail.clv_points, detail.hook_outcome, "
            "detail.key_number_outcome, detail.backdoor_outcome "
            "FROM pick_audit_details AS detail "
            "JOIN games AS game ON game.game_id = detail.game_id "
            "WHERE detail.audit_run_id = ? ORDER BY game.start_date, detail.game_id",
            (audit_run_id,),
        )
    )
    policy = conn.execute(
        "SELECT id FROM sportsbook_recommendation_policies WHERE policy_version = ?",
        (context.sportsbook_policy_version,),
    ).fetchone()
    sportsbook_by_game: dict[int, dict[str, object]] = {}
    sportsbook_completion: dict[str, object] | None = None
    if policy is not None:
        sportsbook_run = conn.execute(
            "SELECT run.id FROM sportsbook_postgame_audit_runs AS run "
            "JOIN sportsbook_postgame_audit_completions AS completion "
            "ON completion.audit_run_id = run.id "
            "WHERE run.season = ? AND run.week = ? AND run.policy_id = ? "
            "ORDER BY run.sequence DESC, run.id DESC LIMIT 1",
            (context.season, context.week, int(policy[0])),
        ).fetchone()
        if sportsbook_run is not None:
            sportsbook_rows = _row_dicts(
                conn.execute(
                    "SELECT game_id, decision, lifecycle_state, ats_result, "
                    "realized_profit_units, closing_selected_spread, "
                    "closing_selected_price, clv_points, clv_evidence_status "
                    "FROM sportsbook_postgame_audit_details "
                    "WHERE audit_run_id = ? AND lower(trim(bookmaker)) = ? "
                    "ORDER BY game_id, decision = 'bet' DESC, evaluation_id DESC",
                    (int(sportsbook_run[0]), DRAFTKINGS_BOOKMAKER),
                )
            )
            for item in sportsbook_rows:
                sportsbook_by_game.setdefault(int(item["game_id"]), item)
            draftkings_bet_summary = _one(
                conn.execute(
                    "SELECT COUNT(*) AS bet_count, "
                    "COALESCE(SUM(ats_result = 'win'), 0) AS win_count, "
                    "COALESCE(SUM(ats_result = 'loss'), 0) AS loss_count, "
                    "COALESCE(SUM(ats_result = 'push'), 0) AS push_count, "
                    "COALESCE(SUM(stake_units), 0.0) AS total_staked_units, "
                    "COALESCE(SUM(realized_profit_units), 0.0) AS realized_profit_units, "
                    "SUM(clv_evidence_status = 'available') AS clv_graded_count, "
                    "AVG(CASE WHEN clv_evidence_status = 'available' THEN clv_points END) "
                    "AS average_clv_points "
                    "FROM sportsbook_postgame_audit_details "
                    "WHERE audit_run_id = ? AND lower(trim(bookmaker)) = ? "
                    "AND decision = 'bet'",
                    (int(sportsbook_run[0]), DRAFTKINGS_BOOKMAKER),
                ),
                "DraftKings BET summary is not unique",
            )
            staked = float(draftkings_bet_summary["total_staked_units"])
            profit = float(draftkings_bet_summary["realized_profit_units"])
            sportsbook_completion = {
                **draftkings_bet_summary,
                "roi_percent": None if staked == 0 else profit / staked * 100,
            }
    games: list[dict[str, object]] = []
    for row in rows:
        sportsbook = sportsbook_by_game.get(int(row["game_id"]))
        games.append(
            {
                "game_id": int(row["game_id"]),
                "matchup": f"{row['away_team']} at {row['home_team']}",
                "final_score": f"{row['away_team']} {row['final_away_points']}, "
                f"{row['home_team']} {row['final_home_points']}",
                "splashsports_ats_result": row["ats_result"],
                "top_five": bool(row["is_top_five"]),
                "confidence": int(row["confidence"]),
                "contest_closing_home_spread": float(row["closing_home_spread"]),
                "contest_closing_book": row["closing_book"],
                "contest_clv_points": float(row["clv_points"]),
                "hook_outcome": row["hook_outcome"],
                "key_number_outcome": row["key_number_outcome"],
                "backdoor_outcome": row["backdoor_outcome"],
                "draftkings": (
                    None
                    if sportsbook is None
                    else {
                        "decision": str(sportsbook["decision"]).upper().replace("_", " "),
                        "lifecycle": str(sportsbook["lifecycle_state"]).upper(),
                        "ats_result": sportsbook["ats_result"],
                        "realized_profit_units": float(
                            sportsbook["realized_profit_units"]
                        ),
                        "closing_spread": sportsbook["closing_selected_spread"],
                        "closing_price": sportsbook["closing_selected_price"],
                        "clv_points": sportsbook["clv_points"],
                        "clv_status": sportsbook["clv_evidence_status"],
                    }
                ),
            }
        )
    contest_completion = _one(
        conn.execute(
            "SELECT audit_count, win_count, loss_count, push_count "
            "FROM card_postgame_audit_completions WHERE audit_run_id = ?",
            (audit_run_id,),
        ),
        "contest audit completion is not unique",
    )
    top_five = [item for item in games if item["top_five"]]
    top_summary = {
        "win_count": sum(item["splashsports_ats_result"] == "win" for item in top_five),
        "loss_count": sum(item["splashsports_ats_result"] == "loss" for item in top_five),
        "push_count": sum(item["splashsports_ats_result"] == "push" for item in top_five),
    }
    diagnostic = conn.execute(
        "SELECT run.id FROM weekly_diagnostic_runs AS run "
        "JOIN weekly_diagnostic_completions AS completion "
        "ON completion.diagnostic_run_id = run.id "
        "WHERE run.audit_run_id = ? ORDER BY run.sequence DESC, run.id DESC LIMIT 1",
        (audit_run_id,),
    ).fetchone()
    segments: list[dict[str, object]] = []
    lessons: list[dict[str, object]] = []
    if diagnostic is not None:
        diagnostic_id = int(diagnostic[0])
        segments = _row_dicts(
            conn.execute(
                "SELECT dimension_code, category_code, sample_count, win_count, "
                "loss_count, push_count, ats_win_rate FROM weekly_diagnostic_segments "
                "WHERE diagnostic_run_id = ? ORDER BY dimension_code, category_code",
                (diagnostic_id,),
            )
        )
        lesson_rows = _row_dicts(
            conn.execute(
                "SELECT lesson_order, lesson_code, evidence_status, sample_count, narrative "
                "FROM weekly_diagnostic_lessons WHERE diagnostic_run_id = ? "
                "ORDER BY lesson_order",
                (diagnostic_id,),
            )
        )
        lessons = [
            {
                "lesson_order": row["lesson_order"],
                "lesson_code": row["lesson_code"],
                "sample_status": row["evidence_status"],
                "sample_count": row["sample_count"],
                "narrative": row["narrative"],
            }
            for row in lesson_rows
        ]
    return {
        "available": True,
        "games": games,
        "weekly_summary": {
            "full_card": contest_completion,
            "top_five": top_summary,
            "draftkings": sportsbook_completion,
            "segments": segments,
            "lessons_learned": lessons,
        },
        "profitability_note": (
            "Operational grading only. One week and other small samples are "
            "insufficient evidence for a profitability claim."
        ),
    }


def _assert_no_sensitive_content(value: object, path: str = "dashboard") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            label = str(key).casefold()
            if any(part in label for part in _BLOCKED_KEY_PARTS):
                raise PublicDashboardError(f"public field is forbidden: {path}.{key}")
            _assert_no_sensitive_content(child, f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_no_sensitive_content(child, f"{path}[{index}]")
        return
    if isinstance(value, str):
        for pattern in _BLOCKED_TEXT_PATTERNS:
            if pattern.search(value):
                raise PublicDashboardError(f"sensitive text is forbidden at {path}")


def validate_public_dashboard_payload(payload: Mapping[str, object]) -> None:
    """Fail closed unless the public contract is complete and provider-specific."""
    if payload.get("schema_version") != PUBLIC_DASHBOARD_SCHEMA_VERSION:
        raise PublicDashboardError("public dashboard schema version is invalid")
    card = payload.get("splashsports_card")
    if not isinstance(card, Mapping) or card.get("source") != "SplashSports":
        raise PublicDashboardError("SplashSports card identity is invalid")
    games = card.get("games")
    expected = card.get("expected_game_count")
    if not isinstance(games, list) or not isinstance(expected, int) or len(games) != expected:
        raise PublicDashboardError("every locked SplashSports game must be published")
    if len({item.get("game_id") for item in games if isinstance(item, Mapping)}) != expected:
        raise PublicDashboardError("SplashSports games must be unique")
    for game in games:
        if not isinstance(game, Mapping):
            raise PublicDashboardError("SplashSports card rows must be objects")
        if game.get("locked_line_source") != "SplashSports":
            raise PublicDashboardError("locked lines cannot be cross-substituted")
        confidence = game.get("confidence")
        if not isinstance(confidence, int) or isinstance(confidence, bool) or not 1 <= confidence <= 5:
            raise PublicDashboardError("Confidence must be present and between 1 and 5")
    top_five = payload.get("top_five")
    expected_top = min(5, expected)
    if not isinstance(top_five, list) or len(top_five) != expected_top:
        raise PublicDashboardError("Top 5 must contain the exact eligible count")
    ranks = [item.get("top_five_rank") for item in top_five if isinstance(item, Mapping)]
    if ranks != list(range(1, expected_top + 1)):
        raise PublicDashboardError("Top 5 ranks must be complete and ordered")
    draftkings = payload.get("draftkings_board")
    if not isinstance(draftkings, Mapping) or draftkings.get("bookmaker") != "DraftKings":
        raise PublicDashboardError("DraftKings board identity is invalid")
    dk_games = draftkings.get("games")
    if not isinstance(dk_games, list) or len(dk_games) != expected:
        raise PublicDashboardError("DraftKings board must cover every locked game")
    if {item["game_id"] for item in games} != {
        item.get("game_id") for item in dk_games if isinstance(item, Mapping)
    }:
        raise PublicDashboardError("DraftKings and contest coverage must match")
    for row in dk_games:
        if not isinstance(row, Mapping) or row.get("bookmaker") != "DraftKings":
            raise PublicDashboardError("other books cannot masquerade as DraftKings")
        if row.get("decision") not in ("BET", "NO BET", "DRAFTKINGS UNAVAILABLE"):
            raise PublicDashboardError("DraftKings state must be explicit")
    results = payload.get("results")
    if not isinstance(results, Mapping) or not isinstance(results.get("available"), bool):
        raise PublicDashboardError("results availability must be explicit")
    if results["available"]:
        result_games = results.get("games")
        summary = results.get("weekly_summary")
        required_result_fields = {
            "game_id",
            "final_score",
            "splashsports_ats_result",
            "top_five",
            "confidence",
            "contest_clv_points",
            "hook_outcome",
            "key_number_outcome",
            "backdoor_outcome",
            "draftkings",
        }
        if (
            not isinstance(result_games, list)
            or not result_games
            or any(
                not isinstance(row, Mapping)
                or not required_result_fields.issubset(row)
                for row in result_games
            )
        ):
            raise PublicDashboardError("graded results are incomplete")
        if not isinstance(summary, Mapping) or not {
            "full_card",
            "top_five",
            "draftkings",
            "segments",
            "lessons_learned",
        }.issubset(summary):
            raise PublicDashboardError("weekly audit summary is incomplete")
    market = payload.get("market_comparison")
    if not isinstance(market, list) or any(
        not isinstance(row, Mapping)
        or str(row.get("bookmaker", "")).casefold() == DRAFTKINGS_BOOKMAKER
        or row.get("context_only") is not True
        for row in market
    ):
        raise PublicDashboardError("secondary books must remain non-actionable context")
    _assert_no_sensitive_content(payload)
    try:
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise PublicDashboardError("public payload is not canonical JSON") from exc


def build_public_dashboard_payload(
    conn: sqlite3.Connection, context: PublicDashboardContext
) -> dict[str, object]:
    """Build an allowlisted public view from the governed SQLite snapshot."""
    publication = _latest_publication(conn, context)
    games, contest_changes = _card_games(conn, publication)
    draftkings, dk_changes, dk_timestamp = _draftkings_board(
        conn, publication=publication, context=context
    )
    freshness_rows, freshness_state = _freshness(conn, int(publication["card_id"]))
    if any(row["freshness"] in ("STALE", "UNAVAILABLE") for row in draftkings):
        freshness_state = "STALE" if freshness_state == "CURRENT" else freshness_state
    warning = None
    if freshness_state != "CURRENT":
        warning = (
            "Data is not fully current. Values remain from the last successful governed "
            "publication; no provider substitution has been made."
        )
    system_status = "ATTENTION" if warning else "OPERATIONAL"
    if context.execution_profile == "shadow":
        system_status = "SHADOW"
        shadow_warning = (
            "Controlled shadow rehearsal output. Production execution remains disabled."
        )
        warning = f"{shadow_warning} {warning}" if warning else shadow_warning
    payload: dict[str, object] = {
        "schema_version": PUBLIC_DASHBOARD_SCHEMA_VERSION,
        "product": {
            "name": "CFB Betting System V3",
            "url": PUBLIC_DASHBOARD_URL,
            "generated_at": context.generated_at,
            "operation": context.operation,
            "execution_profile": context.execution_profile,
            "display_timezone": context.display_timezone,
        },
        "status": {
            "season": context.season,
            "week": context.week,
            "last_successful_data_refresh": _latest_refresh(conn, context),
            "splashsports_line_locked_at": publication["locked_at"],
            "draftkings_odds_at": dk_timestamp,
            "card_published_at": publication["published_at"],
            "freshness": freshness_state,
            "next_scheduled_refresh": context.next_scheduled_refresh,
            "schedule_status": (
                "Recurring schedules disabled; manual governed publication only."
                if context.next_scheduled_refresh is None
                else "Next governed refresh is scheduled."
            ),
            "system_status": system_status,
            "warning": warning,
            "sources": freshness_rows,
        },
        "splashsports_card": {
            "source": "SplashSports",
            "contest_name": publication["contest_name"],
            "card_version": publication["card_version"],
            "expected_game_count": context.expected_lined_game_count,
            "published_game_count": len(games),
            "games": games,
        },
        "top_five": sorted(
            (game for game in games if game["is_top_five"]),
            key=lambda item: int(item["top_five_rank"]),
        ),
        "draftkings_board": {
            "bookmaker": "DraftKings",
            "primary_actionable_sportsbook": True,
            "wager_placement_available": False,
            "expected_game_count": context.expected_lined_game_count,
            "games": draftkings,
        },
        "market_comparison": _market_comparison(
            conn, season=context.season, week=context.week
        ),
        "changes_since_last_refresh": sorted(
            (*contest_changes, *dk_changes),
            key=lambda item: (
                str(item["observed_at"]),
                str(item["category"]),
                str(item["matchup"]),
            ),
            reverse=True,
        ),
        "results": _results(conn, publication=publication, context=context),
    }
    validate_public_dashboard_payload(payload)
    return payload


def write_public_dashboard_site(
    *,
    payload: Mapping[str, object],
    output_directory: Path,
    asset_directory: Path,
) -> Path:
    """Validate and atomically create a fresh Pages artifact directory."""
    validate_public_dashboard_payload(payload)
    output = output_directory.resolve()
    assets = asset_directory.resolve()
    if output.exists():
        raise PublicDashboardError(
            "Pages output already exists; refusing to replace a last-good artifact"
        )
    if not output.parent.is_dir():
        raise PublicDashboardError("Pages output parent directory does not exist")
    missing = [name for name in PUBLIC_DASHBOARD_ASSETS if not (assets / name).is_file()]
    if missing:
        raise PublicDashboardError(f"dashboard assets are missing: {', '.join(missing)}")
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ) + "\n"
    with tempfile.TemporaryDirectory(prefix=".v3-pages-stage-", dir=output.parent) as directory:
        stage = Path(directory) / "site"
        stage.mkdir()
        for name in PUBLIC_DASHBOARD_ASSETS:
            shutil.copyfile(assets / name, stage / name)
        (stage / "dashboard.json").write_text(canonical, encoding="utf-8")
        (stage / ".nojekyll").write_text("", encoding="utf-8")
        for path in stage.iterdir():
            text = path.read_text(encoding="utf-8")
            for pattern in _BLOCKED_TEXT_PATTERNS:
                if pattern.search(text):
                    raise PublicDashboardError(
                        f"generated Pages artifact contains sensitive text: {path.name}"
                    )
        os.replace(stage, output)
    return output


def generate_public_dashboard_site(
    conn: sqlite3.Connection,
    *,
    configuration: WeeklyOperationConfiguration,
    operation: ProductionExecutionResult,
    output_directory: Path,
    repository_root: Path,
    execution_profile: str = "production",
) -> Path:
    """Build, validate, and stage a sanitized site before durable state commits."""
    policies = dict(configuration.policy_versions)
    context = PublicDashboardContext(
        season=configuration.season,
        week=configuration.week,
        contest_key=configuration.contest_key,
        expected_lined_game_count=configuration.expected_lined_game_count,
        display_timezone=configuration.display_timezone,
        sportsbook_policy_version=policies["sportsbook"],
        generated_at=operation.completed_at,
        operation=operation.operation,
        execution_profile=execution_profile,
        draftkings_rows=tuple(operation.draftkings_betting_board),
    )
    payload = build_public_dashboard_payload(conn, context)
    return write_public_dashboard_site(
        payload=payload,
        output_directory=output_directory,
        asset_directory=repository_root / "docs",
    )
