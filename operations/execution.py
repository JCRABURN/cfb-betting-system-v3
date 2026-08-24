"""Production operation adapter that only orchestrates governed V3 services."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from business_entities.complete_audits import (
    PostgameAuditRequest,
    audit_contest_card,
)
from business_entities.live_sportsbook import evaluate_live_sportsbook_board
from business_entities.weekly_controller import (
    ContextualAdjustmentInput,
    ContestLineInput,
    DailyRefreshRequest,
    FreshnessFallbackDecision,
    SportsbookNoBetInput,
    TuesdayCardRequest,
    inspect_official_card,
    run_daily_controller,
    run_tuesday_controller,
)
from business_entities.weekly_diagnostics import generate_weekly_diagnostics

from operations.config import (
    ACTIVE_MODEL_NAME,
    ACTIVE_MODEL_VERSION,
    EXPECTED_REPOSITORY,
    ProductionSettings,
)
from operations.policies import load_registered_policy_set
from operations.preflight import ProductionPreflightReport, run_production_preflight
from operations.providers import ingest_provider_bundle, load_provider_bundle
from operations.weekly_config import WeeklyOperationConfiguration
from operations.writer_lock import ProductionWriterLock


EXECUTION_ADAPTER_VERSION = "v3-production-execution-adapter-v3"


class ProductionExecutionError(RuntimeError):
    """Raised when a guarded operation cannot complete without weakening controls."""


@dataclass(frozen=True)
class ProductionExecutionResult:
    adapter_version: str
    operation: str
    operation_key: str
    weekly_configuration_sha256: str
    execution_mode: str
    status: str
    replayed: bool
    source_database_sha256_before: str
    source_database_sha256_after: str
    source_database_unchanged: bool
    working_database_sha256_after: str
    backup_path: str | None
    backup_sha256: str | None
    provider_ingestion_run_ids: tuple[int, ...]
    controller_run_id: int | None
    publication_id: int | None
    card_id: int | None
    audit_run_id: int | None
    diagnostic_run_id: int | None
    pick_count: int | None
    top_five_count: int | None
    fallback_pick_count: int | None
    sportsbook_recommendation_count: int
    sportsbook_bet_count: int
    live_betting_board: tuple[dict[str, object], ...]
    wagers_placed: int
    completed_at: str
    result_sha256: str


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_no_sqlite_sidecars(path: Path) -> None:
    active = [
        sidecar.name
        for suffix in ("-wal", "-journal")
        if (sidecar := path.with_name(path.name + suffix)).exists()
    ]
    if active:
        raise ProductionExecutionError(
            "authoritative database has an active SQLite sidecar; stop all writers "
            "and recover it before staged execution"
        )


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProductionExecutionError(f"{field} must be non-empty text")
    return value.strip()


def _integer(value: object, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ProductionExecutionError(f"{field} must be an integer >= {minimum}")
    return value


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProductionExecutionError(f"{field} must be numeric")
    return float(value)


def _fallbacks(
    values: tuple[dict[str, object], ...] | tuple[object, ...],
) -> tuple[FreshnessFallbackDecision, ...]:
    result = []
    for index, raw in enumerate(values):
        if not isinstance(raw, dict):
            raw = dict(raw)  # type: ignore[arg-type]
        result.append(
            FreshnessFallbackDecision(
                data_type=_required_text(raw.get("data_type"), f"fallback[{index}].data_type"),
                fallback_code=_required_text(
                    raw.get("fallback_code"), f"fallback[{index}].fallback_code"
                ),
                reason=_required_text(raw.get("reason"), f"fallback[{index}].reason"),
                evidence=_required_text(raw.get("evidence"), f"fallback[{index}].evidence"),
                provenance=_required_text(
                    raw.get("provenance"), f"fallback[{index}].provenance"
                ),
            )
        )
    return tuple(result)


def _adjustments(
    values: tuple[dict[str, object], ...] | tuple[object, ...],
) -> tuple[ContextualAdjustmentInput, ...]:
    result = []
    for index, raw in enumerate(values):
        if not isinstance(raw, dict):
            raw = dict(raw)  # type: ignore[arg-type]
        result.append(
            ContextualAdjustmentInput(
                adjustment_key=_required_text(
                    raw.get("adjustment_key"), f"adjustment[{index}].adjustment_key"
                ),
                game_id=_integer(raw.get("game_id"), f"adjustment[{index}].game_id", 1),
                category=_required_text(raw.get("category"), f"adjustment[{index}].category"),
                affected_side=_required_text(
                    raw.get("affected_side"), f"adjustment[{index}].affected_side"
                ),
                margin_adjustment=_number(
                    raw.get("margin_adjustment"),
                    f"adjustment[{index}].margin_adjustment",
                ),
                confidence_adjustment=_integer(
                    raw.get("confidence_adjustment"),
                    f"adjustment[{index}].confidence_adjustment",
                    -100,
                ),
                reason=_required_text(raw.get("reason"), f"adjustment[{index}].reason"),
                evidence=_required_text(
                    raw.get("evidence"), f"adjustment[{index}].evidence"
                ),
                source=_required_text(raw.get("source"), f"adjustment[{index}].source"),
                author=_required_text(raw.get("author"), f"adjustment[{index}].author"),
                provenance=_required_text(
                    raw.get("provenance"), f"adjustment[{index}].provenance"
                ),
            )
        )
    return tuple(result)


def _no_bets(
    values: tuple[dict[str, object], ...] | tuple[object, ...],
) -> tuple[SportsbookNoBetInput, ...]:
    result = []
    for index, raw in enumerate(values):
        if not isinstance(raw, dict):
            raw = dict(raw)  # type: ignore[arg-type]
        result.append(
            SportsbookNoBetInput(
                recommendation_key=_required_text(
                    raw.get("recommendation_key"), f"recommendation[{index}].key"
                ),
                game_id=_integer(raw.get("game_id"), f"recommendation[{index}].game_id", 1),
                policy_version=_required_text(
                    raw.get("policy_version"), f"recommendation[{index}].policy_version"
                ),
                reason_code=_required_text(
                    raw.get("reason_code"), f"recommendation[{index}].reason_code"
                ),
                provenance=_required_text(
                    raw.get("provenance"), f"recommendation[{index}].provenance"
                ),
            )
        )
    return tuple(result)


def _manifest_lines(configuration: WeeklyOperationConfiguration) -> tuple[ContestLineInput, ...]:
    try:
        payload = json.loads(configuration.line_manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ProductionExecutionError("contest-line manifest cannot be read") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("lines"), list):
        raise ProductionExecutionError("contest-line manifest shape is invalid")
    if (
        payload.get("repository") != EXPECTED_REPOSITORY
        or payload.get("source") != "SplashSports"
        or payload.get("season") != configuration.season
        or payload.get("week") != configuration.week
    ):
        raise ProductionExecutionError("contest-line manifest identity is invalid")
    result = []
    for index, raw in enumerate(payload["lines"]):
        if not isinstance(raw, dict):
            raise ProductionExecutionError(f"manifest line {index} is invalid")
        total = raw.get("total")
        result.append(
            ContestLineInput(
                raw_home_team=_required_text(raw.get("raw_home_team"), "raw_home_team"),
                raw_away_team=_required_text(raw.get("raw_away_team"), "raw_away_team"),
                home_spread=_number(raw.get("home_spread"), "home_spread"),
                source_line_id=_required_text(raw.get("source_line_id"), "source_line_id"),
                total=None if total is None else _number(total, "total"),
            )
        )
    if len(result) != configuration.expected_lined_game_count:
        raise ProductionExecutionError("manifest line count changed after preflight")
    return tuple(result)


def _prior_publication_id(conn: sqlite3.Connection, settings: ProductionSettings) -> int:
    expected_version = {
        "wednesday_refresh": 1,
        "thursday_refresh": 2,
        "friday_refresh": 3,
        "saturday_final": 4,
    }[settings.operation]
    rows = conn.execute(
        "SELECT publication.id FROM official_card_publications AS publication "
        "JOIN contests AS contest ON contest.id = publication.contest_id "
        "WHERE contest.contest_key = ? AND publication.card_version = ?",
        (settings.contest_key, expected_version),
    ).fetchall()
    if len(rows) != 1:
        raise ProductionExecutionError("required prior official publication is not unique")
    return int(rows[0][0])


def _final_card_id(conn: sqlite3.Connection, settings: ProductionSettings) -> int:
    rows = conn.execute(
        "SELECT publication.card_id FROM official_card_publications AS publication "
        "JOIN contests AS contest ON contest.id = publication.contest_id "
        "WHERE contest.contest_key = ? AND publication.card_version = 5",
        (settings.contest_key,),
    ).fetchall()
    if len(rows) != 1:
        raise ProductionExecutionError("final official publication is not unique")
    return int(rows[0][0])


def _audit_requests(
    conn: sqlite3.Connection,
    *,
    card_id: int,
    closing_book: str,
) -> dict[int, PostgameAuditRequest]:
    rows = conn.execute(
        "SELECT pick.locked_line_id, locked.game_id, game.start_date "
        "FROM contest_picks AS pick "
        "JOIN contest_locked_lines AS locked ON locked.id = pick.locked_line_id "
        "JOIN games AS game ON game.game_id = locked.game_id "
        "WHERE pick.card_id = ? ORDER BY pick.locked_line_id",
        (card_id,),
    ).fetchall()
    requests: dict[int, PostgameAuditRequest] = {}
    for locked_line_id, game_id, kickoff in rows:
        closing = conn.execute(
            "SELECT id FROM betting_lines WHERE game_id = ? AND book = ? "
            "AND line_type = 'closing' AND home_spread IS NOT NULL "
            "AND julianday(fetched_at) <= julianday(?) "
            "ORDER BY julianday(fetched_at) DESC, id DESC LIMIT 1",
            (game_id, closing_book, kickoff),
        ).fetchone()
        if closing is None:
            raise ProductionExecutionError(
                f"game {game_id} has no pre-kickoff closing line from {closing_book}"
            )
        requests[int(locked_line_id)] = PostgameAuditRequest(int(closing[0]))
    if not requests:
        raise ProductionExecutionError("final card has no picks to audit")
    return requests


def _operation(
    conn: sqlite3.Connection,
    *,
    settings: ProductionSettings,
    configuration: WeeklyOperationConfiguration,
    generated_at: datetime,
    code_commit_sha: str,
    pre_ingestion_ids: tuple[int, ...] = (),
) -> tuple[dict[str, object], tuple[int, ...]]:
    policies = load_registered_policy_set(conn, settings)
    bundle = (
        load_provider_bundle(
            configuration.provider_bundle_path,
            repository_root=settings.repository_root,
            season=configuration.season,
            week=configuration.week,
        )
        if configuration.provider_bundle_path is not None
        else None
    )
    ingestion_ids: list[int] = list(pre_ingestion_ids)

    def refresh_provider_data(
        target: sqlite3.Connection,
        *,
        season: int,
        week: int,
        as_of: datetime,
    ) -> None:
        if bundle is None:
            return
        if (season, week) != (bundle.season, bundle.week):
            raise ProductionExecutionError("provider bundle week conflicts with controller")
        summaries = ingest_provider_bundle(target, bundle)
        ingestion_ids.extend(summary.ingestion_run_id for summary in summaries)

    fallbacks = _fallbacks(configuration.freshness_fallbacks)
    adjustments = _adjustments(configuration.contextual_adjustments)
    no_bets = _no_bets(configuration.sportsbook_recommendations)

    def live_board() -> tuple[dict[str, object], ...]:
        evaluations = evaluate_live_sportsbook_board(
            conn,
            season=configuration.season,
            week=configuration.week,
            policy_id=policies.sportsbook.id,
            evaluated_at=generated_at,
            provenance=configuration.provenance,
        )
        return tuple(item.board_payload() for item in evaluations)

    if settings.operation == "tuesday_lock":
        result = run_tuesday_controller(
            conn,
            TuesdayCardRequest(
                run_key=settings.idempotency_key,
                publication_key=f"{settings.idempotency_key}:official:v1",
                contest_key=settings.contest_key,
                contest_name=settings.contest_name,
                source_contest_id=settings.source_contest_id,
                season=configuration.season,
                week=configuration.week,
                expected_lined_game_count=configuration.expected_lined_game_count,
                line_payload_sha256=configuration.line_manifest_sha256,
                raw_payload_reference=str(configuration.line_manifest_path),
                lines=_manifest_lines(configuration),
                model_run_key=f"{settings.idempotency_key}:epa-only",
                code_commit_sha=code_commit_sha,
                controller_policy=policies.controller,
                selection_policy=policies.selection,
                confidence_policy=policies.confidence,
                adjustment_policy=policies.adjustment,
                freshness_fallbacks=fallbacks,
                contextual_adjustments=adjustments,
                sportsbook_recommendations=no_bets,
                generated_at=generated_at,
                actor=configuration.actor,
                provenance=configuration.provenance,
            ),
            data_refresh=refresh_provider_data,
        )
        board = live_board()
        return (
            {
                "replayed": result.replayed,
                "controller_run_id": result.run.id,
                "publication_id": result.publication.id,
                "card_id": result.card.card.id,
                "audit_run_id": None,
                "diagnostic_run_id": None,
                "pick_count": len(result.card.picks),
                "top_five_count": sum(pick.is_top_five for pick in result.card.picks),
                "fallback_pick_count": sum(
                    pick.fallback_code is not None for pick in result.card.picks
                ),
                "live_betting_board": board,
                "sportsbook_recommendation_count": len(board),
                "sportsbook_bet_count": sum(
                    item["decision"] == "BET" for item in board
                ),
            },
            tuple(ingestion_ids),
        )
    if settings.operation in (
        "wednesday_refresh",
        "thursday_refresh",
        "friday_refresh",
        "saturday_final",
    ):
        next_version = {
            "wednesday_refresh": 2,
            "thursday_refresh": 3,
            "friday_refresh": 4,
            "saturday_final": 5,
        }[settings.operation]
        result = run_daily_controller(
            conn,
            DailyRefreshRequest(
                run_key=settings.idempotency_key,
                publication_key=f"{settings.idempotency_key}:official:v{next_version}",
                prior_publication_id=_prior_publication_id(conn, settings),
                model_run_key=(
                    None
                    if configuration.daily_change_type == "contextual_adjustment"
                    else f"{settings.idempotency_key}:epa-only"
                ),
                code_commit_sha=code_commit_sha,
                change_type=configuration.daily_change_type,
                reason=configuration.daily_reason,
                refresh_policy=policies.refresh,
                controller_policy=policies.controller,
                freshness_fallbacks=fallbacks,
                contextual_adjustments=adjustments,
                sportsbook_recommendations=no_bets,
                generated_at=generated_at,
                actor=configuration.actor,
                provenance=configuration.provenance,
            ),
            data_refresh=refresh_provider_data,
        )
        board = live_board()
        return (
            {
                "replayed": result.replayed,
                "controller_run_id": result.run.id,
                "publication_id": result.publication.id,
                "card_id": result.card.card.id,
                "audit_run_id": None,
                "diagnostic_run_id": None,
                "pick_count": len(result.card.picks),
                "top_five_count": sum(pick.is_top_five for pick in result.card.picks),
                "fallback_pick_count": sum(
                    pick.fallback_code is not None for pick in result.card.picks
                ),
                "live_betting_board": board,
                "sportsbook_recommendation_count": len(board),
                "sportsbook_bet_count": sum(
                    item["decision"] == "BET" for item in board
                ),
            },
            tuple(ingestion_ids),
        )
    if settings.operation == "postgame_grading":
        card_id = _final_card_id(conn, settings)
        audit = audit_contest_card(
            conn,
            audit_run_key=settings.idempotency_key,
            card_id=card_id,
            audit_policy=policies.audit,
            requests_by_locked_line_id=_audit_requests(
                conn, card_id=card_id, closing_book=configuration.closing_book
            ),
            source="governed-production-provider-custody",
            provenance=configuration.provenance,
            audited_at=generated_at,
        )
        return (
            {
                "replayed": audit.run.sequence > 1,
                "controller_run_id": None,
                "publication_id": None,
                "card_id": card_id,
                "audit_run_id": audit.run.id,
                "diagnostic_run_id": None,
                "pick_count": len(audit.details),
                "top_five_count": sum(detail.is_top_five for detail in audit.details),
                "fallback_pick_count": None,
                "live_betting_board": (),
                "sportsbook_recommendation_count": 0,
                "sportsbook_bet_count": 0,
            },
            tuple(ingestion_ids),
        )
    if settings.operation == "weekly_audit":
        card_id = _final_card_id(conn, settings)
        audit_row = conn.execute(
            "SELECT run.id FROM card_postgame_audit_runs AS run "
            "JOIN card_postgame_audit_completions AS completion "
            "ON completion.audit_run_id = run.id WHERE run.card_id = ? "
            "ORDER BY run.sequence DESC LIMIT 1",
            (card_id,),
        ).fetchone()
        if audit_row is None:
            raise ProductionExecutionError("weekly audit requires a completed postgame audit")
        diagnostics = generate_weekly_diagnostics(
            conn,
            diagnostic_run_key=settings.idempotency_key,
            audit_run_id=int(audit_row[0]),
            diagnostic_policy=policies.diagnostics,
            source="governed-production-weekly-audit",
            provenance=configuration.provenance,
            generated_at=generated_at,
        )
        return (
            {
                "replayed": diagnostics.run.sequence > 1,
                "controller_run_id": None,
                "publication_id": None,
                "card_id": card_id,
                "audit_run_id": int(audit_row[0]),
                "diagnostic_run_id": diagnostics.run.id,
                "pick_count": None,
                "top_five_count": None,
                "fallback_pick_count": None,
                "live_betting_board": (),
                "sportsbook_recommendation_count": 0,
                "sportsbook_bet_count": 0,
            },
            (),
        )
    raise ProductionExecutionError(f"unsupported operation: {settings.operation}")


def execute_production_operation(
    settings: ProductionSettings,
    configuration: WeeklyOperationConfiguration,
    *,
    code_commit_sha: str,
    dry_run: bool,
    now: datetime | None = None,
    managed_workspace: bool = False,
) -> tuple[ProductionExecutionResult, ProductionPreflightReport]:
    """Preflight, execute, and verify one governed SQLite workspace.

    ``managed_workspace`` is reserved for a temporary snapshot held under the
    PostgreSQL writer transaction in ``operations.cloud_execution``. It skips
    host-file locking and replacement because the runner filesystem is not the
    durable commit boundary.
    """
    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if (
        len(code_commit_sha) != 40
        or any(character not in "0123456789abcdef" for character in code_commit_sha)
    ):
        raise ProductionExecutionError("code_commit_sha must be lowercase SHA-1")
    if settings.model_name != ACTIVE_MODEL_NAME or settings.model_version != ACTIVE_MODEL_VERSION:
        raise ProductionExecutionError("only the EPA-only production baseline is executable")
    preflight = run_production_preflight(
        settings,
        now=generated_at,
        allow_disposable_database=managed_workspace,
    )
    initial_blocking_names = {
        check.name for check in preflight.checks if check.status == "block"
    }
    postgame_bundle_preparation = (
        settings.operation == "postgame_grading"
        and configuration.provider_bundle_path is not None
        and initial_blocking_names == {"postgame_stage_readiness"}
    )
    if not preflight.production_ready and not postgame_bundle_preparation:
        raise ProductionExecutionError(preflight.production_ready_status)
    source = settings.database_path.resolve()
    source_before = _file_sha256(source)
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    staging_path: Path | None = None
    working = source
    lock = None
    backup_path: Path | None = None
    backup_sha256: str | None = None
    if managed_workspace and dry_run:
        raise ProductionExecutionError("managed workspace cannot also be a local dry run")
    if managed_workspace:
        working = source
    elif dry_run:
        temporary_directory = tempfile.TemporaryDirectory(prefix="cfb-v3-production-dry-run-")
        working = Path(temporary_directory.name) / "cfb.db"
        shutil.copy2(source, working)
    else:
        lock = ProductionWriterLock(
            source,
            settings.idempotency_key,
            configuration.actor,
            generated_at,
        )
        lock.acquire()
        second = run_production_preflight(settings, now=generated_at)
        if not second.production_ready and not postgame_bundle_preparation:
            lock.release()
            raise ProductionExecutionError("preflight changed after writer lock acquisition")
        if _file_sha256(source) != source_before:
            lock.release()
            raise ProductionExecutionError(
                "authoritative database changed before writer lock acquisition"
            )
        _assert_no_sqlite_sidecars(source)
        descriptor, stage_name = tempfile.mkstemp(
            prefix=f".{source.name}.v3-stage-",
            suffix=".db",
            dir=source.parent,
        )
        os.close(descriptor)
        staging_path = Path(stage_name)
        shutil.copy2(source, staging_path)
        working = staging_path
    try:
        pre_ingestion_ids: tuple[int, ...] = ()
        if postgame_bundle_preparation:
            assert configuration.provider_bundle_path is not None
            bundle = load_provider_bundle(
                configuration.provider_bundle_path,
                repository_root=settings.repository_root,
                season=configuration.season,
                week=configuration.week,
            )
            preparation_connection = sqlite3.connect(working)
            preparation_connection.execute("PRAGMA foreign_keys = ON")
            try:
                summaries = ingest_provider_bundle(preparation_connection, bundle)
                preparation_connection.commit()
                pre_ingestion_ids = tuple(
                    summary.ingestion_run_id for summary in summaries
                )
            finally:
                preparation_connection.close()
            prepared_settings = replace(settings, database_path=working)
            preflight = run_production_preflight(
                prepared_settings,
                now=generated_at,
                allow_disposable_database=True,
            )
            if not preflight.production_ready:
                raise ProductionExecutionError(
                    "postgame provider preparation did not clear every preflight gate"
                )
        conn = sqlite3.connect(working)
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            details, ingestion_ids = _operation(
                conn,
                settings=settings,
                configuration=configuration,
                generated_at=generated_at,
                code_commit_sha=code_commit_sha,
                pre_ingestion_ids=pre_ingestion_ids,
            )
            conn.commit()
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = tuple(conn.execute("PRAGMA foreign_key_check"))
            if integrity != "ok" or foreign_keys:
                raise ProductionExecutionError("post-operation database verification failed")
            card_id = details["card_id"]
            if isinstance(card_id, int) and details["publication_id"] is not None:
                inspection = inspect_official_card(
                    conn, publication_id=int(details["publication_id"])
                )
                if not inspection.valid:
                    raise ProductionExecutionError("official publication inspection failed")
        except Exception:
            conn.rollback()
            raise
        finally:
                conn.close()
        working_after = _file_sha256(working)
        if not dry_run and not managed_workspace:
            if _file_sha256(source) != source_before:
                raise ProductionExecutionError(
                    "authoritative database changed during staged execution"
                )
            backup_directory = source.parent / "backups"
            backup_directory.mkdir(parents=True, exist_ok=True)
            timestamp = generated_at.strftime("%Y%m%dT%H%M%S%fZ")
            backup_stem = f"{source.name}.{timestamp}.{source_before[:12]}"
            for sequence in range(1000):
                candidate = backup_directory / f"{backup_stem}.{sequence:03d}.bak"
                if not candidate.exists():
                    backup_path = candidate
                    break
            if backup_path is None:
                raise ProductionExecutionError("no unique operation backup path is available")
            shutil.copy2(source, backup_path)
            backup_sha256 = _file_sha256(backup_path)
            if backup_sha256 != source_before:
                backup_path.unlink(missing_ok=True)
                raise ProductionExecutionError("operation backup checksum mismatch")
            os.replace(working, source)
            staging_path = None
            if _file_sha256(source) != working_after:
                shutil.copy2(backup_path, source)
                raise ProductionExecutionError(
                    "atomic persistence verification failed; backup was restored"
                )
    finally:
        if lock is not None:
            lock.release()
        if staging_path is not None:
            staging_path.unlink(missing_ok=True)
        if temporary_directory is not None:
            temporary_directory.cleanup()
    source_after = _file_sha256(source)
    if dry_run and source_after != source_before:
        raise ProductionExecutionError("dry run changed the source database")
    payload = {
        "adapter_version": EXECUTION_ADAPTER_VERSION,
        "operation": settings.operation,
        "operation_key": settings.idempotency_key,
        "weekly_configuration_sha256": _file_sha256(configuration.path),
        "execution_mode": (
            "managed_cloud_workspace"
            if managed_workspace
            else ("dry_run" if dry_run else "persist")
        ),
        "status": "completed",
        "replayed": bool(details["replayed"]),
        "source_database_sha256_before": source_before,
        "source_database_sha256_after": source_after,
        "source_database_unchanged": source_before == source_after,
        "working_database_sha256_after": working_after,
        "backup_path": str(backup_path) if backup_path is not None else None,
        "backup_sha256": backup_sha256,
        "provider_ingestion_run_ids": ingestion_ids,
        "controller_run_id": details["controller_run_id"],
        "publication_id": details["publication_id"],
        "card_id": details["card_id"],
        "audit_run_id": details["audit_run_id"],
        "diagnostic_run_id": details["diagnostic_run_id"],
        "pick_count": details["pick_count"],
        "top_five_count": details["top_five_count"],
        "fallback_pick_count": details["fallback_pick_count"],
        "sportsbook_recommendation_count": details[
            "sportsbook_recommendation_count"
        ],
        "sportsbook_bet_count": details["sportsbook_bet_count"],
        "live_betting_board": details["live_betting_board"],
        "wagers_placed": 0,
        "completed_at": generated_at.isoformat(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    result = ProductionExecutionResult(
        **payload,
        result_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
    return result, preflight
