import copy
import json
from pathlib import Path

import pytest

from business_entities import run_tuesday_controller
from operations.public_dashboard import (
    PUBLIC_DASHBOARD_ASSETS,
    PUBLIC_DASHBOARD_SCHEMA_VERSION,
    PublicDashboardContext,
    PublicDashboardError,
    build_public_dashboard_payload,
    validate_public_dashboard_payload,
    write_public_dashboard_site,
)
from tests.test_live_sportsbook import _policy as register_sportsbook_policy
from tests.test_weekly_controller import (
    TUESDAY_AT,
    _seed_epa_inputs,
    _seed_games,
    _tuesday_request,
)


ROOT = Path(__file__).resolve().parents[1]


def _draftkings_row(game_id, game, decision, *, freshness="CURRENT"):
    unavailable = decision == "DRAFTKINGS_UNAVAILABLE"
    return {
        "game_id": game_id,
        "game": game,
        "selected_team": None if unavailable else game.split(" at ")[1],
        "selected_side": None if unavailable else "home",
        "decision": decision,
        "bookmaker": "DraftKings",
        "offered_spread": None if unavailable else -3.0,
        "offered_price": None if unavailable else -110,
        "offer_captured_at": None if unavailable else "2026-08-25T14:00:00+00:00",
        "observation_timestamp": "2026-08-25T14:00:00+00:00",
        "model_fair_spread": None if unavailable else -6.0,
        "spread_edge_points": None if unavailable else 3.0,
        "estimated_cover_probability": None if unavailable else 0.58,
        "break_even_probability": None if unavailable else 0.52381,
        "expected_value": None if unavailable else 0.08,
        "stake_units": 0.0 if unavailable or decision != "BET" else 0.75,
        "policy_version": "sportsbook-policy-v1",
        "reason_code": (
            "DRAFTKINGS_SPREAD_NOT_RETURNED"
            if unavailable
            else ("positive_expected_value" if decision == "BET" else "stale_odds")
        ),
        "freshness": freshness,
        "availability_state": "PROVIDER_UNAVAILABLE" if unavailable else "AVAILABLE",
        "provider_capture_attempted": True,
        "provider_ingestion_run_id": None,
        "provider_market_snapshot_id": None,
        "market_offer_id": None,
        "evaluation_id": None,
        "provenance": "not-public",
    }


@pytest.fixture
def dashboard_payload(temp_db):
    conn, lines = _seed_games(temp_db, count=5)
    _seed_epa_inputs(conn, target_count=5)
    result = run_tuesday_controller(conn, _tuesday_request(lines))
    register_sportsbook_policy(conn)
    decisions = (
        ("BET", "CURRENT"),
        ("NO_BET", "CURRENT"),
        ("DRAFTKINGS_UNAVAILABLE", "UNAVAILABLE"),
        ("NO_BET", "STALE"),
        ("BET", "CURRENT"),
    )
    board = tuple(
        _draftkings_row(
            1000 + index,
            f"Away {index} at Home {index}",
            decision,
            freshness=freshness,
        )
        for index, (decision, freshness) in enumerate(decisions, start=1)
    )
    context = PublicDashboardContext(
        season=2026,
        week=1,
        contest_key="splashsports-2026-week-1",
        expected_lined_game_count=5,
        display_timezone="America/Chicago",
        sportsbook_policy_version="sportsbook-policy-v1",
        generated_at=TUESDAY_AT.isoformat(),
        operation="tuesday_lock",
        execution_profile="shadow",
        draftkings_rows=board,
    )
    payload = build_public_dashboard_payload(conn, context)
    assert result.publication.id > 0
    return payload


def test_complete_splashsports_card_confidence_and_exact_top_five(dashboard_payload):
    card = dashboard_payload["splashsports_card"]
    assert card["source"] == "SplashSports"
    assert card["expected_game_count"] == card["published_game_count"] == 5
    assert [game["game_id"] for game in card["games"]] == [1001, 1002, 1003, 1004, 1005]
    assert all(1 <= game["confidence"] <= 5 for game in card["games"])
    assert [game["top_five_rank"] for game in dashboard_payload["top_five"]] == [1, 2, 3, 4, 5]


def test_draftkings_bet_no_bet_unavailable_and_stale_are_explicit(dashboard_payload):
    board = dashboard_payload["draftkings_board"]
    assert board["bookmaker"] == "DraftKings"
    assert board["wager_placement_available"] is False
    by_state = {row["decision"] for row in board["games"]}
    assert by_state == {"BET", "NO BET", "DRAFTKINGS UNAVAILABLE"}
    assert any(row["freshness"] == "STALE" for row in board["games"])
    unavailable = next(row for row in board["games"] if row["decision"] == "DRAFTKINGS UNAVAILABLE")
    assert unavailable["offered_spread"] is None
    assert unavailable["reason"] == "DRAFTKINGS_SPREAD_NOT_RETURNED"
    script = (ROOT / "docs" / "dashboard.js").read_text(encoding="utf-8")
    assert 'badge.textContent = "▲ BET"' in script
    assert 'badge.textContent = "— NO BET"' in script
    assert 'badge.textContent = "! UNAVAILABLE"' in script


def test_contest_and_draftkings_spreads_are_separate_and_books_cannot_masquerade(
    dashboard_payload,
):
    first_contest = dashboard_payload["splashsports_card"]["games"][0]
    first_draftkings = dashboard_payload["draftkings_board"]["games"][0]
    assert first_contest["locked_line_source"] == "SplashSports"
    assert first_contest["locked_home_spread"] == -1.0
    assert first_draftkings["bookmaker"] == "DraftKings"
    assert first_draftkings["offered_spread"] == -3.0

    substituted = copy.deepcopy(dashboard_payload)
    substituted["splashsports_card"]["games"][0]["locked_line_source"] = "DraftKings"
    with pytest.raises(PublicDashboardError, match="cross-substituted"):
        validate_public_dashboard_payload(substituted)

    masquerading = copy.deepcopy(dashboard_payload)
    masquerading["draftkings_board"]["games"][0]["bookmaker"] = "FanDuel"
    with pytest.raises(PublicDashboardError, match="masquerade"):
        validate_public_dashboard_payload(masquerading)


def test_recommendation_changes_and_results_audit_contract_are_rendered(dashboard_payload):
    changed = copy.deepcopy(dashboard_payload)
    changed["draftkings_board"]["games"][0].update(
        changed_since_prior=True,
        change="NO BET → BET · spread -2.5 → -3 · price -105 → -110",
    )
    changed["changes_since_last_refresh"].append(
        {
            "category": "DRAFTKINGS",
            "matchup": "Away 1 at Home 1",
            "change": "NO BET → BET",
            "observed_at": "2026-08-25T14:00:00+00:00",
        }
    )
    changed["results"] = {
        "available": True,
        "profitability_note": "Insufficient evidence for a profitability claim.",
        "games": [
            {
                "game_id": 1001,
                "final_score": "Away 1 20, Home 1 24",
                "splashsports_ats_result": "win",
                "top_five": True,
                "confidence": 5,
                "contest_clv_points": 0.5,
                "hook_outcome": "won_by_hook",
                "key_number_outcome": "key_number_win",
                "backdoor_outcome": "confirmed_not_backdoor",
                "draftkings": {
                    "decision": "BET",
                    "ats_result": "win",
                    "closing_spread": -3.5,
                    "clv_points": 0.5,
                },
            }
        ],
        "weekly_summary": {
            "full_card": {"win_count": 4, "loss_count": 1, "push_count": 0},
            "top_five": {"win_count": 4, "loss_count": 1, "push_count": 0},
            "draftkings": {
                "win_count": 1,
                "loss_count": 0,
                "push_count": 0,
                "realized_profit_units": 0.91,
                "roi_percent": 91.0,
            },
            "segments": [],
            "lessons_learned": [],
        },
    }
    validate_public_dashboard_payload(changed)
    script = (ROOT / "docs" / "dashboard.js").read_text(encoding="utf-8")
    for field in (
        "splashsports_ats_result",
        "closing_spread",
        "clv_points",
        "hook_outcome",
        "key_number_outcome",
        "backdoor_outcome",
        "lessons_learned",
    ):
        assert field in script


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload.update(database_url="postgresql://public:bad@example/db"),
        lambda payload: payload["product"].update(api_key="should-never-publish"),
        lambda payload: payload["product"].update(
            note="Authorization: Bearer should-never-publish"
        ),
        lambda payload: payload.update(raw_provider_payload={"records": ["private"]}),
    ],
)
def test_secret_and_raw_provider_material_is_rejected(dashboard_payload, mutation):
    tainted = copy.deepcopy(dashboard_payload)
    mutation(tainted)
    with pytest.raises(PublicDashboardError):
        validate_public_dashboard_payload(tainted)


def test_failed_generation_cannot_replace_last_good_artifact(dashboard_payload, tmp_path):
    output = tmp_path / "site"
    output.mkdir()
    sentinel = output / "dashboard.json"
    sentinel.write_text("last-good\n", encoding="utf-8")
    with pytest.raises(PublicDashboardError, match="last-good"):
        write_public_dashboard_site(
            payload=dashboard_payload,
            output_directory=output,
            asset_directory=ROOT / "docs",
        )
    assert sentinel.read_text(encoding="utf-8") == "last-good\n"


def test_output_is_deterministic_from_identical_immutable_input(dashboard_payload, tmp_path):
    first = write_public_dashboard_site(
        payload=dashboard_payload,
        output_directory=tmp_path / "first",
        asset_directory=ROOT / "docs",
    )
    second = write_public_dashboard_site(
        payload=dashboard_payload,
        output_directory=tmp_path / "second",
        asset_directory=ROOT / "docs",
    )
    assert {
        path.name: path.read_bytes() for path in first.iterdir()
    } == {path.name: path.read_bytes() for path in second.iterdir()}
    generated = json.loads((first / "dashboard.json").read_text(encoding="utf-8"))
    assert generated["schema_version"] == PUBLIC_DASHBOARD_SCHEMA_VERSION


def test_pages_workflows_are_hosted_least_privilege_manual_and_non_wagering():
    for name in ("v3_production_operations.yml", "v3_shadow_rehearsal.yml"):
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "runs-on: ubuntu-latest" in text
        assert "self-hosted" not in text
        assert "\n  schedule:" not in text
        assert "actions/configure-pages@v5" in text
        assert "actions/upload-pages-artifact@v4" in text
        assert "actions/deploy-pages@v4" in text
        assert "--pages-output" in text
        assert "pages: write" in text
        assert "id-token: write" in text
        assert "contents: write" not in text
        assert "place_wager" not in text
        assert "wager_placement_available" not in text


def test_browser_assets_are_static_self_only_and_credential_free():
    assets = "\n".join(
        (ROOT / "docs" / name).read_text(encoding="utf-8")
        for name in PUBLIC_DASHBOARD_ASSETS
    )
    lowered = assets.casefold()
    assert "connect-src 'self'" in assets
    assert 'fetch("dashboard.json"' in assets
    assert "postgresql://" not in lowered
    assert "postgres://" not in lowered
    assert "cfb_v3_database_url" not in lowered
    assert "cfbd_api_key" not in lowered
    assert "odds_api_key" not in lowered
    assert "http://" not in lowered
    assert "https://" not in lowered


def test_repository_safety_checks_still_pass():
    from scripts.verify_repo_safety import repository_errors

    assert repository_errors(ROOT) == []
