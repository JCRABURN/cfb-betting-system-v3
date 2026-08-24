"""Managed-cloud commit boundary for governed production operations."""

from __future__ import annotations

import sqlite3
import tempfile
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from operations.cloud_persistence import CloudCommit, SnapshotStore
from operations.config import EXPECTED_REPOSITORY, ProductionSettings
from operations.execution import (
    ProductionExecutionResult,
    execute_production_operation,
)
from operations.preflight import ProductionPreflightReport
from operations.public_dashboard import generate_public_dashboard_site
from operations.weekly_config import WeeklyOperationConfiguration


CLOUD_EXECUTION_ADAPTER_VERSION = "v3-managed-postgresql-snapshot-v2"
PRODUCTION_STREAM_KEY = f"{EXPECTED_REPOSITORY}:production"


def durable_stream_key(settings: ProductionSettings) -> str:
    """Return an isolated durable stream for production or one governed shadow week."""
    if not getattr(settings, "is_shadow_rehearsal", False):
        return PRODUCTION_STREAM_KEY
    if settings.season is None or settings.week is None:
        raise ValueError("shadow rehearsal stream requires an explicit season and week")
    return f"{EXPECTED_REPOSITORY}:shadow:{settings.season}:week:{settings.week}"


@dataclass(frozen=True)
class CloudProductionExecutionResult:
    cloud_adapter_version: str
    execution_profile: str
    persistence_backend: str
    durable_stream_key: str
    durable_generation_before: int
    durable_generation_after: int
    durable_snapshot_sha256: str
    durable_snapshot_bytes: int
    durable_state_changed: bool
    durable_commit_replayed: bool
    runner_state_disposable: bool
    operation: ProductionExecutionResult


def execute_cloud_production_operation(
    store: SnapshotStore,
    settings: ProductionSettings,
    configuration: WeeklyOperationConfiguration,
    *,
    code_commit_sha: str,
    now: datetime | None = None,
    pages_output_directory: Path | None = None,
) -> tuple[CloudProductionExecutionResult, ProductionPreflightReport]:
    """Run against an ephemeral snapshot and commit it inside PostgreSQL."""
    generated_at = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    stream_key = durable_stream_key(settings)
    store.apply_migrations()
    with tempfile.TemporaryDirectory(prefix="cfb-v3-cloud-workspace-") as directory:
        workspace = Path(directory) / "cfb.db"
        with store.writer(
            stream_key=stream_key,
            operation_key=settings.idempotency_key,
            actor=configuration.actor,
            code_commit_sha=code_commit_sha,
        ) as lease:
            before = lease.snapshot
            lease.materialize(workspace)
            workspace_settings = replace(settings, database_path=workspace)
            operation, preflight = execute_production_operation(
                workspace_settings,
                configuration,
                code_commit_sha=code_commit_sha,
                dry_run=False,
                now=generated_at,
                managed_workspace=True,
            )
            if pages_output_directory is not None:
                dashboard_connection = sqlite3.connect(workspace)
                dashboard_connection.execute("PRAGMA foreign_keys = ON")
                dashboard_connection.execute("PRAGMA query_only = ON")
                try:
                    generate_public_dashboard_site(
                        dashboard_connection,
                        configuration=configuration,
                        operation=operation,
                        output_directory=pages_output_directory,
                        repository_root=settings.repository_root,
                        execution_profile=getattr(settings, "runtime_mode", "production"),
                    )
                finally:
                    dashboard_connection.close()
            cloud_commit: CloudCommit = lease.publish(
                workspace,
                result_sha256=operation.result_sha256,
                metadata={
                    "adapter_version": CLOUD_EXECUTION_ADAPTER_VERSION,
                    "operation": settings.operation,
                    "operation_key": settings.idempotency_key,
                    "weekly_configuration_sha256": operation.weekly_configuration_sha256,
                    "completed_at": operation.completed_at,
                    "wagers_placed": 0,
                },
            )
            result = CloudProductionExecutionResult(
                cloud_adapter_version=CLOUD_EXECUTION_ADAPTER_VERSION,
                execution_profile=getattr(settings, "runtime_mode", "production"),
                persistence_backend="managed_postgresql",
                durable_stream_key=stream_key,
                durable_generation_before=before.generation,
                durable_generation_after=cloud_commit.snapshot.generation,
                durable_snapshot_sha256=cloud_commit.snapshot.payload_sha256,
                durable_snapshot_bytes=cloud_commit.snapshot.payload_bytes,
                durable_state_changed=cloud_commit.state_changed,
                durable_commit_replayed=cloud_commit.replayed,
                runner_state_disposable=True,
                operation=operation,
            )
    return result, preflight
