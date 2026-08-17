import sqlite3
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from business_entities import (
    BusinessEntityError,
    ConfidenceRankingPolicy,
    FullCardError,
    FullCardPolicy,
    ManualAdjustmentPolicy,
    add_contest_pick,
    assign_card_adjustment_policy,
    create_contest_card,
    generate_full_card,
    get_card_adjustment_policy,
    get_pick_adjustment_snapshot,
    list_manual_adjustments,
    list_pick_adjustment_items,
    record_manual_adjustment,
    record_model_prediction,
    record_model_run,
)
from contest_lines import create_contest, lock_contest_line


POLICY_AT = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
LOCKED_AT = datetime(2026, 8, 25, 14, tzinfo=timezone.utc)
RUN_AT = datetime(2026, 8, 25, 14, 30, tzinfo=timezone.utc)
PREDICTION_AT = datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
ADJUSTMENT_AT = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)
CARD_AT = datetime(2026, 8, 25, 16, tzinfo=timezone.utc)
AFTER_CARD = datetime(2026, 8, 25, 17, tzinfo=timezone.utc)
KICKOFF = "2026-08-29T23:00:00+00:00"

SELECTION_POLICY = FullCardPolicy(
    version="contextual-full-card-v1",
    market_books=("draftkings", "fanduel"),
)
RANKING_POLICY = ConfidenceRankingPolicy(
    policy_key="contextual-confidence-ranking-v1",
    confidence_policy_version="contextual-confidence-v1",
    ranking_policy_version="contextual-top-five-v1",
    confidence_5_max_uncertainty=2.0,
    confidence_4_max_uncertainty=4.0,
    confidence_3_max_uncertainty=6.0,
    confidence_2_max_uncertainty=8.0,
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://contextual-ranking-policy",
)
ADJUSTMENT_POLICY = ManualAdjustmentPolicy(
    policy_version="manual-adjustments-v1",
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://manual-adjustment-policy",
)


def _record_adjustment(
    conn,
    prediction,
    category,
    sequence,
    *,
    margin,
    confidence=0,
    recorded_at=ADJUSTMENT_AT,
):
    return record_manual_adjustment(
        conn,
        adjustment_key=f"context-{prediction.id}-{sequence}",
        model_prediction_id=prediction.id,
        category=category,
        affected_side="both" if category == "weather" else "home",
        margin_adjustment=margin,
        confidence_adjustment=confidence,
        reason=f"Recorded {category} context.",
        evidence=f"Fixture evidence for {category}.",
        source=f"fixture-{category}-report",
        author="test-analyst",
        provenance=f"fixture://context/{prediction.id}/{sequence}",
        recorded_at=recorded_at,
    )


def _seed(temp_db):
    conn = temp_db.get_connection()
    contest = create_contest(
        conn,
        contest_key="contextual-week-1",
        name="Contextual Week 1",
        season=2026,
        week=1,
        source="fixture-contest",
        provenance="fixture://contextual-contest",
        created_at=LOCKED_AT,
    )
    run = record_model_run(
        conn,
        run_key="contextual-run-1",
        model_name="fixture-model",
        model_version="model-v1",
        feature_schema_version="features-v1",
        configuration_version="config-v1",
        code_commit_sha="a" * 40,
        data_snapshot_sha256="b" * 64,
        status="completed",
        provenance="fixture://contextual-run",
        generated_at=RUN_AT,
    )
    predictions = {}
    uncertainties = (3.0, 1.0, 3.0, 5.0, 7.0, 9.0)
    for index, uncertainty in enumerate(uncertainties, start=1):
        game_id = 1100 + index
        home = f"Context Home {index}"
        away = f"Context Away {index}"
        conn.execute(
            "INSERT INTO games "
            "(game_id, season, week, home_team, away_team, start_date) "
            "VALUES (?, 2026, 1, ?, ?, ?)",
            (game_id, home, away, KICKOFF),
        )
        line = lock_contest_line(
            conn,
            contest_id=contest.id,
            game_id=game_id,
            raw_home_team=home,
            raw_away_team=away,
            normalized_home_team=home,
            normalized_away_team=away,
            home_spread=-3.0,
            source="fixture-contest",
            source_line_id=f"context-line-{game_id}",
            provenance=f"fixture://context-line/{game_id}",
            payload_sha256=f"{index:x}" * 64,
            locked_at=LOCKED_AT,
        ).line
        predictions[game_id] = record_model_prediction(
            conn,
            prediction_key=f"context-prediction-{game_id}",
            model_run_id=run.id,
            game_id=game_id,
            predicted_home_margin=1.0 if index == 1 else 5.0,
            uncertainty_points=uncertainty,
            entry_locked_line_id=line.id,
            provenance=f"fixture://context-prediction/{game_id}",
            generated_at=PREDICTION_AT,
        )

    included = [
        _record_adjustment(
            conn,
            predictions[1101],
            "injury",
            1,
            margin=3.0,
            confidence=10,
        )
    ]
    category_values = (
        ("quarterback", -0.5, -10),
        ("coaching", 0.1, 0),
        ("travel", -0.1, 0),
        ("weather", 0.2, 0),
        ("motivation", -0.2, 0),
        ("matchup", 0.3, 0),
    )
    included.extend(
        _record_adjustment(
            conn,
            predictions[1102],
            category,
            sequence,
            margin=margin,
            confidence=confidence,
        )
        for sequence, (category, margin, confidence) in enumerate(
            category_values, start=1
        )
    )
    future = _record_adjustment(
        conn,
        predictions[1101],
        "weather",
        2,
        margin=-20.0,
        confidence=-20,
        recorded_at=AFTER_CARD,
    )
    result = generate_full_card(
        conn,
        card_key="contextual-card-v1",
        contest_id=contest.id,
        model_run_id=run.id,
        version=1,
        policy=SELECTION_POLICY,
        confidence_policy=RANKING_POLICY,
        adjustment_policy=ADJUSTMENT_POLICY,
        created_by="test",
        provenance="fixture://contextual-card",
        generated_at=CARD_AT,
    )
    conn.commit()
    return conn, contest, run, predictions, tuple(included), future, result


def test_applies_sourced_context_without_rewriting_raw_model_or_using_future_data(
    temp_db,
):
    conn, _, _, predictions, included, future, result = _seed(temp_db)
    picks = {pick.model_prediction_id: pick for pick in result.picks}
    first_pick = picks[predictions[1101].id]
    second_pick = picks[predictions[1102].id]
    first_snapshot = get_pick_adjustment_snapshot(conn, first_pick.id)
    second_snapshot = get_pick_adjustment_snapshot(conn, second_pick.id)

    assert (first_pick.selected_side, first_pick.confidence) == ("home", 5)
    assert (first_snapshot.raw_model_margin, first_snapshot.margin_adjustment_total) == (
        1.0,
        3.0,
    )
    assert first_snapshot.adjusted_model_margin == 4.0
    assert (first_snapshot.raw_confidence, first_snapshot.adjusted_confidence) == (
        4,
        5,
    )
    first_items = list_pick_adjustment_items(conn, first_pick.id)
    assert len(first_items) == 1
    included_item = first_items[0]
    assert included_item.adjustment_id == included[0].id
    assert future.id not in {
        item.adjustment_id for item in list_pick_adjustment_items(conn, first_pick.id)
    }
    assert conn.execute(
        "SELECT predicted_home_margin FROM model_predictions WHERE id = ?",
        (predictions[1101].id,),
    ).fetchone()[0] == 1.0

    assert second_snapshot.adjusted_model_margin == pytest.approx(4.8)
    assert (second_snapshot.raw_confidence, second_snapshot.adjusted_confidence) == (
        5,
        1,
    )
    recorded = list_manual_adjustments(conn, predictions[1102].id)
    assert {adjustment.category for adjustment in recorded} == {
        "quarterback",
        "coaching",
        "travel",
        "weather",
        "motivation",
        "matchup",
    }
    assert all(
        adjustment.evidence
        and adjustment.source
        and adjustment.author == "test-analyst"
        for adjustment in recorded
    )
    assert tuple(
        item.adjustment_id
        for item in list_pick_adjustment_items(conn, second_pick.id)
    ) == tuple(adjustment.id for adjustment in included[1:])
    assert result.report.adjustment_policy_matches is True
    assert result.report.adjustment_ledger_matches is True
    assert result.report.contest_complete is True
    assert "raw_model_margin=1.0" in first_pick.provenance
    assert "adjusted_model_margin=4.0" in first_pick.provenance
    conn.close()


def test_policy_snapshots_and_adjustment_items_are_immutable(temp_db):
    conn, _, _, predictions, _, _, result = _seed(temp_db)
    pick = next(
        item
        for item in result.picks
        if item.model_prediction_id == predictions[1101].id
    )
    policy = get_card_adjustment_policy(conn, result.card.id)

    for statement, values in (
        (
            "UPDATE manual_adjustment_policies SET created_by = created_by "
            "WHERE id = ?",
            (policy.id,),
        ),
        (
            "UPDATE contest_pick_adjustment_snapshots "
            "SET raw_model_margin = raw_model_margin WHERE contest_pick_id = ?",
            (pick.id,),
        ),
        (
            "DELETE FROM contest_pick_adjustment_items WHERE contest_pick_id = ?",
            (pick.id,),
        ),
    ):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(statement, values)

    counts_before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "contest_cards",
            "contest_picks",
            "manual_adjustment_policies",
            "contest_pick_adjustment_snapshots",
        )
    }
    with pytest.raises(FullCardError, match="different manual adjustment policy"):
        generate_full_card(
            conn,
            card_key=result.card.card_key,
            contest_id=result.card.contest_id,
            model_run_id=result.card.model_run_id,
            version=result.card.version,
            policy=SELECTION_POLICY,
            confidence_policy=RANKING_POLICY,
            adjustment_policy=replace(
                ADJUSTMENT_POLICY,
                policy_version="manual-adjustments-v2",
            ),
            created_by=result.card.created_by,
            provenance=result.card.provenance,
            generated_at=CARD_AT,
        )
    assert counts_before == {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in counts_before
    }
    conn.close()


def test_database_rejects_a_snapshot_that_omits_eligible_adjustments(temp_db):
    conn, contest, run, predictions, _, _, result = _seed(temp_db)
    original_pick = next(
        pick
        for pick in result.picks
        if pick.model_prediction_id == predictions[1102].id
    )
    policy = get_card_adjustment_policy(conn, result.card.id)
    generated_at = datetime(2026, 8, 25, 16, 30, tzinfo=timezone.utc)
    card = create_contest_card(
        conn,
        card_key="contextual-card-incomplete-ledger",
        contest_id=contest.id,
        model_run_id=run.id,
        version=2,
        status="draft",
        policy_version=SELECTION_POLICY.version,
        locked_line_snapshot_sha256=result.card.locked_line_snapshot_sha256,
        generated_at=generated_at,
        created_by="test",
        provenance="fixture://incomplete-ledger-card",
    )
    assign_card_adjustment_policy(
        conn,
        card_id=card.id,
        adjustment_policy_id=policy.id,
        assigned_at=generated_at,
        provenance="fixture://incomplete-ledger-card",
    )
    pick = add_contest_pick(
        conn,
        pick_key="contextual-card-incomplete-ledger:pick",
        card_id=card.id,
        locked_line_id=original_pick.locked_line_id,
        model_prediction_id=predictions[1102].id,
        selected_side="home",
        confidence=5,
        rank=1,
        is_top_five=True,
        fallback_code=None,
        generated_at=generated_at,
        provenance="fixture://incomplete-ledger-pick",
    )

    with pytest.raises(sqlite3.IntegrityError, match="does not match frozen inputs"):
        conn.execute(
            "INSERT INTO contest_pick_adjustment_snapshots "
            "(contest_pick_id, adjustment_policy_id, model_prediction_id, "
            "raw_model_margin, margin_adjustment_total, adjusted_model_margin, "
            "raw_confidence, confidence_adjustment_total, adjusted_confidence, "
            "adjustment_count, adjustment_history_sha256, generated_at, provenance) "
            "VALUES (?, ?, ?, 5, 0, 5, 5, 0, 5, 0, ?, ?, ?)",
            (
                pick.id,
                policy.id,
                predictions[1102].id,
                "0" * 64,
                generated_at.isoformat(),
                "fixture://fabricated-empty-ledger",
            ),
        )
    assert conn.execute(
        "SELECT COUNT(*) FROM contest_pick_adjustment_snapshots "
        "WHERE contest_pick_id = ?",
        (pick.id,),
    ).fetchone()[0] == 0
    conn.close()


def test_future_effective_policy_rolls_back_card_and_policy_registration(temp_db):
    conn, contest, run, _, _, _, _ = _seed(temp_db)
    counts_before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "contest_cards",
            "contest_picks",
            "manual_adjustment_policies",
            "card_adjustment_policy_assignments",
        )
    }

    with pytest.raises(
        BusinessEntityError,
        match="adjustment policy must be effective at generation",
    ):
        generate_full_card(
            conn,
            card_key="contextual-card-v2",
            contest_id=contest.id,
            model_run_id=run.id,
            version=2,
            policy=SELECTION_POLICY,
            confidence_policy=RANKING_POLICY,
            adjustment_policy=replace(
                ADJUSTMENT_POLICY,
                policy_version="future-manual-adjustments-v1",
                effective_at=AFTER_CARD,
            ),
            created_by="test",
            provenance="fixture://contextual-card/v2",
            generated_at=CARD_AT,
        )

    assert counts_before == {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in counts_before
    }
    conn.close()


@pytest.mark.parametrize("missing_field", ("evidence", "source", "author"))
def test_adjustments_require_attribution_and_a_numeric_effect(
    temp_db, missing_field
):
    conn, _, _, predictions, _, _, _ = _seed(temp_db)
    values = {
        "reason": "Recorded context.",
        "evidence": "Fixture evidence.",
        "source": "fixture-report",
        "author": "test-analyst",
    }
    values[missing_field] = " "
    with pytest.raises(BusinessEntityError, match=missing_field):
        record_manual_adjustment(
            conn,
            adjustment_key=f"missing-{missing_field}",
            model_prediction_id=predictions[1103].id,
            category="injury",
            affected_side="home",
            margin_adjustment=1,
            confidence_adjustment=0,
            provenance="fixture://invalid-attribution",
            recorded_at=AFTER_CARD,
            **values,
        )
    with pytest.raises(BusinessEntityError, match="must change"):
        record_manual_adjustment(
            conn,
            adjustment_key=f"zero-{missing_field}",
            model_prediction_id=predictions[1103].id,
            category="injury",
            affected_side="home",
            margin_adjustment=0,
            confidence_adjustment=0,
            provenance="fixture://zero-adjustment",
            recorded_at=AFTER_CARD,
            reason="Recorded context.",
            evidence="Fixture evidence.",
            source="fixture-report",
            author="test-analyst",
        )
    conn.close()
