"""Strict, secret-free configuration for one governed production week."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ingestion import DEFAULT_FRESHNESS_RULES, FRESHNESS_POLICY_VERSION

from operations.config import (
    ACTIVE_CONFIGURATION_VERSION,
    ACTIVE_FEATURE_SCHEMA_VERSION,
    ACTIVE_MODEL_NAME,
    ACTIVE_MODEL_VERSION,
    EXPECTED_REPOSITORY,
    POLICY_ENVIRONMENT_VARIABLES,
)


WEEKLY_CONFIGURATION_VERSION = "v3-weekly-production-v1"


class WeeklyConfigurationError(RuntimeError):
    """Raised when weekly configuration is incomplete, conflicting, or unsafe."""


@dataclass(frozen=True)
class WeeklyOperationConfiguration:
    path: Path
    season: int
    week: int
    contest_key: str
    contest_name: str
    source_contest_id: str
    expected_lined_game_count: int
    line_manifest_path: Path
    line_manifest_sha256: str
    provider_bundle_path: Path | None
    display_timezone: str
    policy_versions: tuple[tuple[str, str], ...]
    freshness_fallbacks: tuple[Mapping[str, object], ...]
    contextual_adjustments: tuple[Mapping[str, object], ...]
    sportsbook_recommendations: tuple[Mapping[str, object], ...]
    daily_change_type: str
    daily_reason: str
    closing_book: str
    actor: str
    provenance: str

    def environment_values(self) -> dict[str, str]:
        values = {
            "CFB_V3_SEASON": str(self.season),
            "CFB_V3_WEEK": str(self.week),
            "CFB_V3_CONTEST_KEY": self.contest_key,
            "CFB_V3_CONTEST_NAME": self.contest_name,
            "CFB_V3_SOURCE_CONTEST_ID": self.source_contest_id,
            "CFB_V3_CONTEST_SOURCE": "SplashSports",
            "CFB_V3_EXPECTED_LINED_GAME_COUNT": str(
                self.expected_lined_game_count
            ),
            "CFB_V3_CONTEST_LINES_FILE": str(self.line_manifest_path),
            "CFB_V3_CONTEST_LINES_SHA256": self.line_manifest_sha256,
            "CFB_V3_MODEL_NAME": ACTIVE_MODEL_NAME,
            "CFB_V3_MODEL_VERSION": ACTIVE_MODEL_VERSION,
            "CFB_V3_FEATURE_SCHEMA_VERSION": ACTIVE_FEATURE_SCHEMA_VERSION,
            "CFB_V3_CONFIGURATION_VERSION": ACTIVE_CONFIGURATION_VERSION,
        }
        by_name = dict(self.policy_versions)
        for policy_name, variable_name in POLICY_ENVIRONMENT_VARIABLES:
            values[variable_name] = by_name[policy_name]
        return values


def _object(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise WeeklyConfigurationError(f"{field} must be a JSON object")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WeeklyConfigurationError(f"{field} must be non-empty text")
    return value.strip()


def _integer(value: object, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise WeeklyConfigurationError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise WeeklyConfigurationError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return value


def _sha256(value: object, field: str) -> str:
    digest = _text(value, field).casefold()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise WeeklyConfigurationError(f"{field} must be a SHA-256 digest")
    return digest


def _inside_repository(path: Path, root: Path, field: str) -> Path:
    resolved = path.resolve()
    try:
        inside = resolved.is_relative_to(root.resolve())
    except ValueError:
        inside = False
    if not inside:
        raise WeeklyConfigurationError(f"{field} must resolve inside the V3 repository")
    return resolved


def _path(
    value: object,
    field: str,
    *,
    config_path: Path,
    repository_root: Path,
) -> Path:
    raw = Path(_text(value, field))
    resolved = raw if raw.is_absolute() else config_path.parent / raw
    return _inside_repository(resolved, repository_root, field)


def _records(value: object, field: str) -> tuple[Mapping[str, object], ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or any(not isinstance(item, Mapping) for item in value):
        raise WeeklyConfigurationError(f"{field} must be an array of JSON objects")
    return tuple(dict(item) for item in value)


def load_weekly_configuration(
    path: Path,
    *,
    repository_root: Path,
) -> WeeklyOperationConfiguration:
    """Load one explicit week without reading credentials or safety flags."""
    root = repository_root.resolve()
    config_path = _inside_repository(path, root, "weekly configuration path")
    if not config_path.is_file():
        raise WeeklyConfigurationError("weekly configuration file does not exist")
    try:
        payload = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WeeklyConfigurationError("weekly configuration is not valid UTF-8 JSON") from exc
    payload = _object(payload, "weekly configuration")
    if payload.get("configuration_version") != WEEKLY_CONFIGURATION_VERSION:
        raise WeeklyConfigurationError(
            f"configuration_version must be {WEEKLY_CONFIGURATION_VERSION}"
        )
    if payload.get("repository") != EXPECTED_REPOSITORY:
        raise WeeklyConfigurationError(
            f"repository must be exactly {EXPECTED_REPOSITORY}"
        )

    season = _integer(payload.get("season"), "season", 1869, 9999)
    week = _integer(payload.get("week"), "week", 0, 20)
    contest = _object(payload.get("contest"), "contest")
    if contest.get("source") != "SplashSports":
        raise WeeklyConfigurationError("contest.source must be exactly SplashSports")
    expected_count = _integer(
        contest.get("expected_lined_game_count"),
        "contest.expected_lined_game_count",
        1,
        200,
    )
    line_manifest = _object(payload.get("line_manifest"), "line_manifest")
    line_path = _path(
        line_manifest.get("path"),
        "line_manifest.path",
        config_path=config_path,
        repository_root=root,
    )
    provider_bundle_value = payload.get("provider_bundle")
    provider_bundle_path = None
    if provider_bundle_value is not None:
        provider_bundle_path = _path(
            provider_bundle_value,
            "provider_bundle",
            config_path=config_path,
            repository_root=root,
        )

    model = _object(payload.get("model"), "model")
    expected_model = {
        "name": ACTIVE_MODEL_NAME,
        "version": ACTIVE_MODEL_VERSION,
        "feature_schema_version": ACTIVE_FEATURE_SCHEMA_VERSION,
        "configuration_version": ACTIVE_CONFIGURATION_VERSION,
    }
    if dict(model) != expected_model:
        raise WeeklyConfigurationError(
            "model must identify only the locked EPA-only production baseline"
        )
    policies = _object(payload.get("policies"), "policies")
    policy_versions = tuple(
        (name, _text(policies.get(name), f"policies.{name}"))
        for name, _ in POLICY_ENVIRONMENT_VARIABLES
    )
    freshness = _object(payload.get("freshness"), "freshness")
    configured_rules = _object(
        freshness.get("max_age_seconds"), "freshness.max_age_seconds"
    )
    if (
        freshness.get("policy_version") != FRESHNESS_POLICY_VERSION
        or dict(configured_rules) != dict(DEFAULT_FRESHNESS_RULES)
    ):
        raise WeeklyConfigurationError(
            "freshness must exactly match the sanctioned provider_freshness_v1 rules"
        )

    daily = _object(payload.get("daily_refresh", {}), "daily_refresh")
    change_type = str(daily.get("change_type", "data_refresh")).strip()
    if change_type not in (
        "data_refresh",
        "contextual_adjustment",
        "bug_fix",
        "data_correction",
    ):
        raise WeeklyConfigurationError("daily_refresh.change_type is invalid")
    daily_reason = _text(
        daily.get("reason", "Governed daily production refresh."),
        "daily_refresh.reason",
    )
    closing_book = _text(payload.get("closing_book"), "closing_book")
    if closing_book.casefold() == "consensus":
        raise WeeklyConfigurationError("closing_book must name a real sportsbook")

    return WeeklyOperationConfiguration(
        path=config_path,
        season=season,
        week=week,
        contest_key=_text(contest.get("key"), "contest.key"),
        contest_name=_text(contest.get("name"), "contest.name"),
        source_contest_id=_text(
            contest.get("source_contest_id"), "contest.source_contest_id"
        ),
        expected_lined_game_count=expected_count,
        line_manifest_path=line_path,
        line_manifest_sha256=_sha256(
            line_manifest.get("sha256"), "line_manifest.sha256"
        ),
        provider_bundle_path=provider_bundle_path,
        display_timezone=_text(payload.get("display_timezone"), "display_timezone"),
        policy_versions=policy_versions,
        freshness_fallbacks=_records(
            payload.get("freshness_fallbacks"), "freshness_fallbacks"
        ),
        contextual_adjustments=_records(
            payload.get("contextual_adjustments"), "contextual_adjustments"
        ),
        sportsbook_recommendations=_records(
            payload.get("sportsbook_recommendations"),
            "sportsbook_recommendations",
        ),
        daily_change_type=change_type,
        daily_reason=daily_reason,
        closing_book=closing_book,
        actor=_text(payload.get("actor"), "actor"),
        provenance=_text(payload.get("provenance"), "provenance"),
    )


def merge_weekly_environment(
    environment: Mapping[str, str],
    configuration: WeeklyOperationConfiguration,
) -> dict[str, str]:
    """Merge auditable week values while rejecting conflicting environment state."""
    merged = dict(environment)
    for name, configured in configuration.environment_values().items():
        existing = str(merged.get(name, "")).strip()
        if existing and existing != configured:
            raise WeeklyConfigurationError(
                f"{name} conflicts with the weekly configuration file"
            )
        merged[name] = configured
    return merged
