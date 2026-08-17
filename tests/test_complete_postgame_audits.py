import sqlite3
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from business_entities import (
    BusinessEntityConflictError,
    BusinessEntityError,
    ConfidenceRankingPolicy,
    FullCardPolicy,
    ManualAdjustmentPolicy,
    PostgameAuditPolicy,
    PostgameAuditRequest,
    add_contest_pick,
    audit_contest_card,
    create_contest_card,
    generate_full_card,
    list_pick_audits,
    record_manual_adjustment,
    record_model_prediction,
    record_model_run,
    register_postgame_audit_policy,
    validate_postgame_audit_run,
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

SELECTION_POLICY = FullCardPolicy(
    version="postgame-card-v1",
    market_books=("draftkings", "fanduel"),
    model_tie_side="away",
    pickem_tiebreak_side="home",
)
RANKING_POLICY = ConfidenceRankingPolicy(
    policy_key="postgame-ranking-v1",
    confidence_policy_version="postgame-confidence-v1",
    ranking_policy_version="postgame-top-five-v1",
    confidence_5_max_uncertainty=2,
    confidence_4_max_uncertainty=4,
    confidence_3_max_uncertainty=6,
    confidence_2_max_uncertainty=8,
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://postgame-ranking-policy",
)
ADJUSTMENT_POLICY = ManualAdjustmentPolicy(
    policy_version="postgame-adjustments-v1",
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://postgame-adjustment-policy",
)
AUDIT_POLICY = PostgameAuditPolicy(
    policy_version="postgame-audit-v1",
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://postgame-audit-policy",
)


def _seed(temp_db):
    conn = temp_db.get_connection()
    contest = create_contest(
        conn,
        contest_key="postgame-week-1",
        name="Postgame Week 1",
        season=2026,
        week=1,
        source="fixture-contest",
        provenance="fixture://postgame-contest",
        created_at=LOCKED_AT,
    )
    run = record_model_run(
        conn,
        run_key="postgame-model-run",
        model_name="fixture-model",
        model_version="model-v1",
        feature_schema_version="features-v1",
        configuration_version="config-v1",
        code_commit_sha="a" * 40,
        data_snapshot_sha256="b" * 64,
        status="completed",
        provenance="fixture://postgame-model-run",
        generated_at=RUN_AT,
    )
    spreads = (-3.5, -3.5, -3.0, -7.0, 3.0, 0.0)
    projections = (3.0, 5.0, 5.0, 5.0, -5.0)
    uncertainties = (3.0, 1.0, 5.0, 7.0, 9.0)
    lines = {}
    predictions = {}
    for index, spread in enumerate(spreads, 1):
        game_id = 2100 + index
        home, away = f"Audit Home {index}", f"Audit Away {index}"
        conn.execute(
            "INSERT INTO games "
            "(game_id, season, week, home_team, away_team, start_date, neutral_site) "
            "VALUES (?, 2026, 1, ?, ?, ?, ?)",
            (game_id, home, away, KICKOFF_AT.isoformat(), int(index == 5)),
        )
        lines[game_id] = lock_contest_line(
            conn,
            contest_id=contest.id,
            game_id=game_id,
            raw_home_team=home,
            raw_away_team=away,
            normalized_home_team=home,
            normalized_away_team=away,
            home_spread=spread,
            source="fixture-contest",
            source_line_id=f"postgame-line-{game_id}",
            provenance=f"fixture://postgame-line/{game_id}",
            payload_sha256=f"{index:x}" * 64,
            locked_at=LOCKED_AT,
        ).line
        if index <= 5:
            predictions[game_id] = record_model_prediction(
                conn,
                prediction_key=f"postgame-prediction-{game_id}",
                model_run_id=run.id,
                game_id=game_id,
                predicted_home_margin=projections[index - 1],
                uncertainty_points=uncertainties[index - 1],
                entry_locked_line_id=lines[game_id].id,
                provenance=f"fixture://postgame-prediction/{game_id}",
                generated_at=PREDICTION_AT,
            )
    record_manual_adjustment(
        conn,
        adjustment_key="postgame-side-flip-2101",
        model_prediction_id=predictions[2101].id,
        category="injury",
        affected_side="home",
        margin_adjustment=2,
        confidence_adjustment=0,
        reason="Fixture adjustment flips the selected side.",
        evidence="Fixture injury report.",
        source="fixture-injury-report",
        author="test-analyst",
        provenance="fixture://postgame-adjustment/2101",
        recorded_at=ADJUSTMENT_AT,
    )
    for sequence, margin in enumerate((1.0, -1.0), 1):
        record_manual_adjustment(
            conn,
            adjustment_key=f"postgame-net-zero-2102-{sequence}",
            model_prediction_id=predictions[2102].id,
            category="matchup",
            affected_side="home",
            margin_adjustment=margin,
            confidence_adjustment=0,
            reason="Fixture adjustments cancel in the frozen snapshot.",
            evidence=f"Fixture matchup report {sequence}.",
            source="fixture-matchup-report",
            author="test-analyst",
            provenance=f"fixture://postgame-adjustment/2102/{sequence}",
            recorded_at=ADJUSTMENT_AT,
        )
    card_result = generate_full_card(
        conn,
        card_key="postgame-card-v1",
        contest_id=contest.id,
        model_run_id=run.id,
        version=1,
        policy=SELECTION_POLICY,
        confidence_policy=RANKING_POLICY,
        adjustment_policy=ADJUSTMENT_POLICY,
        created_by="test",
        provenance="fixture://postgame-card",
        generated_at=CARD_AT,
    )
    final_scores = {
        2101: (24, 21),
        2102: (24, 20),
        2103: (23, 20),
        2104: (28, 14),
        2105: (17, 24),
        2106: (20, 21),
    }
    closing_spreads = {
        2101: -2.5,
        2102: -4.0,
        2103: -2.5,
        2104: -6.5,
        2105: 2.5,
        2106: 1.0,
    }
    closing_ids = {}
    for game_id, (home_points, away_points) in final_scores.items():
        conn.execute(
            "UPDATE games SET home_points = ?, away_points = ?, completed = 1 "
            "WHERE game_id = ?",
            (home_points, away_points, game_id),
        )
        closing_ids[game_id] = conn.execute(
            "INSERT INTO betting_lines "
            "(game_id, season, week, home_team, away_team, book, home_spread, "
            "line_type, source, fetched_at) VALUES (?, 2026, 1, ?, ?, "
            "'fixturebook', ?, 'closing', 'fixture-market', ?)",
            (
                game_id,
                f"Audit Home {game_id - 2100}",
                f"Audit Away {game_id - 2100}",
                closing_spreads[game_id],
                CLOSING_AT.isoformat(),
            ),
        ).lastrowid
    requests = {
        lines[game_id].id: PostgameAuditRequest(closing_ids[game_id])
        for game_id in lines
    }
    conn.commit()
    return conn, card_result, lines, closing_ids, requests


def _audit(conn, card_result, requests, *, key="postgame-audit-run-1", at=AUDITED_AT):
    return audit_contest_card(
        conn,
        audit_run_key=key,
        card_id=card_result.card.id,
        audit_policy=AUDIT_POLICY,
        requests_by_locked_line_id=requests,
        source="fixture-final-scores",
        provenance="fixture://postgame-audit-run",
        audited_at=at,
    )


def test_complete_audit_records_every_required_dimension_without_backdoor_inference(temp_db):
    conn, card_result, lines, _, requests = _seed(temp_db)
    result = _audit(conn, card_result, requests)
    by_game = {detail.game_id: detail for detail in result.details}

    assert result.report.complete is True
    assert (result.report.expected_pick_count, result.report.audit_count) == (6, 6)
    assert (
        result.report.win_count,
        result.report.loss_count,
        result.report.push_count,
    ) == (2, 3, 1)
    assert all(detail.backdoor_outcome == "not_evaluated" for detail in result.details)
    assert all(detail.scoring_sequence_evidence is None for detail in result.details)
    assert all(1 <= detail.confidence <= 5 for detail in result.details)
    assert sum(detail.is_top_five for detail in result.details) == 5

    first = by_game[2101]
    assert (first.ats_result, first.hook_outcome, first.landed_key_number) == (
        "loss",
        "lost_by_hook",
        3.0,
    )
    assert (first.raw_selected_side, first.raw_ats_result) == ("away", "win")
    assert first.manual_adjustment_effect == "side_flip_harmed"
    assert first.raw_model_margin == 3.0
    assert first.adjusted_model_margin == 5.0

    assert by_game[2102].hook_outcome == "won_by_hook"
    assert by_game[2102].manual_adjustment_effect == "net_zero"
    assert by_game[2103].key_number_outcome == "key_number_push"
    assert by_game[2104].spread_bucket_code == "7_to_9_5"
    assert (by_game[2105].favorite_status, by_game[2105].location_status) == (
        "favorite",
        "neutral",
    )
    assert by_game[2106].manual_adjustment_effect == "no_adjustment"
    assert by_game[2106].raw_model_margin is None

    crossings = {(item.audit_id, item.key_number, item.direction) for item in result.crossings}
    assert (first.audit_id, 3.0, "adverse") in crossings
    failure_codes = {}
    for failure in result.failures:
        failure_codes.setdefault(failure.audit_id, set()).add(failure.failure_code)
    assert {
        "model_backed_loss",
        "hook_loss",
        "key_number_loss",
        "manual_adjustment_harmed",
    } <= failure_codes[first.audit_id]
    fallback_detail = by_game[2106]
    assert "fallback_loss" in failure_codes[fallback_detail.audit_id]
    assert validate_postgame_audit_run(conn, result.run.id) == result.report
    assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert list(conn.execute("PRAGMA foreign_key_check")) == []
    conn.close()


def test_audit_is_atomic_and_rejects_missing_or_lookahead_closing_data(temp_db):
    conn, card_result, lines, _, requests = _seed(temp_db)
    incomplete = dict(requests)
    incomplete.pop(lines[2106].id)
    with pytest.raises(BusinessEntityError, match="cover every locked line"):
        _audit(conn, card_result, incomplete)
    assert conn.execute("SELECT COUNT(*) FROM card_postgame_audit_runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM pick_audits").fetchone()[0] == 0

    post_kickoff_id = conn.execute(
        "INSERT INTO betting_lines "
        "(game_id, season, week, home_team, away_team, book, home_spread, "
        "line_type, source, fetched_at) VALUES (2101, 2026, 1, 'Audit Home 1', "
        "'Audit Away 1', 'fixturebook', -2, 'closing', 'fixture-market', "
        "'2026-08-29T18:00:00+00:00')"
    ).lastrowid
    invalid = dict(requests)
    invalid[lines[2101].id] = PostgameAuditRequest(post_kickoff_id)
    with pytest.raises(BusinessEntityError, match="pre-kickoff closing line"):
        _audit(conn, card_result, invalid)
    assert conn.execute("SELECT COUNT(*) FROM card_postgame_audit_runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM pick_audits").fetchone()[0] == 0
    conn.close()


def test_backdoor_classification_requires_scoring_sequence_evidence(temp_db):
    conn, card_result, lines, _, requests = _seed(temp_db)
    invalid = dict(requests)
    invalid[lines[2102].id] = replace(
        invalid[lines[2102].id], backdoor_outcome="confirmed_backdoor_cover"
    )
    with pytest.raises(BusinessEntityError, match="scoring-sequence evidence"):
        _audit(conn, card_result, invalid)

    confirmed = dict(requests)
    confirmed[lines[2102].id] = PostgameAuditRequest(
        confirmed[lines[2102].id].closing_market_line_id,
        backdoor_outcome="confirmed_backdoor_cover",
        scoring_sequence_evidence=(
            "Fixture scoring sequence shows the cover changed on the final "
            "possession."
        ),
    )
    result = _audit(conn, card_result, confirmed)
    detail = next(item for item in result.details if item.game_id == 2102)
    assert detail.backdoor_outcome == "confirmed_backdoor_cover"
    assert detail.scoring_sequence_evidence.startswith("Fixture scoring sequence")
    conn.close()


def test_replay_is_idempotent_and_corrections_append_without_overwrite(temp_db):
    conn, card_result, _, _, requests = _seed(temp_db)
    first = _audit(conn, card_result, requests)
    assert _audit(conn, card_result, requests) == first

    correction = _audit(
        conn,
        card_result,
        requests,
        key="postgame-audit-run-2",
        at=datetime(2026, 8, 31, 12, tzinfo=timezone.utc),
    )
    assert (correction.run.sequence, correction.run.supersedes_run_id) == (2, first.run.id)
    for detail in first.details:
        history = list_pick_audits(conn, detail.contest_pick_id)
        assert [item.sequence for item in history] == [1, 2]
        assert history[1].supersedes_audit_id == history[0].id

    with pytest.raises(BusinessEntityConflictError, match="different immutable requests"):
        changed = dict(requests)
        first_line_id = next(iter(changed))
        changed[first_line_id] = replace(
            changed[first_line_id],
            backdoor_outcome="confirmed_not_backdoor",
            scoring_sequence_evidence="Fixture sequence review.",
        )
        _audit(conn, card_result, changed)

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE pick_audit_details SET clv_points = clv_points "
            "WHERE audit_run_id = ?",
            (first.run.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "DELETE FROM card_postgame_audit_completions WHERE audit_run_id = ?",
            (first.run.id,),
        )
    conn.close()


def test_future_policy_and_incomplete_game_fail_without_partial_audit(temp_db):
    conn, card_result, _, _, requests = _seed(temp_db)
    with pytest.raises(BusinessEntityError, match="not yet effective"):
        audit_contest_card(
            conn,
            audit_run_key="future-policy-audit",
            card_id=card_result.card.id,
            audit_policy=replace(
                AUDIT_POLICY,
                policy_version="postgame-audit-future",
                effective_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
            ),
            requests_by_locked_line_id=requests,
            source="fixture-final-scores",
            provenance="fixture://postgame-audit-run",
            audited_at=AUDITED_AT,
        )
    assert conn.execute("SELECT COUNT(*) FROM postgame_audit_policies").fetchone()[0] == 0

    conn.execute("UPDATE games SET completed = 0 WHERE game_id = 2104")
    with pytest.raises(BusinessEntityError, match="not complete"):
        _audit(conn, card_result, requests)
    assert conn.execute("SELECT COUNT(*) FROM card_postgame_audit_runs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM pick_audits").fetchone()[0] == 0
    conn.close()


def test_partial_card_cannot_be_sealed_as_a_complete_audit(temp_db):
    conn, card_result, lines, _, requests = _seed(temp_db)
    original = next(pick for pick in card_result.picks if pick.locked_line_id == lines[2101].id)
    partial = create_contest_card(
        conn,
        card_key="postgame-partial-card-v2",
        contest_id=card_result.card.contest_id,
        model_run_id=card_result.card.model_run_id,
        version=2,
        status="draft",
        policy_version=card_result.card.policy_version,
        locked_line_snapshot_sha256=card_result.card.locked_line_snapshot_sha256,
        created_by="test",
        provenance="fixture://postgame-partial-card",
        generated_at=CARD_AT,
    )
    add_contest_pick(
        conn,
        pick_key="postgame-partial-pick-2101",
        card_id=partial.id,
        locked_line_id=original.locked_line_id,
        model_prediction_id=original.model_prediction_id,
        selected_side=original.selected_side,
        confidence=original.confidence,
        rank=1,
        is_top_five=True,
        provenance="fixture://postgame-partial-pick",
        generated_at=CARD_AT,
    )

    with pytest.raises(BusinessEntityError, match="complete card"):
        audit_contest_card(
            conn,
            audit_run_key="postgame-partial-audit",
            card_id=partial.id,
            audit_policy=AUDIT_POLICY,
            requests_by_locked_line_id={
                original.locked_line_id: requests[original.locked_line_id]
            },
            source="fixture-final-scores",
            provenance="fixture://postgame-partial-audit",
            audited_at=AUDITED_AT,
        )
    assert conn.execute("SELECT COUNT(*) FROM card_postgame_audit_runs").fetchone()[0] == 0
    conn.close()


def test_database_rejects_fabricated_completion_and_policy_extension(temp_db):
    conn, card_result, _, _, _ = _seed(temp_db)
    policy = register_postgame_audit_policy(conn, AUDIT_POLICY)
    run_id = conn.execute(
        "INSERT INTO card_postgame_audit_runs "
        "(audit_run_key, card_id, audit_policy_id, sequence, "
        "supersedes_run_id, expected_pick_count, audited_at, source, provenance) "
        "VALUES ('direct-incomplete-run', ?, ?, 1, NULL, 6, ?, "
        "'fixture-final-scores', 'fixture://direct-incomplete-run')",
        (card_result.card.id, policy.id, AUDITED_AT.isoformat()),
    ).lastrowid

    with pytest.raises(sqlite3.IntegrityError, match="full valid coverage"):
        conn.execute(
            "INSERT INTO card_postgame_audit_completions "
            "(audit_run_id, audit_count, win_count, loss_count, push_count, "
            "ledger_sha256, completed_at, provenance) "
            "VALUES (?, 6, 6, 0, 0, ?, ?, 'fixture://fabricated-completion')",
            (run_id, "f" * 64, AUDITED_AT.isoformat()),
        )
    with pytest.raises(sqlite3.IntegrityError, match="frozen once used"):
        conn.execute(
            "INSERT INTO postgame_audit_key_numbers "
            "(audit_policy_id, priority, key_number) VALUES (?, 5, 21)",
            (policy.id,),
        )
    assert conn.execute(
        "SELECT COUNT(*) FROM card_postgame_audit_completions"
    ).fetchone()[0] == 0
    conn.close()
