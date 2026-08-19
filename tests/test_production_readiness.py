import hashlib
import json
import shutil
import sqlite3
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

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
from migrations.runner import apply_migrations
from operations import (
    EXPECTED_REPOSITORY,
    PRODUCTION_OPERATIONS,
    load_production_settings,
    run_production_preflight,
)
from scripts.production_preflight import main as preflight_main
from scripts.run_production_operation import main as operation_main


ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_DATABASE = ROOT / "data" / "cfb.db"
NOW = datetime(2026, 8, 18, 12, tzinfo=timezone.utc)
SECRET_SENTINELS = ("cfbd-secret-must-never-print", "odds-secret-must-never-print")
POLICY_VERSIONS = {
    "controller": "production-controller-v1",
    "selection": "production-selection-v1",
    "confidence": "production-confidence-v1",
    "ranking": "production-ranking-v1",
    "adjustment": "production-adjustment-v1",
    "refresh": "production-refresh-v1",
    "audit": "production-audit-v1",
    "diagnostics": "production-diagnostics-v1",
}
LINE_GAMES = (
    (401856634, "East Carolina", "Alabama", -28.5),
    (401856636, "Baylor", "Auburn", -2.5),
    (401856637, "Florida Atlantic", "Florida", -31.5),
    (401856660, "Clemson", "LSU", -3.5),
    (401856661, "Louisville", "Ole Miss", -6.5),
    (401856662, "UL Monroe", "Mississippi State", -24.5),
)


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _register_policies(database: Path) -> None:
    effective_at = datetime(2026, 8, 1, tzinfo=timezone.utc)
    provenance = "test-only-registered-policy-fixture"
    actor = "production-readiness-test"
    conn = sqlite3.connect(database)
    conn.execute("PRAGMA foreign_keys = ON")
    register_weekly_controller_policy(
        conn,
        WeeklyControllerPolicy(
            policy_version=POLICY_VERSIONS["controller"],
            authorized_contest_source="SplashSports",
            required_sources=tuple(
                RequiredSourcePolicy(
                    data_type,
                    "production-provider",
                    f"{data_type}_documented_fallback_v1",
                )
                for data_type in (
                    "odds",
                    "injuries",
                    "weather",
                    "game_status",
                    "contextual",
                )
            ),
            effective_at=effective_at,
            created_by=actor,
            provenance=provenance,
        ),
    )
    register_contest_selection_policy(
        conn,
        FullCardPolicy(POLICY_VERSIONS["selection"], ()),
        effective_at=effective_at,
        created_by=actor,
        provenance=provenance,
    )
    register_confidence_ranking_policy(
        conn,
        ConfidenceRankingPolicy(
            policy_key="production-confidence-ranking-v1",
            confidence_policy_version=POLICY_VERSIONS["confidence"],
            ranking_policy_version=POLICY_VERSIONS["ranking"],
            confidence_5_max_uncertainty=2.0,
            confidence_4_max_uncertainty=4.0,
            confidence_3_max_uncertainty=6.0,
            confidence_2_max_uncertainty=8.0,
            effective_at=effective_at,
            created_by=actor,
            provenance=provenance,
        ),
    )
    register_manual_adjustment_policy(
        conn,
        ManualAdjustmentPolicy(
            POLICY_VERSIONS["adjustment"], effective_at, actor, provenance
        ),
    )
    register_daily_refresh_policy(
        conn,
        DailyRefreshPolicy(POLICY_VERSIONS["refresh"], effective_at, actor, provenance),
    )
    register_postgame_audit_policy(
        conn,
        PostgameAuditPolicy(POLICY_VERSIONS["audit"], effective_at, actor, provenance),
    )
    register_weekly_diagnostics_policy(
        conn,
        WeeklyDiagnosticsPolicy(
            policy_version=POLICY_VERSIONS["diagnostics"],
            minimum_recommendation_sample=20,
            minimum_ats_delta_percentage_points=10.0,
            confidence_threshold_step_points=0.5,
            effective_at=effective_at,
            created_by=actor,
            provenance=provenance,
        ),
    )
    conn.commit()
    conn.close()


def _line_manifest() -> dict[str, object]:
    return {
        "manifest_version": "v3-contest-lines-v1",
        "repository": EXPECTED_REPOSITORY,
        "source": "SplashSports",
        "season": 2026,
        "week": 1,
        "contest_key": "splashsports-2026-week-1",
        "source_contest_id": "splashsports-2026-week-1",
        "expected_lined_game_count": len(LINE_GAMES),
        "lines": [
            {
                "source_line_id": f"line-{game_id}",
                "raw_away_team": away,
                "raw_home_team": home,
                "home_spread": spread,
                "total": 50.5,
            }
            for game_id, away, home, spread in LINE_GAMES
        ],
    }


def _valid_environment(line_path: Path) -> dict[str, str]:
    environment = {
        "CFB_V3_RUNTIME_MODE": "production",
        "CFB_V3_PRODUCTION_ENABLED": "true",
        "CFB_V3_OPERATION_EXECUTION_ENABLED": "true",
        "CFB_V3_KILL_SWITCH": "false",
        "CFB_V3_OWNER_CUTOVER_APPROVED": "true",
        "CFB_V3_REPOSITORY": EXPECTED_REPOSITORY,
        "GITHUB_REPOSITORY": EXPECTED_REPOSITORY,
        "CFB_V3_PROVIDER_CONNECTIVITY_AUTHORIZED": "true",
        "CFB_V3_PROVIDER_CONNECTIVITY_VERIFIED_AT": (
            NOW - timedelta(hours=1)
        ).isoformat(),
        "CFB_V3_SEASON": "2026",
        "CFB_V3_WEEK": "1",
        "CFB_V3_CONTEST_KEY": "splashsports-2026-week-1",
        "CFB_V3_CONTEST_NAME": "SplashSports 2026 Week 1",
        "CFB_V3_SOURCE_CONTEST_ID": "splashsports-2026-week-1",
        "CFB_V3_CONTEST_SOURCE": "SplashSports",
        "CFB_V3_EXPECTED_LINED_GAME_COUNT": str(len(LINE_GAMES)),
        "CFB_V3_CONTEST_LINES_FILE": str(line_path),
        "CFB_V3_CONTEST_LINES_SHA256": _file_sha256(line_path),
        "CFB_V3_MODEL_NAME": "epa_only",
        "CFB_V3_MODEL_VERSION": "epa-only-linear-v1",
        "CFB_V3_FEATURE_SCHEMA_VERSION": "epa-differential-v1",
        "CFB_V3_CONFIGURATION_VERSION": "walk-forward-prior-seasons-v1",
        "CFB_V3_CONTROLLER_POLICY_VERSION": POLICY_VERSIONS["controller"],
        "CFB_V3_SELECTION_POLICY_VERSION": POLICY_VERSIONS["selection"],
        "CFB_V3_CONFIDENCE_POLICY_VERSION": POLICY_VERSIONS["confidence"],
        "CFB_V3_RANKING_POLICY_VERSION": POLICY_VERSIONS["ranking"],
        "CFB_V3_ADJUSTMENT_POLICY_VERSION": POLICY_VERSIONS["adjustment"],
        "CFB_V3_REFRESH_POLICY_VERSION": POLICY_VERSIONS["refresh"],
        "CFB_V3_AUDIT_POLICY_VERSION": POLICY_VERSIONS["audit"],
        "CFB_V3_DIAGNOSTICS_POLICY_VERSION": POLICY_VERSIONS["diagnostics"],
        "CFBD_API_KEY": SECRET_SENTINELS[0],
        "ODDS_API_KEY": SECRET_SENTINELS[1],
    }
    return environment


@pytest.fixture(scope="module")
def near_ready_repository(tmp_path_factory):
    root = tmp_path_factory.mktemp("cutover") / "cfb-betting-system-v3"
    (root / "data").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text(
        '[remote "origin"]\n'
        "\turl = https://github.com/JCRABURN/cfb-betting-system-v3.git\n",
        encoding="utf-8",
    )
    shutil.copytree(ROOT / ".github", root / ".github")
    shutil.copy2(ROOT / "requirements.txt", root / "requirements.txt")
    shutil.copy2(ROOT / "requirements-dev.txt", root / "requirements-dev.txt")
    database = root / "data" / "cfb.db"
    shutil.copy2(AUTHORITATIVE_DATABASE, database)
    conn = sqlite3.connect(database)
    apply_migrations(conn)
    conn.close()
    _register_policies(database)
    line_path = root / "contest-lines.json"
    line_path.write_text(
        json.dumps(_line_manifest(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    return root, database, line_path


def _report(root: Path, database: Path, environment: dict[str, str], operation: str):
    settings = load_production_settings(
        environment,
        repository_root=root,
        operation=operation,
        database_path=database,
    )
    return run_production_preflight(settings, now=NOW)


def test_all_implemented_gates_pass_before_the_explicit_adapter_blocker(
    near_ready_repository,
):
    root, database, line_path = near_ready_repository
    before = _file_sha256(database)
    report = _report(
        root,
        database,
        _valid_environment(line_path),
        "tuesday_lock",
    )

    assert report.production_ready is False
    assert report.production_ready_status == "PRODUCTION READY: NO"
    assert report.blocker_count == 1
    assert "no owner-authorized live execution adapter" in report.blockers[0]
    assert all(
        check.status == "pass" or check.name == "authorized_execution_adapter"
        for check in report.checks
    )
    assert report.source_database_unchanged is True
    assert report.authoritative_database_rows_changed == 0
    assert report.live_api_calls == 0
    assert report.execution_attempted is False
    assert _file_sha256(database) == before


@pytest.mark.parametrize("operation", PRODUCTION_OPERATIONS)
def test_kill_switch_blocks_every_operating_stage(
    near_ready_repository,
    operation,
):
    root, database, line_path = near_ready_repository
    environment = _valid_environment(line_path)
    environment["CFB_V3_KILL_SWITCH"] = "true"
    before = _file_sha256(database)

    report = _report(root, database, environment, operation)

    kill_check = next(check for check in report.checks if check.name == "kill_switch")
    assert kill_check.status == "block"
    assert report.production_ready is False
    assert report.execution_attempted is False
    assert _file_sha256(database) == before


def test_secret_values_never_enter_settings_or_report(near_ready_repository):
    root, database, line_path = near_ready_repository
    environment = _valid_environment(line_path)
    settings = load_production_settings(
        environment,
        repository_root=root,
        operation="tuesday_lock",
        database_path=database,
    )
    report = run_production_preflight(settings, now=NOW)
    serialized = json.dumps(asdict(report), sort_keys=True)

    assert settings.present_credential_variables == ("CFBD_API_KEY", "ODDS_API_KEY")
    assert settings.missing_credential_variables == ()
    assert all(secret not in repr(settings) for secret in SECRET_SENTINELS)
    assert all(secret not in serialized for secret in SECRET_SENTINELS)


def test_wrong_weekday_and_missing_prior_postgame_state_fail_closed(
    near_ready_repository,
):
    root, database, line_path = near_ready_repository
    settings = load_production_settings(
        _valid_environment(line_path),
        repository_root=root,
        operation="tuesday_lock",
        database_path=database,
    )
    wrong_day = run_production_preflight(settings, now=NOW + timedelta(days=1))
    timing = next(check for check in wrong_day.checks if check.name == "operation_timing")
    assert timing.status == "block"

    weekly = _report(
        root,
        database,
        _valid_environment(line_path),
        "weekly_audit",
    )
    postgame = next(
        check for check in weekly.checks if check.name == "postgame_stage_readiness"
    )
    assert postgame.status == "block"


def test_reversed_duplicate_line_manifest_fails_closed(near_ready_repository):
    root, database, line_path = near_ready_repository
    payload = _line_manifest()
    first = payload["lines"][0]
    second = payload["lines"][1]
    second["raw_home_team"] = first["raw_away_team"]
    second["raw_away_team"] = first["raw_home_team"]
    line_path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    environment = _valid_environment(line_path)
    before = _file_sha256(database)

    report = _report(root, database, environment, "tuesday_lock")

    manifest_check = next(
        check for check in report.checks if check.name == "contest_line_manifest"
    )
    assert manifest_check.status == "block"
    assert report.production_ready is False
    assert _file_sha256(database) == before
    line_path.write_text(
        json.dumps(_line_manifest(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def test_original_repository_identity_is_rejected(near_ready_repository):
    root, database, line_path = near_ready_repository
    environment = _valid_environment(line_path)
    environment["CFB_V3_REPOSITORY"] = "JCRABURN/cfb-betting-system"
    environment["GITHUB_REPOSITORY"] = "JCRABURN/cfb-betting-system"

    report = _report(root, database, environment, "tuesday_lock")

    identity = next(
        check for check in report.checks if check.name == "repository_allow_list"
    )
    assert identity.status == "block"


def test_preflight_never_applies_pending_migrations(tmp_path):
    root = tmp_path / "cfb-betting-system-v3"
    (root / "data").mkdir(parents=True)
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text(
        '[remote "origin"]\n'
        "\turl = https://github.com/JCRABURN/cfb-betting-system-v3.git\n",
        encoding="utf-8",
    )
    shutil.copytree(ROOT / ".github", root / ".github")
    shutil.copy2(ROOT / "requirements.txt", root / "requirements.txt")
    shutil.copy2(ROOT / "requirements-dev.txt", root / "requirements-dev.txt")
    database = root / "data" / "cfb.db"
    shutil.copy2(AUTHORITATIVE_DATABASE, database)
    line_path = root / "contest-lines.json"
    line_path.write_text(json.dumps(_line_manifest()), encoding="utf-8")
    before = _file_sha256(database)

    report = _report(root, database, _valid_environment(line_path), "tuesday_lock")

    migration_check = next(check for check in report.checks if check.name == "migrations")
    assert migration_check.status == "block"
    assert _file_sha256(database) == before
    conn = sqlite3.connect(database)
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone() is None
    conn.close()


def test_cli_reports_not_ready_without_printing_credentials(monkeypatch, capsys):
    monkeypatch.setenv("CFBD_API_KEY", SECRET_SENTINELS[0])
    monkeypatch.setenv("ODDS_API_KEY", SECRET_SENTINELS[1])

    exit_code = preflight_main(
        ["--operation", "tuesday_lock", "--database", str(AUTHORITATIVE_DATABASE)]
    )
    output = capsys.readouterr()

    assert exit_code == 1
    assert "PRODUCTION READY: NO" in output.out
    assert all(secret not in output.out + output.err for secret in SECRET_SENTINELS)


def test_operation_entry_point_refuses_mutation(monkeypatch, capsys):
    before = _file_sha256(AUTHORITATIVE_DATABASE)
    monkeypatch.setenv("CFBD_API_KEY", SECRET_SENTINELS[0])
    monkeypatch.setenv("ODDS_API_KEY", SECRET_SENTINELS[1])

    exit_code = operation_main(
        ["--operation", "tuesday_lock", "--database", str(AUTHORITATIVE_DATABASE)]
    )
    output = capsys.readouterr()

    assert exit_code == 1
    assert "PRODUCTION READY: NO" in output.err
    assert all(secret not in output.out + output.err for secret in SECRET_SENTINELS)
    assert _file_sha256(AUTHORITATIVE_DATABASE) == before
