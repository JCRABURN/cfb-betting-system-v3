import sqlite3
from datetime import datetime, timezone

import pytest

from business_entities import (
    BusinessEntityConflictError,
    BusinessEntityError,
    add_contest_pick,
    create_contest_card,
    list_manual_adjustments,
    list_pick_audits,
    record_card_revision,
    record_manual_adjustment,
    record_model_prediction,
    record_model_run,
    record_pick_audit,
    record_sportsbook_recommendation,
)
from contest_lines import create_contest, lock_contest_line


RECORDED_AT = datetime(2026, 8, 1, 12, tzinfo=timezone.utc)
FINAL_AT = datetime(2026, 8, 2, 12, tzinfo=timezone.utc)


def _seed(temp_db):
    conn = temp_db.get_connection()
    conn.execute(
        "INSERT INTO games "
        "(game_id, season, week, home_team, away_team) "
        "VALUES (101, 2026, 1, 'Home State', 'Away Tech')"
    )
    current_line_id = conn.execute(
        "INSERT INTO betting_lines "
        "(game_id, season, week, home_team, away_team, book, home_spread, "
        "line_type, source, fetched_at) "
        "VALUES (101, 2026, 1, 'Home State', 'Away Tech', 'fixture', -3.5, "
        "'current', 'fixture', '2026-08-01T11:00:00+00:00')"
    ).lastrowid
    closing_line_id = conn.execute(
        "INSERT INTO betting_lines "
        "(game_id, season, week, home_team, away_team, book, home_spread, "
        "line_type, source, fetched_at) "
        "VALUES (101, 2026, 1, 'Home State', 'Away Tech', 'fixture', -4.0, "
        "'closing', 'fixture', '2026-08-01T20:00:00+00:00')"
    ).lastrowid
    contest = create_contest(
        conn,
        contest_key="week-1",
        name="Week 1",
        season=2026,
        week=1,
        source="fixture",
        provenance="test fixture",
        created_at=RECORDED_AT,
    )
    locked = lock_contest_line(
        conn,
        contest_id=contest.id,
        game_id=101,
        raw_home_team="Home State",
        raw_away_team="Away Tech",
        normalized_home_team="Home State",
        normalized_away_team="Away Tech",
        home_spread=-3.5,
        source="fixture",
        provenance="test fixture",
        payload_sha256="a" * 64,
        locked_at=RECORDED_AT,
    ).line
    run = record_model_run(
        conn,
        run_key="model-run-1",
        model_name="fixture-model",
        model_version="1.0",
        feature_schema_version="1",
        configuration_version="fixture-config-1",
        code_commit_sha="b" * 40,
        data_snapshot_sha256="c" * 64,
        status="completed",
        provenance="test fixture",
        generated_at=RECORDED_AT,
    )
    prediction = record_model_prediction(
        conn,
        prediction_key="prediction-101",
        model_run_id=run.id,
        game_id=101,
        predicted_home_margin=6.25,
        home_win_probability=0.64,
        uncertainty_points=4.5,
        entry_locked_line_id=locked.id,
        provenance="test fixture",
        generated_at=RECORDED_AT,
    )
    card = create_contest_card(
        conn,
        card_key="card-week-1-v1",
        contest_id=contest.id,
        model_run_id=run.id,
        version=1,
        status="draft",
        policy_version="contest-policy-1",
        locked_line_snapshot_sha256="d" * 64,
        created_by="test",
        provenance="test fixture",
        generated_at=RECORDED_AT,
    )
    pick = add_contest_pick(
        conn,
        pick_key="pick-week-1-101",
        card_id=card.id,
        locked_line_id=locked.id,
        model_prediction_id=prediction.id,
        selected_side="home",
        confidence=4,
        rank=1,
        is_top_five=True,
        provenance="test fixture",
        generated_at=RECORDED_AT,
    )
    return {
        "conn": conn,
        "contest": contest,
        "locked": locked,
        "run": run,
        "prediction": prediction,
        "card": card,
        "pick": pick,
        "current_line_id": current_line_id,
        "closing_line_id": closing_line_id,
    }


def test_entities_are_separate_and_do_not_write_legacy_picks(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]

    assert conn.execute("SELECT COUNT(*) FROM model_runs").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM model_predictions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM contest_picks").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sportsbook_recommendations").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM picks").fetchone()[0] == 0
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert list(conn.execute("PRAGMA foreign_key_check")) == []
    conn.close()


def test_model_recording_is_idempotent_and_rejects_key_conflicts(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    run = seeded["run"]

    replay = record_model_run(
        conn,
        run_key="model-run-1",
        model_name="fixture-model",
        model_version="1.0",
        feature_schema_version="1",
        configuration_version="fixture-config-1",
        code_commit_sha="b" * 40,
        data_snapshot_sha256="c" * 64,
        status="completed",
        provenance="test fixture",
    )
    assert replay == run
    with pytest.raises(BusinessEntityConflictError, match="different immutable"):
        record_model_run(
            conn,
            run_key="model-run-1",
            model_name="changed-model",
            model_version="1.0",
            feature_schema_version="1",
            configuration_version="fixture-config-1",
            code_commit_sha="b" * 40,
            data_snapshot_sha256="c" * 64,
            status="completed",
            provenance="test fixture",
        )
    with pytest.raises(BusinessEntityError, match="only one entry-line"):
        record_model_prediction(
            conn,
            prediction_key="bad-prediction",
            model_run_id=run.id,
            game_id=101,
            predicted_home_margin=1,
            entry_market_line_id=seeded["current_line_id"],
            entry_locked_line_id=seeded["locked"].id,
            provenance="test",
        )
    with pytest.raises(BusinessEntityError, match="opening or current"):
        record_model_prediction(
            conn,
            prediction_key="closing-line-lookahead",
            model_run_id=run.id,
            game_id=101,
            predicted_home_margin=1,
            entry_market_line_id=seeded["closing_line_id"],
            provenance="test",
            generated_at=FINAL_AT,
        )
    conn.close()


def test_manual_adjustments_append_without_changing_raw_prediction(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    prediction = seeded["prediction"]
    first = record_manual_adjustment(
        conn,
        adjustment_key="adjustment-1",
        model_prediction_id=prediction.id,
        contest_pick_id=seeded["pick"].id,
        category="injury",
        affected_side="home",
        margin_adjustment=-1.5,
        confidence_adjustment=-1,
        reason="starting quarterback unavailable",
        evidence="starter listed unavailable",
        source="fixture report",
        author="test",
        provenance="test fixture",
        recorded_at=RECORDED_AT,
    )
    second = record_manual_adjustment(
        conn,
        adjustment_key="adjustment-2",
        model_prediction_id=prediction.id,
        category="weather",
        affected_side="both",
        margin_adjustment=0,
        confidence_adjustment=-1,
        reason="high wind",
        evidence="forecast wind above threshold",
        source="fixture weather",
        author="test",
        provenance="test fixture",
        recorded_at=RECORDED_AT,
    )

    assert (first.sequence, first.supersedes_adjustment_id) == (1, None)
    assert (second.sequence, second.supersedes_adjustment_id) == (2, first.id)
    assert [item.id for item in list_manual_adjustments(conn, prediction.id)] == [
        first.id,
        second.id,
    ]
    assert conn.execute(
        "SELECT predicted_home_margin FROM model_predictions WHERE id = ?",
        (prediction.id,),
    ).fetchone()[0] == 6.25
    conn.close()


def test_card_revision_links_consecutive_snapshots(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    revised = create_contest_card(
        conn,
        card_key="card-week-1-v2",
        contest_id=seeded["contest"].id,
        model_run_id=seeded["run"].id,
        version=2,
        status="draft",
        policy_version="contest-policy-1",
        locked_line_snapshot_sha256="e" * 64,
        created_by="test",
        provenance="test fixture",
        generated_at=RECORDED_AT,
    )
    revision = record_card_revision(
        conn,
        revision_key="week-1-revision-1",
        prior_card_id=seeded["card"].id,
        revised_card_id=revised.id,
        change_type="contextual_adjustment",
        reason="documented quarterback change",
        author="test",
        provenance="test fixture",
        revised_at=RECORDED_AT,
    )
    assert revision.prior_card_id == seeded["card"].id
    assert revision.revised_card_id == revised.id
    with pytest.raises(BusinessEntityError, match="consecutive versions"):
        record_card_revision(
            conn,
            revision_key="backwards",
            prior_card_id=revised.id,
            revised_card_id=seeded["card"].id,
            change_type="bug_fix",
            reason="invalid",
            author="test",
            provenance="test fixture",
        )
    conn.close()


def test_sportsbook_recommendations_have_independent_policy_and_validation(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    recommendation = record_sportsbook_recommendation(
        conn,
        recommendation_key="recommendation-101",
        model_prediction_id=seeded["prediction"].id,
        contest_pick_id=seeded["pick"].id,
        market_line_id=seeded["current_line_id"],
        decision="bet",
        recommended_side="home",
        offered_price=-110,
        expected_value=0.034,
        stake_units=0.5,
        policy_version="sportsbook-policy-1",
        reason_code="positive_ev",
        provenance="test fixture",
        generated_at=RECORDED_AT,
    )
    assert recommendation.decision == "bet"
    assert conn.execute("SELECT COUNT(*) FROM contest_picks").fetchone()[0] == 1
    with pytest.raises(BusinessEntityError, match="no_bet"):
        record_sportsbook_recommendation(
            conn,
            recommendation_key="invalid-no-bet",
            model_prediction_id=seeded["prediction"].id,
            decision="no_bet",
            recommended_side="home",
            policy_version="sportsbook-policy-1",
            reason_code="invalid",
            provenance="test fixture",
        )
    with pytest.raises(BusinessEntityError, match="opening or current"):
        record_sportsbook_recommendation(
            conn,
            recommendation_key="closing-line-wager",
            model_prediction_id=seeded["prediction"].id,
            market_line_id=seeded["closing_line_id"],
            decision="bet",
            recommended_side="home",
            offered_price=-110,
            expected_value=0.01,
            stake_units=0.25,
            policy_version="sportsbook-policy-1",
            reason_code="invalid_closing_line",
            provenance="test fixture",
            generated_at=FINAL_AT,
        )
    conn.close()


def test_pick_audit_corrections_append_in_order(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    pending = record_pick_audit(
        conn,
        audit_key="audit-101-pending",
        contest_pick_id=seeded["pick"].id,
        audit_status="pending",
        result="pending",
        policy_version="audit-policy-1",
        source="fixture",
        provenance="test fixture",
        audited_at=RECORDED_AT,
    )
    final = record_pick_audit(
        conn,
        audit_key="audit-101-final",
        contest_pick_id=seeded["pick"].id,
        audit_status="final",
        result="win",
        final_home_points=28,
        final_away_points=20,
        closing_market_line_id=seeded["closing_line_id"],
        clv_points=0.5,
        policy_version="audit-policy-1",
        source="fixture",
        provenance="test fixture",
        audited_at=FINAL_AT,
    )
    assert (final.sequence, final.supersedes_audit_id) == (2, pending.id)
    assert [item.result for item in list_pick_audits(conn, seeded["pick"].id)] == [
        "pending",
        "win",
    ]
    with pytest.raises(BusinessEntityError, match="require a closing"):
        record_pick_audit(
            conn,
            audit_key="invalid-current-line",
            contest_pick_id=seeded["pick"].id,
            audit_status="final",
            result="win",
            final_home_points=28,
            final_away_points=20,
            closing_market_line_id=seeded["current_line_id"],
            policy_version="audit-policy-1",
            source="fixture",
            provenance="test fixture",
            audited_at=FINAL_AT,
        )
    with pytest.raises(BusinessEntityError, match="final audits require"):
        record_pick_audit(
            conn,
            audit_key="invalid-final",
            contest_pick_id=seeded["pick"].id,
            audit_status="final",
            result="win",
            policy_version="audit-policy-1",
            source="fixture",
            provenance="test fixture",
        )
    conn.close()


def test_all_new_business_records_are_immutable_and_non_replaceable(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    revised_card = create_contest_card(
        conn,
        card_key="card-week-1-immutable-v2",
        contest_id=seeded["contest"].id,
        model_run_id=seeded["run"].id,
        version=2,
        status="draft",
        policy_version="contest-policy-1",
        locked_line_snapshot_sha256="f" * 64,
        created_by="test",
        provenance="test fixture",
        generated_at=RECORDED_AT,
    )
    revision = record_card_revision(
        conn,
        revision_key="revision-immutable",
        prior_card_id=seeded["card"].id,
        revised_card_id=revised_card.id,
        change_type="bug_fix",
        reason="fixture correction",
        author="test",
        provenance="test fixture",
        revised_at=RECORDED_AT,
    )
    adjustment = record_manual_adjustment(
        conn,
        adjustment_key="adjustment-immutable",
        model_prediction_id=seeded["prediction"].id,
        category="other",
        affected_side="both",
        margin_adjustment=1,
        confidence_adjustment=0,
        reason="fixture",
        evidence="fixture evidence",
        source="fixture",
        author="test",
        provenance="test fixture",
    )
    audit = record_pick_audit(
        conn,
        audit_key="audit-immutable",
        contest_pick_id=seeded["pick"].id,
        audit_status="pending",
        result="pending",
        policy_version="1",
        source="fixture",
        provenance="test fixture",
    )
    recommendation = record_sportsbook_recommendation(
        conn,
        recommendation_key="recommendation-immutable",
        model_prediction_id=seeded["prediction"].id,
        decision="no_bet",
        policy_version="1",
        reason_code="fixture",
        provenance="test fixture",
    )
    rows = {
        "model_runs": seeded["run"].id,
        "model_predictions": seeded["prediction"].id,
        "contest_cards": seeded["card"].id,
        "contest_picks": seeded["pick"].id,
        "sportsbook_recommendations": recommendation.id,
        "card_revisions": revision.id,
        "manual_adjustments": adjustment.id,
        "pick_audits": audit.id,
    }
    for table, row_id in rows.items():
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(f"UPDATE {table} SET id = id WHERE id = ?", (row_id,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    with pytest.raises(sqlite3.IntegrityError, match="cannot be replaced"):
        conn.execute(
            "INSERT OR REPLACE INTO model_runs "
            "(id, run_key, model_name, model_version, feature_schema_version, "
            "configuration_version, code_commit_sha, data_snapshot_sha256, status, "
            "generated_at, provenance) "
            "SELECT id, run_key, model_name, model_version, feature_schema_version, "
            "configuration_version, code_commit_sha, data_snapshot_sha256, status, "
            "generated_at, provenance "
            "FROM model_runs WHERE id = ?",
            (seeded["run"].id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be replaced"):
        conn.execute(
            "INSERT OR REPLACE INTO model_predictions "
            "(prediction_key, model_run_id, game_id, predicted_home_margin, "
            "generated_at, provenance) "
            "SELECT 'replacement-key', model_run_id, game_id, predicted_home_margin, "
            "generated_at, provenance FROM model_predictions WHERE id = ?",
            (seeded["prediction"].id,),
        )
    conn.close()
