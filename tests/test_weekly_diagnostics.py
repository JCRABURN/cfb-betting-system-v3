import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from business_entities import (
    BusinessEntityConflictError,
    BusinessEntityError,
    ConfidenceRankingPolicy,
    FullCardPolicy,
    ManualAdjustmentPolicy,
    PostgameAuditPolicy,
    PostgameAuditRequest,
    WeeklyDiagnosticsPolicy,
    audit_contest_card,
    generate_full_card,
    generate_weekly_diagnostics,
    record_manual_adjustment,
    record_model_prediction,
    record_model_run,
    validate_weekly_diagnostics,
)
from contest_lines import create_contest, lock_contest_line


POLICY_AT = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
LOCKED_AT = datetime(2026, 8, 25, 14, tzinfo=timezone.utc)
RUN_AT = datetime(2026, 8, 25, 14, 30, tzinfo=timezone.utc)
PREDICTION_AT = datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
ADJUSTMENT_AT = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)
CARD_AT = datetime(2026, 8, 25, 16, tzinfo=timezone.utc)
CLOSING_AT = datetime(2026, 8, 29, 16, tzinfo=timezone.utc)
KICKOFF_AT = datetime(2026, 8, 29, 17, tzinfo=timezone.utc)
AUDITED_AT = datetime(2026, 8, 30, 12, tzinfo=timezone.utc)
DIAGNOSTIC_AT = datetime(2026, 8, 30, 13, tzinfo=timezone.utc)

SELECTION_POLICY = FullCardPolicy(
    version="diagnostic-card-v1",
    market_books=("draftkings", "fanduel"),
    model_tie_side="away",
    pickem_tiebreak_side="home",
)
RANKING_POLICY = ConfidenceRankingPolicy(
    policy_key="diagnostic-ranking-v1",
    confidence_policy_version="diagnostic-confidence-v1",
    ranking_policy_version="diagnostic-top-five-v1",
    confidence_5_max_uncertainty=2,
    confidence_4_max_uncertainty=4,
    confidence_3_max_uncertainty=6,
    confidence_2_max_uncertainty=8,
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://diagnostic-ranking-policy",
)
ADJUSTMENT_POLICY = ManualAdjustmentPolicy(
    policy_version="diagnostic-adjustments-v1",
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://diagnostic-adjustment-policy",
)
AUDIT_POLICY = PostgameAuditPolicy(
    policy_version="diagnostic-audit-v1",
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://diagnostic-audit-policy",
)
DIAGNOSTIC_POLICY = WeeklyDiagnosticsPolicy(
    policy_version="weekly-diagnostics-v1",
    minimum_recommendation_sample=5,
    minimum_ats_delta_percentage_points=20,
    confidence_threshold_step_points=0.5,
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://weekly-diagnostics-policy",
)


def _seed_completed_audit(temp_db):
    conn = temp_db.get_connection()
    contest = create_contest(
        conn,
        contest_key="diagnostic-week-1",
        name="Diagnostic Week 1",
        season=2026,
        week=1,
        source="fixture-contest",
        provenance="fixture://diagnostic-contest",
        created_at=LOCKED_AT,
    )
    model_run = record_model_run(
        conn,
        run_key="diagnostic-model-run",
        model_name="fixture-model",
        model_version="model-v1",
        feature_schema_version="features-v1",
        configuration_version="config-v1",
        code_commit_sha="a" * 40,
        data_snapshot_sha256="b" * 64,
        status="completed",
        provenance="fixture://diagnostic-model-run",
        generated_at=RUN_AT,
    )
    lines = {}
    for index in range(1, 11):
        game_id = 3100 + index
        home = f"Diagnostic Home {index}"
        away = f"Diagnostic Away {index}"
        conn.execute(
            "INSERT INTO games "
            "(game_id, season, week, home_team, away_team, start_date, "
            "neutral_site) VALUES (?, 2026, 1, ?, ?, ?, 0)",
            (game_id, home, away, KICKOFF_AT.isoformat()),
        )
        lines[game_id] = lock_contest_line(
            conn,
            contest_id=contest.id,
            game_id=game_id,
            raw_home_team=home,
            raw_away_team=away,
            normalized_home_team=home,
            normalized_away_team=away,
            home_spread=0,
            source="fixture-contest",
            source_line_id=f"diagnostic-line-{game_id}",
            provenance=f"fixture://diagnostic-line/{game_id}",
            payload_sha256=f"{index:x}" * 64,
            locked_at=LOCKED_AT,
        ).line
        prediction = record_model_prediction(
            conn,
            prediction_key=f"diagnostic-prediction-{game_id}",
            model_run_id=model_run.id,
            game_id=game_id,
            predicted_home_margin=1,
            uncertainty_points=1 if index <= 5 else 3,
            entry_locked_line_id=lines[game_id].id,
            provenance=f"fixture://diagnostic-prediction/{game_id}",
            generated_at=PREDICTION_AT,
        )
        if index <= 5:
            record_manual_adjustment(
                conn,
                adjustment_key=f"diagnostic-side-flip-{game_id}",
                model_prediction_id=prediction.id,
                category="injury",
                affected_side="home",
                margin_adjustment=-2,
                confidence_adjustment=0,
                reason="Fixture adjustment flips the final selection to away.",
                evidence="Fixture injury report.",
                source="fixture-injury-report",
                author="test-analyst",
                provenance=f"fixture://diagnostic-adjustment/{game_id}",
                recorded_at=ADJUSTMENT_AT,
            )

    card = generate_full_card(
        conn,
        card_key="diagnostic-card-v1",
        contest_id=contest.id,
        model_run_id=model_run.id,
        version=1,
        policy=SELECTION_POLICY,
        confidence_policy=RANKING_POLICY,
        adjustment_policy=ADJUSTMENT_POLICY,
        created_by="test",
        provenance="fixture://diagnostic-card",
        generated_at=CARD_AT,
    )
    requests = {}
    for index in range(1, 11):
        game_id = 3100 + index
        conn.execute(
            "UPDATE games SET home_points = 24, away_points = 17, "
            "completed = 1 WHERE game_id = ?",
            (game_id,),
        )
        closing_id = conn.execute(
            "INSERT INTO betting_lines "
            "(game_id, season, week, home_team, away_team, book, "
            "home_spread, line_type, source, fetched_at) "
            "VALUES (?, 2026, 1, ?, ?, 'fixturebook', 1, 'closing', "
            "'fixture-market', ?)",
            (
                game_id,
                f"Diagnostic Home {index}",
                f"Diagnostic Away {index}",
                CLOSING_AT.isoformat(),
            ),
        ).lastrowid
        requests[lines[game_id].id] = PostgameAuditRequest(closing_id)
    conn.commit()
    audit = audit_contest_card(
        conn,
        audit_run_key="diagnostic-audit-run-1",
        card_id=card.card.id,
        audit_policy=AUDIT_POLICY,
        requests_by_locked_line_id=requests,
        source="fixture-final-scores",
        provenance="fixture://diagnostic-audit-run",
        audited_at=AUDITED_AT,
    )
    return conn, audit


def _generate(conn, audit, *, key="weekly-diagnostics-run-1", at=DIAGNOSTIC_AT):
    return generate_weekly_diagnostics(
        conn,
        diagnostic_run_key=key,
        audit_run_id=audit.run.id,
        diagnostic_policy=DIAGNOSTIC_POLICY,
        source="fixture-weekly-diagnostics",
        provenance="fixture://weekly-diagnostics-run",
        generated_at=at,
    )


def test_weekly_diagnostics_cover_all_required_cuts_and_gate_policy_change(temp_db):
    conn, audit = _seed_completed_audit(temp_db)
    result = _generate(conn, audit)
    segments = {
        (segment.dimension_code, segment.category_code): segment
        for segment in result.segments
    }

    assert result.report.complete is True
    assert result.report.segment_count == 26
    assert (segments[("confidence", "5")].sample_count,
            segments[("confidence", "5")].ats_win_rate) == (5, 0.0)
    assert (segments[("confidence", "4")].sample_count,
            segments[("confidence", "4")].ats_win_rate) == (5, 100.0)
    assert (segments[("card_tier", "top_five")].sample_count,
            segments[("card_tier", "top_five")].ats_win_rate) == (5, 0.0)
    assert segments[("card_tier", "remaining")].ats_win_rate == 100.0
    assert segments[("model_output", "raw_model")].ats_win_rate == 100.0
    assert segments[("model_output", "final_adjusted")].ats_win_rate == 50.0
    assert segments[("clv_sign", "positive")].ats_win_rate == 0.0
    assert segments[("clv_sign", "negative")].ats_win_rate == 100.0
    assert segments[("favorite_status", "pickem")].sample_count == 10
    assert segments[("location_status", "home")].sample_count == 5
    assert segments[("location_status", "away")].sample_count == 5
    assert segments[("spread_bucket", "pickem")].sample_count == 10
    assert segments[("road_favorite", "road_favorite")].sample_count == 0

    lessons = {lesson.lesson_code: lesson for lesson in result.lessons}
    assert lessons["raw_vs_adjusted"].delta_percentage_points == -50.0
    assert lessons["clv_signal"].delta_percentage_points == -100.0
    assert all("caus" in lesson.narrative or "Descriptive" in lesson.narrative
               or "rule change" in lesson.narrative
               for lesson in result.lessons)

    recommendations = {
        item.confidence_level: item for item in result.recommendations
    }
    candidate = recommendations[5]
    assert candidate.recommendation_status == "candidate_pending_owner_approval"
    assert candidate.owner_approval_required is True
    assert (candidate.current_value, candidate.recommended_value) == (2.0, 1.5)
    assert candidate.observed_delta_percentage_points == -50.0
    assert candidate.proposed_confidence_policy_version == (
        "diagnostic-confidence-v1.candidate.weekly-diagnostics-run-1"
    )
    assert recommendations[4].recommendation_status == "hold_no_change"
    assert recommendations[3].recommendation_status == "hold_insufficient_evidence"
    assert recommendations[2].recommendation_status == "hold_insufficient_evidence"
    assert result.completion.candidate_recommendation_count == 1
    assert validate_weekly_diagnostics(conn, result.run.id) == result.report
    assert conn.execute("SELECT COUNT(*) FROM contest_ranking_policies").fetchone()[0] == 1
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert list(conn.execute("PRAGMA foreign_key_check")) == []
    conn.close()


def test_diagnostic_replay_is_idempotent_and_corrections_are_append_only(temp_db):
    conn, audit = _seed_completed_audit(temp_db)
    first = _generate(conn, audit)
    replay = _generate(conn, audit)
    second = _generate(
        conn,
        audit,
        key="weekly-diagnostics-run-2",
        at=DIAGNOSTIC_AT + timedelta(minutes=1),
    )

    assert replay == first
    assert (second.run.sequence, second.run.supersedes_run_id) == (2, first.run.id)
    assert conn.execute("SELECT COUNT(*) FROM weekly_diagnostic_runs").fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE weekly_diagnostic_segments SET win_count = 99 "
            "WHERE diagnostic_run_id = ?",
            (first.run.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
        conn.execute(
            "DELETE FROM policy_change_recommendations "
            "WHERE diagnostic_run_id = ?",
            (first.run.id,),
        )
    conn.close()


def test_database_rejects_forged_diagnostic_evidence(temp_db):
    conn, audit = _seed_completed_audit(temp_db)
    first = _generate(conn, audit)
    cursor = conn.execute(
        "INSERT INTO weekly_diagnostic_runs "
        "(diagnostic_run_key, audit_run_id, diagnostic_policy_id, sequence, "
        "supersedes_run_id, expected_segment_count, expected_lesson_count, "
        "expected_recommendation_count, generated_at, source, provenance) "
        "VALUES ('forged-run', ?, ?, 2, ?, 26, 4, 4, ?, "
        "'fixture-weekly-diagnostics', 'fixture://weekly-diagnostics-run')",
        (
            audit.run.id,
            first.run.diagnostic_policy_id,
            first.run.id,
            (DIAGNOSTIC_AT + timedelta(minutes=1)).isoformat(),
        ),
    )
    with pytest.raises(sqlite3.IntegrityError, match="does not match audit"):
        conn.execute(
            "INSERT INTO weekly_diagnostic_segments "
            "(diagnostic_run_id, dimension_code, category_code, sample_count, "
            "win_count, loss_count, push_count, ats_win_rate) "
            "VALUES (?, 'confidence', '5', 5, 5, 0, 0, 100)",
            (cursor.lastrowid,),
        )
    conn.rollback()
    conn.close()


def test_diagnostics_fail_atomically_for_future_or_conflicting_policy(temp_db):
    conn, audit = _seed_completed_audit(temp_db)
    future = WeeklyDiagnosticsPolicy(
        policy_version="future-weekly-diagnostics-v1",
        minimum_recommendation_sample=5,
        minimum_ats_delta_percentage_points=20,
        confidence_threshold_step_points=0.5,
        effective_at=DIAGNOSTIC_AT + timedelta(days=1),
        created_by="test",
        provenance="fixture://future-weekly-diagnostics-policy",
    )
    with pytest.raises(BusinessEntityError, match="not yet effective"):
        generate_weekly_diagnostics(
            conn,
            diagnostic_run_key="future-diagnostic-run",
            audit_run_id=audit.run.id,
            diagnostic_policy=future,
            source="fixture-weekly-diagnostics",
            provenance="fixture://weekly-diagnostics-run",
            generated_at=DIAGNOSTIC_AT,
        )
    assert conn.execute("SELECT COUNT(*) FROM weekly_diagnostic_runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM weekly_diagnostic_policies").fetchone()[0] == 0

    first = _generate(conn, audit)
    conflicting = WeeklyDiagnosticsPolicy(
        policy_version=DIAGNOSTIC_POLICY.policy_version,
        minimum_recommendation_sample=6,
        minimum_ats_delta_percentage_points=20,
        confidence_threshold_step_points=0.5,
        effective_at=POLICY_AT,
        created_by="test",
        provenance="fixture://weekly-diagnostics-policy",
    )
    with pytest.raises(BusinessEntityConflictError, match="different immutable"):
        generate_weekly_diagnostics(
            conn,
            diagnostic_run_key=first.run.diagnostic_run_key,
            audit_run_id=audit.run.id,
            diagnostic_policy=conflicting,
            source=first.run.source,
            provenance=first.run.provenance,
            generated_at=DIAGNOSTIC_AT,
        )
    assert conn.execute("SELECT COUNT(*) FROM weekly_diagnostic_runs").fetchone()[0] == 1
    conn.close()
