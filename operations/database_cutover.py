"""Governed database migration and immutable policy-registration preparation."""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from business_entities.complete_audits import (
    PostgameAuditPolicy,
    register_postgame_audit_policy,
)
from business_entities.contextual_adjustments import (
    ManualAdjustmentPolicy,
    register_manual_adjustment_policy,
)
from business_entities.ranking import (
    ConfidenceRankingPolicy,
    register_confidence_ranking_policy,
)
from business_entities.refreshes import DailyRefreshPolicy, register_daily_refresh_policy
from business_entities.reproducibility import (
    FullCardPolicy,
    register_contest_selection_policy,
)
from business_entities.weekly_controller import (
    RequiredSourcePolicy,
    WeeklyControllerPolicy,
    register_weekly_controller_policy,
)
from business_entities.weekly_diagnostics import (
    WeeklyDiagnosticsPolicy,
    register_weekly_diagnostics_policy,
)
from migrations.runner import apply_migrations, load_migrations, table_row_counts

from operations.config import EXPECTED_REPOSITORY


POLICY_CONFIGURATION_VERSION = "v3-production-policies-v1"


class DatabaseCutoverError(RuntimeError):
    """Raised when a cutover copy, migration, or policy registration is unsafe."""


@dataclass(frozen=True)
class DatabaseCutoverReport:
    source_path: str
    target_path: str
    source_sha256_before: str
    source_sha256_after: str
    source_unchanged: bool
    target_sha256_before: str
    target_sha256_after: str
    backup_path: str | None
    backup_sha256: str | None
    migration_inventory: tuple[tuple[int, str, str], ...]
    migrations_applied: tuple[int, ...]
    row_counts_before: tuple[tuple[str, int], ...]
    row_counts_after: tuple[tuple[str, int], ...]
    pre_integrity_check: str
    pre_foreign_key_violation_count: int
    integrity_check: str
    foreign_key_violation_count: int
    registered_policy_versions: tuple[tuple[str, str], ...]
    authoritative: bool
    completed_at: str
    report_sha256: str


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DatabaseCutoverError(f"{field} must be non-empty text")
    return value.strip()


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DatabaseCutoverError(f"{field} must be numeric")
    return float(value)


def _integer(value: object, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise DatabaseCutoverError(f"{field} must be an integer >= {minimum}")
    return value


def _utc(value: object, field: str) -> datetime:
    raw = _text(value, field)
    raw = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise DatabaseCutoverError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise DatabaseCutoverError(f"{field} must use a UTC offset")
    return parsed.astimezone(timezone.utc)


def _policy_payload(path: Path) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DatabaseCutoverError("policy configuration is not valid UTF-8 JSON") from exc
    if not isinstance(payload, Mapping):
        raise DatabaseCutoverError("policy configuration must be a JSON object")
    if (
        payload.get("configuration_version") != POLICY_CONFIGURATION_VERSION
        or payload.get("repository") != EXPECTED_REPOSITORY
    ):
        raise DatabaseCutoverError("policy configuration identity is invalid")
    return payload


def register_approved_policies(
    conn: sqlite3.Connection,
    policy_config_path: Path,
) -> tuple[tuple[str, str], ...]:
    """Register exact reviewed definitions through existing immutable services."""
    payload = _policy_payload(policy_config_path)
    effective_at = _utc(payload.get("effective_at"), "effective_at")
    created_by = _text(payload.get("created_by"), "created_by")
    provenance = _text(payload.get("provenance"), "provenance")
    controller = payload.get("controller")
    selection = payload.get("selection")
    confidence = payload.get("confidence")
    versions = payload.get("versions")
    if not all(isinstance(item, Mapping) for item in (controller, selection, confidence, versions)):
        raise DatabaseCutoverError(
            "controller, selection, confidence, and versions must be objects"
        )
    assert isinstance(controller, Mapping)
    assert isinstance(selection, Mapping)
    assert isinstance(confidence, Mapping)
    assert isinstance(versions, Mapping)
    raw_sources = controller.get("required_sources")
    if not isinstance(raw_sources, list) or any(not isinstance(item, Mapping) for item in raw_sources):
        raise DatabaseCutoverError("controller.required_sources must be an object array")
    sources = tuple(
        RequiredSourcePolicy(
            _text(item.get("data_type"), "required_source.data_type"),
            _text(item.get("provider"), "required_source.provider"),
            _text(item.get("fallback_code"), "required_source.fallback_code"),
        )
        for item in raw_sources
        if isinstance(item, Mapping)
    )
    controller_version = _text(versions.get("controller"), "versions.controller")
    selection_version = _text(versions.get("selection"), "versions.selection")
    confidence_version = _text(versions.get("confidence"), "versions.confidence")
    ranking_version = _text(versions.get("ranking"), "versions.ranking")
    adjustment_version = _text(versions.get("adjustment"), "versions.adjustment")
    refresh_version = _text(versions.get("refresh"), "versions.refresh")
    audit_version = _text(versions.get("audit"), "versions.audit")
    diagnostics_version = _text(versions.get("diagnostics"), "versions.diagnostics")
    try:
        conn.execute("BEGIN IMMEDIATE")
        register_weekly_controller_policy(
            conn,
            WeeklyControllerPolicy(
                controller_version,
                "SplashSports",
                sources,
                effective_at,
                created_by,
                provenance,
            ),
        )
        market_books = selection.get("market_books")
        if not isinstance(market_books, list) or any(not isinstance(book, str) for book in market_books):
            raise DatabaseCutoverError("selection.market_books must be a string array")
        register_contest_selection_policy(
            conn,
            FullCardPolicy(
                selection_version,
                tuple(market_books),
                _text(selection.get("model_tie_side"), "selection.model_tie_side"),
                _text(
                    selection.get("pickem_tiebreak_side"),
                    "selection.pickem_tiebreak_side",
                ),
            ),
            effective_at=effective_at,
            created_by=created_by,
            provenance=provenance,
        )
        register_confidence_ranking_policy(
            conn,
            ConfidenceRankingPolicy(
                policy_key=_text(confidence.get("policy_key"), "confidence.policy_key"),
                confidence_policy_version=confidence_version,
                ranking_policy_version=ranking_version,
                confidence_5_max_uncertainty=_number(
                    confidence.get("confidence_5_max_uncertainty"),
                    "confidence.confidence_5_max_uncertainty",
                ),
                confidence_4_max_uncertainty=_number(
                    confidence.get("confidence_4_max_uncertainty"),
                    "confidence.confidence_4_max_uncertainty",
                ),
                confidence_3_max_uncertainty=_number(
                    confidence.get("confidence_3_max_uncertainty"),
                    "confidence.confidence_3_max_uncertainty",
                ),
                confidence_2_max_uncertainty=_number(
                    confidence.get("confidence_2_max_uncertainty"),
                    "confidence.confidence_2_max_uncertainty",
                ),
                effective_at=effective_at,
                created_by=created_by,
                provenance=provenance,
            ),
        )
        register_manual_adjustment_policy(
            conn,
            ManualAdjustmentPolicy(
                adjustment_version, effective_at, created_by, provenance
            ),
        )
        register_daily_refresh_policy(
            conn,
            DailyRefreshPolicy(refresh_version, effective_at, created_by, provenance),
        )
        register_postgame_audit_policy(
            conn,
            PostgameAuditPolicy(audit_version, effective_at, created_by, provenance),
        )
        diagnostics = payload.get("diagnostics")
        if not isinstance(diagnostics, Mapping):
            raise DatabaseCutoverError("diagnostics must be an object")
        register_weekly_diagnostics_policy(
            conn,
            WeeklyDiagnosticsPolicy(
                policy_version=diagnostics_version,
                minimum_recommendation_sample=_integer(
                    diagnostics.get("minimum_recommendation_sample"),
                    "diagnostics.minimum_recommendation_sample",
                    1,
                ),
                minimum_ats_delta_percentage_points=_number(
                    diagnostics.get("minimum_ats_delta_percentage_points"),
                    "diagnostics.minimum_ats_delta_percentage_points",
                ),
                confidence_threshold_step_points=_number(
                    diagnostics.get("confidence_threshold_step_points"),
                    "diagnostics.confidence_threshold_step_points",
                ),
                effective_at=effective_at,
                created_by=created_by,
                provenance=provenance,
            ),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return tuple(
        (name, _text(versions.get(name), f"versions.{name}"))
        for name in (
            "controller",
            "selection",
            "confidence",
            "ranking",
            "adjustment",
            "refresh",
            "audit",
            "diagnostics",
        )
    )


def migrate_and_register(
    source: Path,
    target: Path,
    policy_config_path: Path,
    *,
    authoritative: bool,
    backup_path: Path | None = None,
    completed_at: datetime | None = None,
) -> DatabaseCutoverReport:
    """Migrate an explicit target; copies are default, authoritative use needs backup."""
    source = source.resolve()
    target = target.resolve()
    policy_config_path = policy_config_path.resolve()
    if not source.is_file():
        raise DatabaseCutoverError("source database does not exist")
    source_before = _file_sha256(source)
    if authoritative:
        if target != source:
            raise DatabaseCutoverError("authoritative target must equal source")
        if backup_path is None:
            raise DatabaseCutoverError("authoritative migration requires an explicit backup")
        backup = backup_path.resolve()
        if backup.exists() or backup == source:
            raise DatabaseCutoverError("backup path must be new and distinct")
    else:
        backup = None
        if target == source or target.exists():
            raise DatabaseCutoverError("rehearsal target must be new and distinct")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    if authoritative:
        assert backup is not None
        backup.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, backup)
        backup_sha = _file_sha256(backup)
        if backup_sha != source_before:
            raise DatabaseCutoverError("authoritative backup checksum mismatch")
    else:
        backup_sha = None
    target_before = _file_sha256(target)
    if target_before != source_before:
        raise DatabaseCutoverError("cutover target checksum does not match source")
    connection = sqlite3.connect(target)
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        before_counts = table_row_counts(connection)
        pre_integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        pre_violations = tuple(connection.execute("PRAGMA foreign_key_check"))
        if pre_integrity != "ok" or pre_violations:
            raise DatabaseCutoverError("pre-cutover database checks failed")
        migrations = load_migrations()
        migration_results = apply_migrations(connection, migrations)
        policy_versions = register_approved_policies(connection, policy_config_path)
        after_counts = table_row_counts(connection)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        violations = tuple(connection.execute("PRAGMA foreign_key_check"))
        if integrity != "ok" or violations:
            raise DatabaseCutoverError("post-cutover database checks failed")
    finally:
        connection.close()
    source_after = _file_sha256(source)
    target_after = _file_sha256(target)
    timestamp = (completed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    report_payload = {
        "source_path": str(source),
        "target_path": str(target),
        "source_sha256_before": source_before,
        "source_sha256_after": source_after,
        "source_unchanged": source_before == source_after,
        "target_sha256_before": target_before,
        "target_sha256_after": target_after,
        "backup_path": str(backup) if backup is not None else None,
        "backup_sha256": backup_sha,
        "migration_inventory": tuple(
            (migration.version, migration.name, migration.checksum)
            for migration in migrations
        ),
        "migrations_applied": tuple(result.version for result in migration_results),
        "row_counts_before": tuple(sorted(before_counts.items())),
        "row_counts_after": tuple(sorted(after_counts.items())),
        "pre_integrity_check": pre_integrity,
        "pre_foreign_key_violation_count": len(pre_violations),
        "integrity_check": integrity,
        "foreign_key_violation_count": len(violations),
        "registered_policy_versions": policy_versions,
        "authoritative": authoritative,
        "completed_at": timestamp.isoformat(),
    }
    canonical = json.dumps(report_payload, sort_keys=True, separators=(",", ":"))
    return DatabaseCutoverReport(
        **report_payload,
        report_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    )
