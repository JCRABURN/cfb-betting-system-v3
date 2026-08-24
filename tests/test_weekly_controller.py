import hashlib
import sqlite3
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from business_entities import (
    ConfidenceRankingPolicy,
    ContestLineInput,
    ContextualAdjustmentInput,
    DailyRefreshPolicy,
    DailyRefreshRequest,
    FreshnessFallbackDecision,
    FullCardPolicy,
    ManualAdjustmentPolicy,
    PostgameAuditPolicy,
    PostgameAuditRequest,
    RequiredSourcePolicy,
    SportsbookNoBetInput,
    TuesdayCardRequest,
    WeeklyControllerError,
    WeeklyControllerPolicy,
    WeeklyDiagnosticsPolicy,
    audit_contest_card,
    audit_sportsbook_recommendations,
    build_draftkings_betting_board,
    designate_week_closing_offers,
    evaluate_live_sportsbook_board,
    generate_weekly_diagnostics,
    get_card_run_manifest,
    inspect_official_card,
    inspect_controlled_shadow_rehearsal,
    register_sportsbook_recommendation_policy,
    run_daily_controller,
    run_tuesday_controller,
)
from ingestion import (
    AcceptedProviderRecord,
    IngestionRequest,
    OddsSpreadParser,
    ProviderIngestionService,
    payload_sha256,
)
from operations.providers import _odds_writer
from scripts.inspect_official_card import main as inspect_official_card_main


POLICY_AT = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
TUESDAY_AT = datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
WEDNESDAY_AT = datetime(2026, 8, 26, 15, tzinfo=timezone.utc)
THURSDAY_AT = datetime(2026, 8, 27, 15, tzinfo=timezone.utc)
KICKOFF = "2026-08-29T17:00:00+00:00"


SOURCE_RULES = tuple(
    RequiredSourcePolicy(data_type, "fixture-provider", f"{data_type}_fallback_v1")
    for data_type in ("odds", "injuries", "weather", "game_status", "contextual")
)
CONTROLLER_POLICY = WeeklyControllerPolicy(
    policy_version="weekly-controller-v1",
    authorized_contest_source="SplashSports",
    required_sources=SOURCE_RULES,
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://weekly-controller-policy",
)
SELECTION_POLICY = FullCardPolicy(
    version="official-full-card-v1",
    market_books=(),
    model_tie_side="away",
    pickem_tiebreak_side="home",
)
CONFIDENCE_POLICY = ConfidenceRankingPolicy(
    policy_key="official-confidence-ranking-v1",
    confidence_policy_version="official-confidence-v1",
    ranking_policy_version="official-top-five-v1",
    confidence_5_max_uncertainty=2.0,
    confidence_4_max_uncertainty=4.0,
    confidence_3_max_uncertainty=6.0,
    confidence_2_max_uncertainty=8.0,
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://official-confidence-policy",
)
ADJUSTMENT_POLICY = ManualAdjustmentPolicy(
    policy_version="official-adjustments-v1",
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://official-adjustment-policy",
)
REFRESH_POLICY = DailyRefreshPolicy(
    policy_version="official-refresh-v1",
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://official-refresh-policy",
)


def _fallbacks():
    return tuple(
        FreshnessFallbackDecision(
            data_type=source.data_type,
            fallback_code=source.permitted_fallback_code,
            reason=f"Recorded fixture {source.data_type} source is unavailable.",
            evidence=f"fixture://freshness/{source.data_type}/missing",
            provenance=f"fixture://fallback/{source.data_type}",
        )
        for source in SOURCE_RULES
    )


def _seed_games(temp_db, count=5):
    conn = temp_db.get_connection()
    lines = []
    for index in range(1, count + 1):
        home = f"Home {index}"
        away = f"Away {index}"
        conn.execute(
            "INSERT INTO teams (team_id, school, conference) VALUES (?, ?, 'Fixture')",
            (index * 2 - 1, home),
        )
        conn.execute(
            "INSERT INTO teams (team_id, school, conference) VALUES (?, ?, 'Fixture')",
            (index * 2, away),
        )
        conn.execute(
            "INSERT INTO games "
            "(game_id, season, week, home_team, away_team, start_date) "
            "VALUES (?, 2026, 1, ?, ?, ?)",
            (1000 + index, home, away, KICKOFF),
        )
        lines.append(
            ContestLineInput(
                raw_home_team=home,
                raw_away_team=away,
                home_spread=-float(index),
                source_line_id=f"splash-line-{index}",
                total=40.0 + index,
            )
        )
    conn.commit()
    return conn, tuple(lines)


def _seed_epa_inputs(conn, target_count=5):
    training_games = (
        (2101, "Train Home 1", "Train Away 1", 31, 24, 0.30, 0.10, 0.10, 0.20),
        (2102, "Train Home 2", "Train Away 2", 17, 20, 0.05, 0.20, 0.20, 0.10),
        (2103, "Train Home 3", "Train Away 3", 38, 28, 0.40, 0.05, 0.05, 0.25),
    )
    for game_id, home, away, home_points, away_points, ho, hd, ao, ad in training_games:
        conn.execute(
            "INSERT INTO games "
            "(game_id, season, week, home_team, away_team, start_date, "
            "home_points, away_points, completed) "
            "VALUES (?, 2024, 2, ?, ?, '2024-09-07T17:00:00+00:00', ?, ?, 1)",
            (game_id, home, away, home_points, away_points),
        )
        for team, offense, defense in ((home, ho, hd), (away, ao, ad)):
            conn.execute(
                "INSERT INTO team_game_stats "
                "(season, week, team, offense_epa_play, defense_epa_play, "
                "source, fetched_at) "
                "VALUES (2024, 1, ?, ?, ?, 'cfbd_point_in_time', "
                "'2024-09-01T12:00:00+00:00')",
                (team, offense, defense),
            )
    for index in range(1, target_count + 1):
        for team, offense, defense in (
            (f"Home {index}", 0.25 + index / 100, 0.10),
            (f"Away {index}", 0.12, 0.18 + index / 100),
        ):
            conn.execute(
                "INSERT INTO team_game_stats "
                "(season, week, team, offense_epa_play, defense_epa_play, "
                "source, fetched_at) "
                "VALUES (2025, 15, ?, ?, ?, 'cfbd_point_in_time', "
                "'2026-01-15T12:00:00+00:00')",
                (team, offense, defense),
            )
    conn.commit()


def _tuesday_request(lines, **changes):
    values = dict(
        run_key="week-1-tuesday-controller",
        publication_key="week-1-official-v1",
        contest_key="splashsports-2026-week-1",
        contest_name="SplashSports 2026 Week 1",
        source_contest_id="splash-2026-w1",
        season=2026,
        week=1,
        expected_lined_game_count=len(lines),
        line_payload_sha256="c" * 64,
        raw_payload_reference="fixture://splashsports/week-1.json?token=not-stored",
        lines=lines,
        model_run_key="week-1-epa-run-v1",
        code_commit_sha="a" * 40,
        controller_policy=CONTROLLER_POLICY,
        selection_policy=SELECTION_POLICY,
        confidence_policy=CONFIDENCE_POLICY,
        adjustment_policy=ADJUSTMENT_POLICY,
        freshness_fallbacks=_fallbacks(),
        contextual_adjustments=(),
        sportsbook_recommendations=(),
        generated_at=TUESDAY_AT,
        actor="test",
        provenance="fixture://weekly-controller/tuesday",
    )
    values.update(changes)
    return TuesdayCardRequest(**values)


def _daily_request(prior_publication_id, **changes):
    values = dict(
        run_key="week-1-wednesday-controller",
        publication_key="week-1-official-v2",
        prior_publication_id=prior_publication_id,
        model_run_key="week-1-epa-run-v2",
        code_commit_sha="a" * 40,
        change_type="data_refresh",
        reason="Wednesday fixture data refresh.",
        refresh_policy=REFRESH_POLICY,
        controller_policy=CONTROLLER_POLICY,
        freshness_fallbacks=_fallbacks(),
        contextual_adjustments=(),
        sportsbook_recommendations=(),
        generated_at=WEDNESDAY_AT,
        actor="test",
        provenance="fixture://weekly-controller/wednesday",
    )
    values.update(changes)
    return DailyRefreshRequest(**values)


def _table_counts(conn):
    tables = (
        "contests",
        "contest_locked_lines",
        "model_runs",
        "model_predictions",
        "contest_cards",
        "contest_picks",
        "weekly_controller_runs",
        "official_card_publications",
    )
    return {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in tables
    }


def _file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_tuesday_controller_publishes_every_lined_game_with_explicit_fallbacks(temp_db):
    conn, lines = _seed_games(temp_db)

    result = run_tuesday_controller(conn, _tuesday_request(lines))
    inspection = inspect_official_card(conn, publication_id=result.publication.id)

    assert result.persisted is True
    assert result.replayed is False
    assert result.run.operation == "tuesday_lock"
    assert result.publication.card_version == 1
    assert result.card.card.status == "draft"
    assert result.card.card.model_run_id is not None
    assert conn.execute(
        "SELECT model_name FROM model_runs WHERE id = ?", (result.card.card.model_run_id,)
    ).fetchone()[0] == "epa_only"
    assert len(result.card.picks) == len(lines) == 5
    assert all(pick.selected_side in ("home", "away") for pick in result.card.picks)
    assert all(pick.confidence == 1 for pick in result.card.picks)
    assert {pick.rank for pick in result.card.picks} == {1, 2, 3, 4, 5}
    assert all(pick.is_top_five for pick in result.card.picks)
    assert all(pick.fallback_code == "locked_line_underdog" for pick in result.card.picks)
    assert {item.state for item in result.freshness} == {"missing"}
    assert all(item.fallback_code for item in result.freshness)
    assert result.line_batch.source == "SplashSports"
    assert result.line_batch.raw_payload_reference == "fixture://splashsports/week-1.json"
    assert inspection.valid is True
    assert inspection.is_latest_official_version is True
    assert inspection.publication_manifest_matches is True
    assert conn.execute("SELECT COUNT(*) FROM picks").fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM sportsbook_recommendations"
    ).fetchone()[0] == 0
    conn.close()


def test_tuesday_replay_is_idempotent_and_does_not_rerun_model(temp_db):
    conn, lines = _seed_games(temp_db)
    first = run_tuesday_controller(conn, _tuesday_request(lines))
    counts = _table_counts(conn)

    replay = run_tuesday_controller(conn, _tuesday_request(lines))

    assert replay.replayed is True
    assert replay.publication == first.publication
    assert _table_counts(conn) == counts
    conn.close()


def test_tuesday_run_key_rejects_a_different_request_fingerprint(temp_db):
    conn, lines = _seed_games(temp_db)
    run_tuesday_controller(conn, _tuesday_request(lines))

    with pytest.raises(WeeklyControllerError, match="request fingerprint"):
        run_tuesday_controller(
            conn,
            _tuesday_request(lines, publication_key="different-publication-key"),
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM official_card_publications"
    ).fetchone()[0] == 1
    conn.close()


def test_line_lock_identity_is_deterministic_when_provider_order_changes(temp_db):
    conn, lines = _seed_games(temp_db)

    run_tuesday_controller(conn, _tuesday_request(tuple(reversed(lines))))

    assert [
        row[0]
        for row in conn.execute(
            "SELECT source_line_id FROM contest_locked_lines ORDER BY id"
        )
    ] == [f"splash-line-{index}" for index in range(1, 6)]
    conn.close()


def test_different_controller_identity_cannot_relock_an_existing_contest(temp_db):
    conn, lines = _seed_games(temp_db)
    run_tuesday_controller(conn, _tuesday_request(lines))

    with pytest.raises(WeeklyControllerError, match="already locked"):
        run_tuesday_controller(
            conn,
            _tuesday_request(
                lines,
                run_key="week-1-tuesday-relock",
                publication_key="week-1-official-relock",
                model_run_key="week-1-epa-run-relock",
            ),
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM contest_locked_lines"
    ).fetchone()[0] == 5
    assert conn.execute(
        "SELECT COUNT(*) FROM official_card_publications"
    ).fetchone()[0] == 1
    conn.close()


def test_dry_run_uses_isolated_database_and_writes_nothing(temp_db):
    conn, lines = _seed_games(temp_db)
    database = Path(temp_db.DB_PATH)
    before_hash = _file_hash(database)
    before_counts = _table_counts(conn)

    result = run_tuesday_controller(conn, _tuesday_request(lines), dry_run=True)

    assert result.persisted is False
    assert result.publication.card_version == 1
    assert _table_counts(conn) == before_counts
    assert _file_hash(database) == before_hash
    conn.close()


def test_missing_freshness_fallback_rolls_back_all_official_objects(temp_db):
    conn, lines = _seed_games(temp_db)
    request = _tuesday_request(
        lines,
        freshness_fallbacks=tuple(
            fallback for fallback in _fallbacks() if fallback.data_type != "weather"
        ),
    )

    with pytest.raises(WeeklyControllerError, match="weather is missing"):
        run_tuesday_controller(conn, request)

    assert conn.execute("SELECT COUNT(*) FROM contests").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM contest_locked_lines").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM official_card_publications").fetchone()[0] == 0
    conn.close()


def test_publication_failure_after_card_generation_rolls_back_the_partial_card(temp_db):
    conn, lines = _seed_games(temp_db)
    conn.execute(
        "CREATE TRIGGER fixture_force_publication_failure "
        "BEFORE INSERT ON official_card_publications "
        "BEGIN SELECT RAISE(ABORT, 'forced publication failure'); END"
    )
    conn.commit()

    with pytest.raises(WeeklyControllerError, match="forced publication failure"):
        run_tuesday_controller(conn, _tuesday_request(lines))

    assert conn.execute("SELECT COUNT(*) FROM contest_locked_lines").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM model_runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM official_card_publications").fetchone()[0] == 0
    conn.close()


def test_legacy_market_fallback_policy_is_rejected_before_official_generation(temp_db):
    conn, lines = _seed_games(temp_db)
    unsafe_selection_policy = replace(
        SELECTION_POLICY,
        version="unsafe-market-fallback-v1",
        market_books=("draftkings",),
    )

    with pytest.raises(WeeklyControllerError, match="custody lineage"):
        run_tuesday_controller(
            conn,
            _tuesday_request(lines, selection_policy=unsafe_selection_policy),
        )

    assert conn.execute("SELECT COUNT(*) FROM contest_locked_lines").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 0
    conn.close()


def test_fewer_than_five_games_publishes_an_exact_smaller_ranked_set(temp_db):
    conn, lines = _seed_games(temp_db, count=3)

    result = run_tuesday_controller(conn, _tuesday_request(lines))

    assert result.publication.pick_count == 3
    assert result.publication.top_five_count == 3
    assert {pick.rank for pick in result.card.picks} == {1, 2, 3}
    assert all(pick.is_top_five for pick in result.card.picks)
    assert inspect_official_card(conn, publication_id=result.publication.id).valid
    conn.close()


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        (
            lambda lines: lines + (lines[0],),
            "count does not match",
        ),
        (
            lambda lines: lines[:-1] + (lines[0],),
            "duplicate matchup or source line id",
        ),
        (
            lambda lines: lines[:-1]
            + (replace(lines[-1], raw_home_team="Unknown Program"),),
            "normalization is unknown",
        ),
        (
            lambda lines: lines[:-1]
            + (
                replace(
                    lines[-1],
                    raw_home_team=lines[-1].raw_away_team,
                    raw_away_team=lines[-1].raw_home_team,
                ),
            ),
            "reverses canonical",
        ),
    ),
)
def test_invalid_line_batches_fail_before_publication(temp_db, mutation, message):
    conn, lines = _seed_games(temp_db)
    invalid = mutation(lines)
    request = _tuesday_request(
        invalid,
        expected_lined_game_count=len(lines),
    )

    with pytest.raises(WeeklyControllerError, match=message):
        run_tuesday_controller(conn, request)

    assert conn.execute("SELECT COUNT(*) FROM contest_locked_lines").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM official_card_publications").fetchone()[0] == 0
    conn.close()


def test_wrong_source_or_model_candidate_cannot_enter_official_controller(temp_db):
    conn, lines = _seed_games(temp_db)
    unsafe_policy = replace(CONTROLLER_POLICY, authorized_contest_source="other-book")

    with pytest.raises(WeeklyControllerError, match="must be SplashSports"):
        run_tuesday_controller(
            conn, _tuesday_request(lines, controller_policy=unsafe_policy)
        )

    assert conn.execute("SELECT COUNT(*) FROM model_runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM official_card_publications").fetchone()[0] == 0
    conn.close()


def test_database_rejects_non_splashsports_or_incomplete_controller_policy(temp_db):
    conn, _ = _seed_games(temp_db)
    insert = (
        "INSERT INTO weekly_controller_policies "
        "(policy_version, authorized_contest_source, production_model_name, "
        "production_model_version, production_feature_schema_version, "
        "production_configuration_version, freshness_policy_version, "
        "required_source_count, effective_at, created_by, provenance) "
        "VALUES (?, ?, 'epa_only', 'epa-only-linear-v1', 'epa-differential-v1', "
        "'walk-forward-prior-seasons-v1', 'provider_freshness_v1', ?, ?, 'test', "
        "'fixture://unsafe-policy')"
    )

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("wrong-source", "OtherBook", 5, POLICY_AT.isoformat()))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("missing-source", "SplashSports", 4, POLICY_AT.isoformat()))

    assert conn.execute(
        "SELECT COUNT(*) FROM weekly_controller_policies"
    ).fetchone()[0] == 0
    conn.close()


def test_database_rejects_publication_mutation_and_incomplete_direct_insert(temp_db):
    conn, lines = _seed_games(temp_db)
    result = run_tuesday_controller(conn, _tuesday_request(lines))

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE official_card_publications SET provenance = provenance WHERE id = ?",
            (result.publication.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "DELETE FROM official_card_publications WHERE id = ?",
            (result.publication.id,),
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO official_card_publications "
            "(publication_key, controller_run_id, card_id, contest_id, card_version, "
            "published_at, locked_line_snapshot_sha256, publication_manifest_sha256, "
            "expected_locked_line_count, pick_count, top_five_count, "
            "fallback_pick_count, provenance) "
            "VALUES ('unsafe', ?, ?, ?, 99, ?, ?, ?, 5, 5, 5, 5, 'unsafe')",
            (
                result.run.id,
                result.card.card.id,
                result.card.card.contest_id,
                result.card.card.generated_at,
                result.card.card.locked_line_snapshot_sha256,
                "f" * 64,
            ),
        )
    conn.close()


def test_wednesday_refresh_publishes_next_version_without_mutating_locked_lines(temp_db):
    conn, lines = _seed_games(temp_db)
    tuesday = run_tuesday_controller(conn, _tuesday_request(lines))
    originals = list(
        conn.execute(
            "SELECT id, home_spread, locked_at, payload_sha256 "
            "FROM contest_locked_lines ORDER BY id"
        )
    )

    wednesday = run_daily_controller(
        conn, _daily_request(tuesday.publication.id)
    )
    prior_inspection = inspect_official_card(
        conn, publication_id=tuesday.publication.id
    )
    revised_inspection = inspect_official_card(
        conn, publication_id=wednesday.publication.id
    )

    assert wednesday.publication.card_version == 2
    assert wednesday.run.prior_publication_id == tuesday.publication.id
    assert len(wednesday.card.picks) == len(tuesday.card.picks) == 5
    assert list(
        conn.execute(
            "SELECT id, home_spread, locked_at, payload_sha256 "
            "FROM contest_locked_lines ORDER BY id"
        )
    ) == originals
    assert conn.execute("SELECT COUNT(*) FROM card_revisions").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM card_revision_pick_changes"
    ).fetchone()[0] == 5
    assert prior_inspection.valid is True
    assert prior_inspection.is_latest_official_version is False
    assert revised_inspection.valid is True
    assert revised_inspection.is_latest_official_version is True
    conn.close()


def test_daily_refresh_rejects_midweek_policy_change_and_nonlatest_branch(temp_db):
    conn, lines = _seed_games(temp_db)
    tuesday = run_tuesday_controller(conn, _tuesday_request(lines))
    changed_policy = replace(CONTROLLER_POLICY, policy_version="weekly-controller-v2")

    with pytest.raises(WeeklyControllerError, match="cannot change midweek"):
        run_daily_controller(
            conn,
            _daily_request(
                tuesday.publication.id,
                controller_policy=changed_policy,
                run_key="unsafe-policy-refresh",
            ),
        )

    wednesday = run_daily_controller(conn, _daily_request(tuesday.publication.id))
    with pytest.raises(WeeklyControllerError, match="latest valid"):
        run_daily_controller(
            conn,
            _daily_request(
                tuesday.publication.id,
                run_key="branched-refresh",
                publication_key="branched-publication",
                model_run_key="branched-epa-run",
                generated_at=THURSDAY_AT,
            ),
        )

    assert wednesday.publication.card_version == 2
    assert conn.execute("SELECT COUNT(*) FROM official_card_publications").fetchone()[0] == 2
    conn.close()


def test_daily_refresh_is_reproducibly_idempotent(temp_db):
    conn, lines = _seed_games(temp_db)
    tuesday = run_tuesday_controller(conn, _tuesday_request(lines))
    request = _daily_request(tuesday.publication.id)
    first = run_daily_controller(conn, request)
    counts = _table_counts(conn)

    replay = run_daily_controller(conn, request)

    assert replay.replayed is True
    assert replay.publication == first.publication
    assert _table_counts(conn) == counts
    conn.close()


def test_contextual_refresh_preserves_raw_epa_run_and_records_adjustment_effect(temp_db):
    conn, lines = _seed_games(temp_db)
    _seed_epa_inputs(conn)
    tuesday = run_tuesday_controller(conn, _tuesday_request(lines))
    assert all(pick.model_prediction_id is not None for pick in tuesday.card.picks)
    prior_pick = tuesday.card.picks[0]
    adjustment = ContextualAdjustmentInput(
        adjustment_key="week-1-game-1001-injury-1",
        game_id=1001,
        category="injury",
        affected_side="home",
        margin_adjustment=-1.5,
        confidence_adjustment=1,
        reason="Recorded fixture starter limitation.",
        evidence="fixture://injuries/game-1001/report-1",
        source="fixture-injury-report",
        author="test",
        provenance="fixture://adjustments/game-1001/1",
    )

    revised = run_daily_controller(
        conn,
        _daily_request(
            tuesday.publication.id,
            change_type="contextual_adjustment",
            model_run_key=None,
            reason="Wednesday contextual adjustment.",
            contextual_adjustments=(adjustment,),
        ),
    )
    revised_pick = next(
        pick
        for pick in revised.card.picks
        if pick.locked_line_id == prior_pick.locked_line_id
    )
    manifest = get_card_run_manifest(conn, revised.card.card.id)

    assert revised.card.card.model_run_id == tuesday.card.card.model_run_id
    assert revised_pick.model_prediction_id == prior_pick.model_prediction_id
    assert revised_pick.confidence == min(5, prior_pick.confidence + 1)
    assert manifest.adjustment_count == 1
    assert conn.execute("SELECT COUNT(*) FROM manual_adjustments").fetchone()[0] == 1
    assert inspect_official_card(conn, publication_id=revised.publication.id).valid
    conn.close()


def test_explicit_no_bet_advice_stays_separate_and_versioned_with_each_card(temp_db):
    conn, lines = _seed_games(temp_db)
    _seed_epa_inputs(conn)
    tuesday_advice = SportsbookNoBetInput(
        recommendation_key="week-1-game-1001-no-bet-v1",
        game_id=1001,
        policy_version="sportsbook-no-bet-v1",
        reason_code="insufficient_calibrated_edge",
        provenance="fixture://sportsbook/game-1001/v1",
    )
    tuesday = run_tuesday_controller(
        conn,
        _tuesday_request(
            lines,
            sportsbook_recommendations=(tuesday_advice,),
        ),
    )
    tuesday_inspection = inspect_official_card(
        conn, publication_id=tuesday.publication.id
    )

    assert len(tuesday_inspection.sportsbook_recommendations) == 1
    first_advice = tuesday_inspection.sportsbook_recommendations[0]
    first_pick = next(
        pick for pick in tuesday.card.picks if pick.id == first_advice.contest_pick_id
    )
    assert first_advice.model_prediction_id == first_pick.model_prediction_id
    assert first_advice.decision == "no_bet"
    assert first_advice.recommended_side is None
    assert first_advice.market_line_id is None
    assert first_advice.stake_units == 0

    with pytest.raises(sqlite3.IntegrityError, match="closed after publication"):
        conn.execute(
            "INSERT INTO sportsbook_recommendations "
            "(recommendation_key, model_prediction_id, contest_pick_id, "
            "decision, stake_units, policy_version, reason_code, generated_at, provenance) "
            "VALUES ('late-advice', ?, ?, 'no_bet', 0, 'sportsbook-no-bet-v1', "
            "'late_write', ?, 'fixture://sportsbook/late')",
            (
                first_advice.model_prediction_id,
                first_advice.contest_pick_id,
                first_advice.generated_at,
            ),
        )

    wednesday_advice = replace(
        tuesday_advice,
        recommendation_key="week-1-game-1001-no-bet-v2",
        reason_code="current_price_not_custodied",
        provenance="fixture://sportsbook/game-1001/v2",
    )
    wednesday = run_daily_controller(
        conn,
        _daily_request(
            tuesday.publication.id,
            sportsbook_recommendations=(wednesday_advice,),
        ),
    )
    wednesday_inspection = inspect_official_card(
        conn, publication_id=wednesday.publication.id
    )

    assert len(wednesday_inspection.sportsbook_recommendations) == 1
    second_advice = wednesday_inspection.sportsbook_recommendations[0]
    assert second_advice.contest_pick_id != first_advice.contest_pick_id
    assert second_advice.decision == "no_bet"
    assert conn.execute(
        "SELECT COUNT(*) FROM sportsbook_recommendations WHERE decision = 'bet'"
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM sportsbook_recommendations WHERE decision = 'no_bet'"
    ).fetchone()[0] == 2
    assert inspect_official_card(
        conn, publication_id=tuesday.publication.id
    ).valid
    assert wednesday_inspection.valid
    conn.close()


def test_current_custodied_sources_need_no_fallback(temp_db):
    conn, lines = _seed_games(temp_db)

    class Parser:
        version = "fixture_source_v1"

        def parse(self, conn, resolver, provider, request, record_index, record):
            return AcceptedProviderRecord(
                record_index=record_index,
                provider_record_id=record["id"],
                record_key=payload_sha256(record),
                observed_at=datetime.fromisoformat(record["observed_at"]),
                parser_version=self.version,
                raw_record_sha256=payload_sha256(record),
            )

    service = ProviderIngestionService(clock=lambda: TUESDAY_AT)
    for data_type in ("odds", "injuries", "weather", "game_status", "contextual"):
        payload = {
            "records": [
                {
                    "id": f"{data_type}-1",
                    "observed_at": TUESDAY_AT.isoformat(),
                }
            ]
        }
        service.ingest_payload(
            conn,
            IngestionRequest(
                provider="fixture-provider",
                endpoint=f"fixture://{data_type}",
                request_parameters={"season": 2026, "week": 1},
                requested_at=TUESDAY_AT,
                parser_version=Parser.version,
                raw_payload_reference=f"fixture:{data_type}.json",
                data_type=data_type,
            ),
            payload,
            Parser(),
        )
    conn.commit()

    result = run_tuesday_controller(
        conn, _tuesday_request(lines, freshness_fallbacks=())
    )

    assert {item.state for item in result.freshness} == {"current"}
    assert all(item.fallback_code is None for item in result.freshness)
    assert inspect_official_card(conn, publication_id=result.publication.id).valid
    conn.close()


def test_read_only_inspection_cli_reproduces_without_changing_database(
    temp_db, capsys
):
    conn, lines = _seed_games(temp_db)
    result = run_tuesday_controller(conn, _tuesday_request(lines))
    conn.commit()
    conn.close()
    database = Path(temp_db.DB_PATH)
    before_hash = _file_hash(database)

    exit_code = inspect_official_card_main(
        [
            "--database",
            str(database),
            "--publication-key",
            result.publication.publication_key,
        ]
    )
    output = capsys.readouterr()

    assert exit_code == 0
    assert output.err == ""
    payload = __import__("json").loads(output.out)
    assert payload["publication"]["publication_key"] == result.publication.publication_key
    assert payload["verification"]["valid"] is True
    assert payload["verification"]["publication_manifest_matches"] is True
    assert _file_hash(database) == before_hash


def test_controlled_shadow_report_proves_full_card_board_audit_and_lessons(temp_db):
    conn, lines = _seed_games(temp_db)
    _seed_epa_inputs(conn)

    class SourceParser:
        version = "shadow_source_v1"

        def parse(self, conn, resolver, provider, request, record_index, record):
            return AcceptedProviderRecord(
                record_index=record_index,
                provider_record_id=record["id"],
                record_key=payload_sha256(record),
                observed_at=datetime.fromisoformat(record["observed_at"]),
                parser_version=self.version,
                raw_record_sha256=payload_sha256(record),
            )

    service = ProviderIngestionService(clock=lambda: TUESDAY_AT)
    for data_type in ("odds", "injuries", "weather", "game_status", "contextual"):
        payload = {
            "records": [
                {"id": f"shadow-{data_type}", "observed_at": TUESDAY_AT.isoformat()}
            ]
        }
        service.ingest_payload(
            conn,
            IngestionRequest(
                provider="fixture-provider",
                endpoint=f"fixture://shadow/{data_type}",
                request_parameters={"season": 2026, "week": 1},
                requested_at=TUESDAY_AT,
                parser_version=SourceParser.version,
                raw_payload_reference=f"fixture://shadow/{data_type}.json",
                data_type=data_type,
            ),
            payload,
            SourceParser(),
        )
    conn.commit()

    sportsbook_policy = register_sportsbook_recommendation_policy(
        conn,
        policy_version="shadow-sportsbook-v1",
        residual_stddev_points=14.0,
        minimum_spread_edge_points=1.5,
        minimum_cover_probability=0.545,
        minimum_expected_value=0.025,
        maximum_odds_age_seconds=900,
        material_update_seconds=300,
        material_spread_change_points=0.5,
        material_price_change=5,
        maximum_stake_units=1.0,
        stake_units_per_expected_value=10.0,
        stake_increment_units=0.25,
        effective_at=POLICY_AT,
        created_by="test",
        provenance="fixture://shadow/sportsbook-policy",
    )

    def ingest_board(moment: datetime, movement: float) -> None:
        records = [
            {
                "matchup_id": f"shadow-{1000 + index}:draftkings",
                "game_id": 1000 + index,
                "home_team": f"Home {index}",
                "away_team": f"Away {index}",
                "market_type": "spread",
                "home_spread": -float(index) + movement,
                "home_price": -110,
                "away_spread": float(index) - movement,
                "away_price": -110,
                "line_type": "current",
                "season": 2026,
                "week": 1,
                "observed_at": moment.isoformat(),
                "event_start_at": KICKOFF,
                "bookmaker": "draftkings",
            }
            for index in range(1, 6)
        ]
        request_time = moment + timedelta(minutes=1)
        ProviderIngestionService(clock=lambda: request_time).ingest_payload(
            conn,
            IngestionRequest(
                provider="fixture-provider",
                endpoint="fixture://shadow/current-spreads",
                request_parameters={"season": 2026, "week": 1},
                requested_at=request_time,
                parser_version="odds_spread_v3",
                raw_payload_reference=f"fixture://shadow/odds/{moment.date()}.json",
                data_type="odds",
            ),
            {"records": records},
            OddsSpreadParser("odds_spread_v3"),
            accepted_writer=_odds_writer("current"),
        )

    tuesday = run_tuesday_controller(
        conn, _tuesday_request(lines, freshness_fallbacks=())
    )
    ingest_board(TUESDAY_AT, 0.0)
    evaluate_live_sportsbook_board(
        conn,
        season=2026,
        week=1,
        policy_id=sportsbook_policy.id,
        evaluated_at=TUESDAY_AT + timedelta(minutes=2),
        provenance="fixture://shadow/tuesday-board",
    )

    prior = tuesday.publication.id
    refreshes = (
        (WEDNESDAY_AT, "wednesday", 2, 0.5),
        (THURSDAY_AT, "thursday", 3, 1.0),
        (datetime(2026, 8, 28, 15, tzinfo=timezone.utc), "friday", 4, 1.5),
        (datetime(2026, 8, 29, 15, tzinfo=timezone.utc), "saturday", 5, 2.0),
    )
    for moment, label, version, movement in refreshes:
        refresh_fallbacks = tuple(
            fallback
            for fallback in _fallbacks()
            if label != "wednesday" or fallback.data_type != "contextual"
        )
        refreshed = run_daily_controller(
            conn,
            _daily_request(
                prior,
                run_key=f"week-1-{label}-controller",
                publication_key=f"week-1-official-v{version}",
                model_run_key=f"week-1-epa-run-v{version}",
                generated_at=moment,
                reason=f"{label.title()} shadow refresh.",
                freshness_fallbacks=refresh_fallbacks,
                provenance=f"fixture://shadow/{label}",
            ),
        )
        prior = refreshed.publication.id
        ingest_board(moment, movement)
        evaluate_live_sportsbook_board(
            conn,
            season=2026,
            week=1,
            policy_id=sportsbook_policy.id,
            evaluated_at=moment + timedelta(minutes=2),
            provenance=f"fixture://shadow/{label}-board",
        )

    saturday_at = refreshes[-1][0]
    closings = designate_week_closing_offers(
        conn,
        season=2026,
        week=1,
        designated_at=saturday_at + timedelta(minutes=3),
        source="fixture-final-pregame-market",
        provenance="fixture://shadow/closing-designations",
    )
    assert len(closings) == 5
    for index in range(1, 6):
        conn.execute(
            "UPDATE games SET home_points = ?, away_points = ?, completed = 1 "
            "WHERE game_id = ?",
            (24 + index, 17, 1000 + index),
        )
    conn.commit()

    audit_at = datetime(2026, 8, 31, 15, tzinfo=timezone.utc)
    final_card_id = conn.execute(
        "SELECT card_id FROM official_card_publications "
        "WHERE contest_id = ? ORDER BY card_version DESC LIMIT 1",
        (tuesday.publication.contest_id,),
    ).fetchone()[0]
    requests = {
        int(row[0]): PostgameAuditRequest(int(row[1]))
        for row in conn.execute(
            "SELECT locked.id, designation.closing_betting_line_id "
            "FROM contest_locked_lines AS locked "
            "JOIN sportsbook_closing_designations AS designation "
            "ON designation.game_id = locked.game_id "
            "WHERE locked.contest_id = ?",
            (tuesday.publication.contest_id,),
        )
    }
    contest_audit = audit_contest_card(
        conn,
        audit_run_key="shadow-contest-audit",
        card_id=int(final_card_id),
        audit_policy=PostgameAuditPolicy(
            "shadow-audit-v1", POLICY_AT, "test", "fixture://shadow/audit-policy"
        ),
        requests_by_locked_line_id=requests,
        source="fixture-final-scores",
        provenance="fixture://shadow/contest-audit",
        audited_at=audit_at,
    )
    sportsbook_audit = audit_sportsbook_recommendations(
        conn,
        audit_run_key="shadow-sportsbook-audit",
        season=2026,
        week=1,
        policy_id=sportsbook_policy.id,
        source="fixture-final-scores",
        provenance="fixture://shadow/sportsbook-audit",
        audited_at=audit_at,
    )
    assert sportsbook_audit.report.all_clv_available is True
    diagnostics = generate_weekly_diagnostics(
        conn,
        diagnostic_run_key="shadow-weekly-diagnostics",
        audit_run_id=contest_audit.run.id,
        diagnostic_policy=WeeklyDiagnosticsPolicy(
            policy_version="shadow-diagnostics-v1",
            minimum_recommendation_sample=20,
            minimum_ats_delta_percentage_points=10.0,
            confidence_threshold_step_points=0.5,
            effective_at=POLICY_AT,
            created_by="test",
            provenance="fixture://shadow/diagnostics-policy",
        ),
        source="fixture-weekly-audit",
        provenance="fixture://shadow/diagnostics",
        generated_at=audit_at + timedelta(hours=1),
    )
    assert diagnostics.report.complete is True

    report = inspect_controlled_shadow_rehearsal(
        conn,
        contest_key="splashsports-2026-week-1",
        season=2026,
        week=1,
        expected_lined_game_count=5,
        sportsbook_policy_id=sportsbook_policy.id,
    )

    assert report.successful is True
    assert report.official_publication_count == 5
    assert report.revision_count == 4
    assert report.locked_line_count == 5
    assert all(card.pick_count == card.confidence_coverage_count == 5 for card in report.card_versions)
    assert all(card.top_five_count == 5 for card in report.card_versions)
    assert report.sportsbook_game_coverage_count == 5
    assert report.sportsbook_evaluation_count == 25
    assert report.sportsbook_supersession_count == 20
    assert report.sportsbook_audit_count == 25
    assert report.sportsbook_clv_graded_count == 25
    assert report.sportsbook_missing_clv_count == 0
    assert report.draftkings_provider_capture_attempted is True
    assert report.draftkings_offers_received_count == 25
    assert report.draftkings_eligible_games_with_offers_count == 5
    assert report.draftkings_eligible_offers_evaluated_count == 25
    assert report.draftkings_bet_count + report.draftkings_no_bet_count == 25
    assert report.draftkings_unavailable_count == 0
    assert report.draftkings_stale_count == 0
    assert report.draftkings_supersession_count == 20
    assert report.draftkings_recommendation_reproduction_passed is True
    assert report.draftkings_closing_line_coverage == "5/5"
    assert report.draftkings_clv_coverage == "25/25"
    assert report.draftkings_grading_coverage == "25/25"
    assert report.contest_audit_count == 5
    assert report.lesson_count == len(report.lessons) == 4
    assert report.wagers_placed == 0
    conn.close()


def test_draftkings_board_records_unavailable_without_book_or_contest_substitution(
    temp_db,
):
    conn, lines = _seed_games(temp_db)
    _seed_epa_inputs(conn)
    tuesday = run_tuesday_controller(conn, _tuesday_request(lines))
    policy = register_sportsbook_recommendation_policy(
        conn,
        policy_version="draftkings-board-v1",
        residual_stddev_points=14.0,
        minimum_spread_edge_points=1.5,
        minimum_cover_probability=0.545,
        minimum_expected_value=0.025,
        maximum_odds_age_seconds=900,
        material_update_seconds=300,
        material_spread_change_points=0.5,
        material_price_change=5,
        maximum_stake_units=1.0,
        stake_units_per_expected_value=10.0,
        stake_increment_units=0.25,
        effective_at=POLICY_AT,
        created_by="test",
        provenance="fixture://draftkings-board-policy",
    )
    payload = {
        "records": [
            {
                "matchup_id": "fanduel-only-1001",
                "game_id": 1001,
                "home_team": "Home 1",
                "away_team": "Away 1",
                "market_type": "spread",
                "home_spread": -7.5,
                "home_price": -110,
                "away_spread": 7.5,
                "away_price": -110,
                "line_type": "current",
                "season": 2026,
                "week": 1,
                "observed_at": TUESDAY_AT.isoformat(),
                "event_start_at": KICKOFF,
                "bookmaker": "fanduel",
            }
        ]
    }
    summary = ProviderIngestionService(clock=lambda: TUESDAY_AT).ingest_payload(
        conn,
        IngestionRequest(
            provider="fixture-odds",
            endpoint="fixture://draftkings-request-returned-fanduel-only",
            request_parameters={
                "season": 2026,
                "week": 1,
                "bookmakers": "draftkings,fanduel",
            },
            requested_at=TUESDAY_AT,
            parser_version="odds_spread_v3",
            raw_payload_reference="fixture://fanduel-only.json",
            data_type="odds",
        ),
        payload,
        OddsSpreadParser("odds_spread_v3"),
        accepted_writer=_odds_writer("current"),
    )
    evaluate_live_sportsbook_board(
        conn,
        season=2026,
        week=1,
        policy_id=policy.id,
        evaluated_at=TUESDAY_AT + timedelta(minutes=1),
        provenance="fixture://comparison-board",
    )

    board = build_draftkings_betting_board(
        conn,
        contest_id=tuesday.publication.contest_id,
        policy_id=policy.id,
        season=2026,
        week=1,
        provider_ingestion_run_ids=(summary.ingestion_run_id,),
    )

    assert len(board) == len(lines) == 5
    assert all(row.bookmaker == "DraftKings" for row in board)
    assert all(row.decision == "DRAFTKINGS_UNAVAILABLE" for row in board)
    assert all(row.reason_code == "DRAFTKINGS_SPREAD_NOT_RETURNED" for row in board)
    assert all(row.offered_spread is None and row.offered_price is None for row in board)
    assert all(row.provider_capture_attempted is True for row in board)
    assert all(row.observation_timestamp == TUESDAY_AT.isoformat() for row in board)
    assert board[0].owner_summary().startswith("UNAVAILABLE | Away 1 at Home 1")
    assert conn.execute(
        "SELECT COUNT(*) FROM sportsbook_recommendation_evaluations AS evaluation "
        "JOIN sportsbook_market_offers AS offer ON offer.id = evaluation.market_offer_id "
        "WHERE offer.bookmaker = 'fanduel'"
    ).fetchone()[0] == 1
    conn.close()
