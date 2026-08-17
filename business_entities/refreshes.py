"""Tuesday-through-Saturday immutable card refresh and revision history."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone

from business_entities.cards import (
    CardRevision,
    ContestPick,
    get_contest_card,
    list_contest_picks,
    record_card_revision,
)
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
from business_entities.contextual_adjustments import adjustment_policy_from_card
from business_entities.full_card import (
    FullCardResult,
    generate_full_card,
    validate_full_card,
)
from business_entities.reproducibility import (
    CardRunManifest,
    confidence_policy_from_manifest,
    full_card_policy_from_manifest,
    get_card_run_manifest,
)


ALLOWED_WEEKDAY_MASK = 62
OPERATING_TIMEZONE = "UTC"


class DailyRefreshError(BusinessEntityError):
    """Raised when a requested midweek refresh is incomplete or unsafe."""


@dataclass(frozen=True)
class DailyRefreshPolicy:
    policy_version: str
    effective_at: datetime
    created_by: str
    provenance: str
    timezone_name: str = OPERATING_TIMEZONE


@dataclass(frozen=True)
class CardRefreshPolicy:
    id: int
    policy_version: str
    timezone_name: str
    allowed_weekday_mask: int
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class CardRevisionPickChange:
    revision_id: int
    locked_line_id: int
    prior_pick_id: int
    revised_pick_id: int
    prior_model_prediction_id: int | None
    revised_model_prediction_id: int | None
    prior_selected_side: str
    revised_selected_side: str
    prior_confidence: int
    revised_confidence: int
    prior_rank: int | None
    revised_rank: int | None
    prior_is_top_five: bool
    revised_is_top_five: bool
    prior_fallback_code: str | None
    revised_fallback_code: str | None
    side_changed: bool
    confidence_changed: bool
    rank_changed: bool
    top_five_changed: bool
    model_prediction_changed: bool
    fallback_changed: bool


@dataclass(frozen=True)
class CardRefreshRevision:
    revision_id: int
    refresh_policy_id: int
    operating_date: str
    operating_weekday: int
    timezone_name: str
    refreshed_at: str
    provenance: str


@dataclass(frozen=True)
class DailyRefreshResult:
    revision: CardRevision
    refresh: CardRefreshRevision
    revised_card: FullCardResult
    changes: tuple[CardRevisionPickChange, ...]


_POLICY_COLUMNS = (
    "id, policy_version, timezone_name, allowed_weekday_mask, effective_at, "
    "created_by, provenance"
)
_CHANGE_COLUMNS = (
    "revision_id, locked_line_id, prior_pick_id, revised_pick_id, "
    "prior_model_prediction_id, revised_model_prediction_id, "
    "prior_selected_side, revised_selected_side, prior_confidence, "
    "revised_confidence, prior_rank, revised_rank, prior_is_top_five, "
    "revised_is_top_five, prior_fallback_code, revised_fallback_code, "
    "side_changed, confidence_changed, rank_changed, top_five_changed, "
    "model_prediction_changed, fallback_changed"
)
_REFRESH_COLUMNS = (
    "revision_id, refresh_policy_id, operating_date, operating_weekday, "
    "timezone_name, refreshed_at, provenance"
)


def validate_daily_refresh_policy(policy: DailyRefreshPolicy) -> DailyRefreshPolicy:
    if not isinstance(policy, DailyRefreshPolicy):
        raise DailyRefreshError("refresh_policy must be a DailyRefreshPolicy")
    if policy.timezone_name != OPERATING_TIMEZONE:
        raise DailyRefreshError("daily refresh policy timezone must be UTC")
    return DailyRefreshPolicy(
        policy_version=required_text(
            policy.policy_version, "refresh_policy.policy_version"
        ),
        effective_at=datetime.fromisoformat(
            utc_timestamp(policy.effective_at, "refresh_policy.effective_at")
        ),
        created_by=required_text(policy.created_by, "refresh_policy.created_by"),
        provenance=required_text(policy.provenance, "refresh_policy.provenance"),
        timezone_name=OPERATING_TIMEZONE,
    )


def get_card_refresh_policy(
    conn: sqlite3.Connection, refresh_policy_id: int
) -> CardRefreshPolicy:
    row = conn.execute(
        f"SELECT {_POLICY_COLUMNS} FROM card_refresh_policies WHERE id = ?",
        (integer(refresh_policy_id, "refresh_policy_id", 1),),
    ).fetchone()
    if row is None:
        raise DailyRefreshError(
            f"card refresh policy does not exist: {refresh_policy_id}"
        )
    return CardRefreshPolicy(*row)


def register_daily_refresh_policy(
    conn: sqlite3.Connection, policy: DailyRefreshPolicy
) -> CardRefreshPolicy:
    """Register the immutable UTC Tuesday-Saturday operating policy."""
    policy = validate_daily_refresh_policy(policy)
    requested = (
        policy.policy_version,
        policy.timezone_name,
        ALLOWED_WEEKDAY_MASK,
        policy.effective_at.isoformat(),
        policy.created_by,
        policy.provenance,
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM card_refresh_policies "
                "WHERE policy_version = ?",
                (policy.policy_version,),
            ).fetchone()
            if row is not None:
                existing = CardRefreshPolicy(*row)
                if tuple(row[1:]) != requested:
                    raise BusinessEntityConflictError(
                        "refresh policy version has different immutable values"
                    )
                return existing
            cursor = conn.execute(
                "INSERT INTO card_refresh_policies "
                "(policy_version, timezone_name, allowed_weekday_mask, effective_at, "
                "created_by, provenance) VALUES (?, ?, ?, ?, ?, ?)",
                requested,
            )
            return get_card_refresh_policy(conn, cursor.lastrowid)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("card refresh policy", exc) from exc


def _change_from_row(row: tuple[object, ...]) -> CardRevisionPickChange:
    values = list(row)
    for index in (12, 13, 16, 17, 18, 19, 20, 21):
        values[index] = bool(values[index])
    return CardRevisionPickChange(*values)


def list_card_revision_pick_changes(
    conn: sqlite3.Connection, revision_id: int
) -> tuple[CardRevisionPickChange, ...]:
    rows = conn.execute(
        f"SELECT {_CHANGE_COLUMNS} FROM card_revision_pick_changes "
        "WHERE revision_id = ? ORDER BY locked_line_id",
        (integer(revision_id, "revision_id", 1),),
    ).fetchall()
    return tuple(_change_from_row(row) for row in rows)


def get_card_refresh_revision(
    conn: sqlite3.Connection, revision_id: int
) -> CardRefreshRevision:
    row = conn.execute(
        f"SELECT {_REFRESH_COLUMNS} FROM card_refresh_revisions WHERE revision_id = ?",
        (integer(revision_id, "revision_id", 1),),
    ).fetchone()
    if row is None:
        raise DailyRefreshError(f"card revision has no refresh history: {revision_id}")
    return CardRefreshRevision(*row)


def _change_values(
    revision_id: int,
    prior: ContestPick,
    revised: ContestPick,
) -> tuple[object, ...]:
    if prior.locked_line_id != revised.locked_line_id:
        raise DailyRefreshError("revision picks must refer to the same locked line")
    return (
        revision_id,
        prior.locked_line_id,
        prior.id,
        revised.id,
        prior.model_prediction_id,
        revised.model_prediction_id,
        prior.selected_side,
        revised.selected_side,
        prior.confidence,
        revised.confidence,
        prior.rank,
        revised.rank,
        int(prior.is_top_five),
        int(revised.is_top_five),
        prior.fallback_code,
        revised.fallback_code,
        int(prior.selected_side != revised.selected_side),
        int(prior.confidence != revised.confidence),
        int(prior.rank != revised.rank),
        int(prior.is_top_five != revised.is_top_five),
        int(prior.model_prediction_id != revised.model_prediction_id),
        int(prior.fallback_code != revised.fallback_code),
    )


def _record_pick_changes(
    conn: sqlite3.Connection,
    revision: CardRevision,
) -> tuple[CardRevisionPickChange, ...]:
    prior = {
        pick.locked_line_id: pick
        for pick in list_contest_picks(conn, revision.prior_card_id)
    }
    revised = {
        pick.locked_line_id: pick
        for pick in list_contest_picks(conn, revision.revised_card_id)
    }
    if not prior or prior.keys() != revised.keys():
        raise DailyRefreshError(
            "both card versions must cover the exact same locked-line identities"
        )
    try:
        for locked_line_id in sorted(prior):
            requested = _change_values(
                revision.id,
                prior[locked_line_id],
                revised[locked_line_id],
            )
            row = conn.execute(
                f"SELECT {_CHANGE_COLUMNS} FROM card_revision_pick_changes "
                "WHERE revision_id = ? AND locked_line_id = ?",
                (revision.id, locked_line_id),
            ).fetchone()
            if row is not None:
                if tuple(row) != requested:
                    raise BusinessEntityConflictError(
                        "revision pick change has different immutable values"
                    )
                continue
            conn.execute(
                "INSERT INTO card_revision_pick_changes "
                f"({_CHANGE_COLUMNS}) VALUES ({', '.join('?' for _ in requested)})",
                requested,
            )
        return list_card_revision_pick_changes(conn, revision.id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("card revision pick change", exc) from exc


def _validate_change_source(
    *,
    change_type: str,
    prior: CardRunManifest,
    revised: CardRunManifest,
) -> None:
    if (
        prior.selection_policy_id != revised.selection_policy_id
        or prior.ranking_policy_id != revised.ranking_policy_id
    ):
        raise DailyRefreshError("midweek refreshes cannot change contest policies")
    if change_type != "data_correction" and (
        prior.locked_line_snapshot_sha256 != revised.locked_line_snapshot_sha256
    ):
        raise DailyRefreshError("daily refresh cannot change the locked-line snapshot")
    if change_type == "data_refresh":
        unchanged_logic = (
            prior.model_name,
            prior.model_version,
            prior.feature_schema_version,
            prior.configuration_version,
            prior.code_commit_sha,
        ) == (
            revised.model_name,
            revised.model_version,
            revised.feature_schema_version,
            revised.configuration_version,
            revised.code_commit_sha,
        )
        if not unchanged_logic:
            raise DailyRefreshError(
                "data refresh cannot change model logic or configuration"
            )
        if prior.adjustment_history_sha256 != revised.adjustment_history_sha256:
            raise DailyRefreshError(
                "data refresh cannot be combined with contextual adjustments"
            )
    elif change_type == "contextual_adjustment":
        if prior.model_run_id != revised.model_run_id:
            raise DailyRefreshError(
                "contextual adjustment cannot change the model run"
            )
        if prior.adjustment_history_sha256 == revised.adjustment_history_sha256:
            raise DailyRefreshError(
                "contextual adjustment requires new adjustment history"
            )


def _record_refresh_revision(
    conn: sqlite3.Connection,
    *,
    revision: CardRevision,
    refresh_policy: CardRefreshPolicy,
    refreshed_at: datetime,
    provenance: str,
) -> CardRefreshRevision:
    refreshed_at_value = utc_timestamp(refreshed_at, "refreshed_at")
    utc_value = datetime.fromisoformat(refreshed_at_value).astimezone(timezone.utc)
    requested = (
        revision.id,
        refresh_policy.id,
        utc_value.date().isoformat(),
        utc_value.isoweekday(),
        refresh_policy.timezone_name,
        refreshed_at_value,
        required_text(provenance, "provenance"),
    )
    try:
        row = conn.execute(
            f"SELECT {_REFRESH_COLUMNS} FROM card_refresh_revisions "
            "WHERE revision_id = ?",
            (revision.id,),
        ).fetchone()
        if row is not None:
            existing = CardRefreshRevision(*row)
            if tuple(row) != requested:
                raise BusinessEntityConflictError(
                    "card refresh revision has different immutable values"
                )
            return existing
        conn.execute(
            "INSERT INTO card_refresh_revisions "
            "(revision_id, refresh_policy_id, operating_date, operating_weekday, "
            "timezone_name, refreshed_at, provenance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            requested,
        )
        return get_card_refresh_revision(conn, revision.id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("card refresh revision", exc) from exc


def refresh_full_card(
    conn: sqlite3.Connection,
    *,
    prior_card_id: int,
    card_key: str,
    model_run_id: int,
    change_type: str,
    reason: str,
    author: str,
    provenance: str,
    refresh_policy: DailyRefreshPolicy,
    generated_at: datetime,
) -> DailyRefreshResult:
    """Create and audit the next immutable full-card version as one transaction."""
    prior_card = get_contest_card(
        conn, integer(prior_card_id, "prior_card_id", 1)
    )
    card_key = required_text(card_key, "card_key")
    model_run_id = integer(model_run_id, "model_run_id", 1)
    change_type = choice(
        change_type,
        "change_type",
        ("data_refresh", "contextual_adjustment", "bug_fix", "data_correction"),
    )
    reason = required_text(reason, "reason")
    author = required_text(author, "author")
    provenance = required_text(provenance, "provenance")
    refresh_policy = validate_daily_refresh_policy(refresh_policy)
    generated_at_value = utc_timestamp(generated_at, "generated_at")
    generation_time = datetime.fromisoformat(generated_at_value)
    if not timestamp_on_or_before(conn, prior_card.generated_at, generated_at_value):
        raise DailyRefreshError("refresh must follow the prior card generation")
    if prior_card.generated_at == generated_at_value:
        raise DailyRefreshError("refresh must be later than the prior card generation")
    if generation_time.isoweekday() not in (2, 3, 4, 5, 6):
        raise DailyRefreshError(
            "daily refreshes are allowed Tuesday through Saturday UTC"
        )
    if not timestamp_on_or_before(
        conn,
        refresh_policy.effective_at.isoformat(),
        prior_card.generated_at,
    ):
        raise DailyRefreshError(
            "refresh policy must be effective before the prior card"
        )

    existing = conn.execute(
        "SELECT id FROM contest_cards "
        "WHERE card_key = ? OR (contest_id = ? AND version = ?)",
        (card_key, prior_card.contest_id, prior_card.version + 1),
    ).fetchone()
    if existing is not None:
        existing_card = get_contest_card(conn, existing[0])
        if existing_card.generated_at != generated_at_value:
            raise BusinessEntityConflictError(
                "existing revised card has a different generation timestamp"
            )

    prior_manifest = get_card_run_manifest(conn, prior_card.id)
    selection_policy = full_card_policy_from_manifest(conn, prior_manifest)
    confidence_policy = confidence_policy_from_manifest(conn, prior_manifest)
    adjustment_policy = adjustment_policy_from_card(conn, prior_card.id)
    validate_full_card(
        conn,
        prior_card.id,
        policy=selection_policy,
        confidence_policy=confidence_policy,
        adjustment_policy=adjustment_policy,
    )

    revision_key = f"{prior_card.card_key}:revision:{prior_card.version + 1}"
    with atomic(conn):
        recorded_refresh_policy = register_daily_refresh_policy(conn, refresh_policy)
        revised_result = generate_full_card(
            conn,
            card_key=card_key,
            contest_id=prior_card.contest_id,
            model_run_id=model_run_id,
            version=prior_card.version + 1,
            policy=selection_policy,
            confidence_policy=confidence_policy,
            adjustment_policy=adjustment_policy,
            created_by=author,
            provenance=provenance,
            generated_at=generation_time,
        )
        revised_manifest = get_card_run_manifest(conn, revised_result.card.id)
        _validate_change_source(
            change_type=change_type,
            prior=prior_manifest,
            revised=revised_manifest,
        )
        revision = record_card_revision(
            conn,
            revision_key=revision_key,
            prior_card_id=prior_card.id,
            revised_card_id=revised_result.card.id,
            change_type=change_type,
            reason=reason,
            author=author,
            provenance=provenance,
            revised_at=generation_time,
        )
        changes = _record_pick_changes(conn, revision)
        refresh = _record_refresh_revision(
            conn,
            revision=revision,
            refresh_policy=recorded_refresh_policy,
            refreshed_at=generation_time,
            provenance=provenance,
        )
        return DailyRefreshResult(revision, refresh, revised_result, changes)
