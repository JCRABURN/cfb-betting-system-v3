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
    record_card_revision,
)
from business_entities.common import BusinessEntityConflictError, BusinessEntityError
from business_entities.modeling import (
    ModelPrediction,
    ModelRun,
    record_model_prediction,
    record_model_run,
)
from business_entities.wagering import (
    SportsbookRecommendation,
    record_sportsbook_recommendation,
)


__all__ = [
    "BusinessEntityConflictError",
    "BusinessEntityError",
    "CardRevision",
    "ContestCard",
    "ContestPick",
    "ManualAdjustment",
    "ModelPrediction",
    "ModelRun",
    "PickAudit",
    "SportsbookRecommendation",
    "add_contest_pick",
    "create_contest_card",
    "list_manual_adjustments",
    "list_pick_audits",
    "record_card_revision",
    "record_manual_adjustment",
    "record_model_prediction",
    "record_model_run",
    "record_pick_audit",
    "record_sportsbook_recommendation",
]
