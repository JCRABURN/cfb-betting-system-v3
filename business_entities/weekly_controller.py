"""Authoritative Tuesday-through-Saturday contest-card controller.

The controller composes the repository's existing immutable line, forecast,
adjustment, card, revision, and reproducibility services.  An official card is
an append-only publication envelope over a validated immutable card snapshot;
the legacy ``contest_cards.status`` value remains ``draft`` because older
migrations intentionally freeze that row before publication exists.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit, urlunsplit

from contest_lines import (
    Contest,
    ContestLineError,
    create_contest,
    list_effective_locked_lines,
    lock_contest_line,
)
from ingestion.custody import (
    FRESHNESS_POLICY_VERSION,
    SUPPORTED_DATA_TYPE_ORDER,
    CanonicalTeamResolver,
    FreshnessAssessment,
    assess_required_freshness,
)

from business_entities.adjustments import record_manual_adjustment
from business_entities.cards import (
    ContestCard,
    ContestPick,
    get_contest_card,
    list_contest_picks,
)
from business_entities.common import (
    SHA1,
    SHA256,
    BusinessEntityConflictError,
    BusinessEntityError,
    atomic,
    checksum,
    choice,
    integer,
    number,
    required_text,
    timestamp_on_or_before,
    translate_integrity,
    utc_timestamp,
)
from business_entities.contextual_adjustments import (
    ManualAdjustmentPolicy,
    adjustment_policy_from_card,
)
from business_entities.full_card import (
    FullCardResult,
    generate_full_card,
    inspect_full_card,
    locked_line_snapshot_sha256,
    validate_full_card,
)
from business_entities.modeling import (
    ModelRun,
    get_model_run,
    record_model_prediction,
    record_model_run,
)
from business_entities.ranking import ConfidenceRankingPolicy
from business_entities.refreshes import (
    DailyRefreshPolicy,
    DailyRefreshResult,
    refresh_full_card,
)
from business_entities.wagering import (
    SportsbookRecommendation,
    record_sportsbook_recommendation,
)
from business_entities.reproducibility import (
    CardRunManifest,
    FullCardPolicy,
    confidence_policy_from_manifest,
    full_card_policy_from_manifest,
    get_card_run_manifest,
)


EPA_ONLY_MODEL_NAME = "epa_only"
EPA_ONLY_MODEL_VERSION = "epa-only-linear-v1"
EPA_ONLY_FEATURE_SCHEMA_VERSION = "epa-differential-v1"
EPA_ONLY_CONFIGURATION_VERSION = "walk-forward-prior-seasons-v1"


class WeeklyControllerError(BusinessEntityError):
    """Raised when an authoritative weekly operation is incomplete or unsafe."""


class WeeklyControllerConflictError(WeeklyControllerError):
    """Raised when an immutable controller identity is reused differently."""


class DataRefreshHook(Protocol):
    """Provider-specific refresh adapter; it must use the M14 custody layer."""

    def __call__(
        self,
        conn: sqlite3.Connection,
        *,
        season: int,
        week: int,
        as_of: datetime,
    ) -> None: ...


@dataclass(frozen=True)
class RequiredSourcePolicy:
    data_type: str
    provider: str
    permitted_fallback_code: str


@dataclass(frozen=True)
class WeeklyControllerPolicy:
    policy_version: str
    authorized_contest_source: str
    required_sources: tuple[RequiredSourcePolicy, ...]
    effective_at: datetime
    created_by: str
    provenance: str


@dataclass(frozen=True)
class RecordedWeeklyControllerPolicy:
    id: int
    policy_version: str
    authorized_contest_source: str
    production_model_name: str
    production_model_version: str
    production_feature_schema_version: str
    production_configuration_version: str
    freshness_policy_version: str
    required_source_count: int
    effective_at: str
    created_by: str
    provenance: str


@dataclass(frozen=True)
class ContestLineInput:
    raw_home_team: str
    raw_away_team: str
    home_spread: float
    source_line_id: str
    total: float | None = None


@dataclass(frozen=True)
class FreshnessFallbackDecision:
    data_type: str
    fallback_code: str
    reason: str
    evidence: str
    provenance: str


@dataclass(frozen=True)
class ContextualAdjustmentInput:
    adjustment_key: str
    game_id: int
    category: str
    affected_side: str
    margin_adjustment: float
    confidence_adjustment: int
    reason: str
    evidence: str
    source: str
    author: str
    provenance: str


@dataclass(frozen=True)
class SportsbookNoBetInput:
    """Explicit no-bet advice; official contest picks are never wagers by default."""

    recommendation_key: str
    game_id: int
    policy_version: str
    reason_code: str
    provenance: str


@dataclass(frozen=True)
class TuesdayCardRequest:
    run_key: str
    publication_key: str
    contest_key: str
    contest_name: str
    source_contest_id: str
    season: int
    week: int
    expected_lined_game_count: int
    line_payload_sha256: str
    raw_payload_reference: str
    lines: tuple[ContestLineInput, ...]
    model_run_key: str
    code_commit_sha: str
    controller_policy: WeeklyControllerPolicy
    selection_policy: FullCardPolicy
    confidence_policy: ConfidenceRankingPolicy
    adjustment_policy: ManualAdjustmentPolicy
    freshness_fallbacks: tuple[FreshnessFallbackDecision, ...]
    contextual_adjustments: tuple[ContextualAdjustmentInput, ...]
    sportsbook_recommendations: tuple[SportsbookNoBetInput, ...]
    generated_at: datetime
    actor: str
    provenance: str


@dataclass(frozen=True)
class DailyRefreshRequest:
    run_key: str
    publication_key: str
    prior_publication_id: int
    model_run_key: str | None
    code_commit_sha: str
    change_type: str
    reason: str
    refresh_policy: DailyRefreshPolicy
    controller_policy: WeeklyControllerPolicy
    freshness_fallbacks: tuple[FreshnessFallbackDecision, ...]
    contextual_adjustments: tuple[ContextualAdjustmentInput, ...]
    sportsbook_recommendations: tuple[SportsbookNoBetInput, ...]
    generated_at: datetime
    actor: str
    provenance: str


@dataclass(frozen=True)
class WeeklyControllerRun:
    id: int
    run_key: str
    request_sha256: str
    controller_policy_id: int | None
    policy_version: str
    operation: str
    execution_mode: str
    contest_id: int | None
    prior_publication_id: int | None
    card_id: int | None
    requested_at: str
    completed_at: str
    status: str
    failure_reason: str | None
    actor: str
    provenance: str


@dataclass(frozen=True)
class ContestLineLockBatch:
    controller_run_id: int
    contest_id: int
    source: str
    source_contest_id: str | None
    raw_payload_reference: str
    payload_sha256: str
    expected_lined_game_count: int
    imported_line_count: int
    locked_line_count: int
    locked_line_snapshot_sha256: str
    captured_at: str
    provenance: str


@dataclass(frozen=True)
class CardSourceFreshness:
    card_id: int
    controller_run_id: int
    data_type: str
    provider: str | None
    state: str
    ingestion_run_id: int | None
    observed_at: str | None
    expires_at: str | None
    freshness_policy_version: str
    fallback_code: str | None
    fallback_reason: str | None
    fallback_evidence: str | None
    provenance: str


@dataclass(frozen=True)
class OfficialCardPublication:
    id: int
    publication_key: str
    controller_run_id: int
    card_id: int
    contest_id: int
    card_version: int
    published_at: str
    locked_line_snapshot_sha256: str
    publication_manifest_sha256: str
    expected_locked_line_count: int
    pick_count: int
    top_five_count: int
    fallback_pick_count: int
    provenance: str


@dataclass(frozen=True)
class OfficialCardInspection:
    publication: OfficialCardPublication
    controller_run: WeeklyControllerRun
    card: ContestCard
    picks: tuple[ContestPick, ...]
    manifest: CardRunManifest
    freshness: tuple[CardSourceFreshness, ...]
    sportsbook_recommendations: tuple[SportsbookRecommendation, ...]
    line_batch: ContestLineLockBatch
    completeness_report: object
    publication_manifest_matches: bool
    publication_counts_match: bool
    is_latest_official_version: bool

    @property
    def valid(self) -> bool:
        return (
            self.controller_run.status == "completed"
            and self.completeness_report.official_ready
            and self.publication_manifest_matches
            and self.publication_counts_match
        )


@dataclass(frozen=True)
class WeeklyControllerResult:
    run: WeeklyControllerRun
    publication: OfficialCardPublication
    card: FullCardResult
    freshness: tuple[CardSourceFreshness, ...]
    line_batch: ContestLineLockBatch
    persisted: bool
    replayed: bool


_POLICY_COLUMNS = (
    "id, policy_version, authorized_contest_source, production_model_name, "
    "production_model_version, production_feature_schema_version, "
    "production_configuration_version, "
    "freshness_policy_version, required_source_count, effective_at, created_by, provenance"
)
_RUN_COLUMNS = (
    "id, run_key, request_sha256, controller_policy_id, policy_version, operation, execution_mode, "
    "contest_id, prior_publication_id, card_id, requested_at, completed_at, status, "
    "failure_reason, actor, provenance"
)
_BATCH_COLUMNS = (
    "controller_run_id, contest_id, source, source_contest_id, raw_payload_reference, "
    "payload_sha256, expected_lined_game_count, imported_line_count, locked_line_count, "
    "locked_line_snapshot_sha256, captured_at, provenance"
)
_FRESHNESS_COLUMNS = (
    "card_id, controller_run_id, data_type, provider, state, ingestion_run_id, "
    "observed_at, expires_at, freshness_policy_version, fallback_code, fallback_reason, "
    "fallback_evidence, provenance"
)
_PUBLICATION_COLUMNS = (
    "id, publication_key, controller_run_id, card_id, contest_id, card_version, "
    "published_at, locked_line_snapshot_sha256, publication_manifest_sha256, "
    "expected_locked_line_count, pick_count, top_five_count, fallback_pick_count, provenance"
)


def _credential_free_reference(value: str) -> str:
    value = required_text(value, "raw_payload_reference").strip()
    split = urlsplit(value)
    if split.scheme or split.netloc:
        return urlunsplit((split.scheme, split.netloc, split.path, "", ""))
    return value.split("?", 1)[0].split("#", 1)[0]


def _validated_required_source(source: RequiredSourcePolicy) -> RequiredSourcePolicy:
    if not isinstance(source, RequiredSourcePolicy):
        raise WeeklyControllerError("required_sources must contain RequiredSourcePolicy values")
    return RequiredSourcePolicy(
        data_type=choice(
            source.data_type,
            "required_source.data_type",
            tuple(SUPPORTED_DATA_TYPE_ORDER),
        ),
        provider=required_text(source.provider, "required_source.provider"),
        permitted_fallback_code=required_text(
            source.permitted_fallback_code,
            "required_source.permitted_fallback_code",
        ),
    )


def validate_weekly_controller_policy(
    policy: WeeklyControllerPolicy,
) -> WeeklyControllerPolicy:
    if not isinstance(policy, WeeklyControllerPolicy):
        raise WeeklyControllerError("controller_policy must be a WeeklyControllerPolicy")
    required_sources = tuple(
        _validated_required_source(source) for source in policy.required_sources
    )
    if tuple(source.data_type for source in required_sources) != tuple(
        SUPPORTED_DATA_TYPE_ORDER
    ):
        raise WeeklyControllerError(
            "controller policy must require odds, injuries, weather, game_status, "
            "and contextual data in the locked deterministic order"
        )
    source = required_text(
        policy.authorized_contest_source, "authorized_contest_source"
    )
    if source.casefold() != "splashsports":
        raise WeeklyControllerError("the authorized contest source must be SplashSports")
    return WeeklyControllerPolicy(
        policy_version=required_text(policy.policy_version, "policy_version"),
        authorized_contest_source="SplashSports",
        required_sources=required_sources,
        effective_at=datetime.fromisoformat(
            utc_timestamp(policy.effective_at, "controller_policy.effective_at")
        ),
        created_by=required_text(policy.created_by, "controller_policy.created_by"),
        provenance=required_text(policy.provenance, "controller_policy.provenance"),
    )


def get_weekly_controller_policy(
    conn: sqlite3.Connection, policy_id: int
) -> RecordedWeeklyControllerPolicy:
    row = conn.execute(
        f"SELECT {_POLICY_COLUMNS} FROM weekly_controller_policies WHERE id = ?",
        (integer(policy_id, "policy_id", 1),),
    ).fetchone()
    if row is None:
        raise WeeklyControllerError(f"weekly controller policy does not exist: {policy_id}")
    return RecordedWeeklyControllerPolicy(*row)


def _get_policy_sources(
    conn: sqlite3.Connection, policy_id: int
) -> tuple[RequiredSourcePolicy, ...]:
    rows = conn.execute(
        "SELECT data_type, provider, permitted_fallback_code "
        "FROM weekly_controller_policy_sources WHERE controller_policy_id = ? "
        "ORDER BY source_order",
        (policy_id,),
    ).fetchall()
    return tuple(RequiredSourcePolicy(*row) for row in rows)


def register_weekly_controller_policy(
    conn: sqlite3.Connection, policy: WeeklyControllerPolicy
) -> RecordedWeeklyControllerPolicy:
    policy = validate_weekly_controller_policy(policy)
    requested = (
        policy.policy_version,
        policy.authorized_contest_source,
        EPA_ONLY_MODEL_NAME,
        EPA_ONLY_MODEL_VERSION,
        EPA_ONLY_FEATURE_SCHEMA_VERSION,
        EPA_ONLY_CONFIGURATION_VERSION,
        FRESHNESS_POLICY_VERSION,
        len(policy.required_sources),
        policy.effective_at.isoformat(),
        policy.created_by,
        policy.provenance,
    )
    try:
        with atomic(conn):
            row = conn.execute(
                f"SELECT {_POLICY_COLUMNS} FROM weekly_controller_policies "
                "WHERE policy_version = ?",
                (policy.policy_version,),
            ).fetchone()
            if row is not None:
                recorded = RecordedWeeklyControllerPolicy(*row)
                if tuple(row[1:]) != requested or _get_policy_sources(
                    conn, recorded.id
                ) != policy.required_sources:
                    raise BusinessEntityConflictError(
                        "weekly controller policy version has different immutable values"
                    )
                return recorded
            cursor = conn.execute(
                "INSERT INTO weekly_controller_policies "
                "(policy_version, authorized_contest_source, production_model_name, "
                "production_model_version, production_feature_schema_version, "
                "production_configuration_version, freshness_policy_version, "
                "required_source_count, effective_at, created_by, provenance) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                requested,
            )
            policy_id = int(cursor.lastrowid)
            for source_order, source in enumerate(policy.required_sources, start=1):
                conn.execute(
                    "INSERT INTO weekly_controller_policy_sources "
                    "(controller_policy_id, source_order, data_type, provider, "
                    "permitted_fallback_code) VALUES (?, ?, ?, ?, ?)",
                    (
                        policy_id,
                        source_order,
                        source.data_type,
                        source.provider,
                        source.permitted_fallback_code,
                    ),
                )
            return get_weekly_controller_policy(conn, policy_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("weekly controller policy", exc) from exc


def get_weekly_controller_run(
    conn: sqlite3.Connection, run_id: int
) -> WeeklyControllerRun:
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM weekly_controller_runs WHERE id = ?",
        (integer(run_id, "run_id", 1),),
    ).fetchone()
    if row is None:
        raise WeeklyControllerError(f"weekly controller run does not exist: {run_id}")
    return WeeklyControllerRun(*row)


def get_contest_line_lock_batch(
    conn: sqlite3.Connection, contest_id: int
) -> ContestLineLockBatch:
    row = conn.execute(
        f"SELECT {_BATCH_COLUMNS} FROM contest_line_lock_batches WHERE contest_id = ?",
        (integer(contest_id, "contest_id", 1),),
    ).fetchone()
    if row is None:
        raise WeeklyControllerError(f"contest has no authoritative line-lock batch: {contest_id}")
    return ContestLineLockBatch(*row)


def list_card_source_freshness(
    conn: sqlite3.Connection, card_id: int
) -> tuple[CardSourceFreshness, ...]:
    rows = conn.execute(
        f"SELECT {_FRESHNESS_COLUMNS} FROM card_source_freshness "
        "WHERE card_id = ? ORDER BY CASE data_type "
        "WHEN 'odds' THEN 1 WHEN 'injuries' THEN 2 WHEN 'weather' THEN 3 "
        "WHEN 'game_status' THEN 4 ELSE 5 END",
        (integer(card_id, "card_id", 1),),
    ).fetchall()
    return tuple(CardSourceFreshness(*row) for row in rows)


def get_official_card_publication(
    conn: sqlite3.Connection,
    *,
    publication_id: int | None = None,
    publication_key: str | None = None,
) -> OfficialCardPublication:
    if (publication_id is None) == (publication_key is None):
        raise WeeklyControllerError(
            "provide exactly one of publication_id or publication_key"
        )
    if publication_id is not None:
        where, value = "id", integer(publication_id, "publication_id", 1)
    else:
        where, value = "publication_key", required_text(
            publication_key, "publication_key"
        )
    row = conn.execute(
        f"SELECT {_PUBLICATION_COLUMNS} FROM official_card_publications "
        f"WHERE {where} = ?",
        (value,),
    ).fetchone()
    if row is None:
        raise WeeklyControllerError("official card publication does not exist")
    return OfficialCardPublication(*row)


def _canonical_json_sha256(payload: object) -> str:
    def encode_datetime(value: object) -> str:
        if isinstance(value, datetime):
            return utc_timestamp(value, "canonical timestamp")
        raise TypeError(f"unsupported canonical value: {type(value).__name__}")

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=encode_datetime,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _request_sha256(request: TuesdayCardRequest | DailyRefreshRequest) -> str:
    if not isinstance(request, (TuesdayCardRequest, DailyRefreshRequest)):
        raise WeeklyControllerError(
            "controller request must be TuesdayCardRequest or DailyRefreshRequest"
        )
    return _canonical_json_sha256(
        {"request_type": type(request).__name__, "request": asdict(request)}
    )


def _publication_manifest_sha256(
    *,
    card: ContestCard,
    manifest: CardRunManifest,
    picks: tuple[ContestPick, ...],
    freshness: tuple[CardSourceFreshness, ...],
    sportsbook_recommendations: tuple[SportsbookRecommendation, ...],
    policy_version: str,
) -> str:
    return _canonical_json_sha256(
        {
            "card": asdict(card),
            "manifest": asdict(manifest),
            "picks": [asdict(pick) for pick in picks],
            "freshness": [asdict(item) for item in freshness],
            "sportsbook_recommendations": [
                asdict(item) for item in sportsbook_recommendations
            ],
            "weekly_controller_policy_version": policy_version,
        }
    )


def _validate_line_input(line: ContestLineInput) -> ContestLineInput:
    if not isinstance(line, ContestLineInput):
        raise WeeklyControllerError("lines must contain ContestLineInput values")
    spread = number(line.home_spread, "line.home_spread")
    total = None if line.total is None else number(line.total, "line.total")
    if total is not None and total < 0:
        raise WeeklyControllerError("line.total cannot be negative")
    return ContestLineInput(
        raw_home_team=required_text(line.raw_home_team, "line.raw_home_team"),
        raw_away_team=required_text(line.raw_away_team, "line.raw_away_team"),
        home_spread=spread,
        source_line_id=required_text(line.source_line_id, "line.source_line_id"),
        total=total,
    )


def _resolve_game(
    conn: sqlite3.Connection,
    *,
    resolver: CanonicalTeamResolver,
    provider: str,
    line: ContestLineInput,
    season: int,
    week: int,
) -> tuple[int, str, str]:
    home = resolver.resolve(provider, line.raw_home_team)
    away = resolver.resolve(provider, line.raw_away_team)
    for side, resolution in (("home", home), ("away", away)):
        if resolution.status != "resolved" or resolution.canonical_name is None:
            detail = ",".join(resolution.candidates) or "none"
            raise WeeklyControllerError(
                f"{side} team normalization is {resolution.status}: "
                f"{resolution.raw_name}; candidates={detail}"
            )
    if home.canonical_name == away.canonical_name:
        raise WeeklyControllerError("one line cannot contain the same canonical team twice")
    rows = conn.execute(
        "SELECT game_id FROM games WHERE season = ? AND week = ? "
        "AND home_team = ? AND away_team = ? ORDER BY game_id",
        (season, week, home.canonical_name, away.canonical_name),
    ).fetchall()
    if len(rows) == 1:
        return int(rows[0][0]), home.canonical_name, away.canonical_name
    reversed_row = conn.execute(
        "SELECT game_id FROM games WHERE season = ? AND week = ? "
        "AND home_team = ? AND away_team = ? LIMIT 1",
        (season, week, away.canonical_name, home.canonical_name),
    ).fetchone()
    if reversed_row is not None:
        raise WeeklyControllerError(
            f"authorized line reverses canonical home/away orientation for game {reversed_row[0]}"
        )
    if not rows:
        raise WeeklyControllerError(
            "authorized lined matchup has no canonical FBS game mapping: "
            f"{home.canonical_name} vs {away.canonical_name}"
        )
    raise WeeklyControllerError(
        "authorized lined matchup maps to multiple canonical games: "
        f"{home.canonical_name} vs {away.canonical_name}"
    )


def _lock_tuesday_lines(
    conn: sqlite3.Connection,
    *,
    contest: Contest,
    request: TuesdayCardRequest,
    source: str,
    generated_at: datetime,
) -> tuple[int, str]:
    lines = tuple(_validate_line_input(line) for line in request.lines)
    expected = integer(
        request.expected_lined_game_count, "expected_lined_game_count", 1
    )
    if len(lines) != expected:
        raise WeeklyControllerError(
            "authorized line batch count does not match expected lined FBS game count"
        )
    resolver = CanonicalTeamResolver.from_connection(conn)
    seen_matchups: set[tuple[str, str]] = set()
    seen_source_ids: set[str] = set()
    resolved_lines: list[tuple[int, str, str, ContestLineInput]] = []
    for line in lines:
        game_id, home, away = _resolve_game(
            conn,
            resolver=resolver,
            provider=source,
            line=line,
            season=request.season,
            week=request.week,
        )
        matchup = tuple(sorted((home.casefold(), away.casefold())))
        if matchup in seen_matchups or line.source_line_id in seen_source_ids:
            raise WeeklyControllerError(
                "authorized line batch contains a duplicate matchup or source line id"
            )
        seen_matchups.add(matchup)
        seen_source_ids.add(line.source_line_id)
        resolved_lines.append((game_id, home, away, line))
    created_count = 0
    for game_id, home, away, line in sorted(
        resolved_lines, key=lambda item: (item[0], item[3].source_line_id)
    ):
        result = lock_contest_line(
            conn,
            contest_id=contest.id,
            game_id=game_id,
            raw_home_team=line.raw_home_team,
            raw_away_team=line.raw_away_team,
            normalized_home_team=home,
            normalized_away_team=away,
            home_spread=line.home_spread,
            total=line.total,
            source=source,
            source_line_id=line.source_line_id,
            provenance=(
                f"{request.provenance};controller_run_key={request.run_key};"
                f"source_line_id={line.source_line_id}"
            ),
            payload_sha256=request.line_payload_sha256,
            locked_at=generated_at,
        )
        if not result.created:
            raise WeeklyControllerError(
                f"contest line {result.line.id} is already locked; relocks are rejected"
            )
        created_count += 1
    locked = list_effective_locked_lines(conn, contest.id, as_of=generated_at)
    if created_count != expected or len(locked) != expected:
        raise WeeklyControllerError("line locking did not produce the complete expected set")
    return created_count, locked_line_snapshot_sha256(locked)


def _epa_package_valid(package: dict[str, object]) -> bool:
    try:
        values = (
            package["home_stats"]["offense_epa_play"],
            package["home_stats"]["defense_epa_play"],
            package["away_stats"]["offense_epa_play"],
            package["away_stats"]["defense_epa_play"],
        )
        return all(
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(float(value))
            for value in values
        )
    except (KeyError, TypeError):
        return False


def run_epa_only_model(
    conn: sqlite3.Connection,
    *,
    contest_id: int,
    model_run_key: str,
    code_commit_sha: str,
    generated_at: datetime,
    provenance: str,
) -> ModelRun:
    """Run only the locked EPA baseline; missing inputs create explicit skips."""
    from models import backtest_harness as harness
    from models import baseline_epa

    contest_id = integer(contest_id, "contest_id", 1)
    model_run_key = required_text(model_run_key, "model_run_key")
    code_commit_sha = checksum(code_commit_sha, "code_commit_sha", SHA1)
    lines = list_effective_locked_lines(conn, contest_id, as_of=generated_at)
    if not lines:
        raise WeeklyControllerError("EPA run requires at least one locked line")
    season = lines[0].season
    training_seasons = tuple(harness.available_seasons_before(conn, season))
    training_rows: list[tuple[float, ...]] = []
    training_targets: list[float] = []
    training_error: str | None = None
    try:
        rows, targets = harness.build_training_set(
            conn, baseline_epa.epa_differential, training_seasons
        )
        training_rows = [tuple(float(value) for value in row) for row in rows]
        training_targets = [float(value) for value in targets]
    except (TypeError, ValueError, ArithmeticError):
        training_error = "missing_or_invalid_training_inputs"

    coefficients: tuple[float, ...] | None = None
    intercept: float | None = None
    if training_rows and training_error is None:
        try:
            fitted_intercept, fitted = harness.fit_multilinear(
                training_rows, training_targets
            )
            intercept = float(fitted_intercept)
            coefficients = tuple(float(value) for value in fitted)
        except (TypeError, ValueError, ArithmeticError):
            training_error = "epa_fit_unavailable"

    targets: list[tuple[object, dict[str, object] | None, str | None]] = []
    for line in lines:
        game = conn.execute(
            "SELECT home_team, away_team, start_date FROM games WHERE game_id = ?",
            (line.game_id,),
        ).fetchone()
        if game is None or game[2] is None:
            targets.append((line, None, "missing_game_or_kickoff"))
            continue
        package = harness.get_pregame_stats(
            conn, game[0], game[1], line.season, line.week, game[2]
        )
        if package is None or not _epa_package_valid(package):
            targets.append((line, None, "missing_point_in_time_epa"))
            continue
        targets.append((line, package, None))

    data_snapshot_sha256 = _canonical_json_sha256(
        {
            "model": EPA_ONLY_MODEL_NAME,
            "model_version": EPA_ONLY_MODEL_VERSION,
            "training_seasons": training_seasons,
            "training_rows": training_rows,
            "training_targets": training_targets,
            "training_error": training_error,
            "targets": [
                {
                    "locked_line_id": line.locked_line_id,
                    "game_id": line.game_id,
                    "package": package,
                    "skip_reason": skip_reason,
                }
                for line, package, skip_reason in targets
            ],
        }
    )
    skipped = [
        f"{line.game_id}:{skip_reason or training_error}"
        for line, package, skip_reason in targets
        if package is None or coefficients is None or intercept is None
    ]
    run = record_model_run(
        conn,
        run_key=model_run_key,
        model_name=EPA_ONLY_MODEL_NAME,
        model_version=EPA_ONLY_MODEL_VERSION,
        feature_schema_version=EPA_ONLY_FEATURE_SCHEMA_VERSION,
        configuration_version=EPA_ONLY_CONFIGURATION_VERSION,
        code_commit_sha=code_commit_sha,
        data_snapshot_sha256=data_snapshot_sha256,
        status="completed",
        generated_at=generated_at,
        provenance=(
            f"{provenance};model=epa_only;training_seasons="
            f"{','.join(str(item) for item in training_seasons) or 'none'};"
            f"training_rows={len(training_rows)};skipped={','.join(skipped) or 'none'}"
        ),
    )
    if coefficients is None or intercept is None:
        return run
    for line, package, skip_reason in targets:
        if package is None or skip_reason is not None or line.game_id is None:
            continue
        predicted_margin = baseline_epa.predict_margin(package, intercept, coefficients)
        record_model_prediction(
            conn,
            prediction_key=f"{model_run_key}:game:{line.game_id}",
            model_run_id=run.id,
            game_id=line.game_id,
            predicted_home_margin=predicted_margin,
            uncertainty_points=None,
            entry_locked_line_id=line.locked_line_id,
            generated_at=generated_at,
            provenance=(
                f"{provenance};model=epa_only;locked_line_id={line.locked_line_id};"
                f"training_snapshot_sha256={data_snapshot_sha256}"
            ),
        )
    return run


def _apply_contextual_adjustments(
    conn: sqlite3.Connection,
    *,
    model_run_id: int,
    adjustments: tuple[ContextualAdjustmentInput, ...],
    recorded_at: datetime,
) -> None:
    predictions = {
        int(game_id): int(prediction_id)
        for prediction_id, game_id in conn.execute(
            "SELECT id, game_id FROM model_predictions WHERE model_run_id = ?",
            (model_run_id,),
        )
    }
    for adjustment in adjustments:
        if not isinstance(adjustment, ContextualAdjustmentInput):
            raise WeeklyControllerError(
                "contextual_adjustments must contain ContextualAdjustmentInput values"
            )
        game_id = integer(adjustment.game_id, "adjustment.game_id", 1)
        prediction_id = predictions.get(game_id)
        if prediction_id is None:
            raise WeeklyControllerError(
                f"contextual adjustment targets game {game_id} without an EPA prediction"
            )
        record_manual_adjustment(
            conn,
            adjustment_key=adjustment.adjustment_key,
            model_prediction_id=prediction_id,
            category=adjustment.category,
            affected_side=adjustment.affected_side,
            margin_adjustment=adjustment.margin_adjustment,
            confidence_adjustment=adjustment.confidence_adjustment,
            reason=adjustment.reason,
            evidence=adjustment.evidence,
            source=adjustment.source,
            author=adjustment.author,
            provenance=adjustment.provenance,
            recorded_at=recorded_at,
        )


def _record_sportsbook_no_bet_recommendations(
    conn: sqlite3.Connection,
    *,
    card_result: FullCardResult,
    recommendations: tuple[SportsbookNoBetInput, ...],
    generated_at: datetime,
) -> tuple[SportsbookRecommendation, ...]:
    lines = {
        line.locked_line_id: line
        for line in list_effective_locked_lines(
            conn, card_result.card.contest_id, as_of=generated_at
        )
    }
    picks_by_game = {
        lines[pick.locked_line_id].game_id: pick
        for pick in card_result.picks
        if lines[pick.locked_line_id].game_id is not None
    }
    recorded: list[SportsbookRecommendation] = []
    seen_games: set[int] = set()
    for recommendation in recommendations:
        if not isinstance(recommendation, SportsbookNoBetInput):
            raise WeeklyControllerError(
                "sportsbook_recommendations must contain SportsbookNoBetInput values"
            )
        game_id = integer(recommendation.game_id, "recommendation.game_id", 1)
        if game_id in seen_games:
            raise WeeklyControllerError(
                f"duplicate sportsbook recommendation for game {game_id}"
            )
        seen_games.add(game_id)
        pick = picks_by_game.get(game_id)
        if pick is None or pick.model_prediction_id is None:
            raise WeeklyControllerError(
                f"sportsbook no-bet advice requires a model-backed pick for game {game_id}"
            )
        recorded.append(
            record_sportsbook_recommendation(
                conn,
                recommendation_key=recommendation.recommendation_key,
                model_prediction_id=pick.model_prediction_id,
                contest_pick_id=pick.id,
                decision="no_bet",
                policy_version=recommendation.policy_version,
                reason_code=recommendation.reason_code,
                provenance=recommendation.provenance,
                generated_at=generated_at,
            )
        )
    return tuple(recorded)


def _list_card_sportsbook_recommendations(
    conn: sqlite3.Connection, card_id: int
) -> tuple[SportsbookRecommendation, ...]:
    rows = conn.execute(
        "SELECT recommendation.id, recommendation.recommendation_key, "
        "recommendation.model_prediction_id, recommendation.contest_pick_id, "
        "recommendation.market_line_id, recommendation.decision, "
        "recommendation.recommended_side, recommendation.offered_price, "
        "recommendation.expected_value, recommendation.stake_units, "
        "recommendation.policy_version, recommendation.reason_code, "
        "recommendation.generated_at, recommendation.provenance "
        "FROM sportsbook_recommendations AS recommendation "
        "JOIN contest_picks AS pick ON pick.id = recommendation.contest_pick_id "
        "WHERE pick.card_id = ? ORDER BY pick.locked_line_id, recommendation.id",
        (card_id,),
    ).fetchall()
    return tuple(SportsbookRecommendation(*row) for row in rows)


def _evaluate_freshness(
    conn: sqlite3.Connection,
    *,
    policy: WeeklyControllerPolicy,
    as_of: datetime,
    fallbacks: tuple[FreshnessFallbackDecision, ...],
) -> tuple[tuple[FreshnessAssessment, FreshnessFallbackDecision | None], ...]:
    policy = validate_weekly_controller_policy(policy)
    fallback_by_type: dict[str, FreshnessFallbackDecision] = {}
    for fallback in fallbacks:
        if not isinstance(fallback, FreshnessFallbackDecision):
            raise WeeklyControllerError(
                "freshness_fallbacks must contain FreshnessFallbackDecision values"
            )
        data_type = choice(
            fallback.data_type, "fallback.data_type", tuple(SUPPORTED_DATA_TYPE_ORDER)
        )
        if data_type in fallback_by_type:
            raise WeeklyControllerError(f"duplicate freshness fallback: {data_type}")
        fallback_by_type[data_type] = replace(
            fallback,
            data_type=data_type,
            fallback_code=required_text(fallback.fallback_code, "fallback_code"),
            reason=required_text(fallback.reason, "fallback.reason"),
            evidence=required_text(fallback.evidence, "fallback.evidence"),
            provenance=required_text(fallback.provenance, "fallback.provenance"),
        )
    required_by_type = {source.data_type: source for source in policy.required_sources}
    assessments = assess_required_freshness(
        conn,
        as_of=as_of,
        required_data_types=tuple(required_by_type),
        provider_by_data_type={
            data_type: source.provider for data_type, source in required_by_type.items()
        },
    )
    evaluated: list[tuple[FreshnessAssessment, FreshnessFallbackDecision | None]] = []
    for assessment in assessments:
        fallback = fallback_by_type.pop(assessment.data_type, None)
        required = required_by_type[assessment.data_type]
        if assessment.state == "current":
            if fallback is not None:
                raise WeeklyControllerError(
                    f"current source cannot record a fallback: {assessment.data_type}"
                )
        elif fallback is None:
            raise WeeklyControllerError(
                f"{assessment.data_type} is {assessment.state}; an explicit permitted fallback is required"
            )
        elif fallback.fallback_code != required.permitted_fallback_code:
            raise WeeklyControllerError(
                f"unpermitted fallback for {assessment.data_type}: {fallback.fallback_code}"
            )
        evaluated.append((assessment, fallback))
    if fallback_by_type:
        raise WeeklyControllerError(
            "fallbacks were supplied for current or unrequired sources: "
            + ", ".join(sorted(fallback_by_type))
        )
    return tuple(evaluated)


def _record_completed_run(
    conn: sqlite3.Connection,
    *,
    run_key: str,
    request_sha256: str,
    policy: RecordedWeeklyControllerPolicy,
    operation: str,
    execution_mode: str,
    contest_id: int,
    prior_publication_id: int | None,
    card_id: int,
    requested_at: datetime,
    actor: str,
    provenance: str,
) -> WeeklyControllerRun:
    requested_at_value = utc_timestamp(requested_at, "requested_at")
    try:
        cursor = conn.execute(
            "INSERT INTO weekly_controller_runs "
            "(run_key, request_sha256, controller_policy_id, policy_version, operation, execution_mode, "
            "contest_id, prior_publication_id, card_id, requested_at, completed_at, "
            "status, failure_reason, actor, provenance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed', NULL, ?, ?)",
            (
                required_text(run_key, "run_key"),
                checksum(request_sha256, "request_sha256", SHA256),
                policy.id,
                policy.policy_version,
                operation,
                execution_mode,
                contest_id,
                prior_publication_id,
                card_id,
                requested_at_value,
                requested_at_value,
                required_text(actor, "actor"),
                required_text(provenance, "provenance"),
            ),
        )
        return get_weekly_controller_run(conn, int(cursor.lastrowid))
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("weekly controller run", exc) from exc


def _record_failed_run(
    conn: sqlite3.Connection,
    *,
    run_key: str,
    request_sha256: str,
    policy_version: str,
    operation: str,
    execution_mode: str,
    requested_at: datetime,
    actor: str,
    provenance: str,
    failure_reason: str,
) -> None:
    if conn.execute(
        "SELECT 1 FROM weekly_controller_runs WHERE run_key = ?", (run_key,)
    ).fetchone() is not None:
        return
    value = utc_timestamp(requested_at, "requested_at")
    conn.execute(
        "INSERT INTO weekly_controller_runs "
        "(run_key, request_sha256, controller_policy_id, policy_version, operation, execution_mode, "
        "contest_id, prior_publication_id, card_id, requested_at, completed_at, status, "
        "failure_reason, actor, provenance) "
        "VALUES (?, ?, NULL, ?, ?, ?, NULL, NULL, NULL, ?, ?, 'failed', ?, ?, ?)",
        (
            run_key,
            checksum(request_sha256, "request_sha256", SHA256),
            policy_version,
            operation,
            execution_mode,
            value,
            value,
            required_text(failure_reason, "failure_reason")[:2000],
            actor,
            provenance,
        ),
    )


def _record_freshness(
    conn: sqlite3.Connection,
    *,
    run: WeeklyControllerRun,
    card_id: int,
    evaluated: tuple[tuple[FreshnessAssessment, FreshnessFallbackDecision | None], ...],
    provenance: str,
) -> tuple[CardSourceFreshness, ...]:
    try:
        for assessment, fallback in evaluated:
            conn.execute(
                "INSERT INTO card_source_freshness "
                f"({_FRESHNESS_COLUMNS}) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    card_id,
                    run.id,
                    assessment.data_type,
                    assessment.provider,
                    assessment.state,
                    assessment.ingestion_run_id,
                    assessment.observed_at,
                    assessment.expires_at,
                    assessment.policy_version,
                    fallback.fallback_code if fallback is not None else None,
                    fallback.reason if fallback is not None else None,
                    fallback.evidence if fallback is not None else None,
                    (
                        f"{provenance};freshness_reason={assessment.reason};"
                        f"fallback_provenance="
                        f"{fallback.provenance if fallback is not None else 'none'}"
                    ),
                ),
            )
        return list_card_source_freshness(conn, card_id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("card source freshness", exc) from exc


def _assert_freshness_safe_fallbacks(
    picks: tuple[ContestPick, ...], freshness: tuple[CardSourceFreshness, ...]
) -> None:
    odds = next(item for item in freshness if item.data_type == "odds")
    if odds.state != "current" and any(
        (pick.fallback_code or "").startswith("market_") for pick in picks
    ):
        raise WeeklyControllerError(
            "non-current odds cannot support a current/opening market fallback; "
            "use the locked-line fallback policy"
        )


def _record_line_batch(
    conn: sqlite3.Connection,
    *,
    run: WeeklyControllerRun,
    contest: Contest,
    request: TuesdayCardRequest,
    source: str,
    locked_count: int,
    snapshot_sha256: str,
) -> ContestLineLockBatch:
    requested = (
        run.id,
        contest.id,
        source,
        request.source_contest_id,
        _credential_free_reference(request.raw_payload_reference),
        request.line_payload_sha256,
        request.expected_lined_game_count,
        len(request.lines),
        locked_count,
        snapshot_sha256,
        utc_timestamp(request.generated_at, "captured_at"),
        request.provenance,
    )
    try:
        conn.execute(
            "INSERT INTO contest_line_lock_batches "
            f"({_BATCH_COLUMNS}) VALUES ({', '.join('?' for _ in requested)})",
            requested,
        )
        return get_contest_line_lock_batch(conn, contest.id)
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("contest line-lock batch", exc) from exc


def _record_publication(
    conn: sqlite3.Connection,
    *,
    publication_key: str,
    run: WeeklyControllerRun,
    card_result: FullCardResult,
    freshness: tuple[CardSourceFreshness, ...],
    provenance: str,
) -> OfficialCardPublication:
    card = card_result.card
    picks = card_result.picks
    manifest = get_card_run_manifest(conn, card.id)
    sportsbook_recommendations = _list_card_sportsbook_recommendations(
        conn, card.id
    )
    manifest_sha256 = _publication_manifest_sha256(
        card=card,
        manifest=manifest,
        picks=picks,
        freshness=freshness,
        sportsbook_recommendations=sportsbook_recommendations,
        policy_version=run.policy_version,
    )
    requested = (
        required_text(publication_key, "publication_key"),
        run.id,
        card.id,
        card.contest_id,
        card.version,
        card.generated_at,
        card.locked_line_snapshot_sha256,
        manifest_sha256,
        card_result.report.expected_locked_line_count,
        len(picks),
        sum(pick.is_top_five for pick in picks),
        sum(pick.fallback_code is not None for pick in picks),
        required_text(provenance, "provenance"),
    )
    try:
        cursor = conn.execute(
            "INSERT INTO official_card_publications "
            "(publication_key, controller_run_id, card_id, contest_id, card_version, "
            "published_at, locked_line_snapshot_sha256, publication_manifest_sha256, "
            "expected_locked_line_count, pick_count, top_five_count, "
            "fallback_pick_count, provenance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            requested,
        )
        return get_official_card_publication(
            conn, publication_id=int(cursor.lastrowid)
        )
    except sqlite3.IntegrityError as exc:
        raise translate_integrity("official card publication", exc) from exc


def inspect_official_card(
    conn: sqlite3.Connection,
    *,
    publication_id: int | None = None,
    publication_key: str | None = None,
) -> OfficialCardInspection:
    """Inspect and reproduce an official publication without performing writes."""
    publication = get_official_card_publication(
        conn, publication_id=publication_id, publication_key=publication_key
    )
    run = get_weekly_controller_run(conn, publication.controller_run_id)
    card = get_contest_card(conn, publication.card_id)
    picks = list_contest_picks(conn, card.id)
    manifest = get_card_run_manifest(conn, card.id)
    freshness = list_card_source_freshness(conn, card.id)
    sportsbook_recommendations = _list_card_sportsbook_recommendations(
        conn, card.id
    )
    line_batch = get_contest_line_lock_batch(conn, card.contest_id)
    selection_policy = full_card_policy_from_manifest(conn, manifest)
    confidence_policy = confidence_policy_from_manifest(conn, manifest)
    adjustment_policy = adjustment_policy_from_card(conn, card.id)
    report = inspect_full_card(
        conn,
        card.id,
        policy=selection_policy,
        confidence_policy=confidence_policy,
        adjustment_policy=adjustment_policy,
    )
    expected_manifest = _publication_manifest_sha256(
        card=card,
        manifest=manifest,
        picks=picks,
        freshness=freshness,
        sportsbook_recommendations=sportsbook_recommendations,
        policy_version=run.policy_version,
    )
    expected_top_five = min(5, len(picks))
    counts_match = (
        publication.expected_locked_line_count == report.expected_locked_line_count
        and publication.pick_count == len(picks)
        and publication.top_five_count == expected_top_five
        and publication.fallback_pick_count
        == sum(pick.fallback_code is not None for pick in picks)
    )
    latest = conn.execute(
        "SELECT id FROM official_card_publications WHERE contest_id = ? "
        "ORDER BY card_version DESC, id DESC LIMIT 1",
        (card.contest_id,),
    ).fetchone()
    return OfficialCardInspection(
        publication=publication,
        controller_run=run,
        card=card,
        picks=picks,
        manifest=manifest,
        freshness=freshness,
        sportsbook_recommendations=sportsbook_recommendations,
        line_batch=line_batch,
        completeness_report=report,
        publication_manifest_matches=(
            publication.publication_manifest_sha256 == expected_manifest
        ),
        publication_counts_match=counts_match,
        is_latest_official_version=latest is not None and latest[0] == publication.id,
    )


def _existing_result(
    conn: sqlite3.Connection, run_key: str, request_sha256: str
) -> WeeklyControllerResult | None:
    row = conn.execute(
        f"SELECT {_RUN_COLUMNS} FROM weekly_controller_runs WHERE run_key = ?",
        (run_key,),
    ).fetchone()
    if row is None:
        return None
    run = WeeklyControllerRun(*row)
    if run.request_sha256 != request_sha256:
        raise WeeklyControllerConflictError(
            "controller run key was reused with a different request fingerprint"
        )
    if run.status != "completed":
        raise WeeklyControllerConflictError(
            f"controller run key records a prior failure: {run.failure_reason}"
        )
    publication_row = conn.execute(
        "SELECT id FROM official_card_publications WHERE controller_run_id = ?",
        (run.id,),
    ).fetchone()
    if publication_row is None:
        raise WeeklyControllerConflictError(
            "completed controller run has no official publication"
        )
    inspection = inspect_official_card(conn, publication_id=publication_row[0])
    if not inspection.valid:
        raise WeeklyControllerConflictError(
            "existing official publication no longer passes read-only inspection"
        )
    result = FullCardResult(
        inspection.card,
        inspection.picks,
        inspection.completeness_report,
    )
    return WeeklyControllerResult(
        run,
        inspection.publication,
        result,
        inspection.freshness,
        inspection.line_batch,
        persisted=run.execution_mode == "persist",
        replayed=True,
    )


def _validate_request_time(value: datetime, *, weekdays: tuple[int, ...]) -> datetime:
    moment = datetime.fromisoformat(utc_timestamp(value, "generated_at"))
    if moment.isoweekday() not in weekdays:
        allowed = ",".join(str(day) for day in weekdays)
        raise WeeklyControllerError(
            f"controller operation is not permitted on this UTC weekday; allowed={allowed}"
        )
    return moment


def _run_tuesday_persisted(
    conn: sqlite3.Connection,
    request: TuesdayCardRequest,
    *,
    data_refresh: DataRefreshHook | None,
    execution_mode: str,
) -> WeeklyControllerResult:
    request_sha256 = _request_sha256(request)
    existing = _existing_result(
        conn, required_text(request.run_key, "run_key"), request_sha256
    )
    if existing is not None:
        if existing.run.operation != "tuesday_lock":
            raise WeeklyControllerConflictError("run key belongs to another operation")
        return existing
    generation_time = _validate_request_time(request.generated_at, weekdays=(2,))
    policy = validate_weekly_controller_policy(request.controller_policy)
    if not timestamp_on_or_before(
        conn, policy.effective_at.isoformat(), generation_time.isoformat()
    ):
        raise WeeklyControllerError("controller policy is not effective on lock day")
    source = policy.authorized_contest_source
    if request.selection_policy.market_books:
        raise WeeklyControllerError(
            "official controller market fallbacks are disabled until legacy market "
            "rows have direct Milestone 14 custody lineage; use the locked-line fallback"
        )
    request = replace(
        request,
        line_payload_sha256=checksum(
            request.line_payload_sha256, "line_payload_sha256", SHA256
        ),
        code_commit_sha=checksum(request.code_commit_sha, "code_commit_sha", SHA1),
    )
    if data_refresh is not None:
        data_refresh(
            conn,
            season=integer(request.season, "season", 1869),
            week=integer(request.week, "week", 0),
            as_of=generation_time,
        )
    evaluated = _evaluate_freshness(
        conn,
        policy=policy,
        as_of=generation_time,
        fallbacks=request.freshness_fallbacks,
    )
    try:
        with atomic(conn):
            recorded_policy = register_weekly_controller_policy(conn, policy)
            contest = create_contest(
                conn,
                contest_key=required_text(request.contest_key, "contest_key"),
                name=required_text(request.contest_name, "contest_name"),
                season=integer(request.season, "season", 1869),
                week=integer(request.week, "week", 0),
                source=source,
                source_contest_id=required_text(
                    request.source_contest_id, "source_contest_id"
                ),
                provenance=request.provenance,
                created_at=generation_time,
            )
            locked_count, snapshot_sha256 = _lock_tuesday_lines(
                conn,
                contest=contest,
                request=request,
                source=source,
                generated_at=generation_time,
            )
            model_run = run_epa_only_model(
                conn,
                contest_id=contest.id,
                model_run_key=request.model_run_key,
                code_commit_sha=request.code_commit_sha,
                generated_at=generation_time,
                provenance=request.provenance,
            )
            _apply_contextual_adjustments(
                conn,
                model_run_id=model_run.id,
                adjustments=request.contextual_adjustments,
                recorded_at=generation_time,
            )
            card_result = generate_full_card(
                conn,
                card_key=f"{request.contest_key}:official:v1",
                contest_id=contest.id,
                model_run_id=model_run.id,
                version=1,
                policy=request.selection_policy,
                confidence_policy=request.confidence_policy,
                adjustment_policy=request.adjustment_policy,
                created_by=request.actor,
                provenance=request.provenance,
                generated_at=generation_time,
            )
            validate_full_card(
                conn,
                card_result.card.id,
                policy=request.selection_policy,
                confidence_policy=request.confidence_policy,
                adjustment_policy=request.adjustment_policy,
            )
            if card_result.card.locked_line_snapshot_sha256 != snapshot_sha256:
                raise WeeklyControllerError("card and lock-batch snapshots differ")
            _record_sportsbook_no_bet_recommendations(
                conn,
                card_result=card_result,
                recommendations=request.sportsbook_recommendations,
                generated_at=generation_time,
            )
            run = _record_completed_run(
                conn,
                run_key=request.run_key,
                request_sha256=request_sha256,
                policy=recorded_policy,
                operation="tuesday_lock",
                execution_mode=execution_mode,
                contest_id=contest.id,
                prior_publication_id=None,
                card_id=card_result.card.id,
                requested_at=generation_time,
                actor=request.actor,
                provenance=request.provenance,
            )
            line_batch = _record_line_batch(
                conn,
                run=run,
                contest=contest,
                request=request,
                source=source,
                locked_count=locked_count,
                snapshot_sha256=snapshot_sha256,
            )
            freshness = _record_freshness(
                conn,
                run=run,
                card_id=card_result.card.id,
                evaluated=evaluated,
                provenance=request.provenance,
            )
            _assert_freshness_safe_fallbacks(card_result.picks, freshness)
            publication = _record_publication(
                conn,
                publication_key=request.publication_key,
                run=run,
                card_result=card_result,
                freshness=freshness,
                provenance=request.provenance,
            )
            inspection = inspect_official_card(conn, publication_id=publication.id)
            if not inspection.valid:
                raise WeeklyControllerError(
                    "new official publication failed post-insert inspection"
                )
            return WeeklyControllerResult(
                run,
                publication,
                card_result,
                freshness,
                line_batch,
                persisted=execution_mode == "persist",
                replayed=False,
            )
    except Exception as exc:
        if execution_mode == "persist":
            try:
                _record_failed_run(
                    conn,
                    run_key=request.run_key,
                    request_sha256=request_sha256,
                    policy_version=policy.policy_version,
                    operation="tuesday_lock",
                    execution_mode=execution_mode,
                    requested_at=generation_time,
                    actor=request.actor,
                    provenance=request.provenance,
                    failure_reason=str(exc),
                )
            except sqlite3.DatabaseError:
                pass
        if isinstance(exc, WeeklyControllerError):
            raise
        if isinstance(exc, (BusinessEntityError, ContestLineError)):
            raise WeeklyControllerError(str(exc)) from exc
        raise WeeklyControllerError(str(exc)) from exc


def _clone_connection(conn: sqlite3.Connection) -> sqlite3.Connection:
    if conn.in_transaction:
        raise WeeklyControllerError(
            "dry-run requires a connection with no active transaction"
        )
    clone = sqlite3.connect(":memory:")
    clone.execute("PRAGMA foreign_keys = ON")
    conn.backup(clone)
    return clone


def run_tuesday_controller(
    conn: sqlite3.Connection,
    request: TuesdayCardRequest,
    *,
    dry_run: bool = False,
    data_refresh: DataRefreshHook | None = None,
) -> WeeklyControllerResult:
    """Lock, model, validate, and publish Tuesday's complete card."""
    if not dry_run:
        return _run_tuesday_persisted(
            conn, request, data_refresh=data_refresh, execution_mode="persist"
        )
    clone = _clone_connection(conn)
    try:
        result = _run_tuesday_persisted(
            clone, request, data_refresh=data_refresh, execution_mode="dry_run"
        )
        return replace(result, persisted=False)
    finally:
        clone.close()


def _run_daily_persisted(
    conn: sqlite3.Connection,
    request: DailyRefreshRequest,
    *,
    data_refresh: DataRefreshHook | None,
    execution_mode: str,
) -> WeeklyControllerResult:
    request_sha256 = _request_sha256(request)
    existing = _existing_result(
        conn, required_text(request.run_key, "run_key"), request_sha256
    )
    if existing is not None:
        if existing.run.operation != "daily_refresh":
            raise WeeklyControllerConflictError("run key belongs to another operation")
        return existing
    generation_time = _validate_request_time(request.generated_at, weekdays=(3, 4, 5, 6))
    prior = inspect_official_card(conn, publication_id=request.prior_publication_id)
    if not prior.valid or not prior.is_latest_official_version:
        raise WeeklyControllerError(
            "daily refresh must start from the latest valid official publication"
        )
    policy = validate_weekly_controller_policy(request.controller_policy)
    if policy.policy_version != prior.controller_run.policy_version:
        raise WeeklyControllerError("weekly controller policy cannot change midweek")
    contest_row = conn.execute(
        "SELECT season, week FROM contests WHERE id = ?", (prior.card.contest_id,)
    ).fetchone()
    if contest_row is None:
        raise WeeklyControllerError("prior official contest does not exist")
    if data_refresh is not None:
        data_refresh(
            conn,
            season=int(contest_row[0]),
            week=int(contest_row[1]),
            as_of=generation_time,
        )
    evaluated = _evaluate_freshness(
        conn,
        policy=policy,
        as_of=generation_time,
        fallbacks=request.freshness_fallbacks,
    )
    change_type = choice(
        request.change_type,
        "change_type",
        ("data_refresh", "contextual_adjustment", "bug_fix", "data_correction"),
    )
    try:
        with atomic(conn):
            recorded_policy = register_weekly_controller_policy(conn, policy)
            if change_type == "contextual_adjustment":
                if request.model_run_key is not None:
                    raise WeeklyControllerError(
                        "contextual-only refresh must reuse the prior EPA model run"
                    )
                model_run = get_model_run(conn, prior.card.model_run_id)
            else:
                if request.model_run_key is None:
                    raise WeeklyControllerError(
                        "data, bug-fix, and correction refreshes require a new EPA model run key"
                    )
                model_run = run_epa_only_model(
                    conn,
                    contest_id=prior.card.contest_id,
                    model_run_key=request.model_run_key,
                    code_commit_sha=checksum(
                        request.code_commit_sha, "code_commit_sha", SHA1
                    ),
                    generated_at=generation_time,
                    provenance=request.provenance,
                )
            if model_run.model_name != EPA_ONLY_MODEL_NAME:
                raise WeeklyControllerError("daily refresh must use the EPA-only baseline")
            _apply_contextual_adjustments(
                conn,
                model_run_id=model_run.id,
                adjustments=request.contextual_adjustments,
                recorded_at=generation_time,
            )
            refresh_result: DailyRefreshResult = refresh_full_card(
                conn,
                prior_card_id=prior.card.id,
                card_key=(
                    f"{conn.execute('SELECT contest_key FROM contests WHERE id = ?', (prior.card.contest_id,)).fetchone()[0]}:"
                    f"official:v{prior.card.version + 1}"
                ),
                model_run_id=model_run.id,
                change_type=change_type,
                reason=required_text(request.reason, "reason"),
                author=request.actor,
                provenance=request.provenance,
                refresh_policy=request.refresh_policy,
                generated_at=generation_time,
            )
            card_result = refresh_result.revised_card
            _record_sportsbook_no_bet_recommendations(
                conn,
                card_result=card_result,
                recommendations=request.sportsbook_recommendations,
                generated_at=generation_time,
            )
            run = _record_completed_run(
                conn,
                run_key=request.run_key,
                request_sha256=request_sha256,
                policy=recorded_policy,
                operation="daily_refresh",
                execution_mode=execution_mode,
                contest_id=card_result.card.contest_id,
                prior_publication_id=prior.publication.id,
                card_id=card_result.card.id,
                requested_at=generation_time,
                actor=request.actor,
                provenance=request.provenance,
            )
            freshness = _record_freshness(
                conn,
                run=run,
                card_id=card_result.card.id,
                evaluated=evaluated,
                provenance=request.provenance,
            )
            _assert_freshness_safe_fallbacks(card_result.picks, freshness)
            publication = _record_publication(
                conn,
                publication_key=request.publication_key,
                run=run,
                card_result=card_result,
                freshness=freshness,
                provenance=request.provenance,
            )
            inspection = inspect_official_card(conn, publication_id=publication.id)
            if not inspection.valid:
                raise WeeklyControllerError(
                    "refreshed official publication failed post-insert inspection"
                )
            return WeeklyControllerResult(
                run,
                publication,
                card_result,
                freshness,
                prior.line_batch,
                persisted=execution_mode == "persist",
                replayed=False,
            )
    except Exception as exc:
        if execution_mode == "persist":
            try:
                _record_failed_run(
                    conn,
                    run_key=request.run_key,
                    request_sha256=request_sha256,
                    policy_version=policy.policy_version,
                    operation="daily_refresh",
                    execution_mode=execution_mode,
                    requested_at=generation_time,
                    actor=request.actor,
                    provenance=request.provenance,
                    failure_reason=str(exc),
                )
            except sqlite3.DatabaseError:
                pass
        if isinstance(exc, WeeklyControllerError):
            raise
        if isinstance(exc, (BusinessEntityError, ContestLineError)):
            raise WeeklyControllerError(str(exc)) from exc
        raise WeeklyControllerError(str(exc)) from exc


def run_daily_controller(
    conn: sqlite3.Connection,
    request: DailyRefreshRequest,
    *,
    dry_run: bool = False,
    data_refresh: DataRefreshHook | None = None,
) -> WeeklyControllerResult:
    """Refresh and publish the next immutable Wednesday-Saturday version."""
    if not dry_run:
        return _run_daily_persisted(
            conn, request, data_refresh=data_refresh, execution_mode="persist"
        )
    clone = _clone_connection(conn)
    try:
        result = _run_daily_persisted(
            clone, request, data_refresh=data_refresh, execution_mode="dry_run"
        )
        return replace(result, persisted=False)
    finally:
        clone.close()
