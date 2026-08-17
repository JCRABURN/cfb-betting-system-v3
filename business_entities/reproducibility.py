"""Immutable run manifests and deterministic card replay from stored identifiers."""

from __future__ import annotations

import sqlite3
from dataclasses import astuple, dataclass
from datetime import datetime

from business_entities.adjustments import ManualAdjustment
from business_entities.cards import ContestCard, get_contest_card
from business_entities.common import (
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    choice,
    integer,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)
from business_entities.contextual_adjustments import (
    ManualAdjustmentPolicy,
    adjustment_history_sha256 as _adjustment_history_sha256,
    adjustment_policy_from_card,
    get_card_adjustment_policy,
    get_card_adjustment_policy_assignment,
    recorded_manual_adjustment_policy_matches,
)
from business_entities.modeling import ModelRun, get_model_run
from business_entities.ranking import (
    ConfidenceRankingPolicy,
    ContestRankingPolicy,
    get_card_policy_assignment,
    get_contest_ranking_policy,
    recorded_policy_matches,
)


class ReproducibilityError(BusinessEntityError):
    """Raised when stored run identifiers cannot reproduce an immutable card."""


@dataclass(frozen=True)
class FullCardPolicy:
    """Versioned side-selection policy and exact real-book fallback order."""

    version: str
    market_books: tuple[str, ...]
    model_tie_side: str = "away"
    pickem_tiebreak_side: str = "home"


@dataclass(frozen=True)
class ContestSelectionPolicy:
    id: int
    policy_version: str
    market_books: tuple[str, ...]
    model_tie_side: str
    pickem_tiebreak_side: str
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class CardRunManifest:
    card_id: int
    model_run_id: int
    selection_policy_id: int
    ranking_policy_id: int
    model_name: str
    model_version: str
    selection_policy_version: str
    confidence_policy_version: str
    ranking_policy_version: str
    feature_schema_version: str
    configuration_version: str
    code_commit_sha: str
    data_snapshot_sha256: str
    locked_line_snapshot_sha256: str
    adjustment_history_sha256: str
    adjustment_count: int
    generated_at: str
    provenance: str


_SELECTION_POLICY_COLUMNS = (
    "id, policy_version, market_book_count, model_tie_side, "
    "pickem_tiebreak_side, effective_at, created_by, provenance"
)
_MANIFEST_COLUMNS = (
    "card_id, model_run_id, selection_policy_id, ranking_policy_id, model_name, "
    "model_version, selection_policy_version, confidence_policy_version, "
    "ranking_policy_version, feature_schema_version, configuration_version, "
    "code_commit_sha, data_snapshot_sha256, locked_line_snapshot_sha256, "
    "adjustment_history_sha256, adjustment_count, generated_at, provenance"
)
_ADJUSTMENT_COLUMNS = (
    "adjustment.id, adjustment.adjustment_key, adjustment.model_prediction_id, "
    "adjustment.contest_pick_id, adjustment.sequence, "
    "adjustment.supersedes_adjustment_id, adjustment.category, "
    "adjustment.affected_side, adjustment.margin_adjustment, "
    "adjustment.confidence_adjustment, adjustment.reason, adjustment.evidence, "
    "adjustment.source, adjustment.author, adjustment.recorded_at, "
    "adjustment.provenance"
)


def validate_full_card_policy(policy: FullCardPolicy) -> FullCardPolicy:
    """Validate policy inputs without consulting undocumented local state."""
    if not isinstance(policy, FullCardPolicy):
        raise ReproducibilityError("policy must be a FullCardPolicy")
    version = required_text(policy.version, "policy.version")
    if not isinstance(policy.market_books, tuple):
        raise ReproducibilityError("policy.market_books must be a tuple")
    books = tuple(
        required_text(book, "policy.market_books entry")
        for book in policy.market_books
    )
    folded = tuple(book.casefold() for book in books)
    if len(folded) != len(set(folded)):
        raise ReproducibilityError("policy.market_books cannot contain duplicates")
    if any(book == "consensus" for book in folded):
        raise ReproducibilityError(
            "market fallback requires explicitly named real books, not consensus"
        )
    return FullCardPolicy(
        version=version,
        market_books=books,
        model_tie_side=choice(
            policy.model_tie_side,
            "policy.model_tie_side",
            ("home", "away"),
        ),
        pickem_tiebreak_side=choice(
            policy.pickem_tiebreak_side,
            "policy.pickem_tiebreak_side",
            ("home", "away"),
        ),
    )


def _selection_policy_from_row(
    conn: sqlite3.Connection, row: tuple[object, ...]
) -> ContestSelectionPolicy:
    policy_id = int(row[0])
    books = tuple(
        book_row[0]
        for book_row in conn.execute(
            "SELECT book FROM contest_selection_policy_books "
            "WHERE selection_policy_id = ? ORDER BY priority",
            (policy_id,),
        )
    )
    if len(books) != row[2]:
        raise ReproducibilityError(
            f"contest selection policy has incomplete book order: {policy_id}"
        )
    return ContestSelectionPolicy(
        id=policy_id,
        policy_version=str(row[1]),
        market_books=books,
        model_tie_side=str(row[3]),
        pickem_tiebreak_side=str(row[4]),
        effective_at=str(row[5]),
        created_by=str(row[6]),
        provenance=str(row[7]),
    )


def get_contest_selection_policy(
    conn: sqlite3.Connection, selection_policy_id: int
) -> ContestSelectionPolicy:
    row = conn.execute(
        f"SELECT {_SELECTION_POLICY_COLUMNS} FROM contest_selection_policies "
        "WHERE id = ?",
        (integer(selection_policy_id, "selection_policy_id", 1),),
    ).fetchone()
    if row is None:
        raise ReproducibilityError(
            f"contest selection policy does not exist: {selection_policy_id}"
        )
    return _selection_policy_from_row(conn, row)


def selection_policy_matches(
    recorded: ContestSelectionPolicy, requested: FullCardPolicy
) -> bool:
    requested = validate_full_card_policy(requested)
    return (
        recorded.policy_version,
        recorded.market_books,
        recorded.model_tie_side,
        recorded.pickem_tiebreak_side,
    ) == (
        requested.version,
        requested.market_books,
        requested.model_tie_side,
        requested.pickem_tiebreak_side,
    )


def register_contest_selection_policy(
    conn: sqlite3.Connection,
    policy: FullCardPolicy,
    *,
    effective_at: datetime,
    created_by: str,
    provenance: str,
) -> ContestSelectionPolicy:
    """Register the complete immutable meaning of a selection-policy version."""
    policy = validate_full_card_policy(policy)
    effective_at_value = utc_timestamp(effective_at, "effective_at")
    created_by = required_text(created_by, "created_by")
    provenance = required_text(provenance, "provenance")
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_SELECTION_POLICY_COLUMNS} FROM contest_selection_policies "
                "WHERE policy_version = ?",
                (policy.version,),
            ).fetchone()
            if row is not None:
                existing = _selection_policy_from_row(conn, row)
                if not selection_policy_matches(existing, policy):
                    raise BusinessEntityConflictError(
                        "selection policy version has different immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO contest_selection_policies "
                "(policy_version, market_book_count, model_tie_side, "
                "pickem_tiebreak_side, effective_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    policy.version,
                    len(policy.market_books),
                    policy.model_tie_side,
                    policy.pickem_tiebreak_side,
                    effective_at_value,
                    created_by,
                    provenance,
                ),
            )
            policy_id = cursor.lastrowid
            for priority, book in enumerate(policy.market_books, start=1):
                conn.execute(
                    "INSERT INTO contest_selection_policy_books "
                    "(selection_policy_id, priority, book) VALUES (?, ?, ?)",
                    (policy_id, priority, book),
                )
            return get_contest_selection_policy(conn, policy_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("contest selection policy", exc) from exc


def list_card_adjustment_history(
    conn: sqlite3.Connection, card_id: int
) -> tuple[ManualAdjustment, ...]:
    """Return only adjustments known by the immutable card generation instant."""
    card = get_contest_card(conn, integer(card_id, "card_id", 1))
    rows = conn.execute(
        f"SELECT {_ADJUSTMENT_COLUMNS} FROM manual_adjustments AS adjustment "
        "JOIN contest_picks AS pick "
        "ON pick.model_prediction_id = adjustment.model_prediction_id "
        "WHERE pick.card_id = ? "
        "AND julianday(adjustment.recorded_at) <= julianday(?) "
        "ORDER BY adjustment.model_prediction_id, adjustment.sequence, adjustment.id",
        (card.id, card.generated_at),
    ).fetchall()
    return tuple(ManualAdjustment(*row) for row in rows)


def adjustment_history_sha256(
    adjustments: tuple[ManualAdjustment, ...],
) -> str:
    return _adjustment_history_sha256(adjustments)


def get_card_run_manifest(
    conn: sqlite3.Connection, card_id: int
) -> CardRunManifest:
    row = conn.execute(
        f"SELECT {_MANIFEST_COLUMNS} FROM card_run_manifests WHERE card_id = ?",
        (integer(card_id, "card_id", 1),),
    ).fetchone()
    if row is None:
        raise ReproducibilityError(f"contest card has no run manifest: {card_id}")
    return CardRunManifest(*row)


def _manifest_values(
    conn: sqlite3.Connection,
    *,
    card: ContestCard,
    run: ModelRun,
    selection_policy: ContestSelectionPolicy,
    ranking_policy: ContestRankingPolicy,
) -> tuple[object, ...]:
    adjustments = list_card_adjustment_history(conn, card.id)
    return (
        card.id,
        run.id,
        selection_policy.id,
        ranking_policy.id,
        run.model_name,
        run.model_version,
        selection_policy.policy_version,
        ranking_policy.confidence_policy_version,
        ranking_policy.ranking_policy_version,
        run.feature_schema_version,
        run.configuration_version,
        run.code_commit_sha,
        run.data_snapshot_sha256,
        card.locked_line_snapshot_sha256,
        adjustment_history_sha256(adjustments),
        len(adjustments),
        card.generated_at,
        card.provenance,
    )


def record_card_run_manifest(
    conn: sqlite3.Connection,
    *,
    card_id: int,
    selection_policy_id: int,
    ranking_policy_id: int,
) -> CardRunManifest:
    """Freeze all identifiers needed to reproduce a card and its as-of context."""
    card = get_contest_card(conn, integer(card_id, "card_id", 1))
    if card.model_run_id is None:
        raise ReproducibilityError("reproducible cards require a model run")
    run = get_model_run(conn, card.model_run_id)
    selection_policy = get_contest_selection_policy(
        conn, integer(selection_policy_id, "selection_policy_id", 1)
    )
    ranking_policy = get_contest_ranking_policy(
        conn, integer(ranking_policy_id, "ranking_policy_id", 1)
    )
    assignment = get_card_policy_assignment(conn, card.id)
    adjustment_assignment = get_card_adjustment_policy_assignment(conn, card.id)
    if assignment.ranking_policy_id != ranking_policy.id:
        raise ReproducibilityError("manifest ranking policy is not assigned to card")
    if card.policy_version != selection_policy.policy_version:
        raise ReproducibilityError("manifest selection policy is not assigned to card")
    adjustment_policy = get_card_adjustment_policy(conn, card.id)
    if adjustment_assignment.adjustment_policy_id != adjustment_policy.id:
        raise ReproducibilityError(
            "manifest adjustment policy is not assigned to card"
        )
    if not timestamp_on_or_before(
        conn, adjustment_policy.effective_at, card.generated_at
    ):
        raise ReproducibilityError(
            "manual adjustment policy was not effective at generation"
        )
    if not timestamp_on_or_before(conn, selection_policy.effective_at, card.generated_at):
        raise ReproducibilityError("selection policy was not effective at generation")
    requested = _manifest_values(
        conn,
        card=card,
        run=run,
        selection_policy=selection_policy,
        ranking_policy=ranking_policy,
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_MANIFEST_COLUMNS} FROM card_run_manifests WHERE card_id = ?",
                (card.id,),
            ).fetchone()
            if row is not None:
                existing = CardRunManifest(*row)
                if tuple(row) != requested:
                    raise BusinessEntityConflictError(
                        "card run manifest has different immutable values"
                    )
                return existing
            conn.execute(
                "INSERT INTO card_run_manifests "
                "(card_id, model_run_id, selection_policy_id, ranking_policy_id, "
                "model_name, model_version, selection_policy_version, "
                "confidence_policy_version, ranking_policy_version, "
                "feature_schema_version, configuration_version, code_commit_sha, "
                "data_snapshot_sha256, locked_line_snapshot_sha256, "
                "adjustment_history_sha256, adjustment_count, generated_at, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            return get_card_run_manifest(conn, card.id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("card run manifest", exc) from exc


def full_card_policy_from_manifest(
    conn: sqlite3.Connection, manifest: CardRunManifest
) -> FullCardPolicy:
    recorded = get_contest_selection_policy(conn, manifest.selection_policy_id)
    return FullCardPolicy(
        version=recorded.policy_version,
        market_books=recorded.market_books,
        model_tie_side=recorded.model_tie_side,
        pickem_tiebreak_side=recorded.pickem_tiebreak_side,
    )


def confidence_policy_from_manifest(
    conn: sqlite3.Connection, manifest: CardRunManifest
) -> ConfidenceRankingPolicy:
    recorded = get_contest_ranking_policy(conn, manifest.ranking_policy_id)
    return ConfidenceRankingPolicy(
        policy_key=recorded.policy_key,
        confidence_policy_version=recorded.confidence_policy_version,
        ranking_policy_version=recorded.ranking_policy_version,
        confidence_5_max_uncertainty=recorded.confidence_5_max_uncertainty,
        confidence_4_max_uncertainty=recorded.confidence_4_max_uncertainty,
        confidence_3_max_uncertainty=recorded.confidence_3_max_uncertainty,
        confidence_2_max_uncertainty=recorded.confidence_2_max_uncertainty,
        effective_at=datetime.fromisoformat(recorded.effective_at),
        created_by=recorded.created_by,
        provenance=recorded.provenance,
    )


def card_run_manifest_matches(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    policy: FullCardPolicy,
    confidence_policy: ConfidenceRankingPolicy,
    adjustment_policy: ManualAdjustmentPolicy,
) -> bool:
    try:
        card = get_contest_card(conn, card_id)
        if card.model_run_id is None:
            return False
        manifest = get_card_run_manifest(conn, card.id)
        run = get_model_run(conn, card.model_run_id)
        selection_policy = get_contest_selection_policy(
            conn, manifest.selection_policy_id
        )
        ranking_policy = get_contest_ranking_policy(conn, manifest.ranking_policy_id)
        assignment = get_card_policy_assignment(conn, card.id)
        recorded_adjustment_policy = get_card_adjustment_policy(conn, card.id)
        expected = _manifest_values(
            conn,
            card=card,
            run=run,
            selection_policy=selection_policy,
            ranking_policy=ranking_policy,
        )
        return (
            astuple(manifest) == expected
            and manifest.model_run_id == card.model_run_id
            and assignment.ranking_policy_id == manifest.ranking_policy_id
            and selection_policy_matches(selection_policy, policy)
            and recorded_policy_matches(ranking_policy, confidence_policy)
            and recorded_manual_adjustment_policy_matches(
                recorded_adjustment_policy,
                adjustment_policy,
            )
        )
    except (BusinessEntityError, sqlite3.DatabaseError, ValueError):
        return False


def assert_card_run_manifest(
    conn: sqlite3.Connection,
    card_id: int,
    *,
    policy: FullCardPolicy,
    confidence_policy: ConfidenceRankingPolicy,
    adjustment_policy: ManualAdjustmentPolicy,
) -> CardRunManifest:
    if not card_run_manifest_matches(
        conn,
        card_id,
        policy=policy,
        confidence_policy=confidence_policy,
        adjustment_policy=adjustment_policy,
    ):
        raise ReproducibilityError(
            "card run manifest or stored policy inputs do not match replay"
        )
    return get_card_run_manifest(conn, card_id)


def resolve_card_run(
    conn: sqlite3.Connection, *, card_key: str, model_run_key: str
) -> tuple[ContestCard, ModelRun, CardRunManifest]:
    card_key = required_text(card_key, "card_key")
    model_run_key = required_text(model_run_key, "model_run_key")
    row = conn.execute(
        "SELECT card.id, run.id FROM contest_cards AS card "
        "JOIN model_runs AS run ON run.id = card.model_run_id "
        "WHERE card.card_key = ? AND run.run_key = ?",
        (card_key, model_run_key),
    ).fetchone()
    if row is None:
        raise ReproducibilityError(
            "card_key and model_run_key do not identify one recorded card run"
        )
    card = get_contest_card(conn, row[0])
    run = get_model_run(conn, row[1])
    return card, run, get_card_run_manifest(conn, card.id)


def reproduce_card(
    conn: sqlite3.Connection, *, card_key: str, model_run_key: str
):
    """Recompute and verify a prior card using only its persisted run identifiers."""
    card, run, manifest = resolve_card_run(
        conn,
        card_key=card_key,
        model_run_key=model_run_key,
    )
    policy = full_card_policy_from_manifest(conn, manifest)
    confidence_policy = confidence_policy_from_manifest(conn, manifest)
    adjustment_policy = adjustment_policy_from_card(conn, card.id)
    assert_card_run_manifest(
        conn,
        card.id,
        policy=policy,
        confidence_policy=confidence_policy,
        adjustment_policy=adjustment_policy,
    )
    from business_entities.full_card import generate_full_card

    return generate_full_card(
        conn,
        card_key=card.card_key,
        contest_id=card.contest_id,
        model_run_id=run.id,
        version=card.version,
        policy=policy,
        confidence_policy=confidence_policy,
        adjustment_policy=adjustment_policy,
        created_by=card.created_by,
        provenance=card.provenance,
        generated_at=datetime.fromisoformat(card.generated_at),
    )
