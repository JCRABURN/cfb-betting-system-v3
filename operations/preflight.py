"""Read-only, machine-verifiable V3 production cutover preflight."""

from __future__ import annotations

import configparser
import hashlib
import json
import math
import re
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

from ingestion import (
    CanonicalTeamResolver,
    DEFAULT_FRESHNESS_RULES,
    FRESHNESS_POLICY_VERSION,
)
from ingestion.custody import SUPPORTED_DATA_TYPE_ORDER
from migrations.runner import LEDGER_TABLE, load_migrations
from scripts.verify_repo_safety import repository_errors

from operations.config import (
    ACTIVE_CONFIGURATION_VERSION,
    ACTIVE_FEATURE_SCHEMA_VERSION,
    ACTIVE_MODEL_NAME,
    ACTIVE_MODEL_VERSION,
    EXPECTED_REPOSITORY,
    ORIGINAL_REPOSITORY,
    PRODUCTION_OPERATIONS,
    ProductionSettings,
)


CONNECTIVITY_EVIDENCE_MAX_AGE = timedelta(hours=24)
LIVE_EXECUTION_ADAPTER_AVAILABLE = True
EXPECTED_POLICY_TABLES = (
    "weekly_controller_policies",
    "contest_selection_policies",
    "contest_ranking_policies",
    "manual_adjustment_policies",
    "card_refresh_policies",
    "postgame_audit_policies",
    "weekly_diagnostic_policies",
)


@dataclass(frozen=True)
class PreflightCheck:
    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class ProductionPreflightReport:
    operation: str
    idempotency_key: str
    generated_at: str
    production_ready: bool
    production_ready_status: str
    blocker_count: int
    warning_count: int
    checks: tuple[PreflightCheck, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]
    credential_variables_checked: tuple[str, ...]
    present_credential_variables: tuple[str, ...]
    missing_credential_variables: tuple[str, ...]
    source_database_sha256_before: str | None
    source_database_sha256_after: str | None
    source_database_unchanged: bool
    authoritative_database_rows_changed: int | None
    live_api_calls: int
    execution_attempted: bool
    report_sha256: str


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def _parse_utc(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(timezone.utc)


def _origin_repository(root: Path) -> str | None:
    git_path = root / ".git"
    config_path = git_path / "config"
    if git_path.is_file():
        try:
            pointer = git_path.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return None
        if pointer.casefold().startswith("gitdir:"):
            target = Path(pointer.split(":", 1)[1].strip())
            if not target.is_absolute():
                target = root / target
            config_path = target.resolve() / "config"
    if not config_path.is_file():
        return None
    parser = configparser.RawConfigParser()
    try:
        parser.read(config_path, encoding="utf-8")
    except (OSError, UnicodeError, configparser.Error):
        return None
    section = 'remote "origin"'
    if not parser.has_option(section, "url"):
        return None
    url = parser.get(section, "url").strip().split("?", 1)[0]
    match = re.search(
        r"github\.com[/:]([^/\s]+/[^/\s]+?)(?:\.git)?$",
        url,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def _record(
    checks: list[PreflightCheck],
    name: str,
    passed: bool,
    success: str,
    failure: str,
    *,
    warning: bool = False,
) -> None:
    status = "pass" if passed else ("warn" if warning else "block")
    checks.append(PreflightCheck(name, status, success if passed else failure))


def _configuration_checks(
    settings: ProductionSettings,
    *,
    now: datetime,
    checks: list[PreflightCheck],
    allow_disposable_database: bool,
) -> None:
    _record(
        checks,
        "runtime_mode",
        settings.runtime_mode == "production",
        "runtime mode is explicitly production",
        "CFB_V3_RUNTIME_MODE must be exactly production",
    )
    _record(
        checks,
        "production_enabled",
        settings.production_enabled is True,
        "the explicit V3 production flag is enabled",
        "CFB_V3_PRODUCTION_ENABLED must be exactly true",
    )
    _record(
        checks,
        "operation_execution_enabled",
        settings.operation_execution_enabled is True,
        "the separate operation-execution flag is enabled",
        "CFB_V3_OPERATION_EXECUTION_ENABLED must be exactly true",
    )
    _record(
        checks,
        "owner_cutover_approval",
        settings.owner_cutover_approved is True,
        "explicit owner cutover approval is recorded",
        "CFB_V3_OWNER_CUTOVER_APPROVED must be exactly true",
    )
    _record(
        checks,
        "kill_switch",
        settings.kill_switch is False,
        "the kill switch is explicitly disengaged",
        "CFB_V3_KILL_SWITCH is missing, invalid, or engaged",
    )
    _record(
        checks,
        "boolean_configuration",
        not settings.invalid_boolean_variables,
        "all safety booleans use exact true/false values",
        "missing or invalid booleans: "
        + ", ".join(settings.invalid_boolean_variables),
    )
    _record(
        checks,
        "operation",
        settings.operation in PRODUCTION_OPERATIONS,
        f"operation is recognized: {settings.operation}",
        f"operation must be one of: {', '.join(PRODUCTION_OPERATIONS)}",
    )
    expected_weekday = {
        "tuesday_lock": 1,
        "wednesday_refresh": 2,
        "thursday_refresh": 3,
        "friday_refresh": 4,
        "saturday_final": 5,
    }.get(settings.operation)
    timing_ok = expected_weekday is None or generated_at_weekday_is(
        now, expected_weekday
    )
    _record(
        checks,
        "operation_timing",
        timing_ok,
        "operation is running on its governed UTC weekday",
        "card-stage operation does not match its governed Tuesday-Saturday UTC day",
    )

    root_identity_ok = (
        settings.repository_root.name == "cfb-betting-system-v3"
        and settings.repository_root.name != "cfb-betting-system"
    )
    _record(
        checks,
        "repository_root_identity",
        root_identity_ok,
        "repository root is the isolated cfb-betting-system-v3 checkout",
        "repository root must end with cfb-betting-system-v3 and never the original name",
    )
    repository_values_ok = (
        settings.configured_repository == EXPECTED_REPOSITORY
        and settings.github_repository == EXPECTED_REPOSITORY
        and settings.configured_repository != ORIGINAL_REPOSITORY
    )
    _record(
        checks,
        "repository_allow_list",
        repository_values_ok,
        f"runtime and GitHub repository identities equal {EXPECTED_REPOSITORY}",
        "CFB_V3_REPOSITORY and GITHUB_REPOSITORY must both equal "
        + EXPECTED_REPOSITORY,
    )
    origin_repository = _origin_repository(settings.repository_root)
    _record(
        checks,
        "origin_remote",
        origin_repository is not None
        and origin_repository.casefold() == EXPECTED_REPOSITORY.casefold(),
        f"origin resolves to {EXPECTED_REPOSITORY}",
        "origin must resolve to the V3 repository; credentials and URL details are not logged",
    )
    expected_database = (settings.repository_root / "data" / "cfb.db").resolve()
    _record(
        checks,
        "write_path",
        settings.database_path == expected_database or allow_disposable_database,
        (
            "database target is an explicitly authorized disposable copy"
            if allow_disposable_database and settings.database_path != expected_database
            else "database write target is exactly the V3 authoritative database path"
        ),
        "CFB_V3_DATABASE_PATH must resolve exactly to data/cfb.db inside the V3 root",
    )

    provider_connectivity_required = settings.operation != "weekly_audit"
    _record(
        checks,
        "credentials",
        not settings.missing_credential_variables or not provider_connectivity_required,
        (
            "provider credentials are not needed for the API-free weekly audit"
            if not provider_connectivity_required
            else "required credential variable names are present; values were not read into the report"
        ),
        "missing credential variables: "
        + ", ".join(settings.missing_credential_variables),
    )
    _record(
        checks,
        "provider_connectivity_authorization",
        settings.provider_connectivity_authorized is True or not provider_connectivity_required,
        (
            "provider connectivity is not needed for the API-free weekly audit"
            if not provider_connectivity_required
            else "live provider connectivity has explicit authorization"
        ),
        "CFB_V3_PROVIDER_CONNECTIVITY_AUTHORIZED must be exactly true",
    )
    verified_at = _parse_utc(settings.provider_connectivity_verified_at)
    verification_current = not provider_connectivity_required or (
        verified_at is not None
        and verified_at <= now
        and now - verified_at <= CONNECTIVITY_EVIDENCE_MAX_AGE
    )
    _record(
        checks,
        "provider_connectivity_evidence",
        verification_current,
        (
            "provider connectivity evidence is not needed for the API-free weekly audit"
            if not provider_connectivity_required
            else "authorized provider connectivity evidence is no more than 24 hours old"
        ),
        "CFB_V3_PROVIDER_CONNECTIVITY_VERIFIED_AT must be a current UTC timestamp "
        "from an owner-authorized external check",
    )

    season_ok = (
        settings.season is not None
        and settings.season in {now.year, now.year - 1}
    )
    week_ok = settings.week is not None and 0 <= settings.week <= 20
    _record(
        checks,
        "season_and_week",
        season_ok and week_ok,
        f"configured season/week is {settings.season}/{settings.week}",
        "CFB_V3_SEASON must identify the current or immediately prior season and "
        "CFB_V3_WEEK must be between 0 and 20",
    )
    contest_ok = (
        bool(settings.contest_key)
        and bool(settings.contest_name)
        and bool(settings.source_contest_id)
        and settings.contest_source == "SplashSports"
        and settings.expected_lined_game_count is not None
        and settings.expected_lined_game_count > 0
    )
    _record(
        checks,
        "contest_configuration",
        contest_ok,
        "contest identity, authorized source, and expected lined-game count are explicit",
        "contest key, name, source contest id, SplashSports source, and a positive "
        "expected lined-game count are required",
    )

    model_ok = (
        settings.model_name == ACTIVE_MODEL_NAME
        and settings.model_version == ACTIVE_MODEL_VERSION
        and settings.feature_schema_version == ACTIVE_FEATURE_SCHEMA_VERSION
        and settings.configuration_version == ACTIVE_CONFIGURATION_VERSION
    )
    _record(
        checks,
        "production_model_contract",
        model_ok,
        "configured model is the locked EPA-only production baseline",
        "model identifiers must remain epa_only / epa-only-linear-v1 / "
        "epa-differential-v1 / walk-forward-prior-seasons-v1",
    )
    missing_policies = tuple(
        name for name, version in settings.policy_versions if not version
    )
    _record(
        checks,
        "policy_configuration",
        not missing_policies,
        "all eight active policy-version identifiers are explicit",
        "missing policy versions: " + ", ".join(missing_policies),
    )

    freshness_ok = (
        FRESHNESS_POLICY_VERSION == "provider_freshness_v1"
        and tuple(DEFAULT_FRESHNESS_RULES) == SUPPORTED_DATA_TYPE_ORDER
        and len(DEFAULT_FRESHNESS_RULES) == 5
        and all(value > 0 for value in DEFAULT_FRESHNESS_RULES.values())
    )
    freshness_detail = ", ".join(
        f"{name}={seconds}s" for name, seconds in DEFAULT_FRESHNESS_RULES.items()
    )
    _record(
        checks,
        "stale_data_thresholds",
        freshness_ok,
        f"{FRESHNESS_POLICY_VERSION}: {freshness_detail}",
        "the sanctioned five-source freshness policy is missing or invalid",
    )


def _migration_check(conn: sqlite3.Connection, checks: list[PreflightCheck]) -> bool:
    try:
        migrations = load_migrations()
    except Exception as exc:
        _record(
            checks,
            "migrations",
            False,
            "",
            f"migration definitions failed validation: {type(exc).__name__}",
        )
        return False
    if not _table_exists(conn, LEDGER_TABLE):
        _record(
            checks,
            "migrations",
            False,
            "",
            f"governed migration ledger is absent; versions 1-{len(migrations)} are pending",
        )
        return False
    applied = tuple(
        conn.execute(
            f"SELECT version, name, checksum FROM {LEDGER_TABLE} ORDER BY version"
        )
    )
    expected = tuple(
        (migration.version, migration.name, migration.checksum)
        for migration in migrations
    )
    _record(
        checks,
        "migrations",
        applied == expected,
        f"all governed migrations 1-{len(migrations)} are applied with matching checksums",
        "migration ledger is pending, out of order, or has a checksum mismatch",
    )
    return applied == expected


def generated_at_weekday_is(value: datetime, expected_weekday: int) -> bool:
    """Keep weekday validation explicit and easy to exercise adversarially."""
    return value.weekday() == expected_weekday


def _registered_policy_checks(
    conn: sqlite3.Connection,
    settings: ProductionSettings,
    now: datetime,
    checks: list[PreflightCheck],
) -> None:
    missing_tables = tuple(
        table for table in EXPECTED_POLICY_TABLES if not _table_exists(conn, table)
    )
    if missing_tables:
        _record(
            checks,
            "registered_policy_versions",
            False,
            "",
            "policy tables are unavailable until governed migrations are applied: "
            + ", ".join(missing_tables),
        )
        return
    versions = dict(settings.policy_versions)
    effective_at = now.isoformat()
    queries = (
        (
            "controller",
            "SELECT 1 FROM weekly_controller_policies WHERE policy_version = ? "
            "AND authorized_contest_source = 'SplashSports' "
            "AND production_model_name = ? AND production_model_version = ? "
            "AND production_feature_schema_version = ? "
            "AND production_configuration_version = ? "
            "AND freshness_policy_version = ? AND required_source_count = 5 "
            "AND julianday(effective_at) <= julianday(?) "
            "AND 5 = (SELECT COUNT(*) FROM weekly_controller_policy_sources AS source "
            "WHERE source.controller_policy_id = weekly_controller_policies.id)",
            (
                versions.get("controller", ""),
                ACTIVE_MODEL_NAME,
                ACTIVE_MODEL_VERSION,
                ACTIVE_FEATURE_SCHEMA_VERSION,
                ACTIVE_CONFIGURATION_VERSION,
                FRESHNESS_POLICY_VERSION,
                effective_at,
            ),
        ),
        (
            "selection",
            "SELECT 1 FROM contest_selection_policies WHERE policy_version = ? "
            "AND julianday(effective_at) <= julianday(?) "
            "AND NOT EXISTS (SELECT 1 FROM contest_selection_policy_books AS book "
            "WHERE book.selection_policy_id = contest_selection_policies.id)",
            (versions.get("selection", ""), effective_at),
        ),
        (
            "confidence/ranking",
            "SELECT 1 FROM contest_ranking_policies "
            "WHERE confidence_policy_version = ? AND ranking_policy_version = ? "
            "AND julianday(effective_at) <= julianday(?)",
            (
                versions.get("confidence", ""),
                versions.get("ranking", ""),
                effective_at,
            ),
        ),
        (
            "adjustment",
            "SELECT 1 FROM manual_adjustment_policies WHERE policy_version = ? "
            "AND julianday(effective_at) <= julianday(?)",
            (versions.get("adjustment", ""), effective_at),
        ),
        (
            "refresh",
            "SELECT 1 FROM card_refresh_policies WHERE policy_version = ? "
            "AND julianday(effective_at) <= julianday(?)",
            (versions.get("refresh", ""), effective_at),
        ),
        (
            "audit",
            "SELECT 1 FROM postgame_audit_policies WHERE policy_version = ? "
            "AND julianday(effective_at) <= julianday(?)",
            (versions.get("audit", ""), effective_at),
        ),
        (
            "diagnostics",
            "SELECT 1 FROM weekly_diagnostic_policies WHERE policy_version = ? "
            "AND julianday(effective_at) <= julianday(?)",
            (versions.get("diagnostics", ""), effective_at),
        ),
    )
    missing = tuple(
        label for label, sql, params in queries if conn.execute(sql, params).fetchone() is None
    )
    _record(
        checks,
        "registered_policy_versions",
        not missing,
        "all configured policy versions are immutably registered",
        "unregistered or mismatched policy versions: " + ", ".join(missing),
    )


def _line_manifest_check(
    conn: sqlite3.Connection,
    settings: ProductionSettings,
    now: datetime,
    checks: list[PreflightCheck],
) -> bool:
    path = settings.contest_lines_path
    if path is None:
        _record(
            checks,
            "contest_line_manifest",
            False,
            "",
            "CFB_V3_CONTEST_LINES_FILE is required",
        )
        return False
    try:
        inside_root = path.is_relative_to(settings.repository_root)
    except ValueError:
        inside_root = False
    if not inside_root or not path.is_file():
        _record(
            checks,
            "contest_line_manifest",
            False,
            "",
            "contest-line manifest must be a file inside the V3 repository root",
        )
        return False
    actual_sha256 = _file_sha256(path)
    expected_sha256 = settings.contest_lines_sha256
    digest_ok = (
        len(expected_sha256) == 64
        and all(character in "0123456789abcdef" for character in expected_sha256)
        and actual_sha256 == expected_sha256
    )
    if not digest_ok:
        _record(
            checks,
            "contest_line_manifest",
            False,
            "",
            "contest-line manifest SHA-256 is missing, malformed, or mismatched",
        )
        return False
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _record(
            checks,
            "contest_line_manifest",
            False,
            "",
            "contest-line manifest is not valid UTF-8 JSON",
        )
        return False
    if not isinstance(payload, dict) or not isinstance(payload.get("lines"), list):
        _record(
            checks,
            "contest_line_manifest",
            False,
            "",
            "contest-line manifest must be an object containing a lines array",
        )
        return False
    lines = payload["lines"]
    header_ok = (
        payload.get("manifest_version") == "v3-contest-lines-v1"
        and payload.get("repository") == EXPECTED_REPOSITORY
        and payload.get("source") == "SplashSports"
        and payload.get("season") == settings.season
        and payload.get("week") == settings.week
        and payload.get("contest_key") == settings.contest_key
        and payload.get("source_contest_id") == settings.source_contest_id
        and payload.get("expected_lined_game_count")
        == settings.expected_lined_game_count
        and len(lines) == settings.expected_lined_game_count
    )
    line_shapes_ok = True
    source_line_ids: set[str] = set()
    raw_matchups: set[tuple[str, str]] = set()
    normalized_seen: set[tuple[str, str]] = set()
    normalized_matchups: list[tuple[str, str]] = []
    resolver: CanonicalTeamResolver | None = None
    if _table_exists(conn, "provider_team_aliases") and _table_exists(conn, "teams"):
        resolver = CanonicalTeamResolver.from_connection(conn)
    for line in lines:
        if not isinstance(line, dict):
            line_shapes_ok = False
            continue
        home = line.get("raw_home_team")
        away = line.get("raw_away_team")
        line_id = line.get("source_line_id")
        spread = line.get("home_spread")
        total = line.get("total")
        valid_spread = (
            isinstance(spread, (int, float))
            and not isinstance(spread, bool)
            and math.isfinite(float(spread))
        )
        valid_total = total is None or (
            isinstance(total, (int, float))
            and not isinstance(total, bool)
            and math.isfinite(float(total))
            and float(total) >= 0
        )
        if (
            not isinstance(home, str)
            or not home.strip()
            or not isinstance(away, str)
            or not away.strip()
            or home.strip().casefold() == away.strip().casefold()
            or not isinstance(line_id, str)
            or not line_id.strip()
            or not valid_spread
            or not valid_total
        ):
            line_shapes_ok = False
            continue
        raw_pair = (home.strip().casefold(), away.strip().casefold())
        if (
            line_id.strip() in source_line_ids
            or raw_pair in raw_matchups
            or (raw_pair[1], raw_pair[0]) in raw_matchups
        ):
            line_shapes_ok = False
            continue
        source_line_ids.add(line_id.strip())
        raw_matchups.add(raw_pair)
        if resolver is None:
            line_shapes_ok = False
            continue
        home_resolution = resolver.resolve("SplashSports", home)
        away_resolution = resolver.resolve("SplashSports", away)
        if (
            home_resolution.status != "resolved"
            or away_resolution.status != "resolved"
            or home_resolution.canonical_name is None
            or away_resolution.canonical_name is None
        ):
            line_shapes_ok = False
            continue
        normalized_pair = (
            home_resolution.canonical_name,
            away_resolution.canonical_name,
        )
        if (
            normalized_pair in normalized_seen
            or (normalized_pair[1], normalized_pair[0]) in normalized_seen
        ):
            line_shapes_ok = False
            continue
        normalized_seen.add(normalized_pair)
        normalized_matchups.append(normalized_pair)
    games_ok = len(normalized_matchups) == len(lines)
    if games_ok and settings.season is not None and settings.week is not None:
        for home, away in normalized_matchups:
            game_rows = conn.execute(
                "SELECT start_date FROM games WHERE season = ? AND week = ? "
                "AND home_team = ? AND away_team = ?",
                (settings.season, settings.week, home, away),
            ).fetchall()
            kickoff = _parse_utc(game_rows[0][0]) if len(game_rows) == 1 else None
            pre_kickoff = (
                settings.operation not in PRODUCTION_OPERATIONS[:5]
                or (kickoff is not None and now < kickoff)
            )
            if len(game_rows) != 1 or not pre_kickoff:
                games_ok = False
                break
    manifest_ok = header_ok and line_shapes_ok and games_ok
    _record(
        checks,
        "contest_line_manifest",
        manifest_ok,
        "authorized line manifest hash, identity, uniqueness, normalization, and "
        "game mappings are complete",
        "contest-line manifest identity, line shape, uniqueness, normalization, "
        "or season/week game mapping is invalid",
    )
    return manifest_ok


def _line_lock_readiness(
    conn: sqlite3.Connection,
    settings: ProductionSettings,
    manifest_valid: bool,
    checks: list[PreflightCheck],
) -> None:
    required_tables = (
        "contests",
        "contest_locked_lines",
        "official_card_publications",
        "weekly_controller_runs",
    )
    if not manifest_valid or any(not _table_exists(conn, table) for table in required_tables):
        _record(
            checks,
            "line_lock_readiness",
            False,
            "",
            "line-lock readiness requires a valid manifest and the governed controller schema",
        )
        return
    contest = conn.execute(
        "SELECT id, name, season, week, source, source_contest_id FROM contests "
        "WHERE contest_key = ? AND season = ? AND week = ?",
        (settings.contest_key, settings.season, settings.week),
    ).fetchone()
    if contest is None:
        _record(
            checks,
            "line_lock_readiness",
            settings.operation == "tuesday_lock",
            "no prior contest or lock exists; Tuesday can perform the first immutable lock",
            "the configured contest must already exist for every post-Tuesday operation",
        )
        return
    contest_id, name, season, week, source, source_contest_id = contest
    identity_ok = (
        name == settings.contest_name
        and season == settings.season
        and week == settings.week
        and source == "SplashSports"
        and source_contest_id == settings.source_contest_id
    )
    locked_count = conn.execute(
        "SELECT COUNT(*) FROM contest_locked_lines WHERE contest_id = ?",
        (contest_id,),
    ).fetchone()[0]
    locked_fingerprint = tuple(
        (
            row[0],
            row[1],
            float(row[2]),
            None if row[3] is None else float(row[3]),
            row[4],
            row[5],
            row[6],
        )
        for row in conn.execute(
            "SELECT raw_home_team, raw_away_team, home_spread, total, "
            "source_line_id, source, payload_sha256 FROM contest_locked_lines "
            "WHERE contest_id = ? ORDER BY source_line_id",
            (contest_id,),
        )
    )
    try:
        manifest_payload = json.loads(
            settings.contest_lines_path.read_text(encoding="utf-8")
        )
        manifest_fingerprint = tuple(
            sorted(
                [
                    (
                        line["raw_home_team"].strip(),
                        line["raw_away_team"].strip(),
                        float(line["home_spread"]),
                        None if line.get("total") is None else float(line["total"]),
                        line["source_line_id"].strip(),
                        "SplashSports",
                        settings.contest_lines_sha256,
                    )
                    for line in manifest_payload["lines"]
                ],
                key=lambda item: item[4],
            )
        )
    except (AttributeError, KeyError, OSError, TypeError, ValueError):
        manifest_fingerprint = ()
    locks_match_manifest = locked_fingerprint == manifest_fingerprint
    max_version = conn.execute(
        "SELECT COALESCE(MAX(card_version), 0) FROM official_card_publications "
        "WHERE contest_id = ?",
        (contest_id,),
    ).fetchone()[0]
    expected_count = settings.expected_lined_game_count or -1
    if settings.operation == "tuesday_lock":
        ready = (
            identity_ok
            and locked_count == expected_count
            and locks_match_manifest
            and max_version >= 1
        )
        failure = (
            "an existing contest is partial or conflicts with the configured identity; "
            "never relock or repair it in place"
        )
        success = "Tuesday operation already has a complete immutable v1 and is idempotent"
    else:
        required_version = {
            "wednesday_refresh": 1,
            "thursday_refresh": 2,
            "friday_refresh": 3,
            "saturday_final": 4,
            "postgame_grading": 5,
            "weekly_audit": 5,
        }.get(settings.operation, 999)
        ready = (
            identity_ok
            and locked_count == expected_count
            and locks_match_manifest
            and max_version >= required_version
        )
        success = (
            f"immutable lock count is {locked_count}; prerequisite official card "
            f"version {required_version} is present"
        )
        failure = (
            "contest identity, immutable lock count, or prior official publication "
            "sequence is incomplete"
        )
    _record(checks, "line_lock_readiness", ready, success, failure)


def _postgame_stage_readiness(
    conn: sqlite3.Connection,
    settings: ProductionSettings,
    checks: list[PreflightCheck],
) -> None:
    if settings.operation not in ("postgame_grading", "weekly_audit"):
        return
    required_tables = (
        "contests",
        "contest_locked_lines",
        "official_card_publications",
        "contest_cards",
        "card_postgame_audit_runs",
        "card_postgame_audit_completions",
    )
    if any(not _table_exists(conn, table) for table in required_tables):
        _record(
            checks,
            "postgame_stage_readiness",
            False,
            "",
            "postgame stage requires the complete governed publication and audit schema",
        )
        return
    contest = conn.execute(
        "SELECT id FROM contests WHERE contest_key = ? AND season = ? AND week = ?",
        (settings.contest_key, settings.season, settings.week),
    ).fetchone()
    if contest is None:
        _record(
            checks,
            "postgame_stage_readiness",
            False,
            "",
            "postgame stage requires the configured contest",
        )
        return
    publication = conn.execute(
        "SELECT publication.card_id FROM official_card_publications AS publication "
        "WHERE publication.contest_id = ? ORDER BY publication.card_version DESC LIMIT 1",
        (contest[0],),
    ).fetchone()
    if publication is None:
        _record(
            checks,
            "postgame_stage_readiness",
            False,
            "",
            "postgame stage requires a final official publication",
        )
        return
    card_id = publication[0]
    if settings.operation == "postgame_grading":
        expected = settings.expected_lined_game_count or -1
        ready_count = conn.execute(
            "SELECT COUNT(*) FROM contest_locked_lines AS locked "
            "JOIN games AS game ON game.game_id = locked.game_id "
            "WHERE locked.contest_id = ? AND game.completed = 1 "
            "AND game.home_points IS NOT NULL AND game.away_points IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM betting_lines AS closing "
            "WHERE closing.game_id = game.game_id AND closing.line_type = 'closing' "
            "AND julianday(closing.fetched_at) >= (SELECT julianday(generated_at) "
            "FROM contest_cards WHERE id = ?) "
            "AND julianday(closing.fetched_at) <= julianday(game.start_date))",
            (contest[0], card_id),
        ).fetchone()[0]
        _record(
            checks,
            "postgame_stage_readiness",
            ready_count == expected,
            "every final pick has a completed game and point-in-time closing line",
            "postgame grading requires completed scores and a pre-kickoff closing line "
            "for every locked game",
        )
        return
    completed_audit = conn.execute(
        "SELECT 1 FROM card_postgame_audit_runs AS run "
        "JOIN card_postgame_audit_completions AS completion "
        "ON completion.audit_run_id = run.id WHERE run.card_id = ? LIMIT 1",
        (card_id,),
    ).fetchone()
    _record(
        checks,
        "postgame_stage_readiness",
        completed_audit is not None,
        "the final official card has a completed postgame audit",
        "weekly audit requires a completed postgame audit for the final official card",
    )


def _idempotency_check(
    conn: sqlite3.Connection,
    settings: ProductionSettings,
    checks: list[PreflightCheck],
) -> None:
    key = settings.idempotency_key
    if settings.operation in PRODUCTION_OPERATIONS[:5]:
        if not _table_exists(conn, "weekly_controller_runs"):
            _record(
                checks,
                "idempotency",
                False,
                "",
                "weekly controller idempotency ledger is unavailable",
            )
            return
        row = conn.execute(
            "SELECT status FROM weekly_controller_runs WHERE run_key = ?",
            (key,),
        ).fetchone()
        passed = row is None or row[0] == "completed"
        detail = (
            "operation key is unused and reserved for one atomic execution"
            if row is None
            else "completed operation key will replay idempotently"
        )
        _record(
            checks,
            "idempotency",
            passed,
            detail,
            "operation key belongs to a failed attempt and cannot be silently reused",
        )
        return
    table, key_column, completion_table, join_column = (
        (
            "card_postgame_audit_runs",
            "audit_run_key",
            "card_postgame_audit_completions",
            "audit_run_id",
        )
        if settings.operation == "postgame_grading"
        else (
            "weekly_diagnostic_runs",
            "diagnostic_run_key",
            "weekly_diagnostic_completions",
            "diagnostic_run_id",
        )
    )
    if not _table_exists(conn, table) or not _table_exists(conn, completion_table):
        _record(
            checks,
            "idempotency",
            False,
            "",
            "postgame idempotency ledger is unavailable",
        )
        return
    row = conn.execute(
        f"SELECT id FROM {table} WHERE {key_column} = ?",
        (key,),
    ).fetchone()
    completed = row is not None and conn.execute(
        f"SELECT 1 FROM {completion_table} WHERE {join_column} = ?",
        (row[0],),
    ).fetchone() is not None
    passed = row is None or completed
    _record(
        checks,
        "idempotency",
        passed,
        (
            "operation key is unused and reserved for one atomic execution"
            if row is None
            else "completed postgame operation will replay idempotently"
        ),
        "operation key identifies an incomplete postgame run and requires recovery review",
    )


def _database_checks(
    settings: ProductionSettings,
    now: datetime,
    checks: list[PreflightCheck],
) -> tuple[str | None, str | None]:
    path = settings.database_path
    if not path.is_file():
        _record(
            checks,
            "database_exists",
            False,
            "",
            "configured authoritative database does not exist",
        )
        return None, None
    try:
        before = _file_sha256(path)
    except OSError as exc:
        _record(
            checks,
            "database_access",
            False,
            "",
            f"database hash failed safely: {type(exc).__name__}",
        )
        return None, None
    _record(
        checks,
        "database_exists",
        True,
        "authoritative database exists and was opened read-only",
        "",
    )
    uri = f"file:{quote(path.as_posix(), safe='/:')}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.execute("PRAGMA query_only = ON")
    except sqlite3.Error as exc:
        _record(
            checks,
            "database_access",
            False,
            "",
            f"read-only database open failed safely: {type(exc).__name__}",
        )
        try:
            after_open_failure = _file_sha256(path)
        except OSError:
            after_open_failure = None
        return before, after_open_failure
    try:
        try:
            integrity_rows = tuple(
                row[0] for row in conn.execute("PRAGMA integrity_check")
            )
            _record(
                checks,
                "database_integrity",
                integrity_rows == ("ok",),
                "SQLite integrity_check is ok",
                f"SQLite integrity_check failed with {len(integrity_rows)} result rows",
            )
            foreign_key_violations = tuple(conn.execute("PRAGMA foreign_key_check"))
            _record(
                checks,
                "foreign_keys",
                not foreign_key_violations,
                "SQLite foreign_key_check found zero violations",
                f"SQLite foreign_key_check found {len(foreign_key_violations)} violations",
            )
            _migration_check(conn, checks)
            if settings.season is not None and settings.week is not None:
                game_count = conn.execute(
                    "SELECT COUNT(*) FROM games WHERE season = ? AND week = ?",
                    (settings.season, settings.week),
                ).fetchone()[0]
            else:
                game_count = 0
            _record(
                checks,
                "season_week_database_coverage",
                game_count > 0,
                f"database contains {game_count} games for the configured season/week",
                "database contains no games for the configured season/week",
            )
            _registered_policy_checks(conn, settings, now, checks)
            manifest_valid = _line_manifest_check(conn, settings, now, checks)
            _line_lock_readiness(conn, settings, manifest_valid, checks)
            _postgame_stage_readiness(conn, settings, checks)
            _idempotency_check(conn, settings, checks)
        except (OSError, ValueError, sqlite3.Error) as exc:
            _record(
                checks,
                "database_verification",
                False,
                "",
                f"database verification failed safely: {type(exc).__name__}",
            )
    finally:
        conn.close()
    try:
        after = _file_sha256(path)
    except OSError as exc:
        _record(
            checks,
            "read_only_database_verification",
            False,
            "",
            f"post-preflight database hash failed safely: {type(exc).__name__}",
        )
        return before, None
    _record(
        checks,
        "read_only_database_verification",
        before == after,
        "database SHA-256 is unchanged after all preflight checks",
        "database SHA-256 changed during read-only preflight",
    )
    return before, after


def run_production_preflight(
    settings: ProductionSettings,
    *,
    now: datetime | None = None,
    allow_disposable_database: bool = False,
) -> ProductionPreflightReport:
    """Run every cutover gate without applying migrations, calling APIs, or writing."""
    generated_at = now or datetime.now(timezone.utc)
    if generated_at.tzinfo is None or generated_at.utcoffset() != timedelta(0):
        raise ValueError("preflight now must be timezone-aware UTC")
    generated_at = generated_at.astimezone(timezone.utc)
    checks: list[PreflightCheck] = []
    _configuration_checks(
        settings,
        now=generated_at,
        checks=checks,
        allow_disposable_database=allow_disposable_database,
    )

    try:
        safety_errors = repository_errors(settings.repository_root)
    except (OSError, UnicodeError, ValueError) as exc:
        safety_errors = [f"safety inspection failed safely: {type(exc).__name__}"]
    _record(
        checks,
        "workflow_and_dependency_safety",
        not safety_errors,
        "repository workflow and dependency safety controls pass",
        "repository safety errors: " + " | ".join(safety_errors),
    )
    before, after = _database_checks(settings, generated_at, checks)
    _record(
        checks,
        "authorized_execution_adapter",
        LIVE_EXECUTION_ADAPTER_AVAILABLE,
        "an owner-authorized V3 execution adapter is installed",
        "production execution adapter availability check failed",
    )

    blockers = tuple(check.detail for check in checks if check.status == "block")
    warnings = tuple(check.detail for check in checks if check.status == "warn")
    ready = not blockers
    payload: dict[str, object] = {
        "operation": settings.operation,
        "idempotency_key": settings.idempotency_key,
        "generated_at": generated_at.isoformat(),
        "production_ready": ready,
        "production_ready_status": f"PRODUCTION READY: {'YES' if ready else 'NO'}",
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
        "checks": tuple(checks),
        "blockers": blockers,
        "warnings": warnings,
        "credential_variables_checked": tuple(
            sorted(
                settings.present_credential_variables
                + settings.missing_credential_variables
            )
        ),
        "present_credential_variables": settings.present_credential_variables,
        "missing_credential_variables": settings.missing_credential_variables,
        "source_database_sha256_before": before,
        "source_database_sha256_after": after,
        "source_database_unchanged": before is not None and before == after,
        "authoritative_database_rows_changed": (
            0 if before is not None and before == after else None
        ),
        "live_api_calls": 0,
        "execution_attempted": False,
    }
    canonical_payload = {
        key: (
            [asdict(item) for item in value]
            if key == "checks"
            else value
        )
        for key, value in payload.items()
    }
    payload["report_sha256"] = _canonical_sha256(canonical_payload)
    return ProductionPreflightReport(**payload)
