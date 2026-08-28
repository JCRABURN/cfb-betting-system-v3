import sqlite3
from dataclasses import asdict
from datetime import datetime, timezone

from business_entities import (
    ConfidenceRankingPolicy,
    ContestLineInput,
    FreshnessFallbackDecision,
    FullCardPolicy,
    ManualAdjustmentPolicy,
    RequiredSourcePolicy,
    SportsbookNoBetInput,
    TuesdayCardRequest,
    WeeklyControllerPolicy,
    run_tuesday_controller,
)
from migrations.runner import apply_migrations, load_migrations


POLICY_AT = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
GENERATED_AT = datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
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
    created_by="identity-parity-test",
    provenance="fixture://football-identity/product-a/controller-policy",
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
    created_by="identity-parity-test",
    provenance="fixture://football-identity/product-a/confidence-policy",
)
ADJUSTMENT_POLICY = ManualAdjustmentPolicy(
    policy_version="official-adjustments-v1",
    effective_at=POLICY_AT,
    created_by="identity-parity-test",
    provenance="fixture://football-identity/product-a/adjustment-policy",
)


def _connection(migration_count):
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    apply_migrations(conn, load_migrations()[:migration_count])
    return conn


def _seed_product_a_fixture(conn):
    lines = []
    for index in range(1, 6):
        home = f"Home {index}"
        away = f"Away {index}"
        conn.execute(
            "INSERT INTO teams (team_id, school, conference, division) "
            "VALUES (?, ?, 'Fixture Conference', 'FBS')",
            (index * 2 - 1, home),
        )
        conn.execute(
            "INSERT INTO teams (team_id, school, conference, division) "
            "VALUES (?, ?, 'Fixture Conference', 'FBS')",
            (index * 2, away),
        )
        conn.execute(
            "INSERT INTO games "
            "(game_id, season, week, season_type, start_date, home_team, away_team, "
            "venue, venue_latitude, venue_longitude, neutral_site, completed) "
            "VALUES (?, 2026, 1, 'regular', ?, ?, ?, ?, 40.0, -75.0, ?, 0)",
            (
                1000 + index,
                KICKOFF,
                home,
                away,
                "Fixture Neutral Stadium" if index == 1 else f"Home {index} Stadium",
                1 if index == 1 else 0,
            ),
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

    for team_id, school in (
        (101, "Historic Home 2024"),
        (102, "Historic Away 2024"),
        (103, "Historic Home 2025"),
        (104, "Historic Away 2025"),
    ):
        conn.execute(
            "INSERT INTO teams (team_id, school, conference, division) "
            "VALUES (?, ?, 'Historic Fixture', 'FBS')",
            (team_id, school),
        )
    conn.execute(
        "INSERT INTO games "
        "(game_id, season, week, season_type, start_date, home_team, away_team, "
        "neutral_site, home_points, away_points, completed) VALUES "
        "(9001, 2024, 3, 'regular', '2024-09-14T17:00:00+00:00', "
        "'Historic Home 2024', 'Historic Away 2024', 0, 24, 17, 1), "
        "(9002, 2025, 15, 'postseason', '2025-12-20T20:00:00+00:00', "
        "'Historic Home 2025', 'Historic Away 2025', 1, 31, 28, 1)"
    )
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
    for index in range(1, 6):
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
    return tuple(lines)


def _fallbacks():
    return tuple(
        FreshnessFallbackDecision(
            data_type=source.data_type,
            fallback_code=source.permitted_fallback_code,
            reason=f"Fixture {source.data_type} source is unavailable.",
            evidence=f"fixture://football-identity/freshness/{source.data_type}",
            provenance=f"fixture://football-identity/fallback/{source.data_type}",
        )
        for source in SOURCE_RULES
    )


def _request(lines):
    return TuesdayCardRequest(
        run_key="identity-parity-week-1-controller",
        publication_key="identity-parity-week-1-official-v1",
        contest_key="splashsports-2026-week-1",
        contest_name="SplashSports 2026 Week 1",
        source_contest_id="splash-2026-w1",
        season=2026,
        week=1,
        expected_lined_game_count=len(lines),
        line_payload_sha256="c" * 64,
        raw_payload_reference="fixture://football-identity/splashsports/week-1.json",
        lines=lines,
        model_run_key="identity-parity-epa-run-v1",
        code_commit_sha="a" * 40,
        controller_policy=CONTROLLER_POLICY,
        selection_policy=SELECTION_POLICY,
        confidence_policy=CONFIDENCE_POLICY,
        adjustment_policy=ADJUSTMENT_POLICY,
        freshness_fallbacks=_fallbacks(),
        contextual_adjustments=(),
        sportsbook_recommendations=(
            SportsbookNoBetInput(
                recommendation_key="identity-parity-game-1001-no-bet-v1",
                game_id=1001,
                policy_version="sportsbook-no-bet-v1",
                reason_code="insufficient_calibrated_edge",
                provenance="fixture://football-identity/sportsbook/game-1001",
            ),
        ),
        generated_at=GENERATED_AT,
        actor="identity-parity-test",
        provenance="fixture://football-identity/product-a/controller",
    )


def _application_tables(conn):
    return tuple(
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' "
            "AND name != 'schema_migrations' ORDER BY name"
        )
    )


def _table_snapshot(conn, tables):
    return {
        table: tuple(conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid'))
        for table in tables
    }


def _result_signature(result):
    return {
        "run": asdict(result.run),
        "publication": asdict(result.publication),
        "card": asdict(result.card.card),
        "picks": tuple(asdict(pick) for pick in result.card.picks),
        "completeness": asdict(result.card.report),
        "freshness": tuple(asdict(item) for item in result.freshness),
        "line_batch": asdict(result.line_batch),
        "persisted": result.persisted,
        "replayed": result.replayed,
    }


def test_migration_preserves_product_a_rows_and_controller_outputs_exactly():
    before_conn = _connection(18)
    after_conn = _connection(18)
    before_lines = _seed_product_a_fixture(before_conn)
    after_lines = _seed_product_a_fixture(after_conn)
    product_a_tables = _application_tables(before_conn)
    pre_migration_rows = _table_snapshot(after_conn, product_a_tables)

    applied = apply_migrations(after_conn, load_migrations()[:19])

    assert tuple(result.version for result in applied) == (19,)
    assert _table_snapshot(after_conn, product_a_tables) == pre_migration_rows

    before_result = run_tuesday_controller(before_conn, _request(before_lines))
    after_result = run_tuesday_controller(after_conn, _request(after_lines))

    assert _result_signature(after_result) == _result_signature(before_result)
    assert _table_snapshot(after_conn, product_a_tables) == _table_snapshot(
        before_conn, product_a_tables
    )
    assert len(after_result.card.picks) == 5
    assert {pick.confidence for pick in after_result.card.picks} == {1}
    assert {pick.rank for pick in after_result.card.picks} == {1, 2, 3, 4, 5}
    assert all(pick.is_top_five for pick in after_result.card.picks)
    assert after_conn.execute(
        "SELECT decision, recommended_side, stake_units, reason_code "
        "FROM sportsbook_recommendations"
    ).fetchall() == [
        ("no_bet", None, 0.0, "insufficient_calibrated_edge")
    ]
    assert after_conn.execute(
        "SELECT COUNT(*) FROM legacy_cfb_game_links"
    ).fetchone()[0] == 0
    before_conn.close()
    after_conn.close()


def test_product_a_runs_when_only_required_sport_registry_exists():
    conn = _connection(19)
    lines = _seed_product_a_fixture(conn)
    empty_identity_tables = (
        "football_franchises",
        "football_teams",
        "football_team_seasons",
        "football_team_aliases",
        "football_venues",
        "football_venue_versions",
        "football_events",
        "football_event_revisions",
        "football_provider_event_ids",
        "legacy_cfb_game_links",
    )
    assert conn.execute("SELECT COUNT(*) FROM football_sports").fetchone()[0] == 2
    assert all(
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        for table in empty_identity_tables
    )

    result = run_tuesday_controller(conn, _request(lines))

    assert result.publication.pick_count == 5
    assert result.publication.top_five_count == 5
    assert result.publication.fallback_pick_count == 0
    assert all(
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        for table in empty_identity_tables
    )
    conn.close()


def test_migration_20_preserves_product_a_rows_and_controller_outputs_exactly():
    before_conn = _connection(19)
    after_conn = _connection(19)
    before_lines = _seed_product_a_fixture(before_conn)
    after_lines = _seed_product_a_fixture(after_conn)
    product_a_tables = _application_tables(before_conn)
    pre_migration_rows = _table_snapshot(after_conn, product_a_tables)

    applied = apply_migrations(after_conn)

    assert tuple(result.version for result in applied) == (20,)
    assert _table_snapshot(after_conn, product_a_tables) == pre_migration_rows

    before_result = run_tuesday_controller(before_conn, _request(before_lines))
    after_result = run_tuesday_controller(after_conn, _request(after_lines))

    assert _result_signature(after_result) == _result_signature(before_result)
    assert _table_snapshot(after_conn, product_a_tables) == _table_snapshot(
        before_conn, product_a_tables
    )
    assert len(after_result.card.picks) == 5
    assert {pick.confidence for pick in after_result.card.picks} == {1}
    assert {pick.rank for pick in after_result.card.picks} == {1, 2, 3, 4, 5}
    assert all(pick.is_top_five for pick in after_result.card.picks)
    assert after_conn.execute(
        "SELECT decision, recommended_side, stake_units, reason_code "
        "FROM sportsbook_recommendations"
    ).fetchall() == [
        ("no_bet", None, 0.0, "insufficient_calibrated_edge")
    ]
    before_conn.close()
    after_conn.close()


def test_product_a_has_no_dependency_on_product_b_operational_state():
    conn = _connection(20)
    lines = _seed_product_a_fixture(conn)
    operational_tables = (
        "mixed_contest_seasons",
        "mixed_contest_rounds",
        "mixed_slate_imports",
        "mixed_slate_import_rows",
        "mixed_slate_manifests",
        "mixed_slate_manifest_rows",
        "mixed_deadline_derivations",
        "mixed_slate_approvals",
        "mixed_line_lock_batches",
        "mixed_contest_lines",
    )
    assert all(
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        for table in operational_tables
    )

    result = run_tuesday_controller(conn, _request(lines))

    assert result.publication.pick_count == 5
    assert result.publication.top_five_count == 5
    assert result.publication.fallback_pick_count == 0
    assert all(
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
        for table in operational_tables
    )
    conn.close()
