import json
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from business_entities import ConfidenceRankingPolicy, FullCardPolicy, ManualAdjustmentPolicy
from business_entities.full_card import generate_full_card
from business_entities.weekly_controller import WeeklyControllerError, run_epa_only_model
from contest_lines import create_contest, lock_contest_line
from migrations.runner import apply_migrations
from migrations.versions import v0023_ats_official_uncertainty_gate as migration_23
from models.epa_uncertainty import load_uncertainty_artifact


ROOT = Path(__file__).resolve().parents[1]
SOURCE_DATABASE = ROOT / "data" / "cfb.db"
MANIFEST = ROOT / "production-weeks" / "2026-week2-splashsports-manifest.json"
LOCKED_AT = datetime(2026, 9, 9, 13, 39, tzinfo=timezone.utc)
GENERATED_AT = datetime(2026, 9, 10, 15, 38, 30, tzinfo=timezone.utc)
POLICY_AT = datetime(2026, 8, 1, tzinfo=timezone.utc)
PRODUCTION_POLICY_PROVENANCE = (
    "proposed-v3-production-policy-registration-requires-owner-approval"
)
SELECTION_POLICY = FullCardPolicy(
    version="production-selection-v1",
    market_books=(),
    model_tie_side="away",
    pickem_tiebreak_side="home",
)
CONFIDENCE_POLICY = ConfidenceRankingPolicy(
    policy_key="production-confidence-ranking-v1",
    confidence_policy_version="production-confidence-v1",
    ranking_policy_version="production-ranking-v1",
    confidence_5_max_uncertainty=2.0,
    confidence_4_max_uncertainty=4.0,
    confidence_3_max_uncertainty=6.0,
    confidence_2_max_uncertainty=8.0,
    effective_at=POLICY_AT,
    created_by="repository-owner",
    provenance=PRODUCTION_POLICY_PROVENANCE,
)
ADJUSTMENT_POLICY = ManualAdjustmentPolicy(
    policy_version="production-adjustment-v1",
    effective_at=POLICY_AT,
    created_by="repository-owner",
    provenance=PRODUCTION_POLICY_PROVENANCE,
)


def _week2_variant(
    tmp_path: Path,
    *,
    name: str,
    order: tuple[int, ...],
    remap_game_ids: bool = False,
    row_padding: int = 0,
) -> dict[str, dict[str, object]]:
    database = tmp_path / f"{name}.db"
    shutil.copy2(SOURCE_DATABASE, database)
    conn = sqlite3.connect(database)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        apply_migrations(conn)
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        lines = payload["lines"]
        game_ids: dict[int, int] = {}
        if remap_game_ids:
            for index, line in enumerate(lines):
                old_id = int(line["game_id"])
                new_id = 910_000_000_000 + (len(lines) - index)
                game = conn.execute(
                    "SELECT season, week, home_team, away_team, start_date "
                    "FROM games WHERE game_id = ?",
                    (old_id,),
                ).fetchone()
                assert game is not None
                conn.execute(
                    "INSERT INTO games "
                    "(game_id, season, week, home_team, away_team, start_date) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (new_id, *game),
                )
                game_ids[index] = new_id
        else:
            game_ids = {index: int(line["game_id"]) for index, line in enumerate(lines)}

        if row_padding:
            padding = create_contest(
                conn,
                contest_key=f"week2-padding-{name}",
                name="Identity padding",
                season=2026,
                week=2,
                source="SplashSports",
                source_contest_id=f"padding-{name}",
                provenance="fixture://identity-padding",
                created_at=LOCKED_AT,
            )
            for index in range(row_padding):
                line = lines[index]
                lock_contest_line(
                    conn,
                    contest_id=padding.id,
                    raw_home_team=line["raw_home_team"],
                    raw_away_team=line["raw_away_team"],
                    normalized_home_team=line["normalized_home_team"],
                    normalized_away_team=line["normalized_away_team"],
                    home_spread=line["home_spread"],
                    total=line["total"],
                    source="SplashSports",
                    source_line_id=f"padding-{index}",
                    payload_sha256="a" * 64,
                    game_id=int(line["game_id"]),
                    provenance="fixture://identity-padding",
                    locked_at=LOCKED_AT,
                )

        contest = create_contest(
            conn,
            contest_key=f"week2-uncertainty-{name}",
            name="Week 2 uncertainty replay",
            season=2026,
            week=2,
            source="SplashSports",
            source_contest_id=f"week2-uncertainty-{name}",
            provenance="fixture://week2-uncertainty-replay",
            created_at=LOCKED_AT,
        )
        for index in order:
            line = lines[index]
            lock_contest_line(
                conn,
                contest_id=contest.id,
                raw_home_team=line["raw_home_team"],
                raw_away_team=line["raw_away_team"],
                normalized_home_team=line["normalized_home_team"],
                normalized_away_team=line["normalized_away_team"],
                home_spread=line["home_spread"],
                total=line["total"],
                source="SplashSports",
                source_line_id=line["source_line_id"],
                payload_sha256="b" * 64,
                game_id=game_ids[index],
                provenance="fixture://week2-uncertainty-replay",
                locked_at=LOCKED_AT,
            )
        model_run = run_epa_only_model(
            conn,
            contest_id=contest.id,
            model_run_key=f"week2-uncertainty-{name}:model",
            code_commit_sha="c" * 40,
            generated_at=GENERATED_AT,
            provenance="fixture://week2-uncertainty-replay",
        )
        card = generate_full_card(
            conn,
            card_key=f"week2-uncertainty-{name}:card",
            contest_id=contest.id,
            model_run_id=model_run.id,
            version=1,
            policy=SELECTION_POLICY,
            confidence_policy=CONFIDENCE_POLICY,
            adjustment_policy=ADJUSTMENT_POLICY,
            created_by="test",
            provenance="fixture://week2-uncertainty-replay",
            generated_at=GENERATED_AT,
        )
        rows: dict[str, dict[str, object]] = {}
        for pick in card.picks:
            row = conn.execute(
                "SELECT line.normalized_away_team, line.normalized_home_team, "
                "line.home_spread, line.id, prediction.predicted_home_margin, "
                "prediction.uncertainty_points "
                "FROM contest_locked_lines AS line "
                "JOIN model_predictions AS prediction ON prediction.id = ? "
                "WHERE line.id = ?",
                (pick.model_prediction_id, pick.locked_line_id),
            ).fetchone()
            assert row is not None
            semantic_key = f"{row[0]} @ {row[1]}"
            rows[semantic_key] = {
                "home_spread": row[2],
                "locked_line_id": row[3],
                "projected_home_margin": row[4],
                "uncertainty_points": row[5],
                "selected_side": pick.selected_side,
                "confidence": pick.confidence,
                "rank": pick.rank,
                "is_top_five": pick.is_top_five,
            }
        conn.commit()
        return rows
    finally:
        conn.close()


def _semantic_output(rows: dict[str, dict[str, object]]) -> dict[str, dict[str, object]]:
    return {
        matchup: {key: value for key, value in row.items() if key != "locked_line_id"}
        for matchup, row in rows.items()
    }


def test_governed_artifact_has_exact_frozen_oos_custody():
    artifact = load_uncertainty_artifact()
    assert artifact.evaluation_seasons == (2020, 2021, 2022, 2023, 2024, 2025)
    assert artifact.eligible_predictions == 3714
    assert artifact.skipped_predictions == 503
    assert artifact.residual_rmse_points == 18.279631175886248
    assert artifact.ledger_sha256 == (
        "7cc76abf69fccb966235c74b38dda4824f974b566b00e75d766439e6ba376d91"
    )
    assert artifact.uncertainty_points(artifact.feature_mean) > 0


def test_exact_week2_top_five_is_order_and_identity_invariant(tmp_path):
    natural = tuple(range(49))
    reversed_order = tuple(reversed(natural))
    shuffled = tuple(natural[::2] + natural[1::2])
    baseline = _week2_variant(tmp_path, name="baseline", order=natural)
    reverse_locks = _week2_variant(
        tmp_path, name="reverse-locks", order=reversed_order
    )
    shuffled_rows = _week2_variant(tmp_path, name="shuffled-rows", order=shuffled)
    remapped_games = _week2_variant(
        tmp_path, name="remapped-games", order=natural, remap_game_ids=True
    )
    shifted_identity = _week2_variant(
        tmp_path, name="shifted-identity", order=natural, row_padding=7
    )

    expected = _semantic_output(baseline)
    assert _semantic_output(reverse_locks) == expected
    assert _semantic_output(shuffled_rows) == expected
    assert _semantic_output(remapped_games) == expected
    assert _semantic_output(shifted_identity) == expected
    assert any(
        baseline[matchup]["locked_line_id"]
        != reverse_locks[matchup]["locked_line_id"]
        for matchup in baseline
    )
    assert any(
        baseline[matchup]["locked_line_id"]
        != shifted_identity[matchup]["locked_line_id"]
        for matchup in baseline
    )
    top_five = {
        matchup for matchup, row in baseline.items() if row["is_top_five"]
    }
    assert len(top_five) == 5
    assert all(row["uncertainty_points"] > 0 for row in baseline.values())


def test_schema_rejects_official_model_backed_top_five_with_null_uncertainty():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        "CREATE TABLE model_predictions (id INTEGER PRIMARY KEY, uncertainty_points REAL);"
        "CREATE TABLE contest_picks ("
        "id INTEGER PRIMARY KEY, card_id INTEGER, model_prediction_id INTEGER, "
        "is_top_five INTEGER);"
        "CREATE TABLE official_card_publications (id INTEGER PRIMARY KEY, card_id INTEGER);"
    )
    migration_23.upgrade(conn)
    conn.execute("INSERT INTO model_predictions VALUES (1, NULL)")
    conn.execute("INSERT INTO contest_picks VALUES (1, 10, 1, 1)")
    with pytest.raises(sqlite3.IntegrityError, match="governed uncertainty"):
        conn.execute("INSERT INTO official_card_publications VALUES (1, 10)")
    conn.execute("UPDATE model_predictions SET uncertainty_points = 18.25 WHERE id = 1")
    conn.execute("INSERT INTO official_card_publications VALUES (1, 10)")
    assert conn.execute(
        "SELECT COUNT(*) FROM official_card_publications"
    ).fetchone()[0] == 1
    conn.close()


def test_missing_governed_artifact_fails_model_run_closed(temp_db, monkeypatch):
    from models import epa_uncertainty

    conn = temp_db.get_connection()
    conn.execute(
        "INSERT INTO games "
        "(game_id, season, week, home_team, away_team, start_date) "
        "VALUES (1, 2026, 2, 'Home', 'Away', '2026-09-12T17:00:00+00:00')"
    )
    contest = create_contest(
        conn,
        contest_key="missing-artifact",
        name="Missing artifact",
        season=2026,
        week=2,
        source="SplashSports",
        provenance="fixture://missing-artifact",
        created_at=LOCKED_AT,
    )
    lock_contest_line(
        conn,
        contest_id=contest.id,
        raw_home_team="Home",
        raw_away_team="Away",
        normalized_home_team="Home",
        normalized_away_team="Away",
        home_spread=-3.5,
        source="SplashSports",
        provenance="fixture://missing-artifact",
        payload_sha256="d" * 64,
        game_id=1,
        locked_at=LOCKED_AT,
    )
    def unavailable():
        raise epa_uncertainty.EpaUncertaintyError("fixture missing")

    monkeypatch.setattr(epa_uncertainty, "load_uncertainty_artifact", unavailable)
    with pytest.raises(WeeklyControllerError, match="failed closed"):
        run_epa_only_model(
            conn,
            contest_id=contest.id,
            model_run_key="missing-artifact:model",
            code_commit_sha="e" * 40,
            generated_at=GENERATED_AT,
            provenance="fixture://missing-artifact",
        )
    assert conn.execute("SELECT COUNT(*) FROM model_runs").fetchone()[0] == 0
    conn.close()
