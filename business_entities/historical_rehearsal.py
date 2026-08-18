"""Deterministic Milestone 16 historical lifecycle rehearsal.

The rehearsal reads the committed database through a read-only connection,
clones it into memory, and mutates only that disposable clone.  It replays a
six-game Saturday contest slate from 2024 Week 15 through lock day, four daily
official revisions, postgame audit, diagnostics, lessons, and policy-change
recommendations.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from contest_lines import list_effective_locked_lines
from ingestion import (
    AcceptedProviderRecord,
    IngestionRequest,
    ProviderIngestionService,
    payload_sha256,
)
from migrations.runner import apply_migrations

from business_entities.complete_audits import (
    PostgameAuditPolicy,
    PostgameAuditRequest,
    audit_contest_card,
)
from business_entities.contextual_adjustments import ManualAdjustmentPolicy
from business_entities.full_card import FullCardPolicy
from business_entities.ranking import ConfidenceRankingPolicy
from business_entities.refreshes import DailyRefreshPolicy
from business_entities.reproducibility import reproduce_card
from business_entities.weekly_controller import (
    ContestLineInput,
    ContextualAdjustmentInput,
    DailyRefreshRequest,
    RequiredSourcePolicy,
    SportsbookNoBetInput,
    TuesdayCardRequest,
    WeeklyControllerPolicy,
    inspect_official_card,
    run_daily_controller,
    run_tuesday_controller,
)
from business_entities.weekly_diagnostics import (
    WeeklyDiagnosticsPolicy,
    generate_weekly_diagnostics,
)


REHEARSAL_VERSION = "historical-rehearsal-v1"
HISTORICAL_SEASON = 2024
HISTORICAL_WEEK = 15
HISTORICAL_GAME_IDS = (
    401673463,
    401673464,
    401673465,
    401673467,
    401673469,
    401673470,
)
ADJUSTED_GAME_ID = 401673464
SOURCE_PROVIDER = "historical-rehearsal"
POLICY_AT = datetime(2024, 12, 2, 12, tzinfo=timezone.utc)
TUESDAY_AT = datetime(2024, 12, 3, 15, tzinfo=timezone.utc)
WEDNESDAY_AT = datetime(2024, 12, 4, 15, tzinfo=timezone.utc)
THURSDAY_AT = datetime(2024, 12, 5, 15, tzinfo=timezone.utc)
FRIDAY_AT = datetime(2024, 12, 6, 15, tzinfo=timezone.utc)
SATURDAY_AT = datetime(2024, 12, 7, 14, tzinfo=timezone.utc)
AUDITED_AT = datetime(2024, 12, 9, 15, tzinfo=timezone.utc)
DIAGNOSTICS_AT = datetime(2024, 12, 9, 16, tzinfo=timezone.utc)


class HistoricalRehearsalError(RuntimeError):
    """Raised when the historical lifecycle cannot be reproduced safely."""


@dataclass(frozen=True)
class HistoricalCardVersion:
    card_version: int
    publication_key: str
    generated_at: str
    model_name: str
    model_version: str
    feature_schema_version: str
    configuration_version: str
    data_snapshot_sha256: str
    selection_policy_version: str
    confidence_policy_version: str
    ranking_policy_version: str
    pick_count: int
    top_five_count: int
    fallback_pick_count: int
    source_freshness_count: int
    all_sources_current: bool
    adjustment_count: int
    publication_manifest_sha256: str
    reproduced_exactly: bool


@dataclass(frozen=True)
class HistoricalPickResult:
    game_id: int
    matchup: str
    locked_home_spread: float
    closing_home_spread: float
    selected_side: str
    confidence: int
    rank: int | None
    is_top_five: bool
    ats_result: str
    clv_points: float
    hook_outcome: str
    key_number_outcome: str
    raw_model_margin: float | None
    adjusted_model_margin: float | None
    manual_adjustment_effect: str


@dataclass(frozen=True)
class HistoricalPolicyRecommendation:
    confidence_level: int
    parameter_name: str
    current_value: float
    recommended_value: float
    sample_count: int
    observed_delta_percentage_points: float | None
    status: str
    owner_approval_required: bool


@dataclass(frozen=True)
class HistoricalRehearsalReport:
    rehearsal_version: str
    season: int
    week: int
    game_ids: tuple[int, ...]
    code_commit_sha: str
    source_database_sha256_before: str
    source_database_sha256_after: str
    source_database_unchanged: bool
    historical_fixture_sha256: str
    locked_line_snapshot_sha256: str
    locked_lines_unchanged: bool
    target_scores_hidden_during_forecast: bool
    finalization_method: str
    final_publication_key: str
    official_publication_count: int
    revision_count: int
    revision_pick_change_count: int
    card_versions: tuple[HistoricalCardVersion, ...]
    final_pick_count: int
    final_top_five_count: int
    audit_complete: bool
    audit_win_count: int
    audit_loss_count: int
    audit_push_count: int
    audited_pick_count: int
    clv_graded_count: int
    hook_classified_count: int
    key_number_classified_count: int
    manual_adjustment_count: int
    manual_adjustment_effects: tuple[str, ...]
    picks: tuple[HistoricalPickResult, ...]
    diagnostics_complete: bool
    diagnostic_segment_count: int
    lesson_count: int
    lessons: tuple[str, ...]
    recommendation_count: int
    candidate_recommendation_count: int
    policy_recommendations: tuple[HistoricalPolicyRecommendation, ...]
    policy_versions_unchanged: bool
    integrity_check: str
    foreign_key_violation_count: int
    live_api_calls: int
    authoritative_database_rows_changed: int
    rehearsal_sha256: str

    @property
    def successful(self) -> bool:
        return (
            self.source_database_unchanged
            and self.locked_lines_unchanged
            and self.target_scores_hidden_during_forecast
            and self.official_publication_count == 5
            and len(self.card_versions) == 5
            and all(version.reproduced_exactly for version in self.card_versions)
            and all(version.all_sources_current for version in self.card_versions)
            and all(version.model_name == "epa_only" for version in self.card_versions)
            and all(version.pick_count == len(self.game_ids) for version in self.card_versions)
            and all(version.top_five_count == 5 for version in self.card_versions)
            and all(version.fallback_pick_count == 0 for version in self.card_versions)
            and self.revision_count == 4
            and self.revision_pick_change_count == 4 * len(self.game_ids)
            and self.final_pick_count == len(self.game_ids)
            and self.final_top_five_count == 5
            and self.audit_complete
            and self.audited_pick_count == len(self.game_ids)
            and self.audit_win_count + self.audit_loss_count + self.audit_push_count
            == len(self.game_ids)
            and self.clv_graded_count == len(self.game_ids)
            and self.hook_classified_count == len(self.game_ids)
            and self.key_number_classified_count == len(self.game_ids)
            and self.manual_adjustment_count == 1
            and self.diagnostics_complete
            and self.diagnostic_segment_count == 26
            and self.lesson_count == 4
            and self.recommendation_count == 4
            and self.candidate_recommendation_count == 0
            and all(
                recommendation.status == "hold_insufficient_evidence"
                and recommendation.current_value == recommendation.recommended_value
                and not recommendation.owner_approval_required
                for recommendation in self.policy_recommendations
            )
            and self.policy_versions_unchanged
            and self.integrity_check == "ok"
            and self.foreign_key_violation_count == 0
            and self.live_api_calls == 0
            and self.authoritative_database_rows_changed == 0
        )


@dataclass(frozen=True)
class _HistoricalGame:
    game_id: int
    start_date: str
    home_team: str
    away_team: str
    home_points: int
    away_points: int
    neutral_site: bool


@dataclass(frozen=True)
class _ArchivedLine:
    row_id: int
    game_id: int
    book: str
    home_spread: float
    total: float | None
    source: str


def _canonical_sha256(value: object) -> str:
    def encode_dataclass(item: object) -> object:
        if is_dataclass(item) and not isinstance(item, type):
            return asdict(item)
        raise TypeError(f"unsupported canonical value: {type(item).__name__}")

    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
        default=encode_dataclass,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise HistoricalRehearsalError(f"historical timestamp is not UTC: {value}")
    return parsed.astimezone(timezone.utc)


def _clone_database(source_database: Path) -> tuple[sqlite3.Connection, str]:
    resolved = source_database.resolve()
    if not resolved.is_file():
        raise HistoricalRehearsalError(f"database does not exist: {resolved}")
    source_hash = _file_sha256(resolved)
    uri = f"file:{quote(resolved.as_posix(), safe='/:')}?mode=ro"
    source = sqlite3.connect(uri, uri=True)
    source.execute("PRAGMA query_only = ON")
    clone = sqlite3.connect(":memory:")
    clone.execute("PRAGMA foreign_keys = ON")
    try:
        source.backup(clone)
    finally:
        source.close()
    apply_migrations(clone)
    clone.commit()
    return clone, source_hash


def _load_games(conn: sqlite3.Connection) -> tuple[_HistoricalGame, ...]:
    placeholders = ",".join("?" for _ in HISTORICAL_GAME_IDS)
    rows = conn.execute(
        "SELECT game_id, start_date, home_team, away_team, home_points, "
        "away_points, neutral_site, completed, season, week FROM games "
        f"WHERE game_id IN ({placeholders}) ORDER BY game_id",
        HISTORICAL_GAME_IDS,
    ).fetchall()
    if tuple(row[0] for row in rows) != HISTORICAL_GAME_IDS:
        raise HistoricalRehearsalError(
            "the locked 2024 Week 15 historical game set is incomplete"
        )
    games = []
    for row in rows:
        if (
            row[1] is None
            or row[4] is None
            or row[5] is None
            or row[7] != 1
            or row[8] != HISTORICAL_SEASON
            or row[9] != HISTORICAL_WEEK
        ):
            raise HistoricalRehearsalError(
                f"historical game {row[0]} lacks a final score or week identity"
            )
        if _utc(row[1]) <= SATURDAY_AT:
            raise HistoricalRehearsalError(
                f"historical game {row[0]} kicks before the Saturday rehearsal refresh"
            )
        games.append(
            _HistoricalGame(
                int(row[0]),
                row[1],
                row[2],
                row[3],
                int(row[4]),
                int(row[5]),
                bool(row[6]),
            )
        )
    return tuple(games)


def _opening_line(conn: sqlite3.Connection, game_id: int) -> _ArchivedLine:
    row = conn.execute(
        "SELECT id, game_id, book, home_spread, total, source "
        "FROM betting_lines WHERE game_id = ? AND line_type = 'opening' "
        "AND home_spread IS NOT NULL "
        "ORDER BY CASE WHEN book = 'consensus' THEN 0 ELSE 1 END, book, id LIMIT 1",
        (game_id,),
    ).fetchone()
    if row is None:
        raise HistoricalRehearsalError(
            f"historical game {game_id} has no archived opening line"
        )
    return _ArchivedLine(
        int(row[0]),
        int(row[1]),
        row[2],
        float(row[3]),
        None if row[4] is None else float(row[4]),
        row[5],
    )


def _closing_line(
    conn: sqlite3.Connection, game_id: int, opening_book: str
) -> _ArchivedLine:
    row = conn.execute(
        "SELECT id, game_id, book, home_spread, total, source "
        "FROM betting_lines WHERE game_id = ? AND line_type = 'closing' "
        "AND home_spread IS NOT NULL ORDER BY CASE WHEN book = ? THEN 0 "
        "WHEN book = 'consensus' THEN 1 ELSE 2 END, book, id LIMIT 1",
        (game_id, opening_book),
    ).fetchone()
    if row is None:
        raise HistoricalRehearsalError(
            f"historical game {game_id} has no archived closing line"
        )
    return _ArchivedLine(
        int(row[0]),
        int(row[1]),
        row[2],
        float(row[3]),
        None if row[4] is None else float(row[4]),
        row[5],
    )


class _ReplayParser:
    version = "historical_rehearsal_source_v1"

    def parse(self, conn, resolver, provider, request, record_index, record):
        observed_at = _utc(record["observed_at"])
        return AcceptedProviderRecord(
            record_index=record_index,
            provider_record_id=record["id"],
            record_key=payload_sha256(record),
            observed_at=observed_at,
            parser_version=self.version,
            raw_record_sha256=payload_sha256(record),
        )


class _DailySourceReplay:
    def __init__(self) -> None:
        self.ingestion_run_ids: list[int] = []

    def __call__(
        self,
        conn: sqlite3.Connection,
        *,
        season: int,
        week: int,
        as_of: datetime,
    ) -> None:
        parser = _ReplayParser()
        service = ProviderIngestionService(clock=lambda: as_of)
        for data_type in ("odds", "injuries", "weather", "game_status", "contextual"):
            payload = {
                "records": [
                    {
                        "id": (
                            f"{REHEARSAL_VERSION}:{season}:{week}:"
                            f"{as_of.date().isoformat()}:{data_type}"
                        ),
                        "observed_at": as_of.isoformat(),
                    }
                ]
            }
            summary = service.ingest_payload(
                conn,
                IngestionRequest(
                    provider=SOURCE_PROVIDER,
                    endpoint=f"fixture://{REHEARSAL_VERSION}/{data_type}",
                    request_parameters={"season": season, "week": week},
                    requested_at=as_of,
                    parser_version=parser.version,
                    raw_payload_reference=(
                        f"fixture://{REHEARSAL_VERSION}/{season}/week-{week}/"
                        f"{as_of.date().isoformat()}/{data_type}.json"
                    ),
                    data_type=data_type,
                    expected_payload_sha256=payload_sha256(payload),
                ),
                payload,
                parser,
            )
            if summary.status != "completed" or summary.rows_accepted != 1:
                raise HistoricalRehearsalError(
                    f"{data_type} replay did not produce one current accepted record"
                )
            self.ingestion_run_ids.append(summary.ingestion_run_id)


def _controller_policy() -> WeeklyControllerPolicy:
    sources = tuple(
        RequiredSourcePolicy(
            data_type,
            SOURCE_PROVIDER,
            f"{REHEARSAL_VERSION}_{data_type}_fallback",
        )
        for data_type in ("odds", "injuries", "weather", "game_status", "contextual")
    )
    return WeeklyControllerPolicy(
        policy_version=f"{REHEARSAL_VERSION}-controller-policy",
        authorized_contest_source="SplashSports",
        required_sources=sources,
        effective_at=POLICY_AT,
        created_by="milestone-16-rehearsal",
        provenance=f"fixture://{REHEARSAL_VERSION}/controller-policy",
    )


def _selection_policy() -> FullCardPolicy:
    return FullCardPolicy(
        version=f"{REHEARSAL_VERSION}-selection-policy",
        market_books=(),
        model_tie_side="away",
        pickem_tiebreak_side="home",
    )


def _confidence_policy() -> ConfidenceRankingPolicy:
    return ConfidenceRankingPolicy(
        policy_key=f"{REHEARSAL_VERSION}-confidence-ranking",
        confidence_policy_version=f"{REHEARSAL_VERSION}-confidence-policy",
        ranking_policy_version=f"{REHEARSAL_VERSION}-ranking-policy",
        confidence_5_max_uncertainty=2.0,
        confidence_4_max_uncertainty=4.0,
        confidence_3_max_uncertainty=6.0,
        confidence_2_max_uncertainty=8.0,
        effective_at=POLICY_AT,
        created_by="milestone-16-rehearsal",
        provenance=f"fixture://{REHEARSAL_VERSION}/confidence-policy",
    )


def _adjustment_policy() -> ManualAdjustmentPolicy:
    return ManualAdjustmentPolicy(
        policy_version=f"{REHEARSAL_VERSION}-adjustment-policy",
        effective_at=POLICY_AT,
        created_by="milestone-16-rehearsal",
        provenance=f"fixture://{REHEARSAL_VERSION}/adjustment-policy",
    )


def _refresh_policy() -> DailyRefreshPolicy:
    return DailyRefreshPolicy(
        policy_version=f"{REHEARSAL_VERSION}-refresh-policy",
        effective_at=POLICY_AT,
        created_by="milestone-16-rehearsal",
        provenance=f"fixture://{REHEARSAL_VERSION}/refresh-policy",
    )


def _lock_fingerprint(conn: sqlite3.Connection, contest_id: int) -> tuple[tuple, ...]:
    return tuple(
        conn.execute(
            "SELECT id, contest_id, game_id, raw_home_team, raw_away_team, "
            "normalized_home_team, normalized_away_team, home_spread, total, "
            "locked_at, source, source_line_id, provenance, payload_sha256 "
            "FROM contest_locked_lines WHERE contest_id = ? ORDER BY id",
            (contest_id,),
        ).fetchall()
    )


def _insert_replay_closers(
    conn: sqlite3.Connection,
    games: tuple[_HistoricalGame, ...],
    closings: dict[int, _ArchivedLine],
) -> dict[int, int]:
    recorded: dict[int, int] = {}
    for game in games:
        closing = closings[game.game_id]
        captured_at = _utc(game.start_date) - timedelta(minutes=30)
        if captured_at <= SATURDAY_AT:
            raise HistoricalRehearsalError(
                f"closing capture for game {game.game_id} is not after finalization"
            )
        cursor = conn.execute(
            "INSERT INTO betting_lines "
            "(game_id, season, week, home_team, away_team, book, home_spread, "
            "total, line_type, source, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, "
            "'closing', ?, ?)",
            (
                game.game_id,
                HISTORICAL_SEASON,
                HISTORICAL_WEEK,
                game.home_team,
                game.away_team,
                f"replay:{closing.book}",
                closing.home_spread,
                closing.total,
                (
                    f"{REHEARSAL_VERSION}:archived-closing-row-{closing.row_id}:"
                    f"{closing.source}"
                ),
                captured_at.isoformat(),
            ),
        )
        recorded[game.game_id] = int(cursor.lastrowid)
    return recorded


def _report_sha256(payload: dict[str, object]) -> str:
    excluded = dict(payload)
    excluded.pop("rehearsal_sha256", None)
    return _canonical_sha256(excluded)


def run_historical_rehearsal(
    source_database: Path | str,
    *,
    code_commit_sha: str,
) -> HistoricalRehearsalReport:
    """Run the complete rehearsal against an isolated in-memory clone."""
    database = Path(source_database).resolve()
    conn, source_hash_before = _clone_database(database)
    try:
        games = _load_games(conn)
        openings = {game.game_id: _opening_line(conn, game.game_id) for game in games}
        closings = {
            game.game_id: _closing_line(
                conn, game.game_id, openings[game.game_id].book
            )
            for game in games
        }
        fixture_payload = [
            {
                "game": asdict(game),
                "opening": asdict(openings[game.game_id]),
                "closing": asdict(closings[game.game_id]),
            }
            for game in games
        ]
        fixture_hash = _canonical_sha256(fixture_payload)
        line_inputs = tuple(
            ContestLineInput(
                raw_home_team=game.home_team,
                raw_away_team=game.away_team,
                home_spread=openings[game.game_id].home_spread,
                total=openings[game.game_id].total,
                source_line_id=f"archived-opening-{openings[game.game_id].row_id}",
            )
            for game in games
        )
        line_payload_sha256 = _canonical_sha256(
            [asdict(line) for line in line_inputs]
        )

        conn.executemany(
            "UPDATE games SET home_points = NULL, away_points = NULL, completed = 0 "
            "WHERE game_id = ?",
            ((game.game_id,) for game in games),
        )
        conn.commit()
        hidden = all(
            row == (None, None, 0)
            for row in conn.execute(
                "SELECT home_points, away_points, completed FROM games WHERE game_id IN "
                f"({','.join('?' for _ in games)}) ORDER BY game_id",
                tuple(game.game_id for game in games),
            )
        )
        if not hidden:
            raise HistoricalRehearsalError(
                "target final scores were not hidden before prediction"
            )

        replay_sources = _DailySourceReplay()
        controller_policy = _controller_policy()
        selection_policy = _selection_policy()
        confidence_policy = _confidence_policy()
        adjustment_policy = _adjustment_policy()
        refresh_policy = _refresh_policy()
        provenance = f"fixture://{REHEARSAL_VERSION}/2024/week-15"
        tuesday = run_tuesday_controller(
            conn,
            TuesdayCardRequest(
                run_key=f"{REHEARSAL_VERSION}:tuesday",
                publication_key=f"{REHEARSAL_VERSION}:official:v1",
                contest_key=f"{REHEARSAL_VERSION}:contest",
                contest_name="Historical Rehearsal 2024 Week 15 Saturday Slate",
                source_contest_id=f"{REHEARSAL_VERSION}:2024:15:saturday",
                season=HISTORICAL_SEASON,
                week=HISTORICAL_WEEK,
                expected_lined_game_count=len(games),
                line_payload_sha256=line_payload_sha256,
                raw_payload_reference=(
                    f"fixture://{REHEARSAL_VERSION}/2024/week-15/"
                    "saturday-opening-lines.json"
                ),
                lines=line_inputs,
                model_run_key=f"{REHEARSAL_VERSION}:epa:tuesday",
                code_commit_sha=code_commit_sha,
                controller_policy=controller_policy,
                selection_policy=selection_policy,
                confidence_policy=confidence_policy,
                adjustment_policy=adjustment_policy,
                freshness_fallbacks=(),
                contextual_adjustments=(),
                sportsbook_recommendations=(),
                generated_at=TUESDAY_AT,
                actor="milestone-16-rehearsal",
                provenance=provenance,
            ),
            data_refresh=replay_sources,
        )
        conn.commit()
        initial_lock_fingerprint = _lock_fingerprint(
            conn, tuesday.card.card.contest_id
        )

        daily_results = []
        prior = tuesday
        for label, generated_at in (
            ("wednesday", WEDNESDAY_AT),
            ("thursday", THURSDAY_AT),
            ("friday", FRIDAY_AT),
        ):
            result = run_daily_controller(
                conn,
                DailyRefreshRequest(
                    run_key=f"{REHEARSAL_VERSION}:{label}",
                    publication_key=(
                        f"{REHEARSAL_VERSION}:official:"
                        f"v{prior.publication.card_version + 1}"
                    ),
                    prior_publication_id=prior.publication.id,
                    model_run_key=f"{REHEARSAL_VERSION}:epa:{label}",
                    code_commit_sha=code_commit_sha,
                    change_type="data_refresh",
                    reason=f"Controlled historical {label} point-in-time refresh.",
                    refresh_policy=refresh_policy,
                    controller_policy=controller_policy,
                    freshness_fallbacks=(),
                    contextual_adjustments=(),
                    sportsbook_recommendations=(),
                    generated_at=generated_at,
                    actor="milestone-16-rehearsal",
                    provenance=provenance,
                ),
                data_refresh=replay_sources,
            )
            conn.commit()
            daily_results.append(result)
            prior = result

        adjustment = ContextualAdjustmentInput(
            adjustment_key=f"{REHEARSAL_VERSION}:oregon-home-scenario",
            game_id=ADJUSTED_GAME_ID,
            category="other",
            affected_side="home",
            margin_adjustment=1.5,
            confidence_adjustment=1,
            reason=(
                "Controlled synthetic rehearsal scenario used only to exercise "
                "raw-versus-adjusted auditing; it is not historical evidence."
            ),
            evidence=(
                f"fixture://{REHEARSAL_VERSION}/synthetic-context/"
                "oregon-home-plus-1.5.json"
            ),
            source="synthetic-rehearsal-fixture",
            author="milestone-16-rehearsal",
            provenance=f"{provenance}/synthetic-adjustment",
        )
        saturday = run_daily_controller(
            conn,
            DailyRefreshRequest(
                run_key=f"{REHEARSAL_VERSION}:saturday-final",
                publication_key=f"{REHEARSAL_VERSION}:official:v5",
                prior_publication_id=prior.publication.id,
                model_run_key=None,
                code_commit_sha=code_commit_sha,
                change_type="contextual_adjustment",
                reason=(
                    "Controlled Saturday-morning final refresh with one explicit "
                    "synthetic adjustment scenario."
                ),
                refresh_policy=refresh_policy,
                controller_policy=controller_policy,
                freshness_fallbacks=(),
                contextual_adjustments=(adjustment,),
                sportsbook_recommendations=(
                    SportsbookNoBetInput(
                        recommendation_key=(
                            f"{REHEARSAL_VERSION}:oregon-explicit-no-bet"
                        ),
                        game_id=ADJUSTED_GAME_ID,
                        policy_version=f"{REHEARSAL_VERSION}:sportsbook-policy",
                        reason_code="synthetic_rehearsal_no_wager",
                        provenance=f"{provenance}/sportsbook-no-bet",
                    ),
                ),
                generated_at=SATURDAY_AT,
                actor="milestone-16-rehearsal",
                provenance=provenance,
            ),
            data_refresh=replay_sources,
        )
        conn.commit()
        daily_results.append(saturday)
        all_results = (tuesday, *daily_results)

        final_inspection = inspect_official_card(
            conn, publication_id=saturday.publication.id
        )
        if not final_inspection.valid or not final_inspection.is_latest_official_version:
            raise HistoricalRehearsalError(
                "Saturday publication is not the latest valid official card"
            )

        versions = []
        policy_versions = set()
        for result in all_results:
            inspection = inspect_official_card(
                conn, publication_id=result.publication.id
            )
            model_run_key = conn.execute(
                "SELECT run_key FROM model_runs WHERE id = ?",
                (inspection.card.model_run_id,),
            ).fetchone()[0]
            reproduced = reproduce_card(
                conn,
                card_key=inspection.card.card_key,
                model_run_key=model_run_key,
            )
            exact = (
                reproduced.card == inspection.card
                and reproduced.picks == inspection.picks
                and reproduced.report.official_ready
            )
            if not inspection.valid or not exact:
                raise HistoricalRehearsalError(
                    f"official card version {inspection.card.version} did not reproduce"
                )
            policy_versions.add(
                (
                    inspection.manifest.selection_policy_version,
                    inspection.manifest.confidence_policy_version,
                    inspection.manifest.ranking_policy_version,
                    inspection.controller_run.policy_version,
                )
            )
            versions.append(
                HistoricalCardVersion(
                    inspection.card.version,
                    inspection.publication.publication_key,
                    inspection.card.generated_at,
                    inspection.manifest.model_name,
                    inspection.manifest.model_version,
                    inspection.manifest.feature_schema_version,
                    inspection.manifest.configuration_version,
                    inspection.manifest.data_snapshot_sha256,
                    inspection.manifest.selection_policy_version,
                    inspection.manifest.confidence_policy_version,
                    inspection.manifest.ranking_policy_version,
                    len(inspection.picks),
                    sum(pick.is_top_five for pick in inspection.picks),
                    inspection.publication.fallback_pick_count,
                    len(inspection.freshness),
                    all(item.state == "current" for item in inspection.freshness),
                    inspection.manifest.adjustment_count,
                    inspection.publication.publication_manifest_sha256,
                    exact,
                )
            )

        conn.executemany(
            "UPDATE games SET home_points = ?, away_points = ?, completed = 1 "
            "WHERE game_id = ?",
            (
                (game.home_points, game.away_points, game.game_id)
                for game in games
            ),
        )
        closing_ids = _insert_replay_closers(conn, games, closings)
        conn.commit()

        line_by_game = {
            line.game_id: line
            for line in list_effective_locked_lines(
                conn, saturday.card.card.contest_id, as_of=SATURDAY_AT
            )
        }
        audit = audit_contest_card(
            conn,
            audit_run_key=f"{REHEARSAL_VERSION}:postgame-audit",
            card_id=saturday.card.card.id,
            audit_policy=PostgameAuditPolicy(
                policy_version=f"{REHEARSAL_VERSION}:postgame-audit-policy",
                effective_at=POLICY_AT,
                created_by="milestone-16-rehearsal",
                provenance=f"{provenance}/postgame-policy",
            ),
            requests_by_locked_line_id={
                line_by_game[game.game_id].locked_line_id: PostgameAuditRequest(
                    closing_ids[game.game_id]
                )
                for game in games
            },
            source="historical-score-and-closing-line-replay",
            provenance=f"{provenance}/postgame-audit",
            audited_at=AUDITED_AT,
        )
        conn.commit()
        diagnostics = generate_weekly_diagnostics(
            conn,
            diagnostic_run_key=f"{REHEARSAL_VERSION}:weekly-diagnostics",
            audit_run_id=audit.run.id,
            diagnostic_policy=WeeklyDiagnosticsPolicy(
                policy_version=f"{REHEARSAL_VERSION}:diagnostics-policy",
                minimum_recommendation_sample=5,
                minimum_ats_delta_percentage_points=10.0,
                confidence_threshold_step_points=0.5,
                effective_at=POLICY_AT,
                created_by="milestone-16-rehearsal",
                provenance=f"{provenance}/diagnostics-policy",
            ),
            source="historical-weekly-rehearsal",
            provenance=f"{provenance}/diagnostics",
            generated_at=DIAGNOSTICS_AT,
        )
        conn.commit()

        game_by_id = {game.game_id: game for game in games}
        picks = tuple(
            HistoricalPickResult(
                detail.game_id,
                (
                    f"{game_by_id[detail.game_id].away_team} at "
                    f"{game_by_id[detail.game_id].home_team}"
                ),
                detail.locked_home_spread,
                detail.closing_home_spread,
                detail.selected_side,
                detail.confidence,
                detail.rank,
                detail.is_top_five,
                detail.ats_result,
                detail.clv_points,
                detail.hook_outcome,
                detail.key_number_outcome,
                detail.raw_model_margin,
                detail.adjusted_model_margin,
                detail.manual_adjustment_effect,
            )
            for detail in audit.details
        )
        recommendations = tuple(
            HistoricalPolicyRecommendation(
                item.confidence_level,
                item.parameter_name,
                item.current_value,
                item.recommended_value,
                item.sample_count,
                item.observed_delta_percentage_points,
                item.recommendation_status,
                item.owner_approval_required,
            )
            for item in diagnostics.recommendations
        )
        final_lock_fingerprint = _lock_fingerprint(
            conn, tuesday.card.card.contest_id
        )
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_violations = tuple(conn.execute("PRAGMA foreign_key_check"))
        source_hash_after = _file_sha256(database)
        payload: dict[str, object] = {
            "rehearsal_version": REHEARSAL_VERSION,
            "season": HISTORICAL_SEASON,
            "week": HISTORICAL_WEEK,
            "game_ids": HISTORICAL_GAME_IDS,
            "code_commit_sha": code_commit_sha,
            "source_database_sha256_before": source_hash_before,
            "source_database_sha256_after": source_hash_after,
            "source_database_unchanged": source_hash_before == source_hash_after,
            "historical_fixture_sha256": fixture_hash,
            "locked_line_snapshot_sha256": tuesday.line_batch.locked_line_snapshot_sha256,
            "locked_lines_unchanged": initial_lock_fingerprint == final_lock_fingerprint,
            "target_scores_hidden_during_forecast": hidden,
            "finalization_method": "latest_valid_saturday_publication",
            "final_publication_key": saturday.publication.publication_key,
            "official_publication_count": conn.execute(
                "SELECT COUNT(*) FROM official_card_publications WHERE contest_id = ?",
                (tuesday.card.card.contest_id,),
            ).fetchone()[0],
            "revision_count": conn.execute(
                "SELECT COUNT(*) FROM card_revisions WHERE prior_card_id IN "
                "(SELECT id FROM contest_cards WHERE contest_id = ?)",
                (tuesday.card.card.contest_id,),
            ).fetchone()[0],
            "revision_pick_change_count": conn.execute(
                "SELECT COUNT(*) FROM card_revision_pick_changes AS change "
                "JOIN card_revisions AS revision ON revision.id = change.revision_id "
                "JOIN contest_cards AS card ON card.id = revision.revised_card_id "
                "WHERE card.contest_id = ?",
                (tuesday.card.card.contest_id,),
            ).fetchone()[0],
            "card_versions": tuple(versions),
            "final_pick_count": len(saturday.card.picks),
            "final_top_five_count": sum(
                pick.is_top_five for pick in saturday.card.picks
            ),
            "audit_complete": audit.report.complete,
            "audit_win_count": audit.report.win_count,
            "audit_loss_count": audit.report.loss_count,
            "audit_push_count": audit.report.push_count,
            "audited_pick_count": audit.report.audit_count,
            "clv_graded_count": sum(
                detail.closing_market_line_id is not None for detail in audit.details
            ),
            "hook_classified_count": sum(
                bool(detail.hook_outcome) for detail in audit.details
            ),
            "key_number_classified_count": sum(
                bool(detail.key_number_outcome) for detail in audit.details
            ),
            "manual_adjustment_count": sum(
                detail.manual_adjustment_count for detail in audit.details
            ),
            "manual_adjustment_effects": tuple(
                sorted(
                    {
                        detail.manual_adjustment_effect
                        for detail in audit.details
                        if detail.manual_adjustment_count
                    }
                )
            ),
            "picks": picks,
            "diagnostics_complete": diagnostics.report.complete,
            "diagnostic_segment_count": diagnostics.report.segment_count,
            "lesson_count": diagnostics.report.lesson_count,
            "lessons": tuple(lesson.narrative for lesson in diagnostics.lessons),
            "recommendation_count": diagnostics.report.recommendation_count,
            "candidate_recommendation_count": (
                diagnostics.report.candidate_recommendation_count
            ),
            "policy_recommendations": recommendations,
            "policy_versions_unchanged": len(policy_versions) == 1,
            "integrity_check": integrity,
            "foreign_key_violation_count": len(foreign_key_violations),
            "live_api_calls": 0,
            "authoritative_database_rows_changed": 0,
        }
        payload["rehearsal_sha256"] = _report_sha256(payload)
        report = HistoricalRehearsalReport(**payload)
        if not report.successful:
            raise HistoricalRehearsalError(
                "historical lifecycle completed but failed one or more acceptance gates"
            )
        return report
    finally:
        conn.close()
