"""Typed environment configuration for guarded V3 production operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


EXPECTED_REPOSITORY = "JCRABURN/cfb-betting-system-v3"
ORIGINAL_REPOSITORY = "JCRABURN/cfb-betting-system"
ACTIVE_MODEL_NAME = "epa_only"
ACTIVE_MODEL_VERSION = "epa-only-linear-v1"
ACTIVE_FEATURE_SCHEMA_VERSION = "epa-differential-v1"
ACTIVE_CONFIGURATION_VERSION = "walk-forward-prior-seasons-v1"

PRODUCTION_OPERATIONS = (
    "tuesday_lock",
    "wednesday_refresh",
    "thursday_refresh",
    "friday_refresh",
    "saturday_final",
    "postgame_grading",
    "weekly_audit",
)

REQUIRED_CREDENTIAL_VARIABLES = (
    "CFBD_API_KEY",
    "ODDS_API_KEY",
)

POLICY_ENVIRONMENT_VARIABLES = (
    ("controller", "CFB_V3_CONTROLLER_POLICY_VERSION"),
    ("selection", "CFB_V3_SELECTION_POLICY_VERSION"),
    ("confidence", "CFB_V3_CONFIDENCE_POLICY_VERSION"),
    ("ranking", "CFB_V3_RANKING_POLICY_VERSION"),
    ("adjustment", "CFB_V3_ADJUSTMENT_POLICY_VERSION"),
    ("refresh", "CFB_V3_REFRESH_POLICY_VERSION"),
    ("audit", "CFB_V3_AUDIT_POLICY_VERSION"),
    ("diagnostics", "CFB_V3_DIAGNOSTICS_POLICY_VERSION"),
)

BOOLEAN_ENVIRONMENT_VARIABLES = (
    "CFB_V3_PRODUCTION_ENABLED",
    "CFB_V3_OPERATION_EXECUTION_ENABLED",
    "CFB_V3_KILL_SWITCH",
    "CFB_V3_OWNER_CUTOVER_APPROVED",
    "CFB_V3_PROVIDER_CONNECTIVITY_AUTHORIZED",
)


def _text(environment: Mapping[str, str], name: str) -> str:
    return environment.get(name, "").strip()


def _boolean(environment: Mapping[str, str], name: str) -> bool | None:
    value = _text(environment, name).casefold()
    if value == "true":
        return True
    if value == "false":
        return False
    return None


def _integer(environment: Mapping[str, str], name: str) -> int | None:
    value = _text(environment, name)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@dataclass(frozen=True)
class ProductionSettings:
    """Safe configuration snapshot that stores credential presence, never values."""

    repository_root: Path
    database_path: Path
    operation: str
    runtime_mode: str
    production_enabled: bool | None
    operation_execution_enabled: bool | None
    kill_switch: bool | None
    owner_cutover_approved: bool | None
    configured_repository: str
    github_repository: str
    provider_connectivity_authorized: bool | None
    provider_connectivity_verified_at: str
    season: int | None
    week: int | None
    contest_key: str
    contest_name: str
    source_contest_id: str
    contest_source: str
    expected_lined_game_count: int | None
    contest_lines_path: Path | None
    contest_lines_sha256: str
    model_name: str
    model_version: str
    feature_schema_version: str
    configuration_version: str
    policy_versions: tuple[tuple[str, str], ...]
    present_credential_variables: tuple[str, ...]
    missing_credential_variables: tuple[str, ...]
    invalid_boolean_variables: tuple[str, ...]

    def policy_version(self, policy_name: str) -> str:
        return dict(self.policy_versions).get(policy_name, "")

    @property
    def idempotency_key(self) -> str:
        season = self.season if self.season is not None else "missing-season"
        week = self.week if self.week is not None else "missing-week"
        return f"v3:{season}:week:{week}:{self.operation}"


def load_production_settings(
    environment: Mapping[str, str],
    *,
    repository_root: Path,
    operation: str,
    database_path: Path | None = None,
) -> ProductionSettings:
    """Load environment names without retaining or exposing credential values."""
    root = repository_root.resolve()
    configured_database = database_path
    if configured_database is None:
        raw_database = _text(environment, "CFB_V3_DATABASE_PATH") or "data/cfb.db"
        configured_database = Path(raw_database)
    if not configured_database.is_absolute():
        configured_database = root / configured_database
    configured_database = configured_database.resolve()

    raw_lines_path = _text(environment, "CFB_V3_CONTEST_LINES_FILE")
    lines_path: Path | None = None
    if raw_lines_path:
        lines_path = Path(raw_lines_path)
        if not lines_path.is_absolute():
            lines_path = root / lines_path
        lines_path = lines_path.resolve()

    present_credentials = tuple(
        name for name in REQUIRED_CREDENTIAL_VARIABLES if bool(_text(environment, name))
    )
    missing_credentials = tuple(
        name for name in REQUIRED_CREDENTIAL_VARIABLES if name not in present_credentials
    )
    invalid_booleans = tuple(
        name
        for name in BOOLEAN_ENVIRONMENT_VARIABLES
        if _boolean(environment, name) is None
    )
    policy_versions = tuple(
        (policy_name, _text(environment, variable_name))
        for policy_name, variable_name in POLICY_ENVIRONMENT_VARIABLES
    )

    return ProductionSettings(
        repository_root=root,
        database_path=configured_database,
        operation=operation.strip(),
        runtime_mode=_text(environment, "CFB_V3_RUNTIME_MODE"),
        production_enabled=_boolean(environment, "CFB_V3_PRODUCTION_ENABLED"),
        operation_execution_enabled=_boolean(
            environment, "CFB_V3_OPERATION_EXECUTION_ENABLED"
        ),
        kill_switch=_boolean(environment, "CFB_V3_KILL_SWITCH"),
        owner_cutover_approved=_boolean(
            environment, "CFB_V3_OWNER_CUTOVER_APPROVED"
        ),
        configured_repository=_text(environment, "CFB_V3_REPOSITORY"),
        github_repository=_text(environment, "GITHUB_REPOSITORY"),
        provider_connectivity_authorized=_boolean(
            environment, "CFB_V3_PROVIDER_CONNECTIVITY_AUTHORIZED"
        ),
        provider_connectivity_verified_at=_text(
            environment, "CFB_V3_PROVIDER_CONNECTIVITY_VERIFIED_AT"
        ),
        season=_integer(environment, "CFB_V3_SEASON"),
        week=_integer(environment, "CFB_V3_WEEK"),
        contest_key=_text(environment, "CFB_V3_CONTEST_KEY"),
        contest_name=_text(environment, "CFB_V3_CONTEST_NAME"),
        source_contest_id=_text(environment, "CFB_V3_SOURCE_CONTEST_ID"),
        contest_source=_text(environment, "CFB_V3_CONTEST_SOURCE"),
        expected_lined_game_count=_integer(
            environment, "CFB_V3_EXPECTED_LINED_GAME_COUNT"
        ),
        contest_lines_path=lines_path,
        contest_lines_sha256=_text(
            environment, "CFB_V3_CONTEST_LINES_SHA256"
        ).casefold(),
        model_name=_text(environment, "CFB_V3_MODEL_NAME"),
        model_version=_text(environment, "CFB_V3_MODEL_VERSION"),
        feature_schema_version=_text(
            environment, "CFB_V3_FEATURE_SCHEMA_VERSION"
        ),
        configuration_version=_text(
            environment, "CFB_V3_CONFIGURATION_VERSION"
        ),
        policy_versions=policy_versions,
        present_credential_variables=present_credentials,
        missing_credential_variables=missing_credentials,
        invalid_boolean_variables=invalid_booleans,
    )
