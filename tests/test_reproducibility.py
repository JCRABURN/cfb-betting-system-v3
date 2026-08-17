import hashlib
import json
import sqlite3
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from business_entities import (
    BusinessEntityConflictError,
    ConfidenceRankingPolicy,
    FullCardError,
    FullCardPolicy,
    generate_full_card,
    get_card_run_manifest,
    get_contest_selection_policy,
    list_card_adjustment_history,
    record_manual_adjustment,
    record_model_prediction,
    record_model_run,
    reproduce_card,
)
from business_entities.reproducibility import (
    adjustment_history_sha256,
    register_contest_selection_policy,
)
from contest_lines import create_contest, lock_contest_line
from scripts.reproduce_card import main as reproduce_card_main


POLICY_AT = datetime(2026, 8, 24, 12, tzinfo=timezone.utc)
LOCKED_AT = datetime(2026, 8, 25, 15, tzinfo=timezone.utc)
RUN_AT = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)
PREDICTION_AT = datetime(2026, 8, 25, 15, 45, tzinfo=timezone.utc)
ADJUSTMENT_AT = datetime(2026, 8, 25, 15, 50, tzinfo=timezone.utc)
GENERATED_AT = datetime(2026, 8, 25, 16, tzinfo=timezone.utc)
AFTER_CARD = datetime(2026, 8, 25, 17, tzinfo=timezone.utc)
KICKOFF = "2026-08-29T17:00:00+00:00"

SELECTION_POLICY = FullCardPolicy(
    version="full-card-v1",
    market_books=("draftkings", "fanduel"),
    model_tie_side="away",
    pickem_tiebreak_side="home",
)
RANKING_POLICY = ConfidenceRankingPolicy(
    policy_key="confidence-ranking-v1",
    confidence_policy_version="confidence-v1",
    ranking_policy_version="top-five-v1",
    confidence_5_max_uncertainty=2.0,
    confidence_4_max_uncertainty=4.0,
    confidence_3_max_uncertainty=6.0,
    confidence_2_max_uncertainty=8.0,
    effective_at=POLICY_AT,
    created_by="test",
    provenance="fixture://ranking-policy",
)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_card(temp_db, *, with_adjustment=True):
    conn = temp_db.get_connection()
    contest = create_contest(
        conn,
        contest_key="repro-week-1",
        name="Reproducibility Week 1",
        season=2026,
        week=1,
        source="fixture-contest",
        provenance="fixture://repro-contest",
        created_at=LOCKED_AT,
    )
    run = record_model_run(
        conn,
        run_key="repro-model-run-1",
        model_name="fixture-model",
        model_version="model-v1",
        feature_schema_version="features-v1",
        configuration_version="config-v1",
        code_commit_sha="a" * 40,
        data_snapshot_sha256="b" * 64,
        status="completed",
        provenance="fixture://repro-model-run",
        generated_at=RUN_AT,
    )
    conn.execute(
        "INSERT INTO games "
        "(game_id, season, week, home_team, away_team, start_date) "
        "VALUES (801, 2026, 1, 'Repro Home', 'Repro Away', ?)",
        (KICKOFF,),
    )
    line = lock_contest_line(
        conn,
        contest_id=contest.id,
        game_id=801,
        raw_home_team="Repro Home",
        raw_away_team="Repro Away",
        normalized_home_team="Repro Home",
        normalized_away_team="Repro Away",
        home_spread=-3.0,
        source="fixture-contest",
        source_line_id="repro-line-801",
        provenance="fixture://repro-line/801",
        payload_sha256="c" * 64,
        locked_at=LOCKED_AT,
    ).line
    prediction = record_model_prediction(
        conn,
        prediction_key="repro-prediction-801",
        model_run_id=run.id,
        game_id=801,
        predicted_home_margin=7.0,
        uncertainty_points=2.5,
        entry_locked_line_id=line.id,
        provenance="fixture://repro-prediction/801",
        generated_at=PREDICTION_AT,
    )
    adjustment = None
    if with_adjustment:
        adjustment = record_manual_adjustment(
            conn,
            adjustment_key="repro-adjustment-801-1",
            model_prediction_id=prediction.id,
            category="injury",
            affected_side="home",
            margin_adjustment=-1.0,
            confidence_adjustment=-1,
            reason="Fixture starter unavailable.",
            evidence="Recorded fixture injury report.",
            source="fixture-report",
            author="test",
            provenance="fixture://repro-adjustment/801/1",
            recorded_at=ADJUSTMENT_AT,
        )
    result = generate_full_card(
        conn,
        card_key="repro-card-v1",
        contest_id=contest.id,
        model_run_id=run.id,
        version=1,
        policy=SELECTION_POLICY,
        confidence_policy=RANKING_POLICY,
        created_by="test",
        provenance="fixture://repro-card",
        generated_at=GENERATED_AT,
    )
    conn.commit()
    return conn, run, prediction, adjustment, result


def test_card_manifest_stores_every_run_identifier_and_replays_without_writes(temp_db):
    conn, run, _, adjustment, result = _seed_card(temp_db)
    database = Path(temp_db.DB_PATH)
    manifest = get_card_run_manifest(conn, result.card.id)
    history = list_card_adjustment_history(conn, result.card.id)

    assert manifest.model_run_id == run.id
    assert manifest.model_name == "fixture-model"
    assert manifest.model_version == "model-v1"
    assert manifest.selection_policy_version == "full-card-v1"
    assert manifest.confidence_policy_version == "confidence-v1"
    assert manifest.ranking_policy_version == "top-five-v1"
    assert manifest.feature_schema_version == "features-v1"
    assert manifest.configuration_version == "config-v1"
    assert manifest.code_commit_sha == "a" * 40
    assert manifest.data_snapshot_sha256 == "b" * 64
    assert manifest.locked_line_snapshot_sha256 == result.card.locked_line_snapshot_sha256
    assert manifest.generated_at == GENERATED_AT.isoformat()
    assert history == (adjustment,)
    assert manifest.adjustment_count == 1
    assert manifest.adjustment_history_sha256 == adjustment_history_sha256(history)
    assert result.report.reproducibility_manifest_matches is True

    hash_before = _file_hash(database)
    changes_before = conn.total_changes
    replay = reproduce_card(
        conn,
        card_key=result.card.card_key,
        model_run_key=run.run_key,
    )
    conn.commit()

    assert replay == result
    assert conn.total_changes == changes_before
    assert _file_hash(database) == hash_before
    assert conn.execute("SELECT COUNT(*) FROM card_run_manifests").fetchone()[0] == 1
    conn.close()


def test_cli_reproduces_from_both_keys_on_a_read_only_connection(
    temp_db, capsys
):
    conn, run, _, _, result = _seed_card(temp_db)
    database = Path(temp_db.DB_PATH)
    conn.close()
    hash_before = _file_hash(database)

    exit_code = reproduce_card_main(
        [
            "--database",
            str(database),
            "--card-key",
            result.card.card_key,
            "--model-run-key",
            run.run_key,
        ]
    )
    output = capsys.readouterr()
    payload = json.loads(output.out)

    assert exit_code == 0
    assert output.err == ""
    assert payload["card"]["card_key"] == result.card.card_key
    assert payload["model_run_key"] == run.run_key
    assert payload["manifest"]["adjustment_count"] == 1
    assert len(payload["adjustment_history"]) == 1
    assert payload["verification"]["contest_complete"] is True
    assert payload["verification"]["reproducibility_manifest_matches"] is True
    assert _file_hash(database) == hash_before


def test_cli_rejects_mismatched_run_identifiers_without_mutation(temp_db, capsys):
    conn, _, _, _, result = _seed_card(temp_db)
    database = Path(temp_db.DB_PATH)
    conn.close()
    hash_before = _file_hash(database)

    exit_code = reproduce_card_main(
        [
            "--database",
            str(database),
            "--card-key",
            result.card.card_key,
            "--model-run-key",
            "wrong-run-key",
        ]
    )
    output = capsys.readouterr()

    assert exit_code == 1
    assert output.out == ""
    assert "do not identify one recorded card run" in output.err
    assert _file_hash(database) == hash_before


def test_selection_policy_and_manifest_are_immutable_after_card_generation(temp_db):
    conn, _, _, _, result = _seed_card(temp_db)
    manifest = get_card_run_manifest(conn, result.card.id)
    selection = get_contest_selection_policy(conn, manifest.selection_policy_id)

    with pytest.raises(BusinessEntityConflictError, match="different immutable"):
        register_contest_selection_policy(
            conn,
            replace(SELECTION_POLICY, market_books=("fanduel", "draftkings")),
            effective_at=GENERATED_AT,
            created_by="test",
            provenance="fixture://changed-policy",
        )
    counts_before = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in ("contest_cards", "contest_picks", "card_run_manifests")
    }
    with pytest.raises(FullCardError, match="matching immutable run manifest"):
        generate_full_card(
            conn,
            card_key=result.card.card_key,
            contest_id=result.card.contest_id,
            model_run_id=manifest.model_run_id,
            version=result.card.version,
            policy=replace(
                SELECTION_POLICY,
                market_books=("fanduel", "draftkings"),
            ),
            confidence_policy=RANKING_POLICY,
            created_by=result.card.created_by,
            provenance=result.card.provenance,
            generated_at=GENERATED_AT,
        )
    assert counts_before == {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in counts_before
    }
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE contest_selection_policies SET policy_version = policy_version "
            "WHERE id = ?",
            (selection.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "DELETE FROM contest_selection_policies WHERE id = ?",
            (selection.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="invalid or frozen"):
        conn.execute(
            "INSERT INTO contest_selection_policy_books "
            "(selection_policy_id, priority, book) VALUES (?, 3, 'betmgm')",
            (selection.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "UPDATE card_run_manifests SET model_version = model_version "
            "WHERE card_id = ?",
            (result.card.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        conn.execute(
            "DELETE FROM card_run_manifests WHERE card_id = ?",
            (result.card.id,),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be replaced"):
        conn.execute(
            "INSERT OR REPLACE INTO card_run_manifests "
            "SELECT * FROM card_run_manifests WHERE card_id = ?",
            (result.card.id,),
        )
    conn.close()


def test_frozen_adjustment_history_rejects_backdating_and_ignores_later_context(temp_db):
    conn, run, prediction, _, result = _seed_card(temp_db, with_adjustment=False)
    original_manifest = get_card_run_manifest(conn, result.card.id)
    assert original_manifest.adjustment_count == 0

    with pytest.raises(BusinessEntityConflictError, match="frozen card history"):
        record_manual_adjustment(
            conn,
            adjustment_key="backdated-adjustment",
            model_prediction_id=prediction.id,
            category="weather",
            affected_side="both",
            margin_adjustment=-0.5,
            confidence_adjustment=0,
            reason="Backdated fixture context.",
            evidence="Recorded fixture weather report.",
            source="fixture-report",
            author="test",
            provenance="fixture://backdated-adjustment",
            recorded_at=ADJUSTMENT_AT,
        )

    record_manual_adjustment(
        conn,
        adjustment_key="later-adjustment",
        model_prediction_id=prediction.id,
        contest_pick_id=result.picks[0].id,
        category="weather",
        affected_side="both",
        margin_adjustment=-0.5,
        confidence_adjustment=0,
        reason="Later fixture context.",
        evidence="Recorded later fixture weather report.",
        source="fixture-report",
        author="test",
        provenance="fixture://later-adjustment",
        recorded_at=AFTER_CARD,
    )
    conn.commit()

    assert list_card_adjustment_history(conn, result.card.id) == ()
    assert get_card_run_manifest(conn, result.card.id) == original_manifest
    replay = reproduce_card(
        conn,
        card_key=result.card.card_key,
        model_run_key=run.run_key,
    )
    assert replay == result
    conn.close()
