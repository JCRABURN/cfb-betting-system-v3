"""Explicit business entities that replace new uses of the legacy ``picks`` table.

The legacy table remains readable for compatibility. New model, contest,
sportsbook, adjustment, revision, and audit writes belong in these append-only
services so that each concept has one auditable meaning.
"""

from business_entities.adjustments import (
    ManualAdjustment,
    list_manual_adjustments,
    record_manual_adjustment,
)
from business_entities.audits import PickAudit, list_pick_audits, record_pick_audit
from business_entities.cards import (
    CardRevision,
    ContestCard,
    ContestPick,
    add_contest_pick,
    create_contest_card,
    list_contest_picks,
    record_card_revision,
)
from business_entities.common import BusinessEntityConflictError, BusinessEntityError
from business_entities.full_card import (
    CardCompletenessReport,
    FullCardError,
    FullCardPolicy,
    FullCardResult,
    IncompleteCardError,
    generate_full_card,
    inspect_full_card,
    validate_full_card,
)
from business_entities.modeling import (
    ModelPrediction,
    ModelRun,
    record_model_prediction,
    record_model_run,
)
from business_entities.ranking import (
    CardPolicyAssignment,
    ConfidenceRankingPolicy,
    ContestRankingPolicy,
    assign_card_ranking_policy,
    get_card_ranking_policy,
    register_confidence_ranking_policy,
)
from business_entities.wagering import (
    SportsbookRecommendation,
    record_sportsbook_recommendation,
)


__all__ = [
    "BusinessEntityConflictError",
    "BusinessEntityError",
    "CardRevision",
    "CardCompletenessReport",
    "CardPolicyAssignment",
    "ConfidenceRankingPolicy",
    "ContestCard",
    "ContestPick",
    "ContestRankingPolicy",
    "ManualAdjustment",
    "ModelPrediction",
    "ModelRun",
    "PickAudit",
    "SportsbookRecommendation",
    "FullCardError",
    "FullCardPolicy",
    "FullCardResult",
    "IncompleteCardError",
    "add_contest_pick",
    "assign_card_ranking_policy",
    "create_contest_card",
    "generate_full_card",
    "get_card_ranking_policy",
    "inspect_full_card",
    "list_manual_adjustments",
    "list_contest_picks",
    "list_pick_audits",
    "record_card_revision",
    "record_manual_adjustment",
    "record_model_prediction",
    "record_model_run",
    "record_pick_audit",
    "record_sportsbook_recommendation",
    "register_confidence_ranking_policy",
    "validate_full_card",
]
