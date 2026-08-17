import sqlite3
from datetime import datetime, timezone

import pytest

from business_entities import (
    BusinessEntityConflictError,
    ConfidenceRankingPolicy,
    DailyRefreshError,
    DailyRefreshPolicy,
    FullCardPolicy,
    ManualAdjustmentPolicy,
    generate_full_card,
    get_card_run_manifest,
    get_pick_adjustment_snapshot,
    record_card_revision,
    record_manual_adjustment,
    record_model_prediction,
    record_model_run,
    refresh_full_card,
)
from contest_lines import correct_locked_line, create_contest, lock_contest_line


POLICY_AT = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
LOCKED_AT = datetime(2026, 8, 25, 14, tzinfo=timezone.utc)
RUN_AT = datetime(2026, 8, 25, 14, 30, tzinfo=timezone.utc)
PREDICTION_AT = datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
CARD_AT = datetime(2026, 8, 25, 16, tzinfo=timezone.utc)
REFRESH_RUN_AT = datetime(2026, 8, 26, 14, tzinfo=timezone.utc)
REFRESH_PREDICTION_AT = datetime(2026, 8, 26, 14, 30, tzinfo=timezone.utc)
REFRESH_AT = datetime(2026, 8, 26, 15, tzinfo=timezone.utc)
SUNDAY_AT = datetime(2026, 8, 30, 15, tzinfo=timezone.utc)
KICKOFF = "2026-08-29T23:00:00+00:00"

SELECTION_POLICY = FullCardPolicy(
    version="refresh-full-card-v1",
    market_books=("draftkings", "fanduel"),
)
RANKING_POLICY = ConfidenceRankingPolicy(
    policy_key="refresh-confidence-ranking-v1",
    confidence_policy_version="refresh-confidence-v1",
    ranking_policy_version="refresh-top-five-v1",
    confidence_5_max_uncertainty=2.0,
    confidence_4_max_uncertainty=4.0,
    confidence_3_max_uncertainty=6.0,
    confidence_2_max_uncertainty=8.0,
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://refresh-ranking-policy",
)
REFRESH_POLICY = DailyRefreshPolicy(
    policy_version="daily-refresh-v1",
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://daily-refresh-policy",
)
ADJUSTMENT_POLICY = ManualAdjustmentPolicy(
    policy_version="manual-adjustments-v1",
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://manual-adjustment-policy",
)


def _record_run(conn, *, suffix, generated_at, model_version="model-v1"):
    return record_model_run(
        conn,
        run_key=f"refresh-run-{suffix}",
        model_name="fixture-model",
        model_version=model_version,
        feature_schema_version="features-v1",
        configuration_version="config-v1",
        code_commit_sha="a" * 40,
        data_snapshot_sha256=("b" if suffix == "1" else "c") * 64,
        status="completed",
        provenance=f"fixture://refresh-run/{suffix}",
        generated_at=generated_at,
    )


def _record_predictions(conn, run, *, suffix, generated_at, values):
    predictions = {}
    for index, (margin, uncertainty) in enumerate(values, start=1):
        game_id = 900 + index
        predictions[game_id] = record_model_prediction(
            conn,
            prediction_key=f"refresh-prediction-{game_id}-{suffix}",
            model_run_id=run.id,
            game_id=game_id,
            predicted_home_margin=margin,
            uncertainty_points=uncertainty,
            provenance=f"fixture://refresh-prediction/{game_id}/{suffix}",
            generated_at=generated_at,
        )
    return predictions


def _seed(temp_db):
    conn = temp_db.get_connection()
    contest = create_contest(
        conn,
        contest_key="refresh-week-1",
        name="Refresh Week 1",
        season=2026,
        week=1,
        source="fixture-contest",
        provenance="fixture://refresh-contest",
        created_at=LOCKED_AT,
    )
    lines = {}
    for index in range(1, 7):
        game_id = 900 + index
        home = f"Refresh Home {index}"
        away = f"Refresh Away {index}"
        conn.execute(
            "INSERT INTO games "
            "(game_id, season, week, home_team, away_team, start_date) "
            "VALUES (?, 2026, 1, ?, ?, ?)",
            (game_id, home, away, KICKOFF),
        )
        lines[game_id] = lock_contest_line(
            conn,
            contest_id=contest.id,
            game_id=game_id,
            raw_home_team=home,
            raw_away_team=away,
            normalized_home_team=home,
            normalized_away_team=away,
            home_spread=-3,
            source="fixture-contest",
            source_line_id=f"refresh-line-{game_id}",
            provenance=f"fixture://refresh-line/{game_id}",
            payload_sha256=f"{index}" * 64,
            locked_at=LOCKED_AT,
        ).line
    run = _record_run(conn, suffix="1", generated_at=RUN_AT)
    predictions = _record_predictions(
        conn,
        run,
        suffix="1",
        generated_at=PREDICTION_AT,
        values=((7, 1), (7, 3), (7, 5), (7, 7), (7, 9), (7, 10)),
    )
    card = generate_full_card(
        conn,
        card_key="refresh-card-v1",
        contest_id=contest.id,
        model_run_id=run.id,
        version=1,
        policy=SELECTION_POLICY,
        confidence_policy=RANKING_POLICY,
        adjustment_policy=ADJUSTMENT_POLICY,
        created_by="test",
        provenance="fixture://refresh-card/v1",
        generated_at=CARD_AT,
    )
    conn.commit()
    return {
        "conn": conn,
        "contest": contest,
        "lines": lines,
        "run": run,
        "predictions": predictions,
        "card": card,
    }


def _refreshed_run(seeded, *, model_version="model-v1"):
    conn = seeded["conn"]
    run = _record_run(
        conn,
        suffix="2" if model_version == "model-v1" else "changed",
        generated_at=REFRESH_RUN_AT,
        model_version=model_version,
    )
    _record_predictions(
        conn,
        run,
        suffix="2" if model_version == "model-v1" else "changed",
        generated_at=REFRESH_PREDICTION_AT,
        values=((1, 10), (7, 3), (7, 5), (7, 7), (7, 9), (7, 0.5)),
    )
    conn.commit()
    return run


def _refresh(seeded, *, model_run_id, change_type="data_refresh"):
    return refresh_full_card(
        seeded["conn"],
        prior_card_id=seeded["card"].card.id,
        card_key="refresh-card-v2",
        model_run_id=model_run_id,
        change_type=change_type,
        reason=f"Fixture {change_type.replace('_', ' ')}.",
        author="test",
        provenance=f"fixture://refresh-card/v2/{change_type}",
        refresh_policy=REFRESH_POLICY,
        generated_at=REFRESH_AT,
    )


def test_data_refresh_records_each_pick_change_without_changing_lock(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    run = _refreshed_run(seeded)
    original_spreads = tuple(
        conn.execute(
            "SELECT home_spread FROM contest_locked_lines ORDER BY id"
        )
    )

    result = _refresh(seeded, model_run_id=run.id)
    replay = _refresh(seeded, model_run_id=run.id)
    by_line = {change.locked_line_id: change for change in result.changes}
    first = by_line[seeded["lines"][901].id]
    sixth = by_line[seeded["lines"][906].id]

    assert replay == result
    assert result.revised_card.card.version == 2
    assert result.revision.change_type == "data_refresh"
    assert result.revision.revised_at == REFRESH_AT.isoformat()
    assert result.refresh.operating_date == "2026-08-26"
    assert result.refresh.operating_weekday == 3
    assert result.refresh.timezone_name == "UTC"
    assert len(result.changes) == 6
    assert (first.prior_selected_side, first.revised_selected_side) == (
        "home",
        "away",
    )
    assert (first.prior_confidence, first.revised_confidence) == (5, 1)
    assert (first.prior_is_top_five, first.revised_is_top_five) == (True, False)
    assert first.side_changed is True
    assert first.confidence_changed is True
    assert first.top_five_changed is True
    assert (sixth.prior_confidence, sixth.revised_confidence) == (1, 5)
    assert (sixth.prior_is_top_five, sixth.revised_is_top_five) == (False, True)
    assert sixth.top_five_changed is True
    assert all(change.model_prediction_changed for change in result.changes)
    assert seeded["card"].card.locked_line_snapshot_sha256 == (
        result.revised_card.card.locked_line_snapshot_sha256
    )
    assert tuple(
        conn.execute(
            "SELECT home_spread FROM contest_locked_lines ORDER BY id"
        )
    ) == original_spreads
    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM card_revisions").fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM card_revision_pick_changes"
    ).fetchone()[0] == 6
    conn.close()


def test_refresh_rejects_disallowed_day_before_persisting_any_history(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]

    with pytest.raises(DailyRefreshError, match="Tuesday through Saturday UTC"):
        refresh_full_card(
            conn,
            prior_card_id=seeded["card"].card.id,
            card_key="refresh-card-v2",
            model_run_id=seeded["run"].id,
            change_type="data_refresh",
            reason="Disallowed Sunday fixture.",
            author="test",
            provenance="fixture://disallowed-refresh",
            refresh_policy=REFRESH_POLICY,
            generated_at=SUNDAY_AT,
        )

    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM card_revisions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM card_refresh_policies").fetchone()[0] == 0
    conn.close()


@pytest.mark.parametrize(
    "refresh_time, expected_weekday",
    (
        (datetime(2026, 8, 25, 17, tzinfo=timezone.utc), 2),
        (datetime(2026, 8, 26, 15, tzinfo=timezone.utc), 3),
        (datetime(2026, 8, 27, 15, tzinfo=timezone.utc), 4),
        (datetime(2026, 8, 28, 15, tzinfo=timezone.utc), 5),
        (datetime(2026, 8, 29, 22, tzinfo=timezone.utc), 6),
    ),
)
def test_operating_window_accepts_tuesday_through_saturday(
    temp_db, refresh_time, expected_weekday
):
    seeded = _seed(temp_db)
    conn = seeded["conn"]

    result = refresh_full_card(
        conn,
        prior_card_id=seeded["card"].card.id,
        card_key="refresh-card-v2",
        model_run_id=seeded["run"].id,
        change_type="data_refresh",
        reason="Allowed operating day fixture.",
        author="test",
        provenance="fixture://allowed-refresh",
        refresh_policy=REFRESH_POLICY,
        generated_at=refresh_time,
    )

    assert result.refresh.operating_weekday == expected_weekday
    assert result.refresh.operating_date == refresh_time.date().isoformat()
    conn.close()


def test_data_refresh_rejects_model_logic_change_and_rolls_back_card(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    changed_run = _refreshed_run(seeded, model_version="model-v2")

    with pytest.raises(DailyRefreshError, match="model logic or configuration"):
        _refresh(seeded, model_run_id=changed_run.id)

    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM contest_picks").fetchone()[0] == 6
    assert conn.execute("SELECT COUNT(*) FROM card_revisions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM card_refresh_policies").fetchone()[0] == 0
    conn.close()


def test_contextual_refresh_requires_new_adjustment_and_preserves_raw_model(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    prediction = seeded["predictions"][901]
    raw_margin = prediction.predicted_home_margin
    record_manual_adjustment(
        conn,
        adjustment_key="refresh-adjustment-901",
        model_prediction_id=prediction.id,
        contest_pick_id=seeded["card"].picks[0].id,
        category="quarterback",
        affected_side="home",
        margin_adjustment=-2,
        confidence_adjustment=-1,
        reason="Fixture quarterback update.",
        evidence="Fixture availability report.",
        source="fixture-report",
        author="test",
        provenance="fixture://refresh-adjustment/901",
        recorded_at=REFRESH_RUN_AT,
    )
    conn.commit()

    result = _refresh(
        seeded,
        model_run_id=seeded["run"].id,
        change_type="contextual_adjustment",
    )
    prior_manifest = get_card_run_manifest(conn, seeded["card"].card.id)
    revised_manifest = get_card_run_manifest(conn, result.revised_card.card.id)
    revised_pick = next(
        pick
        for pick in result.revised_card.picks
        if pick.model_prediction_id == prediction.id
    )
    snapshot = get_pick_adjustment_snapshot(conn, revised_pick.id)
    first_change = next(
        item
        for item in result.changes
        if item.locked_line_id == seeded["lines"][901].id
    )

    assert revised_manifest.model_run_id == prior_manifest.model_run_id
    assert revised_manifest.adjustment_count == prior_manifest.adjustment_count + 1
    assert revised_manifest.adjustment_history_sha256 != (
        prior_manifest.adjustment_history_sha256
    )
    assert all(not change.model_prediction_changed for change in result.changes)
    assert (first_change.prior_confidence, first_change.revised_confidence) == (5, 4)
    assert first_change.confidence_changed is True
    assert (snapshot.raw_model_margin, snapshot.adjusted_model_margin) == (7.0, 5.0)
    assert (snapshot.raw_confidence, snapshot.adjusted_confidence) == (5, 4)
    assert conn.execute(
        "SELECT predicted_home_margin FROM model_predictions WHERE id = ?",
        (prediction.id,),
    ).fetchone()[0] == raw_margin
    conn.close()


def test_data_refresh_cannot_hide_new_contextual_adjustment(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    prediction = seeded["predictions"][901]
    record_manual_adjustment(
        conn,
        adjustment_key="mixed-source-adjustment-901",
        model_prediction_id=prediction.id,
        category="weather",
        affected_side="both",
        margin_adjustment=-1,
        confidence_adjustment=0,
        reason="Fixture weather update.",
        evidence="Fixture forecast.",
        source="fixture-report",
        author="test",
        provenance="fixture://mixed-source-adjustment/901",
        recorded_at=REFRESH_RUN_AT,
    )
    conn.commit()

    with pytest.raises(DailyRefreshError, match="contextual adjustments"):
        _refresh(seeded, model_run_id=seeded["run"].id)

    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM card_revisions").fetchone()[0] == 0
    conn.close()


def test_line_correction_requires_explicit_type_and_preserves_original(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    original = seeded["lines"][901]
    correct_locked_line(
        conn,
        original.id,
        home_spread=-4,
        reason="Fixture source correction.",
        author="test",
        source="fixture-contest",
        provenance="fixture://line-correction/901",
        payload_sha256="f" * 64,
        corrected_at=REFRESH_RUN_AT,
    )
    conn.commit()

    with pytest.raises(DailyRefreshError, match="locked-line snapshot"):
        _refresh(seeded, model_run_id=seeded["run"].id)
    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 1

    result = _refresh(
        seeded,
        model_run_id=seeded["run"].id,
        change_type="data_correction",
    )

    assert result.revised_card.card.locked_line_snapshot_sha256 != (
        seeded["card"].card.locked_line_snapshot_sha256
    )
    assert conn.execute(
        "SELECT home_spread FROM contest_locked_lines WHERE id = ?",
        (original.id,),
    ).fetchone()[0] == -3
    assert conn.execute(
        "SELECT home_spread FROM contest_line_corrections WHERE locked_line_id = ?",
        (original.id,),
    ).fetchone()[0] == -4
    conn.close()


def test_refresh_history_is_append_only_and_database_validates_copied_values(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    run = _refreshed_run(seeded)
    result = _refresh(seeded, model_run_id=run.id)
    third = generate_full_card(
        conn,
        card_key="refresh-card-v3",
        contest_id=seeded["contest"].id,
        model_run_id=run.id,
        version=3,
        policy=SELECTION_POLICY,
        confidence_policy=RANKING_POLICY,
        adjustment_policy=ADJUSTMENT_POLICY,
        created_by="test",
        provenance="fixture://refresh-card/v3",
        generated_at=datetime(2026, 8, 27, 15, tzinfo=timezone.utc),
    )
    direct_revision = record_card_revision(
        conn,
        revision_key="refresh-card-v2:revision:3",
        prior_card_id=result.revised_card.card.id,
        revised_card_id=third.card.id,
        change_type="bug_fix",
        reason="Fixture direct-trigger validation.",
        author="test",
        provenance="fixture://refresh-card/v3/revision",
        revised_at=datetime(2026, 8, 27, 15, tzinfo=timezone.utc),
    )
    prior_pick = result.revised_card.picks[0]
    revised_pick = third.picks[0]

    with pytest.raises(sqlite3.IntegrityError, match="history is incomplete"):
        conn.execute(
            "INSERT INTO card_refresh_revisions "
            "(revision_id, refresh_policy_id, operating_date, operating_weekday, "
            "timezone_name, refreshed_at, provenance) "
            "VALUES (?, ?, '2026-08-27', 4, 'UTC', ?, ?)",
            (
                direct_revision.id,
                result.refresh.refresh_policy_id,
                datetime(2026, 8, 27, 15, tzinfo=timezone.utc).isoformat(),
                "fixture://incomplete-refresh-history",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError, match="do not match both snapshots"):
        conn.execute(
            "INSERT INTO card_revision_pick_changes "
            "(revision_id, locked_line_id, prior_pick_id, revised_pick_id, "
            "prior_model_prediction_id, revised_model_prediction_id, "
            "prior_selected_side, revised_selected_side, prior_confidence, "
            "revised_confidence, prior_rank, revised_rank, prior_is_top_five, "
            "revised_is_top_five, prior_fallback_code, revised_fallback_code, "
            "side_changed, confidence_changed, rank_changed, top_five_changed, "
            "model_prediction_changed, fallback_changed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                direct_revision.id,
                prior_pick.locked_line_id,
                prior_pick.id,
                revised_pick.id,
                prior_pick.model_prediction_id,
                revised_pick.model_prediction_id,
                prior_pick.selected_side,
                revised_pick.selected_side,
                prior_pick.confidence,
                revised_pick.confidence,
                prior_pick.rank,
                revised_pick.rank,
                int(prior_pick.is_top_five),
                int(revised_pick.is_top_five),
                prior_pick.fallback_code,
                revised_pick.fallback_code,
                1,
                0,
                0,
                0,
                0,
                0,
            ),
        )

    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE card_refresh_revisions SET provenance = provenance "
            "WHERE revision_id = ?",
            (result.revision.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "DELETE FROM card_revision_pick_changes WHERE revision_id = ?",
            (result.revision.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be replaced"):
        conn.execute(
            "INSERT OR REPLACE INTO card_refresh_policies "
            "SELECT * FROM card_refresh_policies WHERE id = ?",
            (result.refresh.refresh_policy_id,),
        )
    conn.close()
