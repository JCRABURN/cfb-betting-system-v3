import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from ingestion import (
    IngestionRequest,
    ProviderIngestionService,
    assess_required_freshness,
    payload_sha256,
)
from operations.context import (
    ContextEvidenceParser,
    record_card_context_status,
    write_context_evidence,
)
from operations.providers import (
    ProductionProviderError,
    _normalized_injury_records,
    capture_live_provider_bundle,
)
from operations.public_dashboard import _context_status


CAPTURED_AT = datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
LATER_CAPTURED_AT = datetime(2026, 8, 25, 18, tzinfo=timezone.utc)
LATEST_CAPTURED_AT = datetime(2026, 8, 25, 19, tzinfo=timezone.utc)
KICKOFF = "2026-08-29T16:00:00+00:00"


def _seed_game(temp_db, *, include_second=False):
    conn = temp_db.get_connection()
    teams = [(1, "Home State"), (2, "Away State")]
    if include_second:
        teams.extend(((3, "Second Home"), (4, "Second Away")))
    for team_id, school in teams:
        conn.execute(
            "INSERT INTO teams (team_id, school, conference) VALUES (?, ?, 'Fixture')",
            (team_id, school),
        )
    conn.execute(
        "INSERT INTO games (game_id, season, week, home_team, away_team, start_date) "
        "VALUES (9001, 2026, 1, 'Home State', 'Away State', ?)",
        (KICKOFF,),
    )
    if include_second:
        conn.execute(
            "INSERT INTO games "
            "(game_id, season, week, home_team, away_team, start_date) "
            "VALUES (9002, 2026, 1, 'Second Home', 'Second Away', ?)",
            (KICKOFF,),
        )
    conn.commit()
    return conn


def _request(data_type, provider, payload, *, requested_at=CAPTURED_AT, label="default"):
    return IngestionRequest(
        provider=provider,
        endpoint=f"fixture://{provider}/{data_type}",
        request_parameters={"season": 2026, "week": 1},
        requested_at=requested_at,
        parser_version=ContextEvidenceParser.version,
        raw_payload_reference=f"fixture://{provider}/{data_type}-{label}.json",
        data_type=data_type,
        expected_payload_sha256=payload_sha256(payload),
    )


def _base(context_class, source_mode="automated"):
    return {
        "record_id": f"9001:{context_class}:1",
        "context_class": context_class,
        "source_mode": source_mode,
        "game_id": 9001,
        "season": 2026,
        "week": 1,
        "home_team": "Home State",
        "away_team": "Away State",
        "affected_side": "home",
        "subject": "fixture subject",
        "evidence_summary": "Fixture point-in-time evidence.",
        "source_name": f"fixture {context_class} source",
        "source_reference": f"fixture://{context_class}/report",
        "observed_at": CAPTURED_AT.isoformat(),
        "margin_adjustment": 0,
        "confidence_adjustment": 0,
        "author": "fixture-provider",
    }


def _games_payload(*, include_second=False):
    games = [
        {
            "id": 9001,
            "season": 2026,
            "week": 1,
            "startDate": KICKOFF,
            "homeTeam": "Home State",
            "awayTeam": "Away State",
        }
    ]
    if include_second:
        games.append(
            {
                "id": 9002,
                "season": 2026,
                "week": 1,
                "startDate": KICKOFF,
                "homeTeam": "Second Home",
                "awayTeam": "Second Away",
            }
        )
    return games


def _injury_group(team, injuries):
    return {"team": {"displayName": team}, "injuries": injuries}


def _normalize_injuries(
    payload,
    *,
    requested_at=CAPTURED_AT,
    games_payload=None,
):
    return _normalized_injury_records(
        payload,
        games_payload=_games_payload() if games_payload is None else games_payload,
        season=2026,
        week=1,
        requested_at=requested_at,
    )


def _ingest_injury_snapshot(
    conn,
    groups,
    *,
    requested_at=CAPTURED_AT,
    games_payload=None,
    label="snapshot",
):
    normalized = _normalize_injuries(
        {"injuries": groups},
        requested_at=requested_at,
        games_payload=games_payload,
    )
    summary = ProviderIngestionService(clock=lambda: requested_at).ingest_payload(
        conn,
        _request(
            "injuries",
            "espn",
            normalized,
            requested_at=requested_at,
            label=label,
        ),
        normalized,
        ContextEvidenceParser(),
        accepted_writer=write_context_evidence,
    )
    return summary, normalized


def test_context_parsers_preserve_pit_provenance_and_quarantine_bad_weather(temp_db):
    conn = _seed_game(temp_db)
    service = ProviderIngestionService(clock=lambda: CAPTURED_AT)
    injury = {**_base("injury"), "report_status": "no_reported_injuries"}
    weather = {
        **_base("weather"),
        "affected_side": "both",
        "forecast_for": KICKOFF,
        "temperature_f": None,
        "wind_mph": 8.0,
        "precipitation_probability": 10.0,
    }
    injury_summary = service.ingest_payload(
        conn,
        _request("injuries", "espn", [injury]),
        [injury],
        ContextEvidenceParser(),
        accepted_writer=write_context_evidence,
    )
    weather_summary = service.ingest_payload(
        conn,
        _request("weather", "open_meteo", [weather]),
        [weather],
        ContextEvidenceParser(),
        accepted_writer=write_context_evidence,
    )

    assert injury_summary.status == "completed"
    assert weather_summary.status == "rejected"
    assert conn.execute(
        "SELECT context_class, source_mode, observed_at FROM provider_context_evidence"
    ).fetchone() == ("injury", "automated", CAPTURED_AT.isoformat())
    assert conn.execute(
        "SELECT rejection_code FROM provider_ingestion_rejections "
        "WHERE ingestion_run_id = ?",
        (weather_summary.ingestion_run_id,),
    ).fetchone()[0] == "malformed_record"
    conn.close()


class _Response:
    status_code = 200
    headers = {}

    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _ContextCaptureSession:
    def __init__(self):
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        params = kwargs.get("params", {})
        if url.endswith("/venues"):
            return _Response(
                [
                    {
                        "id": 10,
                        "name": "Home Stadium",
                        "location": {"latitude": 33.0, "longitude": -87.0},
                    },
                    {
                        "id": 11,
                        "name": "Prior Stadium",
                        "location": {"latitude": 34.0, "longitude": -86.0},
                    },
                ]
            )
        if url.endswith("/injuries"):
            return _Response(
                {
                    "injuries": [
                        _injury_group("Home State", []),
                        _injury_group("Away State", []),
                    ]
                }
            )
        if "open-meteo.com" in url:
            return _Response(
                {
                    "hourly": {
                        "time": ["2026-08-29T16:00"],
                        "temperature_2m": [83.0],
                        "wind_speed_10m": [9.0],
                        "precipitation_probability": [20.0],
                        "weather_code": [2],
                    }
                }
            )
        if url.endswith("/games"):
            current = {
                "id": 9001,
                "season": 2026,
                "week": 1,
                "startDate": "2026-08-29T16:00:00Z",
                "homeTeam": "Home State",
                "awayTeam": "Away State",
                "venueId": 10,
                "venue": "Home Stadium",
                "completed": False,
            }
            prior = {
                "id": 8999,
                "season": 2026,
                "week": 0,
                "startDate": "2026-08-20T16:00:00Z",
                "homeTeam": "Prior State",
                "awayTeam": "Away State",
                "venueId": 11,
                "venue": "Prior Stadium",
                "completed": True,
            }
            return _Response([current] if "week" in params else [prior, current])
        if "americanfootball_ncaaf" in url:
            return _Response(
                [
                    {
                        "id": "odds-9001",
                        "home_team": "Home State",
                        "away_team": "Away State",
                        "commence_time": "2026-08-29T16:00:00Z",
                        "bookmakers": [],
                    }
                ]
            )
        raise AssertionError(f"unexpected provider URL: {url}")


def test_live_card_capture_includes_injury_weather_and_travel_rest_evidence(tmp_path):
    root = tmp_path / "cfb-betting-system-v3"
    evidence_parent = root / "data" / "provider_evidence"
    evidence_parent.mkdir(parents=True)
    session = _ContextCaptureSession()
    bundle_path = capture_live_provider_bundle(
        {"CFBD_API_KEY": "fixture-cfbd", "ODDS_API_KEY": "fixture-odds"},
        repository_root=root,
        output_directory=evidence_parent / "capture",
        season=2026,
        week=1,
        line_type="current",
        capture_context=True,
        authorized=True,
        captured_at=CAPTURED_AT,
        session=session,
    )
    bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    payload_types = {(row["provider"], row["data_type"]) for row in bundle["payloads"]}

    assert ("espn", "injuries") in payload_types
    assert ("open_meteo", "weather") in payload_types
    assert ("collegefootballdata", "contextual") in payload_types
    assert bundle["context_capture"] is True
    assert any("open-meteo.com" in url for url, _ in session.calls)
    assert any(url.endswith("/injuries") for url, _ in session.calls)


def test_empty_espn_response_quarantines_missing_team_coverage(temp_db):
    conn = _seed_game(temp_db)
    normalized = _normalize_injuries({"injuries": []})

    assert len(normalized) == 2
    assert {record["coverage_status"] for record in normalized} == {"missing"}
    assert all("report_status" not in record for record in normalized)
    summary = ProviderIngestionService(clock=lambda: CAPTURED_AT).ingest_payload(
        conn,
        _request("injuries", "espn", normalized),
        normalized,
        ContextEvidenceParser(),
        accepted_writer=write_context_evidence,
    )

    assert summary.status == "rejected"
    assert summary.rows_accepted == 0
    assert summary.rows_rejected == 2
    assert conn.execute("SELECT COUNT(*) FROM provider_context_evidence").fetchone()[0] == 0
    assert assess_required_freshness(
        conn,
        as_of=CAPTURED_AT,
        required_data_types=("injuries",),
        provider_by_data_type={"injuries": "espn"},
    )[0].state == "missing"
    conn.close()


def test_partial_espn_response_accepts_only_explicit_team_report(temp_db):
    conn = _seed_game(temp_db)
    normalized = _normalize_injuries(
        {"injuries": [_injury_group("Home State", [])]}
    )

    assert [(record["affected_side"], record.get("report_status")) for record in normalized] == [
        ("home", "no_reported_injuries"),
        ("away", None),
    ]
    assert normalized[1]["coverage_status"] == "missing"
    summary = ProviderIngestionService(clock=lambda: CAPTURED_AT).ingest_payload(
        conn,
        _request("injuries", "espn", normalized),
        normalized,
        ContextEvidenceParser(),
        accepted_writer=write_context_evidence,
    )

    assert summary.status == "partial"
    assert summary.rows_accepted == 1
    assert summary.rows_rejected == 1
    assert conn.execute(
        "SELECT affected_side, report_status FROM ("
        "SELECT json_extract(raw_record, '$.affected_side') AS affected_side, "
        "json_extract(raw_record, '$.report_status') AS report_status "
        "FROM provider_ingestion_rejections WHERE ingestion_run_id = ?"
        ")",
        (summary.ingestion_run_id,),
    ).fetchone() == ("away", None)
    assert conn.execute(
        "SELECT affected_side FROM provider_context_evidence"
    ).fetchall() == [("home",)]
    assert assess_required_freshness(
        conn,
        as_of=CAPTURED_AT,
        required_data_types=("injuries",),
        provider_by_data_type={"injuries": "espn"},
    )[0].state == "partial"
    conn.close()


def test_espn_explicit_empty_team_report_is_negative_evidence():
    normalized = _normalize_injuries(
        {
            "injuries": [
                _injury_group("Home State", []),
                _injury_group(
                    "Away State",
                    [{"id": "away-1", "athlete": {"displayName": "Away Player"}}],
                ),
            ]
        }
    )

    assert normalized[0]["affected_side"] == "home"
    assert normalized[0]["report_status"] == "no_reported_injuries"
    assert "explicit team report" in normalized[0]["evidence_summary"]
    assert normalized[1]["affected_side"] == "away"
    assert normalized[1]["subject"] == "Away Player"


def test_espn_ambiguous_team_mapping_fails_closed():
    with pytest.raises(ProductionProviderError, match="ambiguously map team Home State"):
        _normalize_injuries(
            {
                "injuries": [
                    _injury_group("Home State", []),
                    _injury_group("Home State Bulldogs", []),
                ]
            }
        )


def _seed_context_card(
    conn,
    suffix,
    *,
    as_of=CAPTURED_AT,
    game_ids=(9001,),
):
    policy = conn.execute(
        "SELECT id FROM weekly_controller_policies WHERE policy_version = 'fixture-context-v1'"
    ).fetchone()
    if policy is None:
        policy_id = int(
            conn.execute(
                "INSERT INTO weekly_controller_policies "
                "(policy_version, authorized_contest_source, production_model_name, "
                "production_model_version, production_feature_schema_version, "
                "production_configuration_version, freshness_policy_version, "
                "required_source_count, effective_at, created_by, provenance) "
                "VALUES ('fixture-context-v1', 'SplashSports', 'epa_only', "
                "'epa-only-linear-v1', 'epa-differential-v1', "
                "'walk-forward-prior-seasons-v1', 'provider_freshness_v1', 5, ?, "
                "'fixture', 'fixture://context-policy')",
                (CAPTURED_AT.isoformat(),),
            ).lastrowid
        )
        for source_order, data_type in enumerate(
            ("odds", "injuries", "weather", "game_status", "contextual"),
            start=1,
        ):
            conn.execute(
                "INSERT INTO weekly_controller_policy_sources "
                "(controller_policy_id, source_order, data_type, provider, "
                "permitted_fallback_code) VALUES (?, ?, ?, 'fixture-provider', ?)",
                (policy_id, source_order, data_type, f"{data_type}_fallback_v1"),
            )
    else:
        policy_id = int(policy[0])
    contest_id = int(
        conn.execute(
            "INSERT INTO contests "
            "(contest_key, name, season, week, source, source_contest_id, provenance, "
            "created_at) VALUES (?, ?, 2026, 1, 'SplashSports', ?, ?, ?)",
            (
                f"fixture-context-{suffix}",
                f"Fixture Context {suffix}",
                f"fixture-context-{suffix}",
                f"fixture://contest/{suffix}",
                CAPTURED_AT.isoformat(),
            ),
        ).lastrowid
    )
    locked_lines = []
    for line_index, game_id in enumerate(game_ids, start=1):
        game = conn.execute(
            "SELECT home_team, away_team FROM games WHERE game_id = ?",
            (game_id,),
        ).fetchone()
        assert game is not None
        locked_line_id = int(
            conn.execute(
                "INSERT INTO contest_locked_lines "
                "(contest_id, game_id, season, week, raw_home_team, raw_away_team, "
                "normalized_home_team, normalized_away_team, home_spread, locked_at, "
                "source, source_line_id, provenance, payload_sha256) "
                "VALUES (?, ?, 2026, 1, ?, ?, ?, ?, -3.0, ?, 'SplashSports', ?, ?, ?)",
                (
                    contest_id,
                    game_id,
                    str(game[0]),
                    str(game[1]),
                    str(game[0]),
                    str(game[1]),
                    CAPTURED_AT.isoformat(),
                    f"line-{suffix}-{line_index}",
                    f"fixture://line/{suffix}/{game_id}",
                    "a" * 64,
                ),
            ).lastrowid
        )
        locked_lines.append((locked_line_id, line_index))
    model_run_id = int(
        conn.execute(
            "INSERT INTO model_runs "
            "(run_key, model_name, model_version, feature_schema_version, "
            "configuration_version, code_commit_sha, data_snapshot_sha256, status, "
            "generated_at, provenance) VALUES (?, 'epa_only', 'epa-only-linear-v1', "
            "'epa-differential-v1', 'walk-forward-prior-seasons-v1', ?, ?, "
            "'completed', ?, ?)",
            (
                f"fixture-model-{suffix}",
                "e" * 40,
                "f" * 64,
                as_of.isoformat(),
                f"fixture://model/{suffix}",
            ),
        ).lastrowid
    )
    card_id = int(
        conn.execute(
            "INSERT INTO contest_cards "
            "(card_key, contest_id, model_run_id, version, status, policy_version, "
            "locked_line_snapshot_sha256, generated_at, created_by, provenance) "
            "VALUES (?, ?, ?, 1, 'draft', 'fixture-card-v1', ?, ?, 'fixture', ?)",
            (
                f"fixture-card-{suffix}",
                contest_id,
                model_run_id,
                "b" * 64,
                as_of.isoformat(),
                f"fixture://card/{suffix}",
            ),
        ).lastrowid
    )
    for locked_line_id, rank in locked_lines:
        conn.execute(
            "INSERT INTO contest_picks "
            "(pick_key, card_id, locked_line_id, selected_side, confidence, rank, "
            "is_top_five, generated_at, provenance) "
            "VALUES (?, ?, ?, 'home', 1, ?, 1, ?, ?)",
            (
                f"fixture-pick-{suffix}-{rank}",
                card_id,
                locked_line_id,
                rank,
                as_of.isoformat(),
                f"fixture://pick/{suffix}/{rank}",
            ),
        )
    run_id = int(
        conn.execute(
            "INSERT INTO weekly_controller_runs "
            "(run_key, request_sha256, controller_policy_id, policy_version, operation, "
            "execution_mode, contest_id, card_id, requested_at, completed_at, status, "
            "actor, provenance) "
            "VALUES (?, ?, ?, 'fixture-context-v1', 'tuesday_lock', 'persist', ?, ?, ?, ?, "
            "'completed', 'fixture', ?)",
            (
                f"fixture-run-{suffix}",
                hashlib.sha256(suffix.encode("utf-8")).hexdigest(),
                policy_id,
                contest_id,
                card_id,
                as_of.isoformat(),
                as_of.isoformat(),
                f"fixture://run/{suffix}",
            ),
        ).lastrowid
    )
    conn.commit()
    return card_id, run_id


def _record_injury_status(conn, suffix, *, as_of, game_ids=(9001,)):
    card_id, run_id = _seed_context_card(
        conn,
        suffix,
        as_of=as_of,
        game_ids=game_ids,
    )
    record_card_context_status(
        conn,
        card_id=card_id,
        controller_run_id=run_id,
        as_of=as_of,
        provenance=f"fixture://context-status/{suffix}",
    )
    conn.commit()
    row = conn.execute(
        "SELECT status.state, status.evidence_count, status.latest_observed_at, "
        "status.fallback_code, status.fallback_reason, status.provenance, "
        "snapshot.provider, snapshot.ingestion_run_id, snapshot.snapshot_evidence_count "
        "FROM card_context_status AS status "
        "JOIN card_context_source_snapshots AS snapshot "
        "ON snapshot.card_id = status.card_id "
        "AND snapshot.context_class = status.context_class "
        "WHERE status.card_id = ? AND status.context_class = 'injury'",
        (card_id,),
    ).fetchone()
    assert row is not None
    return card_id, {
        "state": str(row[0]),
        "legacy_evidence_count": int(row[1]),
        "latest_observed_at": row[2],
        "fallback_code": row[3],
        "fallback_reason": row[4],
        "provenance": str(row[5]),
        "provider": str(row[6]),
        "ingestion_run_id": None if row[7] is None else int(row[7]),
        "snapshot_evidence_count": int(row[8]),
    }


def test_empty_espn_snapshot_records_missing_status(temp_db):
    conn = _seed_game(temp_db)
    summary, _ = _ingest_injury_snapshot(conn, [], label="empty-status")

    _, status = _record_injury_status(
        conn,
        "empty-status",
        as_of=CAPTURED_AT + timedelta(minutes=5),
    )

    assert summary.rows_accepted == 0
    assert status["state"] == "missing"
    assert status["fallback_code"] == "injury_missing"
    assert status["ingestion_run_id"] == summary.ingestion_run_id
    assert status["snapshot_evidence_count"] == 0
    conn.close()


def test_one_team_snapshot_is_partial_and_not_current(temp_db):
    conn = _seed_game(temp_db)
    summary, _ = _ingest_injury_snapshot(
        conn,
        [_injury_group("Home State", [])],
        label="one-team",
    )

    _, status = _record_injury_status(
        conn,
        "one-team",
        as_of=CAPTURED_AT + timedelta(minutes=5),
    )

    assert summary.status == "partial"
    assert summary.rows_accepted == 1
    assert status["state"] == "missing"
    assert status["fallback_code"] == "injury_partial"
    assert status["ingestion_run_id"] == summary.ingestion_run_id
    assert status["snapshot_evidence_count"] == 1
    conn.close()


def test_one_coherent_complete_snapshot_is_current(temp_db):
    conn = _seed_game(temp_db)
    summary, _ = _ingest_injury_snapshot(
        conn,
        [_injury_group("Home State", []), _injury_group("Away State", [])],
        label="coherent-complete",
    )

    _, status = _record_injury_status(
        conn,
        "coherent-complete",
        as_of=CAPTURED_AT + timedelta(minutes=5),
    )

    assert summary.status == "completed"
    assert status["state"] == "current"
    assert status["provider"] == "espn"
    assert status["ingestion_run_id"] == summary.ingestion_run_id
    assert status["snapshot_evidence_count"] == 2
    assert f"injury_ingestion_run_id={summary.ingestion_run_id}" in status["provenance"]
    conn.close()


def test_complementary_partial_snapshots_cannot_be_unioned(temp_db):
    conn = _seed_game(temp_db)
    first, _ = _ingest_injury_snapshot(
        conn,
        [_injury_group("Home State", [])],
        requested_at=CAPTURED_AT,
        label="complement-home",
    )
    second, _ = _ingest_injury_snapshot(
        conn,
        [_injury_group("Away State", [])],
        requested_at=LATER_CAPTURED_AT,
        label="complement-away",
    )

    _, status = _record_injury_status(
        conn,
        "complementary-partials",
        as_of=LATER_CAPTURED_AT + timedelta(minutes=5),
    )

    assert first.rows_accepted == second.rows_accepted == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM provider_context_evidence WHERE context_class = 'injury'"
    ).fetchone()[0] == 2
    assert status["state"] == "missing"
    assert status["fallback_code"] == "injury_partial"
    assert status["ingestion_run_id"] == second.ingestion_run_id
    assert status["snapshot_evidence_count"] == 1
    conn.close()


def test_newer_partial_snapshot_overrides_older_complete_snapshot(temp_db):
    conn = _seed_game(temp_db)
    complete, _ = _ingest_injury_snapshot(
        conn,
        [_injury_group("Home State", []), _injury_group("Away State", [])],
        requested_at=CAPTURED_AT,
        label="older-complete",
    )
    partial, _ = _ingest_injury_snapshot(
        conn,
        [_injury_group("Home State", [])],
        requested_at=LATER_CAPTURED_AT,
        label="newer-partial",
    )

    _, status = _record_injury_status(
        conn,
        "complete-then-partial",
        as_of=LATER_CAPTURED_AT + timedelta(minutes=5),
    )

    assert complete.status == "completed"
    assert partial.status == "partial"
    assert status["state"] == "missing"
    assert status["ingestion_run_id"] == partial.ingestion_run_id
    assert status["snapshot_evidence_count"] == 1
    assert "older runs cannot fill the gaps" in status["fallback_reason"]
    conn.close()


def test_newer_complete_snapshot_overrides_older_partial_snapshot(temp_db):
    conn = _seed_game(temp_db)
    partial, _ = _ingest_injury_snapshot(
        conn,
        [_injury_group("Home State", [])],
        requested_at=CAPTURED_AT,
        label="older-partial",
    )
    complete, _ = _ingest_injury_snapshot(
        conn,
        [_injury_group("Home State", []), _injury_group("Away State", [])],
        requested_at=LATER_CAPTURED_AT,
        label="newer-complete",
    )

    card_id, status = _record_injury_status(
        conn,
        "partial-then-complete",
        as_of=LATER_CAPTURED_AT + timedelta(minutes=5),
    )

    assert partial.status == "partial"
    assert complete.status == "completed"
    assert status["state"] == "current"
    assert status["ingestion_run_id"] == complete.ingestion_run_id
    assert status["snapshot_evidence_count"] == 2
    assert status["legacy_evidence_count"] == 3
    dashboard_injury = {
        row["context_class"]: row for row in _context_status(conn, card_id)
    }["injury"]
    assert dashboard_injury["record_count"] == 2
    assert dashboard_injury["source_ingestion_run_id"] == complete.ingestion_run_id
    conn.close()


def test_multiple_games_require_one_snapshot_to_cover_every_side(temp_db):
    conn = _seed_game(temp_db, include_second=True)
    games = _games_payload(include_second=True)
    partial, _ = _ingest_injury_snapshot(
        conn,
        [
            _injury_group("Home State", []),
            _injury_group("Away State", []),
            _injury_group("Second Home", []),
        ],
        requested_at=LATER_CAPTURED_AT,
        games_payload=games,
        label="multi-partial",
    )

    _, partial_status = _record_injury_status(
        conn,
        "multi-partial",
        as_of=LATER_CAPTURED_AT + timedelta(minutes=5),
        game_ids=(9001, 9002),
    )

    assert partial.status == "partial"
    assert partial_status["state"] == "missing"
    assert partial_status["snapshot_evidence_count"] == 3

    complete, _ = _ingest_injury_snapshot(
        conn,
        [
            _injury_group("Home State", []),
            _injury_group("Away State", []),
            _injury_group("Second Home", []),
            _injury_group("Second Away", []),
        ],
        requested_at=LATEST_CAPTURED_AT,
        games_payload=games,
        label="multi-complete",
    )
    complete_card_id, complete_status = _record_injury_status(
        conn,
        "multi-complete",
        as_of=LATEST_CAPTURED_AT + timedelta(minutes=5),
        game_ids=(9001, 9002),
    )

    assert complete.status == "completed"
    assert complete_status["state"] == "current"
    assert complete_status["ingestion_run_id"] == complete.ingestion_run_id
    assert complete_status["snapshot_evidence_count"] == 4
    assert conn.execute(
        "SELECT COUNT(*) FROM contest_line_corrections"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM contest_picks WHERE card_id = ?",
        (complete_card_id,),
    ).fetchone()[0] == 2
    conn.close()


def test_historical_injury_snapshots_and_status_identity_remain_immutable(temp_db):
    conn = _seed_game(temp_db)
    complete, _ = _ingest_injury_snapshot(
        conn,
        [_injury_group("Home State", []), _injury_group("Away State", [])],
        requested_at=CAPTURED_AT,
        label="history-complete",
    )
    partial, _ = _ingest_injury_snapshot(
        conn,
        [_injury_group("Home State", [])],
        requested_at=LATER_CAPTURED_AT,
        label="history-partial",
    )
    card_id, status = _record_injury_status(
        conn,
        "history",
        as_of=LATER_CAPTURED_AT + timedelta(minutes=5),
    )
    before = conn.execute(
        "SELECT ingestion_run_id, affected_side, observed_at "
        "FROM provider_context_evidence WHERE context_class = 'injury' "
        "ORDER BY ingestion_run_id, affected_side"
    ).fetchall()

    assert {row[0] for row in before} == {
        complete.ingestion_run_id,
        partial.ingestion_run_id,
    }
    assert status["ingestion_run_id"] == partial.ingestion_run_id
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE provider_context_evidence SET evidence_summary = 'changed' "
            "WHERE ingestion_run_id = ?",
            (complete.ingestion_run_id,),
        )
    conn.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "DELETE FROM card_context_source_snapshots WHERE card_id = ?",
            (card_id,),
        )
    conn.rollback()
    assert conn.execute(
        "SELECT ingestion_run_id, affected_side, observed_at "
        "FROM provider_context_evidence WHERE context_class = 'injury' "
        "ORDER BY ingestion_run_id, affected_side"
    ).fetchall() == before
    assert conn.execute(
        "SELECT ingestion_run_id FROM card_context_source_snapshots WHERE card_id = ?",
        (card_id,),
    ).fetchone()[0] == partial.ingestion_run_id
    conn.close()


def test_manual_context_with_future_observation_is_quarantined(temp_db):
    conn = _seed_game(temp_db)
    record = {
        **_base("coaching", "manual_exception"),
        "observed_at": "2026-08-25T16:00:00+00:00",
        "margin_adjustment": 2.0,
        "author": "fixture-owner",
    }
    summary = ProviderIngestionService(clock=lambda: CAPTURED_AT).ingest_payload(
        conn,
        _request("contextual", "owner_context_manifest", [record]),
        [record],
        ContextEvidenceParser(),
        accepted_writer=write_context_evidence,
    )

    assert summary.status == "rejected"
    assert conn.execute(
        "SELECT rejection_code FROM provider_ingestion_rejections "
        "WHERE ingestion_run_id = ?",
        (summary.ingestion_run_id,),
    ).fetchone()[0] == "invalid_timestamp"
    assert conn.execute("SELECT COUNT(*) FROM provider_context_evidence").fetchone()[0] == 0
    conn.close()
