import sqlite3
from datetime import datetime, timezone

import pytest

from business_entities import (
    AtsUnifiedCandidateInput,
    BusinessEntityConflictError,
    BusinessEntityError,
    TotalReliabilityPolicy,
    UnifiedTopFivePolicy,
    add_contest_pick,
    create_contest_card,
    generate_total_shadow_card,
    generate_unified_top_five,
    record_total_model_prediction,
    record_total_model_run,
    register_total_reliability_policy,
    register_unified_top_five_policy,
)
from business_entities.full_card import locked_line_snapshot_sha256
from contest_lines import (
    correct_locked_line,
    create_contest,
    list_effective_locked_lines,
    lock_contest_line,
)


POLICY_AT = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
LOCKED_AT = datetime(2026, 8, 25, 13, tzinfo=timezone.utc)
RUN_AT = datetime(2026, 8, 25, 14, tzinfo=timezone.utc)
ATS_CARD_AT = datetime(2026, 8, 25, 14, 20, tzinfo=timezone.utc)
PREDICTION_AT = datetime(2026, 8, 25, 14, 30, tzinfo=timezone.utc)
TOTAL_CARD_AT = datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
UNIFIED_AT = datetime(2026, 8, 25, 15, 15, tzinfo=timezone.utc)
FUTURE_CORRECTION_AT = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)
AFTER_CORRECTION_AT = datetime(2026, 8, 25, 15, 45, tzinfo=timezone.utc)
KICKOFF_AT = datetime(2026, 8, 29, 17, tzinfo=timezone.utc)


def _seed(temp_db):
    conn = temp_db.get_connection()
    contest = create_contest(
        conn,
        contest_key="totals-shadow-week-1",
        name="Totals Shadow Week 1",
        season=2026,
        week=1,
        source="SplashSports",
        provenance="fixture://totals/contest",
        created_at=LOCKED_AT,
    )
    totals = (45.0, 50.0, 55.0, 60.0, 65.0, None)
    projections = (50.0, 45.0, 55.0, 58.0, 70.0, 40.0)
    lines = []
    for index, total in enumerate(totals, start=1):
        game_id = 4100 + index
        home, away = f"Total Home {index}", f"Total Away {index}"
        conn.execute(
            "INSERT INTO games "
            "(game_id, season, week, home_team, away_team, start_date, completed) "
            "VALUES (?, 2026, 1, ?, ?, ?, 0)",
            (game_id, home, away, KICKOFF_AT.isoformat()),
        )
        lines.append(
            lock_contest_line(
                conn,
                contest_id=contest.id,
                game_id=game_id,
                raw_home_team=home,
                raw_away_team=away,
                normalized_home_team=home,
                normalized_away_team=away,
                home_spread=-float(index),
                total=total,
                source="SplashSports",
                source_line_id=f"splash-total-{index}",
                provenance=f"fixture://totals/line/{index}",
                payload_sha256=f"{index:x}" * 64,
                locked_at=LOCKED_AT,
            ).line
        )

    ats_card = create_contest_card(
        conn,
        card_key="legacy-ats-card-v1",
        contest_id=contest.id,
        version=1,
        status="draft",
        policy_version="unchanged-ats-policy-v1",
        locked_line_snapshot_sha256=locked_line_snapshot_sha256(
            list_effective_locked_lines(conn, contest.id, as_of=ATS_CARD_AT)
        ),
        created_by="test",
        provenance="fixture://totals/legacy-ats-card",
        generated_at=ATS_CARD_AT,
    )
    picks = []
    for index, line in enumerate(lines, start=1):
        picks.append(
            add_contest_pick(
                conn,
                pick_key=f"legacy-ats-pick-{index}",
                card_id=ats_card.id,
                locked_line_id=line.id,
                selected_side="home" if index % 2 else "away",
                confidence=min(index, 5),
                rank=index,
                is_top_five=index <= 5,
                fallback_code="fixture_explicit_fallback",
                provenance="fixture://totals/legacy-ats-pick",
                generated_at=ATS_CARD_AT,
            )
        )

    total_run = record_total_model_run(
        conn,
        run_key="totals-shadow-model-run-v1",
        model_name="pit_epa_total_linear",
        model_version="pit-epa-total-linear-v1",
        feature_schema_version="pit-epa-levels-v1",
        configuration_version="weekly-rolling-origin-ridge-v1",
        code_commit_sha="a" * 40,
        data_snapshot_sha256="b" * 64,
        lifecycle_stage="shadow",
        status="completed",
        provenance="fixture://totals/model-run",
        generated_at=RUN_AT,
    )
    predictions = []
    for index, projection in enumerate(projections, start=1):
        predictions.append(
            record_total_model_prediction(
                conn,
                prediction_key=f"total-prediction-{index}",
                total_model_run_id=total_run.id,
                game_id=4100 + index,
                projected_total=projection,
                uncertainty_points=6.0,
                home_stats_as_of_season=2025,
                home_stats_as_of_week=15,
                away_stats_as_of_season=2025,
                away_stats_as_of_week=15,
                features_as_of_at=RUN_AT,
                feature_snapshot_sha256=f"{index:x}" * 64,
                provenance=f"fixture://totals/prediction/{index}",
                generated_at=PREDICTION_AT,
            )
        )
    total_policy = register_total_reliability_policy(
        conn,
        TotalReliabilityPolicy(
            policy_key="total-reliability-shadow-v1",
            reliability_policy_version="total-reliability-v1",
            probability_model_version="normal-total-residual-v1",
            calibration_slope=1.0,
            confidence_2_min_probability=0.55,
            confidence_3_min_probability=0.60,
            confidence_4_min_probability=0.70,
            confidence_5_min_probability=0.80,
            forecast_tie_direction="under",
            effective_at=POLICY_AT,
            created_by="test",
            provenance="fixture://totals/reliability-policy",
        ),
    )
    total_card = generate_total_shadow_card(
        conn,
        card_key="totals-shadow-card-v1",
        contest_id=contest.id,
        total_model_run_id=total_run.id,
        total_reliability_policy_id=total_policy.id,
        version=1,
        generated_at=TOTAL_CARD_AT,
        created_by="test",
        provenance="fixture://totals/card",
    )
    unified_policy = register_unified_top_five_policy(
        conn,
        UnifiedTopFivePolicy(
            policy_key="unified-shadow-top-five-v1",
            policy_version="unified-shadow-top-five-v1",
            allow_multiple_per_game=False,
            effective_at=POLICY_AT,
            created_by="test",
            provenance="fixture://totals/unified-policy",
        ),
    )
    conn.commit()
    return {
        "conn": conn,
        "contest": contest,
        "lines": tuple(lines),
        "ats_card": ats_card,
        "picks": tuple(picks),
        "total_run": total_run,
        "predictions": tuple(predictions),
        "total_policy": total_policy,
        "total_card": total_card,
        "unified_policy": unified_policy,
    }


def _ats_inputs(picks):
    probabilities = (0.95, 0.61, 0.62, 0.63, 0.64, 0.65)
    return tuple(
        AtsUnifiedCandidateInput(
            contest_pick_id=pick.id,
            calibrated_probability=probability,
            reliability_policy_version="ats-shadow-calibration-v7",
        )
        for pick, probability in zip(picks, probabilities)
    )


def test_total_shadow_selects_over_under_tie_and_explicit_missing_total(temp_db):
    seeded = _seed(temp_db)
    result = seeded["total_card"]

    assert [item.selected_direction for item in result.candidates] == [
        "over",
        "under",
        "under",
        "under",
        "over",
    ]
    tie = result.candidates[2]
    assert tie.projected_total == tie.exact_locked_total == 55.0
    assert tie.selected_probability == pytest.approx(0.5)
    assert tie.confidence == 1
    assert len(result.skips) == 1
    assert result.skips[0].reason_code == "missing_locked_total"
    assert result.skips[0].locked_line_id == seeded["lines"][5].id
    assert result.completion.locked_line_count == 6
    assert result.completion.candidate_count == 5
    assert result.completion.skip_count == 1
    assert all(item.reliability_policy_version == "total-reliability-v1" for item in result.candidates)
    assert seeded["conn"].execute("SELECT COUNT(*) FROM contest_picks").fetchone()[0] == 6
    seeded["conn"].close()


def test_corrected_locked_total_is_point_in_time_and_future_correction_is_ignored(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    original = seeded["total_card"].candidates[0]
    assert original.exact_locked_total == 45.0

    correction = correct_locked_line(
        conn,
        seeded["lines"][0].id,
        total=52.0,
        reason="Fixture total correction",
        author="test",
        source="SplashSports",
        provenance="fixture://totals/correction",
        payload_sha256="f" * 64,
        corrected_at=FUTURE_CORRECTION_AT,
    )
    replay = generate_total_shadow_card(
        conn,
        card_key="totals-shadow-card-v1",
        contest_id=seeded["contest"].id,
        total_model_run_id=seeded["total_run"].id,
        total_reliability_policy_id=seeded["total_policy"].id,
        version=1,
        generated_at=TOTAL_CARD_AT,
        created_by="test",
        provenance="fixture://totals/card",
    )
    assert replay.replayed is True
    assert replay.candidates[0].exact_locked_total == 45.0

    later = generate_total_shadow_card(
        conn,
        card_key="totals-shadow-card-after-correction-v1",
        contest_id=seeded["contest"].id,
        total_model_run_id=seeded["total_run"].id,
        total_reliability_policy_id=seeded["total_policy"].id,
        version=2,
        generated_at=AFTER_CORRECTION_AT,
        created_by="test",
        provenance="fixture://totals/card-after-correction",
    )
    assert later.candidates[0].exact_locked_total == 52.0
    assert later.candidates[0].correction_id == correction.id
    assert later.candidates[0].selected_direction == "under"
    conn.close()


def test_future_features_and_post_kickoff_generation_are_rejected(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    with pytest.raises(BusinessEntityError, match="precede the target week"):
        record_total_model_prediction(
            conn,
            prediction_key="future-feature-prediction",
            total_model_run_id=seeded["total_run"].id,
            game_id=4101,
            projected_total=50,
            uncertainty_points=6,
            home_stats_as_of_season=2026,
            home_stats_as_of_week=1,
            away_stats_as_of_season=2025,
            away_stats_as_of_week=15,
            features_as_of_at=RUN_AT,
            feature_snapshot_sha256="e" * 64,
            provenance="fixture://totals/future-feature",
            generated_at=PREDICTION_AT,
        )
    with pytest.raises(BusinessEntityError, match="before kickoff"):
        generate_total_shadow_card(
            conn,
            card_key="post-kickoff-total-card",
            contest_id=seeded["contest"].id,
            total_model_run_id=seeded["total_run"].id,
            total_reliability_policy_id=seeded["total_policy"].id,
            version=2,
            generated_at=KICKOFF_AT,
            created_by="test",
            provenance="fixture://totals/post-kickoff",
        )
    assert conn.execute(
        "SELECT COUNT(*) FROM total_shadow_cards WHERE card_key = 'post-kickoff-total-card'"
    ).fetchone()[0] == 0
    conn.close()


def test_unified_top_five_mixes_markets_uses_probability_and_one_per_game(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    result = generate_unified_top_five(
        conn,
        run_key="unified-shadow-run-v1",
        contest_card_id=seeded["ats_card"].id,
        total_shadow_card_id=seeded["total_card"].card.id,
        unified_top_five_policy_id=seeded["unified_policy"].id,
        ats_candidates=_ats_inputs(seeded["picks"]),
        generated_at=UNIFIED_AT,
        created_by="test",
        provenance="fixture://totals/unified-run",
    )

    assert result.completion.candidate_count == 11
    assert result.completion.selected_count == 5
    assert len(result.top_five) == 5
    assert {item.market_type for item in result.top_five} == {"ATS", "TOTAL"}
    assert len({item.game_id for item in result.top_five}) == 5
    assert result.candidates[0].market_type == "ATS"
    assert result.candidates[0].calibrated_probability == 0.95
    assert all(item.candidate_score == item.calibrated_probability for item in result.candidates)
    game_one = [item for item in result.candidates if item.game_id == 4101]
    assert len(game_one) == 2
    assert sum(item.is_top_five for item in game_one) == 1
    assert {item.reliability_policy_version for item in game_one} == {
        "ats-shadow-calibration-v7",
        "total-reliability-v1",
    }
    assert [item.top_five_rank for item in result.top_five] == [1, 2, 3, 4, 5]
    unified_columns = {
        row[1]
        for row in conn.execute("PRAGMA table_info(unified_top_five_candidates)")
    }
    assert not any("edge" in column for column in unified_columns)
    conn.close()


def test_unified_replay_is_deterministic_and_requires_unambiguous_complete_inputs(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    kwargs = dict(
        run_key="unified-shadow-replay-v1",
        contest_card_id=seeded["ats_card"].id,
        total_shadow_card_id=seeded["total_card"].card.id,
        unified_top_five_policy_id=seeded["unified_policy"].id,
        ats_candidates=_ats_inputs(seeded["picks"]),
        generated_at=UNIFIED_AT,
        created_by="test",
        provenance="fixture://totals/unified-replay",
    )
    first = generate_unified_top_five(conn, **kwargs)
    second = generate_unified_top_five(conn, **kwargs)
    assert second.replayed is True
    assert second.run == first.run
    assert second.candidates == first.candidates
    assert second.completion == first.completion

    with pytest.raises(BusinessEntityError, match="cover every card pick"):
        generate_unified_top_five(
            conn,
            **{**kwargs, "run_key": "unified-incomplete", "ats_candidates": kwargs["ats_candidates"][:-1]},
        )
    with pytest.raises(sqlite3.IntegrityError, match="sealed"):
        conn.execute(
            "INSERT INTO unified_top_five_candidates "
            "(candidate_key, unified_top_five_run_id, market_type, game_id, "
            "contest_pick_id, total_card_candidate_id, calibrated_probability, "
            "candidate_score, reliability_policy_version, pool_rank, "
            "is_top_five, generated_at, provenance) "
            "VALUES ('ambiguous', ?, 'ATS', 4101, ?, ?, 0.6, 0.6, 'x', 99, 0, ?, 'x')",
            (
                first.run.id,
                seeded["picks"][0].id,
                seeded["total_card"].candidates[0].id,
                UNIFIED_AT.isoformat(),
            ),
        )
    conn.close()


def test_totals_shadow_entities_are_immutable_and_policy_is_independent_from_ats(temp_db):
    seeded = _seed(temp_db)
    conn = seeded["conn"]
    unified = generate_unified_top_five(
        conn,
        run_key="unified-shadow-immutable-v1",
        contest_card_id=seeded["ats_card"].id,
        total_shadow_card_id=seeded["total_card"].card.id,
        unified_top_five_policy_id=seeded["unified_policy"].id,
        ats_candidates=_ats_inputs(seeded["picks"]),
        generated_at=UNIFIED_AT,
        created_by="test",
        provenance="fixture://totals/unified-immutable",
    )
    rows = {
        "total_model_runs": seeded["total_run"].id,
        "total_model_predictions": seeded["predictions"][0].id,
        "total_reliability_policies": seeded["total_policy"].id,
        "total_shadow_cards": seeded["total_card"].card.id,
        "total_card_candidates": seeded["total_card"].candidates[0].id,
        "total_card_skips": seeded["total_card"].skips[0].id,
        "total_shadow_card_completions": seeded["total_card"].card.id,
        "unified_top_five_policies": seeded["unified_policy"].id,
        "unified_top_five_runs": unified.run.id,
        "unified_top_five_candidates": unified.candidates[0].id,
        "unified_top_five_completions": unified.run.id,
    }
    primary_keys = {
        "total_shadow_card_completions": "total_shadow_card_id",
        "unified_top_five_completions": "unified_top_five_run_id",
    }
    for table, row_id in rows.items():
        key = primary_keys.get(table, "id")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(f"UPDATE {table} SET {key} = {key} WHERE {key} = ?", (row_id,))
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(f"DELETE FROM {table} WHERE {key} = ?", (row_id,))

    assert seeded["conn"].execute(
        "SELECT selected_side, confidence, rank, is_top_five FROM contest_picks ORDER BY id"
    ).fetchall() == [
        ("home", 1, 1, 1),
        ("away", 2, 2, 1),
        ("home", 3, 3, 1),
        ("away", 4, 4, 1),
        ("home", 5, 5, 1),
        ("away", 5, 6, 0),
    ]
    with pytest.raises(BusinessEntityConflictError, match="different immutable"):
        record_total_model_run(
            conn,
            run_key="totals-shadow-model-run-v1",
            model_name="relabeled-ats-model",
            model_version="pit-epa-total-linear-v1",
            feature_schema_version="pit-epa-levels-v1",
            configuration_version="weekly-rolling-origin-ridge-v1",
            code_commit_sha="a" * 40,
            data_snapshot_sha256="b" * 64,
            lifecycle_stage="shadow",
            status="completed",
            provenance="fixture://totals/model-run",
            generated_at=RUN_AT,
        )
    conn.close()
