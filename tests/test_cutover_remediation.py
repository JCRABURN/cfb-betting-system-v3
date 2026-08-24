from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import zipfile
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from migrations.runner import apply_migrations
from operations import execute_production_operation, load_production_settings
from operations.database_cutover import migrate_and_register, register_approved_policies
from operations.providers import (
    capture_live_provider_bundle,
    ingest_provider_bundle,
    load_provider_bundle,
    run_controlled_connectivity_checks,
)
from operations.splashsports import (
    SplashSportsImportError,
    SplashSportsImportRequest,
    build_splashsports_manifest,
)
from operations.weekly_config import (
    WeeklyConfigurationError,
    load_weekly_configuration,
    merge_weekly_environment,
)
from operations.writer_lock import ProductionWriterLock, WriterLockError


ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_DATABASE = ROOT / "data" / "cfb.db"
POLICY_CONFIG = ROOT / "config" / "production_policies.example.json"
NOW = datetime(2026, 8, 18, 12, tzinfo=timezone.utc)
LINES = (
    (401856634, "East Carolina", "Alabama", -28.5),
    (401856636, "Baylor", "Auburn", -2.5),
    (401856637, "Florida Atlantic", "Florida", -31.5),
    (401856660, "Clemson", "LSU", -3.5),
    (401856661, "Louisville", "Ole Miss", -6.5),
    (401856662, "UL Monroe", "Mississippi State", -24.5),
)
POLICY_VERSIONS = {
    "controller": "production-controller-v1",
    "selection": "production-selection-v1",
    "confidence": "production-confidence-v1",
    "ranking": "production-ranking-v1",
    "adjustment": "production-adjustment-v1",
    "refresh": "production-refresh-v1",
    "audit": "production-audit-v1",
    "diagnostics": "production-diagnostics-v1",
    "sportsbook": "production-sportsbook-v1",
}
SECRET_VALUES = ("cfbd-value-must-not-print", "odds-value-must-not-print")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "cfb-betting-system-v3"
    (root / "data").mkdir(parents=True)
    (root / "config").mkdir()
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text(
        '[remote "origin"]\n'
        "\turl = https://github.com/JCRABURN/cfb-betting-system-v3.git\n",
        encoding="utf-8",
    )
    shutil.copytree(ROOT / ".github", root / ".github")
    shutil.copy2(ROOT / "requirements.txt", root / "requirements.txt")
    shutil.copy2(ROOT / "requirements-dev.txt", root / "requirements-dev.txt")
    shutil.copy2(POLICY_CONFIG, root / "config" / POLICY_CONFIG.name)
    database = root / "data" / "cfb.db"
    shutil.copy2(AUTHORITATIVE_DATABASE, database)
    connection = sqlite3.connect(database)
    apply_migrations(connection)
    register_approved_policies(connection, root / "config" / POLICY_CONFIG.name)
    connection.close()
    return root, database


def _csv(path: Path, lines=LINES) -> None:
    rows = ["Away Team,Home Team,Spread,Total,SplashSports Game ID,Notes"]
    rows.extend(
        f"{away},{home},{spread},50.5,line-{game_id},owner supplied"
        for game_id, away, home, spread in lines
    )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def _request(path: Path, *, input_format: str = "csv", expected: int = 6, **kwargs):
    return SplashSportsImportRequest(
        source_path=path,
        input_format=input_format,
        season=2026,
        week=1,
        contest_key="splashsports-2026-week-1",
        contest_name="SplashSports 2026 Week 1",
        source_contest_id="splashsports-2026-week-1",
        expected_lined_game_count=expected,
        captured_at=NOW,
        imported_by="owner",
        provenance="owner-reviewed-manual-input",
        **kwargs,
    )


def _manifest(root: Path, database: Path) -> Path:
    source = root / "config" / "week.csv"
    _csv(source)
    connection = sqlite3.connect(database)
    manifest = build_splashsports_manifest(connection, _request(source))
    connection.close()
    path = root / "config" / "week-lines.json"
    path.write_text(manifest.canonical_json, encoding="utf-8")
    assert _sha(path) == manifest.sha256
    return path


def _weekly_config(root: Path, manifest: Path) -> Path:
    payload = {
        "configuration_version": "v3-weekly-production-v1",
        "repository": "JCRABURN/cfb-betting-system-v3",
        "season": 2026,
        "week": 1,
        "contest": {
            "key": "splashsports-2026-week-1",
            "name": "SplashSports 2026 Week 1",
            "source": "SplashSports",
            "source_contest_id": "splashsports-2026-week-1",
            "expected_lined_game_count": len(LINES),
        },
        "line_manifest": {
            "path": manifest.name,
            "sha256": _sha(manifest),
        },
        "provider_bundle": None,
        "model": {
            "name": "epa_only",
            "version": "epa-only-linear-v1",
            "feature_schema_version": "epa-differential-v1",
            "configuration_version": "walk-forward-prior-seasons-v1",
        },
        "policies": POLICY_VERSIONS,
        "freshness": {
            "policy_version": "provider_freshness_v1",
            "max_age_seconds": {
                "odds": 900,
                "injuries": 21600,
                "weather": 10800,
                "game_status": 300,
                "contextual": 86400,
            },
        },
        "freshness_fallbacks": [
            {
                "data_type": data_type,
                "fallback_code": f"{data_type}_documented_fallback_v1",
                "reason": f"controlled test fallback for {data_type}",
                "evidence": f"fixture://fallback/{data_type}",
                "provenance": "test-only-fallback",
            }
            for data_type in ("odds", "injuries", "weather", "game_status", "contextual")
        ],
        "contextual_adjustments": [],
        "sportsbook_recommendations": [],
        "daily_refresh": {
            "change_type": "data_refresh",
            "reason": "Governed daily production refresh.",
        },
        "closing_book": "draftkings",
        "display_timezone": "America/Chicago",
        "actor": "repository-owner",
        "provenance": "test-only-production-operation",
    }
    path = root / "config" / "week.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _environment() -> dict[str, str]:
    return {
        "CFB_V3_RUNTIME_MODE": "production",
        "CFB_V3_PRODUCTION_ENABLED": "true",
        "CFB_V3_OPERATION_EXECUTION_ENABLED": "true",
        "CFB_V3_KILL_SWITCH": "false",
        "CFB_V3_OWNER_CUTOVER_APPROVED": "true",
        "CFB_V3_REPOSITORY": "JCRABURN/cfb-betting-system-v3",
        "GITHUB_REPOSITORY": "JCRABURN/cfb-betting-system-v3",
        "CFB_V3_PROVIDER_CONNECTIVITY_AUTHORIZED": "true",
        "CFB_V3_PROVIDER_CONNECTIVITY_VERIFIED_AT": (
            NOW - timedelta(hours=1)
        ).isoformat(),
        "CFBD_API_KEY": SECRET_VALUES[0],
        "ODDS_API_KEY": SECRET_VALUES[1],
    }


@pytest.fixture
def prepared_week(tmp_path):
    root, database = _repo(tmp_path)
    manifest = _manifest(root, database)
    config_path = _weekly_config(root, manifest)
    configuration = load_weekly_configuration(config_path, repository_root=root)
    environment = merge_weekly_environment(_environment(), configuration)
    settings = load_production_settings(
        environment,
        repository_root=root,
        operation="tuesday_lock",
        database_path=database,
    )
    return root, database, configuration, settings


def test_csv_input_builds_validated_manifest_and_preserves_raw_names(tmp_path):
    root, database = _repo(tmp_path)
    source = root / "config" / "lines.csv"
    _csv(source)
    connection = sqlite3.connect(database)
    result = build_splashsports_manifest(connection, _request(source))
    connection.close()

    assert result.parsed_line_count == len(LINES)
    assert result.payload["source"] == "SplashSports"
    assert result.payload["input_custody"]["source_sha256"] == _sha(source)
    assert result.payload["lines"][0]["raw_away_team"] == "East Carolina"
    assert result.payload["lines"][0]["normalized_away_team"] == "East Carolina"


def test_manual_input_accepts_valid_three_digit_total(tmp_path):
    root, database = _repo(tmp_path)
    source = root / "config" / "lines.csv"
    source.write_text(
        "Away Team,Home Team,Spread,Total\nEast Carolina,Alabama,-28.5,101.5\n",
        encoding="utf-8",
    )
    connection = sqlite3.connect(database)
    result = build_splashsports_manifest(
        connection, _request(source, expected=1)
    )
    connection.close()

    assert result.payload["lines"][0]["total"] == 101.5


def _write_xlsx(path: Path) -> None:
    workbook = """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
 <sheets><sheet name="Lines" sheetId="1" r:id="rId1"/></sheets>
</workbook>"""
    relationships = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Id="rId1" Type="worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>"""
    sheet = """<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>
<row r="1"><c r="A1" t="inlineStr"><is><t>Away Team</t></is></c><c r="B1" t="inlineStr"><is><t>Home Team</t></is></c><c r="C1" t="inlineStr"><is><t>Spread</t></is></c></row>
<row r="2"><c r="A2" t="inlineStr"><is><t>East Carolina</t></is></c><c r="B2" t="inlineStr"><is><t>Alabama</t></is></c><c r="C2"><v>-28.5</v></c></row>
</sheetData></worksheet>"""
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", relationships)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)


def test_xlsx_and_reviewed_screenshot_transcription_converge_on_line_contract(tmp_path):
    root, database = _repo(tmp_path)
    xlsx = root / "config" / "lines.xlsx"
    _write_xlsx(xlsx)
    connection = sqlite3.connect(database)
    spreadsheet = build_splashsports_manifest(
        connection, _request(xlsx, input_format="xlsx", expected=1)
    )

    csv_path = root / "config" / "screenshot.csv"
    _csv(csv_path, LINES[:1])
    image = root / "config" / "screenshot.png"
    image.write_bytes(b"controlled-test-image")
    screenshot = build_splashsports_manifest(
        connection,
        _request(
            csv_path,
            input_format="screenshot_transcription",
            expected=1,
            screenshot_evidence_paths=(image,),
            screenshot_reviewed_by="owner",
            screenshot_reviewed_at=NOW + timedelta(minutes=5),
        ),
    )
    connection.close()

    assert spreadsheet.payload["lines"][0]["home_spread"] == -28.5
    assert screenshot.payload["lines"][0]["home_spread"] == -28.5
    assert screenshot.payload["input_custody"]["screenshot_evidence"][0]["sha256"] == _sha(image)


def test_screenshot_ambiguity_and_malformed_spread_fail_visibly(tmp_path):
    root, database = _repo(tmp_path)
    source = root / "config" / "bad.csv"
    source.write_text("Away Team,Home Team,Spread\nUnknown,Alabama,guess\n", encoding="utf-8")
    image = root / "config" / "source.png"
    image.write_bytes(b"image")
    connection = sqlite3.connect(database)
    with pytest.raises(SplashSportsImportError, match="unknown"):
        build_splashsports_manifest(
            connection,
            _request(
                source,
                input_format="screenshot_transcription",
                expected=1,
                screenshot_evidence_paths=(image,),
                screenshot_reviewed_by="owner",
                screenshot_reviewed_at=NOW,
            ),
        )
    connection.close()


def test_weekly_configuration_rejects_environment_conflicts(prepared_week):
    root, database, configuration, settings = prepared_week
    with pytest.raises(WeeklyConfigurationError, match="CFB_V3_WEEK"):
        merge_weekly_environment({"CFB_V3_WEEK": "2"}, configuration)


def test_database_cutover_rehearsal_preserves_source_and_registers_policies(tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "rehearsal.db"
    shutil.copy2(AUTHORITATIVE_DATABASE, source)
    before = _sha(source)

    report = migrate_and_register(
        source,
        target,
        POLICY_CONFIG,
        authoritative=False,
        completed_at=NOW,
    )

    assert report.source_unchanged is True
    assert _sha(source) == before
    assert report.migrations_applied == tuple(range(1, 16))
    assert dict(report.registered_policy_versions) == POLICY_VERSIONS
    assert report.pre_integrity_check == "ok"
    assert report.pre_foreign_key_violation_count == 0
    assert report.integrity_check == "ok"
    assert report.foreign_key_violation_count == 0


def test_production_adapter_dry_run_publishes_complete_card_on_disposable_copy(
    prepared_week,
):
    root, database, configuration, settings = prepared_week
    before = _sha(database)

    result, preflight = execute_production_operation(
        settings,
        configuration,
        code_commit_sha="a" * 40,
        dry_run=True,
        now=NOW,
    )

    assert preflight.production_ready is True
    assert result.status == "completed"
    assert result.execution_mode == "dry_run"
    assert result.pick_count == len(LINES)
    assert result.top_five_count == 5
    assert result.wagers_placed == 0
    assert result.source_database_unchanged is True
    assert _sha(database) == before


def test_managed_cloud_workspace_preserves_full_card_and_locked_line_gates(
    prepared_week,
):
    root, database, configuration, settings = prepared_week

    result, preflight = execute_production_operation(
        settings,
        configuration,
        code_commit_sha="d" * 40,
        dry_run=False,
        now=NOW,
        managed_workspace=True,
    )

    assert preflight.production_ready is True
    assert result.execution_mode == "managed_cloud_workspace"
    assert result.pick_count == len(LINES)
    assert result.top_five_count == 5
    assert result.wagers_placed == 0
    assert result.backup_path is None
    assert not (database.parent / "backups").exists()
    connection = sqlite3.connect(database)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM contest_locked_lines"
        ).fetchone()[0] == len(LINES)
        assert connection.execute(
            "SELECT COUNT(*) FROM contest_picks WHERE confidence BETWEEN 1 AND 5"
        ).fetchone()[0] == len(LINES)
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute(
                "UPDATE contest_locked_lines SET home_spread = home_spread + 0.5"
            )
    finally:
        connection.close()


def test_production_operation_automatically_emits_live_board_from_current_offer(
    prepared_week,
):
    root, database, configuration, settings = prepared_week
    evidence_parent = root / "data" / "provider_evidence"
    evidence_parent.mkdir()
    bundle_path = capture_live_provider_bundle(
        {"CFBD_API_KEY": SECRET_VALUES[0], "ODDS_API_KEY": SECRET_VALUES[1]},
        repository_root=root,
        output_directory=evidence_parent / "live-board",
        season=2026,
        week=1,
        line_type="current",
        authorized=True,
        captured_at=NOW,
        session=_CaptureSession(),
    )

    result, preflight = execute_production_operation(
        settings,
        replace(
            configuration,
            provider_bundle_path=bundle_path,
            freshness_fallbacks=tuple(
                item
                for item in configuration.freshness_fallbacks
                if item.get("data_type") not in ("odds", "game_status")
            ),
        ),
        code_commit_sha="e" * 40,
        dry_run=True,
        now=NOW,
    )

    assert preflight.production_ready is True
    assert result.sportsbook_recommendation_count == 1
    assert result.live_betting_board[0]["bookmaker"] == "draftkings"
    assert result.live_betting_board[0]["policy_version"] == POLICY_VERSIONS["sportsbook"]
    assert result.live_betting_board[0]["decision"] in ("BET", "NO BET")
    assert result.pick_count == len(LINES)
    assert result.wagers_placed == 0


def test_production_adapter_persists_once_and_replays_idempotently(prepared_week):
    root, database, configuration, settings = prepared_week
    first, _ = execute_production_operation(
        settings,
        configuration,
        code_commit_sha="b" * 40,
        dry_run=False,
        now=NOW,
    )
    after_first = _sha(database)
    second, _ = execute_production_operation(
        settings,
        configuration,
        code_commit_sha="b" * 40,
        dry_run=False,
        now=NOW,
    )

    assert first.replayed is False
    assert first.backup_path is not None
    assert Path(first.backup_path).is_file()
    assert first.backup_sha256 == first.source_database_sha256_before
    assert second.replayed is True
    assert second.publication_id == first.publication_id
    assert second.source_database_unchanged is True
    assert _sha(database) == after_first
    assert not database.with_name(database.name + ".v3-writer.lock").exists()


def test_staged_persistence_failure_leaves_authoritative_database_unchanged(
    prepared_week, monkeypatch
):
    root, database, configuration, settings = prepared_week
    before = _sha(database)

    def fail_operation(*args, **kwargs):
        raise RuntimeError("controlled staged failure")

    monkeypatch.setattr("operations.execution._operation", fail_operation)
    with pytest.raises(RuntimeError, match="controlled staged failure"):
        execute_production_operation(
            settings,
            configuration,
            code_commit_sha="c" * 40,
            dry_run=False,
            now=NOW,
        )

    assert _sha(database) == before
    assert not database.with_name(database.name + ".v3-writer.lock").exists()
    assert not list(database.parent.glob(f".{database.name}.v3-stage-*.db"))


def test_provider_bundle_quarantines_bad_records_without_touching_contest_locks(
    tmp_path,
):
    root, database = _repo(tmp_path)
    payload_path = root / "config" / "injuries.json"
    payload_path.write_text(
        json.dumps(
            [
                {"record_id": "injury-1", "observed_at": NOW.isoformat()},
                {"observed_at": NOW.isoformat()},
            ]
        ),
        encoding="utf-8",
    )
    bundle_path = root / "config" / "provider-bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "bundle_version": "v3-provider-bundle-v1",
                "repository": "JCRABURN/cfb-betting-system-v3",
                "season": 2026,
                "week": 1,
                "payloads": [
                    {
                        "provider": "manual_injury_report",
                        "data_type": "injuries",
                        "endpoint": "fixture://injuries/week-1",
                        "request_parameters": {"season": 2026, "week": 1},
                        "requested_at": NOW.isoformat(),
                        "parser_version": "provider_snapshot_v1",
                        "raw_payload_reference": str(payload_path),
                        "payload_path": payload_path.name,
                        "payload_sha256": _sha(payload_path),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    bundle = load_provider_bundle(
        bundle_path, repository_root=root, season=2026, week=1
    )
    connection = sqlite3.connect(database)
    before_locks = connection.execute(
        "SELECT COUNT(*) FROM contest_locked_lines"
    ).fetchone()[0]
    summaries = ingest_provider_bundle(connection, bundle)
    after_locks = connection.execute(
        "SELECT COUNT(*) FROM contest_locked_lines"
    ).fetchone()[0]
    rejection = connection.execute(
        "SELECT rejection_code FROM provider_ingestion_rejections"
    ).fetchone()[0]
    connection.close()

    assert summaries[0].status == "partial"
    assert summaries[0].rows_accepted == 1
    assert summaries[0].rows_rejected == 1
    assert rejection == "malformed_record"
    assert before_locks == after_locks == 0


def test_writer_lock_rejects_overlap_and_releases(tmp_path):
    database = tmp_path / "cfb.db"
    database.write_bytes(b"database")
    first = ProductionWriterLock(database, "one", "owner", NOW)
    second = ProductionWriterLock(database, "two", "owner", NOW)
    first.acquire()
    with pytest.raises(WriterLockError, match="another writer"):
        second.acquire()
    first.release()
    second.acquire()
    second.release()
    assert not first.lock_path.exists()


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _Session:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return _Response([{"ok": True}])


class _CaptureSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if url.endswith("/games"):
            return _Response(
                [
                    {
                        "id": 401856634,
                        "season": 2026,
                        "week": 1,
                        "seasonType": "regular",
                        "startDate": "2026-09-05T16:00:00Z",
                        "homeTeam": "Alabama",
                        "awayTeam": "East Carolina",
                        "completed": False,
                    }
                ]
            )
        if "americanfootball_ncaaf" in url:
            return _Response(
                [
                    {
                        "id": "odds-event-1",
                        "home_team": "Alabama Crimson Tide",
                        "away_team": "East Carolina Pirates",
                        "commence_time": "2026-09-05T16:00:00Z",
                        "bookmakers": [
                            {
                                "key": "draftkings",
                                "last_update": NOW.isoformat(),
                                "markets": [
                                    {
                                        "key": "spreads",
                                        "outcomes": [
                                            {
                                                "name": "Alabama Crimson Tide",
                                                "point": -28.5,
                                                "price": -110,
                                            },
                                            {
                                                "name": "East Carolina Pirates",
                                                "point": 28.5,
                                                "price": -110,
                                            },
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            )
        return _Response([{"ok": True}])


def test_controlled_connectivity_reports_names_and_hashes_never_secret_values():
    session = _Session()
    environment = {
        "CFBD_API_KEY": SECRET_VALUES[0],
        "ODDS_API_KEY": SECRET_VALUES[1],
    }
    report = run_controlled_connectivity_checks(
        environment,
        season=2026,
        authorized=True,
        session=session,
        checked_at=NOW,
    )
    serialized = json.dumps(report)

    assert report["credential_variables"] == ["CFBD_API_KEY", "ODDS_API_KEY"]
    assert all(value not in serialized for value in SECRET_VALUES)
    assert len(session.calls) == 2


def test_connectivity_is_disabled_without_explicit_authorization():
    with pytest.raises(RuntimeError, match="explicit authorization"):
        run_controlled_connectivity_checks(
            {"CFBD_API_KEY": "x", "ODDS_API_KEY": "y"},
            season=2026,
            authorized=False,
        )


def test_live_capture_preparation_preserves_raw_evidence_without_secret_values(tmp_path):
    root = tmp_path / "cfb-betting-system-v3"
    (root / "data" / "provider_evidence").mkdir(parents=True)
    output = root / "data" / "provider_evidence" / "week-1"
    session = _CaptureSession()

    bundle_path = capture_live_provider_bundle(
        {"CFBD_API_KEY": SECRET_VALUES[0], "ODDS_API_KEY": SECRET_VALUES[1]},
        repository_root=root,
        output_directory=output,
        season=2026,
        week=1,
        line_type="opening",
        authorized=True,
        captured_at=NOW,
        session=session,
    )
    serialized = bundle_path.read_text(encoding="utf-8")
    bundle = load_provider_bundle(
        bundle_path,
        repository_root=root,
        season=2026,
        week=1,
    )

    assert len(bundle.payloads) == 2
    odds_spec = next(item for item in bundle.payloads if item.data_type == "odds")
    normalized = json.loads(odds_spec.payload_path.read_text(encoding="utf-8"))
    assert odds_spec.parser_version == "odds_spread_v3"
    assert normalized[0]["away_spread"] == 28.5
    assert normalized[0]["away_price"] == -110
    assert (output / "cfbd-games.raw.json").is_file()
    assert (output / "odds.raw.json").is_file()
    assert all(value not in serialized for value in SECRET_VALUES)
    assert len(session.calls) == 2


def test_postgame_capture_collects_results_without_requesting_market_data(tmp_path):
    root = tmp_path / "cfb-betting-system-v3"
    (root / "data" / "provider_evidence").mkdir(parents=True)
    output = root / "data" / "provider_evidence" / "week-1-postgame"
    session = _CaptureSession()

    bundle_path = capture_live_provider_bundle(
        {"CFBD_API_KEY": SECRET_VALUES[0]},
        repository_root=root,
        output_directory=output,
        season=2026,
        week=1,
        line_type="closing",
        capture_scope="postgame",
        authorized=True,
        captured_at=NOW,
        session=session,
    )
    bundle = load_provider_bundle(
        bundle_path,
        repository_root=root,
        season=2026,
        week=1,
    )

    assert len(bundle.payloads) == 1
    assert bundle.payloads[0].data_type == "game_status"
    assert len(session.calls) == 1
    assert session.calls[0][0].endswith("/games")
