import sqlite3
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from business_entities import (
    BusinessEntityConflictError,
    BusinessEntityError,
    ConfidenceRankingPolicy,
    FullCardError,
    FullCardPolicy,
    ManualAdjustmentPolicy,
    create_contest_card,
    generate_full_card,
    get_card_ranking_policy,
    inspect_full_card,
    record_model_prediction,
    record_model_run,
    register_confidence_ranking_policy,
)
from business_entities.ranking import (
    confidence_for_uncertainty,
    validate_confidence_ranking_policy,
)
from contest_lines import create_contest, lock_contest_line


POLICY_AT = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
LOCKED_AT = datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
RUN_AT = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)
PREDICTION_AT = datetime(2026, 8, 25, 15, 45, tzinfo=timezone.utc)
GENERATED_AT = datetime(2026, 8, 25, 16, tzinfo=timezone.utc)
AFTER_CARD = datetime(2026, 8, 25, 17, tzinfo=timezone.utc)
KICKOFF = "2026-08-29T17:00:00+00:00"

SIDE_POLICY = FullCardPolicy(
    version="full-card-v1",
    market_books=("draftkings", "fanduel"),
)
CONFIDENCE_POLICY = ConfidenceRankingPolicy(
    policy_key="contest-confidence-ranking-v1",
    confidence_policy_version="confidence-v1",
    ranking_policy_version="top-five-v1",
    confidence_5_max_uncertainty=2.0,
    confidence_4_max_uncertainty=4.0,
    confidence_3_max_uncertainty=6.0,
    confidence_2_max_uncertainty=8.0,
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://confidence-ranking-policy",
)
ADJUSTMENT_POLICY = ManualAdjustmentPolicy(
    policy_version="manual-adjustments-v1",
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://manual-adjustment-policy",
)


def _seed_components(temp_db, uncertainties):
    conn = temp_db.get_connection()
    contest = create_contest(
        conn,
        contest_key="ranking-week-1",
        name="Ranking Week 1",
        season=2026,
        week=1,
        source="fixture-contest",
        provenance="fixture://ranking-contest",
        created_at=LOCKED_AT,
    )
    run = record_model_run(
        conn,
        run_key="ranking-model-run",
        model_name="fixture-model",
        model_version="1",
        feature_schema_version="1",
        configuration_version="fixture-config-1",
        code_commit_sha="a" * 40,
        data_snapshot_sha256="b" * 64,
        status="completed",
        provenance="fixture://ranking-run",
        generated_at=RUN_AT,
    )
    predicted_margins = (4.0, 20.0, -20.0, 50.0, -50.0, 100.0, -100.0)
    lines = []
    for offset, uncertainty in enumerate(uncertainties, start=1):
        game_id = 400 + offset
        home = f"Ranking Home {offset}"
        away = f"Ranking Away {offset}"
        conn.execute(
            "INSERT INTO games "
            "(game_id, season, week, home_team, away_team, start_date) "
            "VALUES (?, 2026, 1, ?, ?, ?)",
            (game_id, home, away, KICKOFF),
        )
        locked = lock_contest_line(
            conn,
            contest_id=contest.id,
            game_id=game_id,
            raw_home_team=home,
            raw_away_team=away,
            normalized_home_team=home,
            normalized_away_team=away,
            home_spread=-3.0,
            source="fixture-contest",
            source_line_id=f"ranking-line-{game_id}",
            provenance=f"fixture://ranking-line/{game_id}",
            payload_sha256=f"{offset:x}" * 64,
            locked_at=LOCKED_AT,
        ).line
        lines.append(locked)
        record_model_prediction(
            conn,
            prediction_key=f"ranking-prediction-{game_id}",
            model_run_id=run.id,
            game_id=game_id,
            predicted_home_margin=predicted_margins[offset - 1],
            uncertainty_points=uncertainty,
            entry_locked_line_id=locked.id,
            provenance=f"fixture://ranking-prediction/{game_id}",
            generated_at=PREDICTION_AT,
        )
    conn.commit()
    return conn, contest, run, tuple(lines)


def _generate(conn, contest, run, confidence_policy=CONFIDENCE_POLICY):
    return generate_full_card(
        conn,
        card_key="ranking-card-v1",
        contest_id=contest.id,
        model_run_id=run.id,
        version=1,
        policy=SIDE_POLICY,
        confidence_policy=confidence_policy,
        adjustment_policy=ADJUSTMENT_POLICY,
        created_by="test",
        provenance="fixture://ranking-card",
        generated_at=GENERATED_AT,
    )


def test_confidence_threshold_boundaries_and_missing_input_floor():
    cases = (
        (None, 1),
        (0.0, 5),
        (2.0, 5),
        (2.01, 4),
        (4.0, 4),
        (4.01, 3),
        (6.0, 3),
        (6.01, 2),
        (8.0, 2),
        (8.01, 1),
    )
    assert [
        confidence_for_uncertainty(CONFIDENCE_POLICY, uncertainty)
        for uncertainty, _ in cases
    ] == [expected for _, expected in cases]


def test_top_five_uses_uncertainty_not_raw_edge_and_stores_policy(temp_db):
    uncertainties = (1.0, 3.0, 5.0, 7.0, 9.0, None, 3.0)
    conn, contest, run, lines = _seed_components(temp_db, uncertainties)
    result = _generate(conn, contest, run)
    picks = result.picks

    assert [pick.confidence for pick in picks] == [5, 4, 3, 2, 1, 1, 4]
    assert [pick.rank for pick in picks] == [5, 4, 2, 1, None, None, 3]
    assert [pick.is_top_five for pick in picks] == [
        True,
        True,
        True,
        True,
        False,
        False,
        True,
    ]
    assert picks[0].rank == 5
    assert abs(4.0 - 3.0) < abs(-50.0 - 3.0)
    assert picks[4].rank is None
    assert picks[1].rank > picks[6].rank
    assert lines[1].id < lines[6].id
    assert all("confidence_policy_version=confidence-v1" in pick.provenance for pick in picks)
    assert all("ranking_policy_version=top-five-v1" in pick.provenance for pick in picks)

    recorded = get_card_ranking_policy(conn, result.card.id)
    assert recorded.confidence_policy_version == "confidence-v1"
    assert recorded.ranking_policy_version == "top-five-v1"
    assert recorded.reliability_metric == "model_uncertainty_points"
    assert recorded.ranking_method == "confidence_desc_uncertainty_asc"
    assert recorded.tie_breaker == "locked_line_id_asc"
    assert conn.execute(
        "SELECT COUNT(*) FROM contest_card_policy_assignments"
    ).fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE contest_card_policy_assignments SET card_id = card_id "
            "WHERE card_id = ?",
            (result.card.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "DELETE FROM contest_card_policy_assignments WHERE card_id = ?",
            (result.card.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be replaced"):
        conn.execute(
            "INSERT OR REPLACE INTO contest_card_policy_assignments "
            "SELECT * FROM contest_card_policy_assignments WHERE card_id = ?",
            (result.card.id,),
        )
    assert result.report.confidence_coverage_count == 7
    assert result.report.top_five_count == 5
    assert result.report.ranked_pick_count == 5
    assert result.report.contest_complete is True
    assert result.report.official_ready is True
    assert conn.execute(
        "SELECT COUNT(*) FROM sportsbook_recommendations"
    ).fetchone()[0] == 0
    conn.close()


def test_fewer_than_five_games_are_all_ranked_with_stable_ties(temp_db):
    conn, contest, run, lines = _seed_components(temp_db, (None, None, None))
    result = _generate(conn, contest, run)

    assert [pick.confidence for pick in result.picks] == [1, 1, 1]
    assert [pick.rank for pick in result.picks] == [3, 2, 1]
    assert all(pick.is_top_five for pick in result.picks)
    assert [pick.locked_line_id for pick in result.picks] == [line.id for line in lines]
    assert result.report.top_five_count == 3
    assert result.report.contest_complete is True
    conn.close()


def test_policy_versions_are_immutable_and_cannot_be_reused_for_new_values(temp_db):
    conn = temp_db.get_connection()
    first = register_confidence_ranking_policy(conn, CONFIDENCE_POLICY)
    replay = register_confidence_ranking_policy(conn, CONFIDENCE_POLICY)
    assert replay == first

    with pytest.raises(BusinessEntityConflictError, match="different immutable"):
        register_confidence_ranking_policy(
            conn,
            replace(CONFIDENCE_POLICY, confidence_5_max_uncertainty=1.5),
        )
    with pytest.raises(BusinessEntityConflictError, match="different immutable"):
        register_confidence_ranking_policy(
            conn,
            replace(CONFIDENCE_POLICY, policy_key="different-key"),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE contest_ranking_policies SET policy_key = policy_key WHERE id = ?",
            (first.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute("DELETE FROM contest_ranking_policies WHERE id = ?", (first.id,))
    with pytest.raises(sqlite3.IntegrityError, match="cannot be replaced"):
        conn.execute(
            "INSERT OR REPLACE INTO contest_ranking_policies "
            "SELECT * FROM contest_ranking_policies WHERE id = ?",
            (first.id,),
        )
    conn.close()


def test_invalid_or_future_policy_fails_without_card_policy_or_pick_rows(temp_db):
    with pytest.raises(BusinessEntityError, match="strictly increasing"):
        validate_confidence_ranking_policy(
            replace(CONFIDENCE_POLICY, confidence_4_max_uncertainty=2.0)
        )

    conn, contest, run, _ = _seed_components(temp_db, (2.0,))
    with pytest.raises(BusinessEntityError, match="effective at generation"):
        _generate(
            conn,
            contest,
            run,
            replace(CONFIDENCE_POLICY, effective_at=AFTER_CARD),
        )
    for table in (
        "contest_ranking_policies",
        "contest_cards",
        "contest_card_policy_assignments",
        "contest_picks",
    ):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    conn.close()


def test_replay_rejects_a_different_policy_without_mutation(temp_db):
    conn, contest, run, _ = _seed_components(temp_db, (1.0, 3.0, 5.0, 7.0, 9.0))
    result = _generate(conn, contest, run)
    different = replace(
        CONFIDENCE_POLICY,
        policy_key="contest-confidence-ranking-v2",
        confidence_policy_version="confidence-v2",
        ranking_policy_version="top-five-v2",
    )

    report = inspect_full_card(
        conn,
        result.card.id,
        policy=SIDE_POLICY,
        confidence_policy=different,
        adjustment_policy=ADJUSTMENT_POLICY,
    )
    assert report.side_complete is True
    assert report.confidence_ranking_policy_matches is False
    assert report.contest_complete is False
    with pytest.raises(FullCardError, match="different Confidence or ranking policy"):
        _generate(conn, contest, run, different)
    assert conn.execute(
        "SELECT COUNT(*) FROM contest_ranking_policies"
    ).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM contest_picks").fetchone()[0] == 5
    conn.close()


def test_official_card_inserts_are_blocked_until_validated_publication_exists(temp_db):
    conn, contest, run, _ = _seed_components(temp_db, (2.0,))
    common = dict(
        card_key="unsafe-official-card",
        contest_id=contest.id,
        model_run_id=run.id,
        version=1,
        status="official",
        policy_version=SIDE_POLICY.version,
        locked_line_snapshot_sha256="c" * 64,
        created_by="test",
        provenance="fixture://unsafe-official",
        generated_at=GENERATED_AT,
    )
    with pytest.raises(BusinessEntityError, match="validated publication"):
        create_contest_card(conn, **common)
    with pytest.raises(sqlite3.IntegrityError, match="validated publication"):
        conn.execute(
            "INSERT INTO contest_cards "
            "(card_key, contest_id, model_run_id, version, status, policy_version, "
            "locked_line_snapshot_sha256, generated_at, created_by, provenance) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                common["card_key"],
                common["contest_id"],
                common["model_run_id"],
                common["version"],
                common["status"],
                common["policy_version"],
                common["locked_line_snapshot_sha256"],
                GENERATED_AT.isoformat(),
                common["created_by"],
                common["provenance"],
            ),
        )
    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 0
    conn.close()
