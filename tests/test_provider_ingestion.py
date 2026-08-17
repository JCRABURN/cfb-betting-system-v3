import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingestion.custody import (
    DEFAULT_FRESHNESS_RULES,
    AcceptedProviderRecord,
    CanonicalTeamResolver,
    IngestionRequest,
    OddsSpreadParser,
    ProviderIngestionError,
    ProviderIngestionService,
    assess_required_freshness,
    payload_sha256,
)
from migrations.runner import MigrationError, apply_migrations


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "provider_ingestion"
VALID_FIXTURE = FIXTURE_ROOT / "odds_valid.json"
ADVERSARIAL_FIXTURE = FIXTURE_ROOT / "odds_adversarial.json"
REQUESTED_AT = "2026-08-25T15:00:00+00:00"


def _seed_canonical_data(conn):
    teams = ("Georgia", "Clemson", "Alabama", "Auburn")
    conn.executemany(
        "INSERT INTO teams (team_id, school) VALUES (?, ?)",
        list(enumerate(teams, start=1)),
    )
    conn.executemany(
        """
        INSERT INTO games (
            game_id, season, week, start_date, home_team, away_team
        ) VALUES (?, 2026, 1, ?, ?, ?)
        """,
        (
            (1001, "2026-08-29T16:00:00+00:00", "Georgia", "Clemson"),
            (1002, "2026-08-29T20:00:00+00:00", "Alabama", "Auburn"),
        ),
    )
    conn.commit()


@pytest.fixture
def custody_connection(temp_db):
    conn = temp_db.get_connection()
    _seed_canonical_data(conn)
    try:
        yield conn
    finally:
        conn.close()


def _request(
    fixture=VALID_FIXTURE,
    *,
    parser_version="odds_spread_v1",
    expected_checksum=None,
    requested_at=REQUESTED_AT,
    raw_reference=None,
):
    return IngestionRequest(
        provider="fixture_odds",
        endpoint="https://fixture.invalid/v1/odds?apiKey=must-not-be-stored",
        request_parameters={
            "season": 2026,
            "week": 1,
            "apiKey": "must-not-be-stored",
            "nested": {"authorization": "must-not-be-stored", "market": "spreads"},
        },
        requested_at=requested_at,
        parser_version=parser_version,
        raw_payload_reference=raw_reference or f"fixture:{fixture.name}",
        data_type="odds",
        expected_payload_sha256=expected_checksum,
    )


def _ingest(conn, fixture=VALID_FIXTURE, **request_kwargs):
    payload = fixture.read_bytes()
    request = _request(fixture, **request_kwargs)
    parser = OddsSpreadParser(request.parser_version)
    return ProviderIngestionService(
        clock=lambda: datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)
    ).ingest_payload(conn, request, payload, parser)


def test_valid_fixture_records_complete_custody_without_credentials(custody_connection):
    summary = _ingest(custody_connection)

    assert summary.status == "completed"
    assert (summary.rows_received, summary.rows_accepted, summary.rows_rejected) == (2, 2, 0)
    run = custody_connection.execute(
        """
        SELECT endpoint, request_parameters, parser_version, payload_sha256,
               raw_payload_reference, status
        FROM provider_ingestion_runs WHERE id = ?
        """,
        (summary.ingestion_run_id,),
    ).fetchone()
    assert run[0] == "https://fixture.invalid/v1/odds"
    parameters = json.loads(run[1])
    assert parameters == {"nested": {"market": "spreads"}, "season": 2026, "week": 1}
    assert "must-not-be-stored" not in run[1]
    assert run[2:] == (
        "odds_spread_v1",
        payload_sha256(VALID_FIXTURE.read_bytes()),
        "fixture:odds_valid.json",
        "completed",
    )
    snapshots = list(
        custody_connection.execute(
            """
            SELECT game_id, raw_home_team, normalized_home_team, home_spread
            FROM provider_market_snapshots ORDER BY game_id
            """
        )
    )
    assert snapshots == [
        (1001, "Georgia Bulldogs", "Georgia", -3.5),
        (1002, "Alabama Crimson Tide", "Alabama", -6.5),
    ]
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_ingestion_rejections"
    ).fetchone()[0] == 0


def test_adversarial_fixture_quarantines_every_invalid_record(custody_connection):
    summary = _ingest(custody_connection, ADVERSARIAL_FIXTURE)

    assert summary.status == "partial"
    assert (summary.rows_received, summary.rows_accepted, summary.rows_rejected) == (10, 1, 9)
    codes = {
        row[0]
        for row in custody_connection.execute(
            "SELECT rejection_code FROM provider_ingestion_rejections"
        )
    }
    assert codes == {
        "duplicate_record",
        "unknown_team",
        "malformed_spread",
        "stale_data",
        "invalid_timestamp",
        "unsupported_market_type",
        "missing_matchup_identifier",
        "reversed_matchup",
        "conflicting_game_mapping",
    }
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_market_snapshots"
    ).fetchone()[0] == 1


def test_ambiguous_team_and_impossible_mapping_are_explicitly_rejected(custody_connection):
    custody_connection.executemany(
        "INSERT INTO teams (team_id, school) VALUES (?, ?)",
        ((10, "Miami"), (11, "Míami")),
    )
    custody_connection.commit()
    base = json.loads(VALID_FIXTURE.read_text(encoding="utf-8"))["records"][0]
    ambiguous = {**base, "matchup_id": "ambiguous", "home_team": "Miami Hurricanes"}
    not_found = {
        **base,
        "matchup_id": "not-found",
        "home_team": "Alabama Crimson Tide",
        "away_team": "Clemson Tigers",
        "event_start_at": "2026-08-29T20:00:00+00:00",
    }

    summary = ProviderIngestionService().ingest_payload(
        custody_connection,
        _request(),
        {"records": [ambiguous, not_found]},
        OddsSpreadParser(),
    )

    assert summary.status == "rejected"
    assert [
        row[0]
        for row in custody_connection.execute(
            "SELECT rejection_code FROM provider_ingestion_rejections ORDER BY record_index"
        )
    ] == ["ambiguous_team_normalization", "game_mapping_not_found"]


def test_exact_replay_is_idempotent(custody_connection):
    first = _ingest(custody_connection)
    second = _ingest(custody_connection)

    assert second.replayed is True
    assert second.ingestion_run_id == first.ingestion_run_id
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_ingestion_runs"
    ).fetchone()[0] == 1
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_market_snapshots"
    ).fetchone()[0] == 2


def test_same_observations_under_a_renamed_replay_are_quarantined(custody_connection):
    _ingest(custody_connection)
    renamed = _ingest(
        custody_connection,
        raw_reference="https://fixtures.invalid/renamed.json?token=must-not-be-stored",
    )

    assert renamed.status == "rejected"
    assert (renamed.rows_accepted, renamed.rows_rejected) == (0, 2)
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_market_snapshots"
    ).fetchone()[0] == 2
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_ingestion_rejections "
        "WHERE rejection_code = 'duplicate_record'"
    ).fetchone()[0] == 2
    reference = custody_connection.execute(
        "SELECT raw_payload_reference FROM provider_ingestion_runs "
        "WHERE id = ?",
        (renamed.ingestion_run_id,),
    ).fetchone()[0]
    assert reference == "https://fixtures.invalid/renamed.json"


def test_parser_version_change_creates_a_distinct_auditable_interpretation(custody_connection):
    first = _ingest(custody_connection)
    second = _ingest(custody_connection, parser_version="odds_spread_v2")

    assert second.replayed is False
    assert second.ingestion_run_id != first.ingestion_run_id
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_ingestion_runs"
    ).fetchone()[0] == 2
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_market_snapshots"
    ).fetchone()[0] == 4


def test_payload_checksum_mismatch_is_recorded_and_never_parsed(custody_connection):
    summary = _ingest(custody_connection, expected_checksum="0" * 64)

    assert summary.status == "checksum_mismatch"
    assert summary.rows_accepted == summary.rows_rejected == 0
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_market_snapshots"
    ).fetchone()[0] == 0
    stored = custody_connection.execute(
        "SELECT status, failure_reason FROM provider_ingestion_runs"
    ).fetchone()
    assert stored[0] == "checksum_mismatch"
    assert "does not match" in stored[1]


def test_malformed_payload_is_a_failed_auditable_run(custody_connection):
    summary = ProviderIngestionService().ingest_payload(
        custody_connection,
        _request(),
        b"{not-valid-json",
        OddsSpreadParser(),
    )

    assert summary.status == "malformed_payload"
    assert custody_connection.execute(
        "SELECT failure_reason FROM provider_ingestion_runs"
    ).fetchone()[0].startswith("payload is not valid UTF-8 JSON")


def test_partial_provider_failure_is_not_reported_as_complete(custody_connection):
    summary = _ingest(custody_connection, ADVERSARIAL_FIXTURE)
    snapshot = custody_connection.execute(
        "SELECT completeness FROM provider_data_snapshots WHERE ingestion_run_id = ?",
        (summary.ingestion_run_id,),
    ).fetchone()

    assert summary.status == "partial"
    assert snapshot == ("partial",)


def test_unexpected_parser_failure_records_a_failed_run_without_canonical_rows(custody_connection):
    class ExplodingParser:
        version = "exploding_v1"

        def parse(self, *args, **kwargs):
            raise RuntimeError("unexpected provider schema")

    request = IngestionRequest(
        provider="fixture_context",
        endpoint="fixture://context",
        request_parameters={},
        requested_at=REQUESTED_AT,
        parser_version="exploding_v1",
        raw_payload_reference="fixture:exploding.json",
        data_type="contextual",
    )
    with pytest.raises(ProviderIngestionError, match="failure run .* recorded"):
        ProviderIngestionService().ingest_payload(
            custody_connection,
            request,
            {"records": [{"unexpected": "shape"}]},
            ExplodingParser(),
        )

    status, reason = custody_connection.execute(
        "SELECT status, failure_reason FROM provider_ingestion_runs"
    ).fetchone()
    assert status == "failed"
    assert "unexpected provider schema" in reason
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_ingestion_acceptances"
    ).fetchone()[0] == 0


def test_writer_failure_rolls_back_every_record_but_preserves_failure_audit(custody_connection):
    custody_connection.execute("CREATE TABLE sentinel (value TEXT NOT NULL)")
    custody_connection.commit()

    def failing_writer(conn, accepted):
        assert len(accepted) == 2
        conn.execute("INSERT INTO sentinel VALUES ('must-roll-back')")
        raise RuntimeError("forced writer failure")

    with pytest.raises(ProviderIngestionError, match="transaction rolled back"):
        ProviderIngestionService().ingest_payload(
            custody_connection,
            _request(),
            VALID_FIXTURE.read_bytes(),
            OddsSpreadParser(),
            accepted_writer=failing_writer,
        )

    assert custody_connection.execute("SELECT COUNT(*) FROM sentinel").fetchone()[0] == 0
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_market_snapshots"
    ).fetchone()[0] == 0
    status, reason = custody_connection.execute(
        "SELECT status, failure_reason FROM provider_ingestion_runs"
    ).fetchone()
    assert status == "failed"
    assert "forced writer failure" in reason


def test_freshness_is_point_in_time_safe_and_uses_worst_record_age(custody_connection):
    _ingest(custody_connection)

    before_run = assess_required_freshness(
        custody_connection,
        as_of="2026-08-25T14:59:00+00:00",
        required_data_types=("odds",),
    )[0]
    current = assess_required_freshness(
        custody_connection,
        as_of="2026-08-25T15:05:00+00:00",
        required_data_types=("odds",),
    )[0]
    stale = assess_required_freshness(
        custody_connection,
        as_of="2026-08-25T15:10:00+00:00",
        required_data_types=("odds",),
    )[0]

    assert before_run.state == "missing"
    assert current.state == "current"
    assert current.observed_at == "2026-08-25T14:54:00+00:00"
    assert current.expires_at == "2026-08-25T15:09:00+00:00"
    assert stale.state == "stale"


def test_partial_snapshot_requires_explicit_fallback(custody_connection):
    _ingest(custody_connection, ADVERSARIAL_FIXTURE)
    assessment = assess_required_freshness(
        custody_connection,
        as_of=REQUESTED_AT,
        required_data_types=("odds",),
    )[0]

    assert assessment.state == "partial"
    assert assessment.usable_without_fallback is False
    assert "explicit fallback" in assessment.reason


def test_all_required_source_types_have_versioned_missing_assessments(custody_connection):
    assessments = assess_required_freshness(
        custody_connection,
        as_of=REQUESTED_AT,
    )

    assert [assessment.data_type for assessment in assessments] == [
        "odds", "injuries", "weather", "game_status", "contextual"
    ]
    assert {assessment.data_type for assessment in assessments} == {
        "odds", "injuries", "weather", "game_status", "contextual"
    }
    assert {assessment.state for assessment in assessments} == {"missing"}
    assert {assessment.policy_version for assessment in assessments} == {
        "provider_freshness_v1"
    }


def test_freshness_policy_has_locked_explicit_windows():
    assert dict(DEFAULT_FRESHNESS_RULES) == {
        "odds": 900,
        "injuries": 21600,
        "weather": 10800,
        "game_status": 300,
        "contextual": 86400,
    }
    with pytest.raises(TypeError):
        DEFAULT_FRESHNESS_RULES["odds"] = 1


def test_provider_neutral_acceptance_can_feed_a_transactional_context_writer(custody_connection):
    class ContextParser:
        version = "context_v1"

        def parse(self, conn, resolver, provider, request, record_index, record):
            observed = datetime.fromisoformat(record["observed_at"])
            return AcceptedProviderRecord(
                record_index=record_index,
                provider_record_id=record["id"],
                record_key=payload_sha256(
                    {"id": record["id"], "observed_at": record["observed_at"]}
                ),
                observed_at=observed,
                parser_version=self.version,
                raw_record_sha256=payload_sha256(record),
            )

    custody_connection.execute(
        "CREATE TABLE context_target (provider_record_id TEXT PRIMARY KEY)"
    )
    custody_connection.commit()
    request = IngestionRequest(
        provider="fixture_context",
        endpoint="fixture://context",
        request_parameters={"season": 2026, "week": 1},
        requested_at=REQUESTED_AT,
        parser_version="context_v1",
        raw_payload_reference="fixture:context.json",
        data_type="contextual",
    )

    def writer(conn, accepted):
        conn.executemany(
            "INSERT INTO context_target VALUES (?)",
            [(record.provider_record_id,) for record in accepted],
        )

    summary = ProviderIngestionService().ingest_payload(
        custody_connection,
        request,
        {"records": [{"id": "travel-1", "observed_at": "2026-08-25T14:00:00+00:00"}]},
        ContextParser(),
        accepted_writer=writer,
    )

    assert summary.status == "completed"
    assert custody_connection.execute(
        "SELECT provider_record_id, data_type FROM provider_ingestion_acceptances"
    ).fetchone() == ("travel-1", "contextual")
    assert custody_connection.execute(
        "SELECT provider_record_id FROM context_target"
    ).fetchone() == ("travel-1",)
    assessment = assess_required_freshness(
        custody_connection,
        as_of=REQUESTED_AT,
        required_data_types=("contextual",),
    )[0]
    assert assessment.state == "current"
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_market_snapshots"
    ).fetchone()[0] == 0


def test_provider_neutral_records_use_their_data_type_freshness_rule(custody_connection):
    class ContextParser:
        version = "context_v1"

        def parse(self, conn, resolver, provider, request, record_index, record):
            return AcceptedProviderRecord(
                record_index=record_index,
                provider_record_id=record["id"],
                record_key=payload_sha256(record),
                observed_at=datetime.fromisoformat(record["observed_at"]),
                parser_version=self.version,
                raw_record_sha256=payload_sha256(record),
            )

    request = IngestionRequest(
        provider="fixture_context",
        endpoint="fixture://context",
        request_parameters={},
        requested_at=REQUESTED_AT,
        parser_version="context_v1",
        raw_payload_reference="fixture:stale-context.json",
        data_type="contextual",
    )
    summary = ProviderIngestionService().ingest_payload(
        custody_connection,
        request,
        {"records": [{"id": "old", "observed_at": "2026-08-24T14:59:00+00:00"}]},
        ContextParser(),
    )

    assert summary.status == "rejected"
    assert custody_connection.execute(
        "SELECT provider_record_id, rejection_code FROM provider_ingestion_rejections"
    ).fetchone() == ("old", "stale_data")
    assert custody_connection.execute(
        "SELECT COUNT(*) FROM provider_ingestion_acceptances"
    ).fetchone()[0] == 0


def test_canonical_resolver_reports_unknown_and_ambiguous_without_guessing():
    resolver = CanonicalTeamResolver(("Miami", "Míami", "Georgia"))

    assert resolver.resolve("fixture", "Unknown State").status == "unknown"
    ambiguous = resolver.resolve("fixture", "Miami Hurricanes")
    assert ambiguous.status == "ambiguous"
    assert ambiguous.candidates == ("Miami", "Míami")


def test_ingestion_custody_records_are_immutable_and_schema_drift_is_detected(temp_db):
    conn = temp_db.get_connection()
    _seed_canonical_data(conn)
    summary = _ingest(conn)
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE provider_ingestion_runs SET status = 'failed' WHERE id = ?",
            (summary.ingestion_run_id,),
        )
    conn.rollback()

    with pytest.raises(sqlite3.IntegrityError, match="does not match its ingestion run"):
        conn.execute(
            """
            INSERT INTO provider_ingestion_rejections (
                ingestion_run_id, record_index, rejection_code,
                rejection_reason, raw_record_sha256, raw_record, rejected_at
            ) VALUES (?, 0, 'malformed_record', 'invalid direct insert', ?, '{}', ?)
            """,
            (summary.ingestion_run_id, "a" * 64, REQUESTED_AT),
        )
    conn.rollback()

    conn.execute("DROP TRIGGER provider_ingestion_runs_no_update")
    conn.commit()
    with pytest.raises(MigrationError, match="schema verification failed"):
        apply_migrations(conn)
    conn.close()


def test_ingestion_duplicate_index_drift_is_detected(temp_db):
    conn = temp_db.get_connection()
    conn.execute("DROP INDEX uq_provider_market_snapshots_observation")
    conn.commit()

    with pytest.raises(MigrationError, match="schema verification failed"):
        apply_migrations(conn)
    conn.close()
