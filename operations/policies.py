"""Load already-registered production policies without creating or promoting rules."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from business_entities.complete_audits import PostgameAuditPolicy, get_postgame_audit_policy
from business_entities.contextual_adjustments import (
    ManualAdjustmentPolicy,
    get_manual_adjustment_policy,
)
from business_entities.live_sportsbook import (
    SportsbookRecommendationPolicy,
    get_sportsbook_recommendation_policy,
)
from business_entities.ranking import (
    ConfidenceRankingPolicy,
    get_contest_ranking_policy,
)
from business_entities.refreshes import DailyRefreshPolicy, get_card_refresh_policy
from business_entities.reproducibility import FullCardPolicy, get_contest_selection_policy
from business_entities.weekly_controller import (
    RequiredSourcePolicy,
    WeeklyControllerPolicy,
    get_weekly_controller_policy,
)
from business_entities.weekly_diagnostics import (
    WeeklyDiagnosticsPolicy,
    get_weekly_diagnostics_policy,
)

from operations.config import ProductionSettings


class ProductionPolicyError(RuntimeError):
    """Raised when configured immutable policies cannot be loaded exactly."""


@dataclass(frozen=True)
class ProductionPolicySet:
    controller: WeeklyControllerPolicy
    selection: FullCardPolicy
    confidence: ConfidenceRankingPolicy
    adjustment: ManualAdjustmentPolicy
    refresh: DailyRefreshPolicy
    audit: PostgameAuditPolicy
    diagnostics: WeeklyDiagnosticsPolicy
    sportsbook: SportsbookRecommendationPolicy


def _id_by_version(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    value: str,
) -> int:
    row = conn.execute(
        f'SELECT id FROM "{table}" WHERE "{column}" = ?',
        (value,),
    ).fetchone()
    if row is None:
        raise ProductionPolicyError(f"registered policy is missing: {table}/{value}")
    return int(row[0])


def load_registered_policy_set(
    conn: sqlite3.Connection,
    settings: ProductionSettings,
) -> ProductionPolicySet:
    """Rehydrate immutable policies; never register or alter policy state."""
    controller_id = _id_by_version(
        conn,
        "weekly_controller_policies",
        "policy_version",
        settings.policy_version("controller"),
    )
    controller_record = get_weekly_controller_policy(conn, controller_id)
    source_rows = conn.execute(
        "SELECT data_type, provider, permitted_fallback_code "
        "FROM weekly_controller_policy_sources WHERE controller_policy_id = ? "
        "ORDER BY source_order",
        (controller_id,),
    ).fetchall()
    controller = WeeklyControllerPolicy(
        policy_version=controller_record.policy_version,
        authorized_contest_source=controller_record.authorized_contest_source,
        required_sources=tuple(RequiredSourcePolicy(*row) for row in source_rows),
        effective_at=datetime.fromisoformat(controller_record.effective_at),
        created_by=controller_record.created_by,
        provenance=controller_record.provenance,
    )

    selection_id = _id_by_version(
        conn,
        "contest_selection_policies",
        "policy_version",
        settings.policy_version("selection"),
    )
    selection_record = get_contest_selection_policy(conn, selection_id)
    selection = FullCardPolicy(
        version=selection_record.policy_version,
        market_books=selection_record.market_books,
        model_tie_side=selection_record.model_tie_side,
        pickem_tiebreak_side=selection_record.pickem_tiebreak_side,
    )

    confidence_row = conn.execute(
        "SELECT id FROM contest_ranking_policies "
        "WHERE confidence_policy_version = ? AND ranking_policy_version = ?",
        (
            settings.policy_version("confidence"),
            settings.policy_version("ranking"),
        ),
    ).fetchone()
    if confidence_row is None:
        raise ProductionPolicyError("registered Confidence/ranking policy is missing")
    confidence_record = get_contest_ranking_policy(conn, int(confidence_row[0]))
    confidence = ConfidenceRankingPolicy(
        policy_key=confidence_record.policy_key,
        confidence_policy_version=confidence_record.confidence_policy_version,
        ranking_policy_version=confidence_record.ranking_policy_version,
        confidence_5_max_uncertainty=confidence_record.confidence_5_max_uncertainty,
        confidence_4_max_uncertainty=confidence_record.confidence_4_max_uncertainty,
        confidence_3_max_uncertainty=confidence_record.confidence_3_max_uncertainty,
        confidence_2_max_uncertainty=confidence_record.confidence_2_max_uncertainty,
        effective_at=datetime.fromisoformat(confidence_record.effective_at),
        created_by=confidence_record.created_by,
        provenance=confidence_record.provenance,
    )

    adjustment_record = get_manual_adjustment_policy(
        conn,
        _id_by_version(
            conn,
            "manual_adjustment_policies",
            "policy_version",
            settings.policy_version("adjustment"),
        ),
    )
    adjustment = ManualAdjustmentPolicy(
        adjustment_record.policy_version,
        datetime.fromisoformat(adjustment_record.effective_at),
        adjustment_record.created_by,
        adjustment_record.provenance,
    )
    refresh_record = get_card_refresh_policy(
        conn,
        _id_by_version(
            conn,
            "card_refresh_policies",
            "policy_version",
            settings.policy_version("refresh"),
        ),
    )
    refresh = DailyRefreshPolicy(
        refresh_record.policy_version,
        datetime.fromisoformat(refresh_record.effective_at),
        refresh_record.created_by,
        refresh_record.provenance,
        refresh_record.timezone_name,
    )
    audit_record = get_postgame_audit_policy(
        conn,
        _id_by_version(
            conn,
            "postgame_audit_policies",
            "policy_version",
            settings.policy_version("audit"),
        ),
    )
    audit = PostgameAuditPolicy(
        audit_record.policy_version,
        datetime.fromisoformat(audit_record.effective_at),
        audit_record.created_by,
        audit_record.provenance,
    )
    diagnostics_record = get_weekly_diagnostics_policy(
        conn,
        _id_by_version(
            conn,
            "weekly_diagnostic_policies",
            "policy_version",
            settings.policy_version("diagnostics"),
        ),
    )
    diagnostics = WeeklyDiagnosticsPolicy(
        policy_version=diagnostics_record.policy_version,
        minimum_recommendation_sample=diagnostics_record.minimum_recommendation_sample,
        minimum_ats_delta_percentage_points=(
            diagnostics_record.minimum_ats_delta_percentage_points
        ),
        confidence_threshold_step_points=(
            diagnostics_record.confidence_threshold_step_points
        ),
        effective_at=datetime.fromisoformat(diagnostics_record.effective_at),
        created_by=diagnostics_record.created_by,
        provenance=diagnostics_record.provenance,
    )
    sportsbook = get_sportsbook_recommendation_policy(
        conn,
        _id_by_version(
            conn,
            "sportsbook_recommendation_policies",
            "policy_version",
            settings.policy_version("sportsbook"),
        ),
    )
    return ProductionPolicySet(
        controller,
        selection,
        confidence,
        adjustment,
        refresh,
        audit,
        diagnostics,
        sportsbook,
    )
