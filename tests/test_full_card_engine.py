from datetime import datetime, timezone

import pytest

from business_entities import (
    ConfidenceRankingPolicy,
    FullCardError,
    FullCardPolicy,
    IncompleteCardError,
    generate_full_card,
    inspect_full_card,
    record_model_prediction,
    record_model_run,
    validate_full_card,
)
from business_entities.cards import add_contest_pick, create_contest_card
from business_entities.full_card import locked_line_snapshot_sha256
from contest_lines import (
    correct_locked_line,
    create_contest,
    get_effective_locked_line,
    get_effective_locked_line_as_of,
    list_effective_locked_lines,
    lock_contest_line,
)


LOCKED_AT = datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
RUN_AT = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)
PREDICTION_AT = datetime(2026, 8, 25, 15, 45, tzinfo=timezone.utc)
GENERATED_AT = datetime(2026, 8, 25, 16, tzinfo=timezone.utc)
AFTER_CARD = datetime(2026, 8, 25, 17, tzinfo=timezone.utc)
KICKOFF = "2026-08-29T17:00:00+00:00"

POLICY = FullCardPolicy(
    version="full-card-v1",
    market_books=("draftkings", "fanduel", "betmgm"),
    model_tie_side="away",
    pickem_tiebreak_side="home",
)
CONFIDENCE_POLICY = ConfidenceRankingPolicy(
    policy_key="contest-confidence-ranking-v1",
    confidence_policy_version="confidence-v1",
    ranking_policy_version="top-five-v1",
    confidence_5_max_uncertainty=2.0,
    confidence_4_max_uncertainty=4.0,
    confidence_3_max_uncertainty=6.0,
    confidence_2_max_uncertainty=8.0,
    effective_at=LOCKED_AT,
    created_by="test",
    provenance="fixture://confidence-ranking-policy",
)


def _insert_game(conn, game_id, home, away, kickoff=KICKOFF):
    conn.execute(
        "INSERT INTO games "
        "(game_id, season, week, home_team, away_team, start_date) "
        "VALUES (?, 2026, 1, ?, ?, ?)",
        (game_id, home, away, kickoff),
    )


def _insert_market_line(
    conn,
    *,
    game_id,
    home,
    away,
    spread,
    line_type,
    book,
    fetched_at=PREDICTION_AT,
):
    return conn.execute(
        "INSERT INTO betting_lines "
        "(game_id, season, week, home_team, away_team, book, home_spread, "
        "line_type, source, fetched_at) VALUES (?, 2026, 1, ?, ?, ?, ?, ?, "
        "'fixture-market', ?)",
        (game_id, home, away, book, spread, line_type, fetched_at.isoformat()),
    ).lastrowid


def _create_run(conn):
    return record_model_run(
        conn,
        run_key="full-card-run-1",
        model_name="fixture-model",
        model_version="1",
        feature_schema_version="1",
        configuration_version="fixture-config-1",
        code_commit_sha="a" * 40,
        data_snapshot_sha256="b" * 64,
        status="completed",
        provenance="fixture://model-run",
        generated_at=RUN_AT,
    )


def _create_contest(conn, key="week-1"):
    return create_contest(
        conn,
        contest_key=key,
        name="Week 1 full card",
        season=2026,
        week=1,
        source="fixture-contest",
        provenance=f"fixture://contest/{key}",
        created_at=LOCKED_AT,
    )


def _lock(
    conn,
    *,
    contest_id,
    game_id,
    home,
    away,
    spread,
    locked_at=LOCKED_AT,
):
    return lock_contest_line(
        conn,
        contest_id=contest_id,
        game_id=game_id,
        raw_home_team=home,
        raw_away_team=away,
        normalized_home_team=home,
        normalized_away_team=away,
        home_spread=spread,
        source="fixture-contest",
        source_line_id=f"line-{game_id}",
        provenance=f"fixture://contest/line-{game_id}",
        payload_sha256=f"{game_id % 16:x}" * 64,
        locked_at=locked_at,
    ).line


def _seed_full_hierarchy(temp_db):
    conn = temp_db.get_connection()
    contest = _create_contest(conn)
    run = _create_run(conn)
    matchups = (
        (101, "Model Home", "Model Away", -3.0),
        (102, "Current Home", "Current Away", -3.5),
        (103, "Opening Home", "Opening Away", 2.5),
        (104, "Underdog Home", "Underdog Away", -7.0),
        (105, "Pickem Home", "Pickem Away", 0.0),
    )
    lines = {}
    for game_id, home, away, spread in matchups:
        _insert_game(conn, game_id, home, away)
        lines[game_id] = _lock(
            conn,
            contest_id=contest.id,
            game_id=game_id,
            home=home,
            away=away,
            spread=spread,
        )

    prediction = record_model_prediction(
        conn,
        prediction_key="prediction-101",
        model_run_id=run.id,
        game_id=101,
        predicted_home_margin=7.0,
        uncertainty_points=3.0,
        entry_locked_line_id=lines[101].id,
        provenance="fixture://prediction/101",
        generated_at=PREDICTION_AT,
    )

    current_id = _insert_market_line(
        conn,
        game_id=102,
        home="Current Home",
        away="Current Away",
        spread=-5.0,
        line_type="current",
        book="draftkings",
    )
    _insert_market_line(
        conn,
        game_id=102,
        home="Current Home",
        away="Current Away",
        spread=-2.0,
        line_type="current",
        book="fanduel",
    )
    _insert_market_line(
        conn,
        game_id=102,
        home="Current Home",
        away="Current Away",
        spread=-9.0,
        line_type="current",
        book="draftkings",
        fetched_at=AFTER_CARD,
    )
    opening_id = _insert_market_line(
        conn,
        game_id=103,
        home="Opening Home",
        away="Opening Away",
        spread=1.0,
        line_type="opening",
        book="fanduel",
    )
    _insert_market_line(
        conn,
        game_id=103,
        home="Opening Home",
        away="Opening Away",
        spread=-10.0,
        line_type="closing",
        book="draftkings",
    )
    _insert_market_line(
        conn,
        game_id=104,
        home="Underdog Home",
        away="Underdog Away",
        spread=-10.0,
        line_type="current",
        book="draftkings",
        fetched_at=AFTER_CARD,
    )
    conn.commit()
    return {
        "conn": conn,
        "contest": contest,
        "run": run,
        "lines": lines,
        "prediction": prediction,
        "current_id": current_id,
        "opening_id": opening_id,
    }


def _generate(seeded):
    return generate_full_card(
        seeded["conn"],
        card_key="week-1-card-v1",
        contest_id=seeded["contest"].id,
        model_run_id=seeded["run"].id,
        version=1,
        policy=POLICY,
        confidence_policy=CONFIDENCE_POLICY,
        created_by="test",
        provenance="fixture://full-card-generation",
        generated_at=GENERATED_AT,
    )


def test_generates_one_side_for_every_locked_game_with_explicit_fallbacks(temp_db):
    seeded = _seed_full_hierarchy(temp_db)
    result = _generate(seeded)
    by_game = {
        seeded["lines"][game_id].id: pick for game_id, pick in zip(
            (101, 102, 103, 104, 105), result.picks
        )
    }

    assert result.card.status == "draft"
    assert [pick.locked_line_id for pick in result.picks] == [
        seeded["lines"][game_id].id for game_id in (101, 102, 103, 104, 105)
    ]
    assert by_game[seeded["lines"][101].id].selected_side == "home"
    assert by_game[seeded["lines"][101].id].fallback_code is None
    assert by_game[seeded["lines"][102].id].selected_side == "home"
    assert by_game[seeded["lines"][102].id].fallback_code == (
        f"market_current_line:{seeded['current_id']}"
    )
    assert by_game[seeded["lines"][103].id].selected_side == "home"
    assert by_game[seeded["lines"][103].id].fallback_code == (
        f"market_opening_line:{seeded['opening_id']}"
    )
    assert by_game[seeded["lines"][104].id].selected_side == "away"
    assert by_game[seeded["lines"][104].id].fallback_code == "locked_line_underdog"
    assert by_game[seeded["lines"][105].id].selected_side == "home"
    assert by_game[seeded["lines"][105].id].fallback_code == (
        "locked_line_pickem_tiebreak_home"
    )
    assert all(pick.selected_side in ("home", "away") for pick in result.picks)
    assert by_game[seeded["lines"][101].id].confidence == 4
    assert by_game[seeded["lines"][101].id].rank == 5
    assert all(pick.confidence == 1 for pick in result.picks[1:])
    assert [pick.rank for pick in result.picks] == [5, 4, 3, 2, 1]
    assert all(pick.is_top_five for pick in result.picks)
    assert all(pick.provenance.startswith("fixture://") for pick in result.picks)
    assert result.report.expected_locked_line_count == 5
    assert result.report.normalized_matchup_count == 5
    assert result.report.pick_count == 5
    assert result.report.model_pick_count == 1
    assert result.report.fallback_pick_count == 4
    assert result.report.policy_replay_matches is True
    assert result.report.confidence_ranking_policy_matches is True
    assert result.report.confidence_coverage_count == 5
    assert result.report.top_five_count == 5
    assert result.report.ranked_pick_count == 5
    assert result.report.side_complete is True
    assert result.report.contest_complete is True
    assert result.report.official_ready is True
    assert seeded["conn"].execute("SELECT COUNT(*) FROM picks").fetchone()[0] == 0
    assert seeded["conn"].execute(
        "SELECT COUNT(*) FROM sportsbook_recommendations"
    ).fetchone()[0] == 0
    seeded["conn"].close()


def test_replay_is_idempotent_and_ignores_future_predictions_locks_and_corrections(temp_db):
    seeded = _seed_full_hierarchy(temp_db)
    first = _generate(seeded)
    conn = seeded["conn"]

    record_model_prediction(
        conn,
        prediction_key="prediction-102-after-card",
        model_run_id=seeded["run"].id,
        game_id=102,
        predicted_home_margin=-20.0,
        provenance="fixture://future-prediction",
        generated_at=AFTER_CARD,
    )
    correct_locked_line(
        conn,
        seeded["lines"][101].id,
        home_spread=-10.0,
        reason="Future correction must not alter the prior card.",
        author="test",
        source="fixture-contest",
        provenance="fixture://future-correction",
        payload_sha256="f" * 64,
        corrected_at=AFTER_CARD,
    )
    _insert_game(conn, 106, "Later Home", "Later Away")
    later_line = _lock(
        conn,
        contest_id=seeded["contest"].id,
        game_id=106,
        home="Later Home",
        away="Later Away",
        spread=-1.0,
        locked_at=AFTER_CARD,
    )
    conn.commit()

    assert get_effective_locked_line(conn, seeded["lines"][101].id).home_spread == -10
    assert get_effective_locked_line_as_of(
        conn, seeded["lines"][101].id, GENERATED_AT
    ).home_spread == -3
    replay = _generate(seeded)

    assert replay == first
    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM contest_picks").fetchone()[0] == 5
    assert later_line.id not in {pick.locked_line_id for pick in replay.picks}
    conn.close()


def test_unresolved_line_fails_before_any_card_or_pick_is_persisted(temp_db):
    conn = temp_db.get_connection()
    contest = _create_contest(conn)
    run = _create_run(conn)
    lock_contest_line(
        conn,
        contest_id=contest.id,
        game_id=None,
        raw_home_team="Unresolved Home",
        raw_away_team="Unresolved Away",
        normalized_home_team="Unresolved Home",
        normalized_away_team="Unresolved Away",
        home_spread=-2.5,
        source="fixture-contest",
        provenance="fixture://unresolved",
        payload_sha256="c" * 64,
        locked_at=LOCKED_AT,
    )
    conn.commit()

    with pytest.raises(FullCardError, match="unresolved or mismatched"):
        generate_full_card(
            conn,
            card_key="invalid-card",
            contest_id=contest.id,
            model_run_id=run.id,
            version=1,
            policy=POLICY,
            confidence_policy=CONFIDENCE_POLICY,
            created_by="test",
            provenance="fixture://invalid-generation",
            generated_at=GENERATED_AT,
        )

    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM contest_picks").fetchone()[0] == 0
    conn.close()


def test_missing_or_past_kickoff_fails_closed_without_persistence(temp_db):
    conn = temp_db.get_connection()
    contest = _create_contest(conn)
    run = _create_run(conn)
    _insert_game(
        conn,
        201,
        "Past Home",
        "Past Away",
        kickoff="2026-08-25T15:59:00+00:00",
    )
    _lock(
        conn,
        contest_id=contest.id,
        game_id=201,
        home="Past Home",
        away="Past Away",
        spread=-3.0,
    )
    conn.commit()

    with pytest.raises(FullCardError, match="future valid kickoff"):
        generate_full_card(
            conn,
            card_key="late-card",
            contest_id=contest.id,
            model_run_id=run.id,
            version=1,
            policy=POLICY,
            confidence_policy=CONFIDENCE_POLICY,
            created_by="test",
            provenance="fixture://late-generation",
            generated_at=GENERATED_AT,
        )
    assert conn.execute("SELECT COUNT(*) FROM contest_cards").fetchone()[0] == 0
    conn.close()


def test_incomplete_existing_card_reports_exact_missing_locked_lines(temp_db):
    seeded = _seed_full_hierarchy(temp_db)
    conn = seeded["conn"]
    lines = list_effective_locked_lines(
        conn, seeded["contest"].id, as_of=GENERATED_AT
    )
    card = create_contest_card(
        conn,
        card_key="partial-card",
        contest_id=seeded["contest"].id,
        model_run_id=seeded["run"].id,
        version=1,
        status="draft",
        policy_version=POLICY.version,
        locked_line_snapshot_sha256=locked_line_snapshot_sha256(lines),
        generated_at=GENERATED_AT,
        created_by="test",
        provenance="fixture://partial-card",
    )
    partial_pick = add_contest_pick(
        conn,
        pick_key="partial-card:101",
        card_id=card.id,
        locked_line_id=seeded["lines"][101].id,
        selected_side="home",
        fallback_code="fabricated_fallback",
        generated_at=GENERATED_AT,
        provenance="fixture://partial-pick",
    )

    report = inspect_full_card(
        conn,
        card.id,
        policy=POLICY,
        confidence_policy=CONFIDENCE_POLICY,
    )
    assert report.side_complete is False
    assert report.missing_locked_line_ids == tuple(
        seeded["lines"][game_id].id for game_id in (102, 103, 104, 105)
    )
    assert report.invalid_fallback_pick_ids == (partial_pick.id,)
    assert report.policy_replay_matches is False
    with pytest.raises(IncompleteCardError) as failure:
        validate_full_card(
            conn,
            card.id,
            policy=POLICY,
            confidence_policy=CONFIDENCE_POLICY,
        )
    assert failure.value.report == report
    conn.close()


def test_policy_rejects_consensus_or_duplicate_book_fallbacks(temp_db):
    seeded = _seed_full_hierarchy(temp_db)
    common = dict(
        conn=seeded["conn"],
        card_key="invalid-policy-card",
        contest_id=seeded["contest"].id,
        model_run_id=seeded["run"].id,
        version=1,
        confidence_policy=CONFIDENCE_POLICY,
        created_by="test",
        provenance="fixture://invalid-policy",
        generated_at=GENERATED_AT,
    )
    with pytest.raises(FullCardError, match="not consensus"):
        generate_full_card(
            **common,
            policy=FullCardPolicy("invalid-1", ("consensus",)),
        )
    with pytest.raises(FullCardError, match="duplicates"):
        generate_full_card(
            **common,
            policy=FullCardPolicy("invalid-2", ("draftkings", "draftkings")),
        )
    assert seeded["conn"].execute(
        "SELECT COUNT(*) FROM contest_cards"
    ).fetchone()[0] == 0
    seeded["conn"].close()


def test_model_tie_uses_the_versioned_tiebreak_and_records_it(temp_db):
    conn = temp_db.get_connection()
    contest = _create_contest(conn)
    run = _create_run(conn)
    _insert_game(conn, 301, "Tie Home", "Tie Away")
    line = _lock(
        conn,
        contest_id=contest.id,
        game_id=301,
        home="Tie Home",
        away="Tie Away",
        spread=-3.0,
    )
    record_model_prediction(
        conn,
        prediction_key="prediction-301",
        model_run_id=run.id,
        game_id=301,
        predicted_home_margin=3.0,
        entry_locked_line_id=line.id,
        provenance="fixture://prediction/301",
        generated_at=PREDICTION_AT,
    )

    result = generate_full_card(
        conn,
        card_key="tie-card",
        contest_id=contest.id,
        model_run_id=run.id,
        version=1,
        policy=POLICY,
        confidence_policy=CONFIDENCE_POLICY,
        created_by="test",
        provenance="fixture://tie-card",
        generated_at=GENERATED_AT,
    )

    assert result.picks[0].selected_side == "away"
    assert result.picks[0].fallback_code == "model_tie_away"
    assert result.picks[0].model_prediction_id is not None
    assert result.report.side_complete is True
    conn.close()
