def test_init_db_creates_all_tables(temp_db):
    conn = temp_db.get_connection()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    expected = {
        "teams", "games", "betting_lines", "team_game_stats",
        "weather", "injuries", "picks", "ingestion_runs",
        "schema_migrations", "supplemental_game_dates",
        "contests", "contest_locked_lines", "contest_line_corrections",
        "model_runs", "model_predictions", "contest_cards", "contest_picks",
        "sportsbook_recommendations", "card_revisions", "manual_adjustments",
        "pick_audits", "contest_selection_policies",
        "contest_selection_policy_books", "card_run_manifests",
        "card_refresh_policies", "card_revision_pick_changes",
        "card_refresh_revisions",
        "manual_adjustment_policies", "card_adjustment_policy_assignments",
        "contest_pick_adjustment_items", "contest_pick_adjustment_snapshots",
        "postgame_audit_policies", "postgame_audit_key_numbers",
        "postgame_audit_spread_buckets", "postgame_audit_failure_taxonomy",
        "card_postgame_audit_runs", "pick_audit_details",
        "pick_audit_key_number_crossings", "pick_audit_failures",
        "card_postgame_audit_completions",
        "weekly_diagnostic_policies", "weekly_diagnostic_runs",
        "weekly_diagnostic_segments", "weekly_diagnostic_lessons",
        "policy_change_recommendations", "weekly_diagnostic_completions",
        "provider_team_aliases", "provider_ingestion_runs",
        "provider_ingestion_rejections", "provider_ingestion_acceptances",
        "provider_market_snapshots",
        "provider_data_snapshots",
        "weekly_controller_policies", "weekly_controller_policy_sources",
        "weekly_controller_runs", "contest_line_lock_batches",
        "card_source_freshness", "official_card_publications",
        "sportsbook_market_offers", "sportsbook_recommendation_policies",
        "sportsbook_recommendation_evaluations",
        "sportsbook_closing_designations",
        "sportsbook_postgame_audit_runs", "sportsbook_postgame_audit_details",
        "sportsbook_postgame_audit_completions",
        "card_context_source_snapshots",
    }
    assert expected.issubset(tables)
    conn.close()


def test_team_game_stats_has_success_and_havoc_columns(temp_db):
    conn = temp_db.get_connection()
    cols = {r[1] for r in conn.execute("PRAGMA table_info(team_game_stats)")}
    assert {"offense_success_rate", "defense_success_rate", "havoc_rate"}.issubset(cols)
    conn.close()


def test_picks_pick_type_defaults_to_live(temp_db):
    conn = temp_db.get_connection()
    conn.execute("INSERT INTO picks (week, year, created_at) VALUES (1, 2025, '2025-01-01')")
    conn.commit()
    row = conn.execute("SELECT pick_type, status FROM picks").fetchone()
    assert row == ("live", "pending")
    conn.close()


def test_log_run_records_success(temp_db):
    with temp_db.log_run("test_source") as run:
        run["rows_added"] = 7
    conn = temp_db.get_connection()
    row = conn.execute(
        "SELECT source, status, rows_added FROM ingestion_runs WHERE source = 'test_source'"
    ).fetchone()
    assert row == ("test_source", "success", 7)
    conn.close()


def test_log_run_records_error_and_reraises(temp_db):
    import pytest
    with pytest.raises(ValueError):
        with temp_db.log_run("failing_source") as run:
            raise ValueError("boom")
    conn = temp_db.get_connection()
    row = conn.execute(
        "SELECT status, error FROM ingestion_runs WHERE source = 'failing_source'"
    ).fetchone()
    assert row[0] == "error"
    assert "boom" in row[1]
    conn.close()
