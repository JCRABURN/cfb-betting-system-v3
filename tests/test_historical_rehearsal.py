import hashlib
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from business_entities import (
    HistoricalRehearsalError,
    run_historical_rehearsal,
)
from scripts.run_historical_rehearsal import main as rehearsal_main


ROOT = Path(__file__).resolve().parents[1]
AUTHORITATIVE_DATABASE = ROOT / "data" / "cfb.db"
FIXTURE_COMMIT_SHA = "a" * 40


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture(scope="module")
def rehearsal_report():
    return run_historical_rehearsal(
        AUTHORITATIVE_DATABASE,
        code_commit_sha=FIXTURE_COMMIT_SHA,
    )


def test_complete_historical_lifecycle_satisfies_every_acceptance_gate(
    rehearsal_report,
):
    report = rehearsal_report

    assert report.successful is True
    assert (report.season, report.week) == (2024, 15)
    assert len(report.game_ids) == 6
    assert report.target_scores_hidden_during_forecast is True
    assert report.official_publication_count == 5
    assert tuple(version.card_version for version in report.card_versions) == (
        1,
        2,
        3,
        4,
        5,
    )
    assert all(version.pick_count == 6 for version in report.card_versions)
    assert all(version.top_five_count == 5 for version in report.card_versions)
    assert all(version.fallback_pick_count == 0 for version in report.card_versions)
    assert all(version.source_freshness_count == 5 for version in report.card_versions)
    assert all(version.all_sources_current for version in report.card_versions)
    assert all(version.model_name == "epa_only" for version in report.card_versions)
    assert all(
        version.model_version == "epa-only-linear-v1"
        and version.feature_schema_version == "epa-differential-v1"
        and version.configuration_version == "walk-forward-prior-seasons-v1"
        for version in report.card_versions
    )
    assert all(
        version.selection_policy_version
        == "historical-rehearsal-v1-selection-policy"
        for version in report.card_versions
    )
    assert all(version.reproduced_exactly for version in report.card_versions)
    assert report.revision_count == 4
    assert report.revision_pick_change_count == 24
    assert report.locked_lines_unchanged is True
    assert report.finalization_method == "latest_valid_saturday_publication"
    assert report.final_pick_count == report.audited_pick_count == 6
    assert report.final_top_five_count == 5
    assert report.audit_complete is True
    assert (
        report.audit_win_count,
        report.audit_loss_count,
        report.audit_push_count,
    ) == (3, 3, 0)
    assert report.clv_graded_count == 6
    assert report.hook_classified_count == 6
    assert report.key_number_classified_count == 6
    assert report.integrity_check == "ok"
    assert report.foreign_key_violation_count == 0


def test_adjustment_diagnostics_and_policy_recommendations_remain_auditable(
    rehearsal_report,
):
    report = rehearsal_report
    adjusted = next(pick for pick in report.picks if pick.game_id == 401673464)

    assert all(pick.selected_side in ("home", "away") for pick in report.picks)
    assert all(1 <= pick.confidence <= 5 for pick in report.picks)
    assert {pick.rank for pick in report.picks if pick.is_top_five} == {1, 2, 3, 4, 5}
    assert report.manual_adjustment_count == 1
    assert report.manual_adjustment_effects == ("side_flip_helped",)
    assert adjusted.raw_model_margin != adjusted.adjusted_model_margin
    assert adjusted.manual_adjustment_effect == "side_flip_helped"
    assert report.diagnostics_complete is True
    assert report.diagnostic_segment_count == 26
    assert report.lesson_count == len(report.lessons) == 4
    assert report.recommendation_count == len(report.policy_recommendations) == 4
    assert report.candidate_recommendation_count == 0
    assert all(
        recommendation.status == "hold_insufficient_evidence"
        for recommendation in report.policy_recommendations
    )
    assert all(
        recommendation.recommended_value == recommendation.current_value
        and recommendation.owner_approval_required is False
        for recommendation in report.policy_recommendations
    )
    assert report.policy_versions_unchanged is True


def test_rehearsal_command_is_reproducible_and_never_mutates_source(
    rehearsal_report, capsys
):
    before = _file_hash(AUTHORITATIVE_DATABASE)

    exit_code = rehearsal_main(
        [
            "--database",
            str(AUTHORITATIVE_DATABASE),
            "--code-commit-sha",
            FIXTURE_COMMIT_SHA,
        ]
    )
    output = capsys.readouterr()
    payload = json.loads(output.out)

    assert exit_code == 0
    assert output.err == ""
    assert payload["rehearsal_sha256"] == rehearsal_report.rehearsal_sha256
    assert payload["successful"] is True
    assert payload["source_database_unchanged"] is True
    assert payload["live_api_calls"] == 0
    assert payload["authoritative_database_rows_changed"] == 0
    assert _file_hash(AUTHORITATIVE_DATABASE) == before


def test_missing_archived_closing_line_fails_before_rehearsal_mutation(tmp_path):
    database = tmp_path / "missing-closing.db"
    shutil.copy2(AUTHORITATIVE_DATABASE, database)
    conn = sqlite3.connect(database)
    conn.execute(
        "DELETE FROM betting_lines WHERE game_id = 401673463 "
        "AND line_type = 'closing'"
    )
    conn.commit()
    conn.close()
    before = _file_hash(database)

    with pytest.raises(HistoricalRehearsalError, match="no archived closing line"):
        run_historical_rehearsal(database, code_commit_sha=FIXTURE_COMMIT_SHA)

    assert _file_hash(database) == before
