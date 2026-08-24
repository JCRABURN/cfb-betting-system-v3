import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from business_entities import (
    BusinessEntityError,
    evaluate_live_sportsbook_board,
    evaluate_sportsbook_offer,
    record_model_prediction,
    record_model_run,
    register_sportsbook_recommendation_policy,
)
from ingestion import IngestionRequest, OddsSpreadParser, ProviderIngestionService
from operations.providers import _odds_writer


BASE = datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc)
KICKOFF = BASE + timedelta(hours=4)


def _seed_game(conn, game_id=9001, home="Georgia", away="Clemson"):
    conn.executemany(
        "INSERT OR IGNORE INTO teams (team_id, school) VALUES (?, ?)",
        ((game_id * 2, home), (game_id * 2 + 1, away)),
    )
    conn.execute(
        "INSERT INTO games (game_id, season, week, start_date, home_team, away_team) "
        "VALUES (?, 2026, 1, ?, ?, ?)",
        (game_id, KICKOFF.isoformat(), home, away),
    )
    conn.commit()


def _prediction(
    conn,
    *,
    game_id=9001,
    margin=7.0,
    run_key="epa-run",
    model_name="epa_only",
    model_version="epa-only-linear-v1",
):
    run = record_model_run(
        conn,
        run_key=run_key,
        model_name=model_name,
        model_version=model_version,
        feature_schema_version="epa-differential-v1",
        configuration_version="walk-forward-prior-seasons-v1",
        code_commit_sha="a" * 40,
        data_snapshot_sha256="b" * 64,
        status="completed",
        provenance="fixture://model-run",
        generated_at=BASE - timedelta(minutes=10),
    )
    return record_model_prediction(
        conn,
        prediction_key=f"{run_key}:game:{game_id}",
        model_run_id=run.id,
        game_id=game_id,
        predicted_home_margin=margin,
        provenance="fixture://prediction",
        generated_at=BASE - timedelta(minutes=5),
    )


def _policy(conn, **overrides):
    values = {
        "policy_version": "sportsbook-policy-v1",
        "residual_stddev_points": 14.0,
        "minimum_spread_edge_points": 1.5,
        "minimum_cover_probability": 0.545,
        "minimum_expected_value": 0.025,
        "maximum_odds_age_seconds": 900,
        "material_update_seconds": 300,
        "material_spread_change_points": 0.5,
        "material_price_change": 5,
        "maximum_stake_units": 1.0,
        "stake_units_per_expected_value": 10.0,
        "stake_increment_units": 0.25,
        "effective_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "created_by": "test",
        "provenance": "fixture://sportsbook-policy",
    }
    values.update(overrides)
    return register_sportsbook_recommendation_policy(conn, **values)


def _offer_payload(
    *,
    game_id=9001,
    home="Georgia",
    away="Clemson",
    book="draftkings",
    observed=BASE,
    home_spread=-3.0,
    home_price=-110,
    away_price=-110,
    line_type="current",
):
    return {
        "records": [
            {
                "matchup_id": f"fixture-game-{game_id}:{book}",
                "game_id": game_id,
                "home_team": home,
                "away_team": away,
                "market_type": "spread",
                "home_spread": home_spread,
                "home_price": home_price,
                "away_spread": -home_spread,
                "away_price": away_price,
                "line_type": line_type,
                "season": 2026,
                "week": 1,
                "observed_at": observed.isoformat(),
                "event_start_at": KICKOFF.isoformat(),
                "bookmaker": book,
            }
        ]
    }


def _ingest_offer(conn, *, requested_at=None, **offer_values):
    payload = _offer_payload(**offer_values)
    observed = datetime.fromisoformat(payload["records"][0]["observed_at"])
    request_time = requested_at or observed
    request = IngestionRequest(
        provider="fixture_odds",
        endpoint="fixture://current-spreads",
        request_parameters={"market": "spreads"},
        requested_at=request_time,
        parser_version="odds_spread_v3",
        raw_payload_reference="fixture://two-sided-offer",
        data_type="odds",
    )
    summary = ProviderIngestionService(clock=lambda: request_time).ingest_payload(
        conn,
        request,
        payload,
        OddsSpreadParser("odds_spread_v3"),
        accepted_writer=_odds_writer(payload["records"][0]["line_type"]),
    )
    row = conn.execute(
        "SELECT offer.id FROM sportsbook_market_offers AS offer "
        "WHERE offer.bookmaker = ? AND offer.observed_at = ?",
        (payload["records"][0]["bookmaker"], observed.isoformat()),
    ).fetchone()
    return summary, None if row is None else int(row[0])


def test_bet_and_no_bet_are_offer_level_auditable_and_contest_independent(temp_db):
    conn = temp_db.get_connection()
    _seed_game(conn)
    prediction = _prediction(conn)
    policy = _policy(conn)
    _, offer_id = _ingest_offer(conn)
    assert offer_id is not None

    bet = evaluate_sportsbook_offer(
        conn,
        market_offer_id=offer_id,
        model_prediction_id=prediction.id,
        policy_id=policy.id,
        evaluated_at=BASE + timedelta(minutes=2),
        provenance="fixture://board-run",
    )

    assert (bet.decision, bet.selected_side, bet.bookmaker) == (
        "bet",
        "home",
        "draftkings",
    )
    assert bet.offered_spread == -3.0
    assert bet.offered_price == -110
    assert bet.model_fair_spread == -7.0
    assert bet.spread_edge_points == 4.0
    assert bet.estimated_cover_probability > bet.break_even_probability
    assert 0 < bet.expected_value
    assert 0 < bet.stake_units <= policy.maximum_stake_units
    assert bet.provenance == (
        f"fixture://board-run;provider=fixture_odds;provider_market_snapshot_id=1;"
        f"market_offer_id={offer_id};raw_record_sha256="
        f"{conn.execute('SELECT raw_record_sha256 FROM sportsbook_market_offers WHERE id = ?', (offer_id,)).fetchone()[0]};"
        f"model_prediction_id={prediction.id};policy_version={policy.policy_version}"
    )
    parent = conn.execute(
        "SELECT contest_pick_id, decision FROM sportsbook_recommendations WHERE id = ?",
        (bet.recommendation_id,),
    ).fetchone()
    assert parent == (None, "bet")
    assert conn.execute("SELECT COUNT(*) FROM contest_picks").fetchone()[0] == 0

    no_bet_prediction = _prediction(
        conn,
        margin=3.5,
        run_key="epa-run-no-bet",
    )
    no_bet = evaluate_sportsbook_offer(
        conn,
        market_offer_id=offer_id,
        model_prediction_id=no_bet_prediction.id,
        policy_id=policy.id,
        evaluated_at=BASE + timedelta(minutes=3),
        provenance="fixture://no-bet-board-run",
    )
    assert no_bet.decision == "no_bet"
    assert no_bet.reason_code.startswith("insufficient_")
    assert no_bet.stake_units == 0
    assert not any(
        row[0].startswith("wager")
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    )
    conn.close()


def test_price_sensitivity_and_multiple_books(temp_db):
    conn = temp_db.get_connection()
    _seed_game(conn)
    _prediction(conn, margin=6.0)
    policy = _policy(conn)
    _ingest_offer(conn, book="draftkings", home_price=-105, away_price=-115)
    _ingest_offer(conn, book="fanduel", home_price=-140, away_price=120)

    board = evaluate_live_sportsbook_board(
        conn,
        season=2026,
        week=1,
        policy_id=policy.id,
        evaluated_at=BASE + timedelta(minutes=2),
        provenance="fixture://multi-book",
    )

    assert len(board) == 2
    by_book = {item.bookmaker: item for item in board}
    assert by_book["draftkings"].decision == "bet"
    assert by_book["fanduel"].decision == "no_bet"
    assert by_book["draftkings"].expected_value > by_book["fanduel"].expected_value
    conn.close()


def test_spread_threshold_crossing_supersedes_without_mutation(temp_db):
    conn = temp_db.get_connection()
    _seed_game(conn)
    _prediction(conn, margin=5.0)
    policy = _policy(conn)
    _ingest_offer(conn, home_spread=-4.0)
    first = evaluate_live_sportsbook_board(
        conn,
        season=2026,
        week=1,
        policy_id=policy.id,
        evaluated_at=BASE + timedelta(minutes=1),
        provenance="fixture://initial-board",
    )[0]
    _ingest_offer(
        conn,
        observed=BASE + timedelta(minutes=4),
        home_spread=-3.0,
    )
    second = evaluate_live_sportsbook_board(
        conn,
        season=2026,
        week=1,
        policy_id=policy.id,
        evaluated_at=BASE + timedelta(minutes=5),
        provenance="fixture://moved-board",
    )[0]

    assert first.decision == "no_bet"
    assert second.decision == "bet"
    assert second.supersedes_evaluation_id == first.id
    assert conn.execute(
        "SELECT COUNT(*) FROM sportsbook_recommendation_evaluations"
    ).fetchone()[0] == 2
    assert conn.execute(
        "SELECT decision FROM sportsbook_recommendation_evaluations WHERE id = ?",
        (first.id,),
    ).fetchone()[0] == "no_bet"
    conn.close()


def test_stale_future_and_closing_offers_fail_safe(temp_db):
    conn = temp_db.get_connection()
    _seed_game(conn)
    prediction = _prediction(conn)
    policy = _policy(conn, maximum_odds_age_seconds=300)
    _, stale_offer_id = _ingest_offer(conn)
    assert stale_offer_id is not None
    active = evaluate_sportsbook_offer(
        conn,
        market_offer_id=stale_offer_id,
        model_prediction_id=prediction.id,
        policy_id=policy.id,
        evaluated_at=BASE + timedelta(minutes=2),
        provenance="fixture://active-board",
    )
    stale = evaluate_live_sportsbook_board(
        conn,
        season=2026,
        week=1,
        policy_id=policy.id,
        evaluated_at=BASE + timedelta(minutes=6),
        provenance="fixture://stale-board",
    )[0]
    assert (stale.lifecycle_state, stale.decision, stale.reason_code) == (
        "expired",
        "no_bet",
        "stale_odds",
    )
    assert stale.supersedes_evaluation_id == active.id

    summary, future_offer_id = _ingest_offer(
        conn,
        book="futurebook",
        observed=BASE + timedelta(minutes=10),
        requested_at=BASE + timedelta(minutes=9),
    )
    assert summary.status == "rejected"
    assert future_offer_id is None

    _, closing_offer_id = _ingest_offer(
        conn,
        book="closingbook",
        observed=BASE + timedelta(minutes=7),
        line_type="closing",
    )
    assert closing_offer_id is not None
    with pytest.raises(BusinessEntityError, match="closing line"):
        evaluate_sportsbook_offer(
            conn,
            market_offer_id=closing_offer_id,
            model_prediction_id=prediction.id,
            policy_id=policy.id,
            evaluated_at=BASE + timedelta(minutes=8),
            provenance="fixture://invalid-closing",
        )
    conn.close()


def test_duplicate_snapshot_replay_creates_one_offer_and_one_evaluation(temp_db):
    conn = temp_db.get_connection()
    _seed_game(conn)
    _prediction(conn)
    policy = _policy(conn)
    first, _ = _ingest_offer(conn)
    second, _ = _ingest_offer(conn)
    assert first.replayed is False
    assert second.replayed is True
    assert conn.execute("SELECT COUNT(*) FROM provider_market_snapshots").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM sportsbook_market_offers").fetchone()[0] == 1

    first_board = evaluate_live_sportsbook_board(
        conn,
        season=2026,
        week=1,
        policy_id=policy.id,
        evaluated_at=BASE + timedelta(minutes=2),
        provenance="fixture://idempotent-board",
    )
    second_board = evaluate_live_sportsbook_board(
        conn,
        season=2026,
        week=1,
        policy_id=policy.id,
        evaluated_at=BASE + timedelta(minutes=2),
        provenance="fixture://idempotent-board",
    )
    assert second_board == first_board
    assert conn.execute(
        "SELECT COUNT(*) FROM sportsbook_recommendation_evaluations"
    ).fetchone()[0] == 1
    for table in (
        "sportsbook_market_offers",
        "sportsbook_recommendation_policies",
        "sportsbook_recommendation_evaluations",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(f"UPDATE {table} SET id = id")
        conn.rollback()
    conn.close()


def test_stake_cap_and_model_mismatch_rejection(temp_db):
    conn = temp_db.get_connection()
    _seed_game(conn)
    prediction = _prediction(conn, margin=35.0)
    policy = _policy(conn, maximum_stake_units=0.75)
    _, offer_id = _ingest_offer(conn)
    assert offer_id is not None
    capped = evaluate_sportsbook_offer(
        conn,
        market_offer_id=offer_id,
        model_prediction_id=prediction.id,
        policy_id=policy.id,
        evaluated_at=BASE + timedelta(minutes=2),
        provenance="fixture://stake-cap",
    )
    assert capped.stake_units == 0.75

    research = _prediction(
        conn,
        margin=35.0,
        run_key="rejected-research-run",
        model_name="ridge",
        model_version="ridge-rejected-v1",
    )
    with pytest.raises(BusinessEntityError, match="EPA-only"):
        evaluate_sportsbook_offer(
            conn,
            market_offer_id=offer_id,
            model_prediction_id=research.id,
            policy_id=policy.id,
            evaluated_at=BASE + timedelta(minutes=3),
            provenance="fixture://model-mismatch",
        )
    conn.close()
