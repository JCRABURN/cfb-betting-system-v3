import json
from datetime import datetime, timezone

from ingestion import IngestionRequest, ProviderIngestionService, payload_sha256
from operations.context import ContextEvidenceParser, write_context_evidence
from operations.providers import capture_live_provider_bundle


CAPTURED_AT = datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
KICKOFF = "2026-08-29T16:00:00+00:00"


def _seed_game(temp_db):
    conn = temp_db.get_connection()
    for team_id, school in ((1, "Home State"), (2, "Away State")):
        conn.execute(
            "INSERT INTO teams (team_id, school, conference) VALUES (?, ?, 'Fixture')",
            (team_id, school),
        )
    conn.execute(
        "INSERT INTO games (game_id, season, week, home_team, away_team, start_date) "
        "VALUES (9001, 2026, 1, 'Home State', 'Away State', ?)",
        (KICKOFF,),
    )
    conn.commit()
    return conn


def _request(data_type, provider, payload):
    return IngestionRequest(
        provider=provider,
        endpoint=f"fixture://{provider}/{data_type}",
        request_parameters={"season": 2026, "week": 1},
        requested_at=CAPTURED_AT,
        parser_version=ContextEvidenceParser.version,
        raw_payload_reference=f"fixture://{provider}/{data_type}.json",
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
            return _Response({"injuries": []})
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
