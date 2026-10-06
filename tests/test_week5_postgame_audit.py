"""Adversarial checks for the replayed, locked-line Week 5 postgame audit."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.build_week5_postgame_audit import _score_reconciliation, _csv, _json, EVIDENCE, V4
from scripts import build_week5_postgame_audit as audit_builder
from scripts.week5_postgame_core import (
    classify_late_score, clv_ats, clv_total, grade_ats, grade_total,
    hook_key_classification,
)


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/2026-week5-postgame-audit"


@pytest.mark.parametrize(
    ("side", "home_spread", "home_margin", "expected_result", "expected_margin"),
    (
        ("home", -3.5, 4, "WIN", "0.5"),
        ("home", 3.5, -3, "WIN", "0.5"),
        ("away", -3.5, 3, "WIN", "0.5"),
        ("away", 3.5, -4, "WIN", "0.5"),
        ("home", -3, 3, "PUSH", "0"),
        ("away", -3, 3, "PUSH", "0"),
        ("home", -3.5, 3, "LOSS", "-0.5"),
        ("away", -3.5, 4, "LOSS", "-0.5"),
    ),
)
def test_ats_grading_honors_side_favorite_dog_half_point_and_push(
    side, home_spread, home_margin, expected_result, expected_margin
):
    result, margin = grade_ats(side, home_spread, home_margin)
    assert (result, str(margin)) == (expected_result, expected_margin)


@pytest.mark.parametrize(
    ("pick", "locked", "actual", "expected"),
    (("over", 51.5, 52, "WIN"), ("under", 51.5, 52, "LOSS"),
     ("over", 52, 52, "PUSH"), ("under", 52, 52, "PUSH")),
)
def test_shadow_total_grading_uses_locked_total(pick, locked, actual, expected):
    assert grade_total(pick, locked, actual)[0] == expected


def test_clv_sign_is_from_selected_side_not_home_only():
    assert clv_ats("home", 3.5, 2.5) == 1
    assert clv_ats("away", -3.5, -2.5) == 1
    assert clv_ats("home", 2.5, 3.5) == -1
    assert clv_total("over", 50.5, 52.5) == 2
    assert clv_total("under", 52.5, 50.5) == 2
    assert clv_total("under", 50.5, 52.5) == -2


def test_hook_and_key_number_require_determinative_final_margin():
    win = hook_key_classification(3.5, -3, 0.5)
    assert win["hook_classification"] == "HOOK_WIN"
    assert win["key_number_classification"] == "KEY_NUMBER_WIN"
    assert win["key_number"] == "3"
    loss = hook_key_classification(-7.5, 7, -0.5)
    assert loss["hook_classification"] == "HOOK_LOSS"
    assert loss["key_number_classification"] == "KEY_NUMBER_LOSS"
    irrelevant = hook_key_classification(3.5, -21, -17.5)
    assert irrelevant["hook_classification"] == "NOT_APPLICABLE"
    assert irrelevant["key_number_classification"] == "NOT_APPLICABLE"
    boundary = hook_key_classification(3, -2, 1)
    assert boundary["one_point_boundary"] == "True"


def _play(away, home, period, seconds, text):
    return {"awayScore": away, "homeScore": home, "period": {"number": period},
            "clock": {"value": seconds, "displayValue": "1:00"}, "text": text}


def test_backdoor_requires_scoring_sequence_and_selected_team_loses_game():
    backdoor = [_play(0, 10, 3, 60, "earlier"), _play(7, 10, 4, 60, "late touchdown")]
    assert classify_late_score(backdoor, "away", -3.5, 7, 10)["classification"] == "BACKDOOR_COVER"
    frontdoor = [_play(0, 10, 3, 60, "earlier"), _play(14, 10, 4, 60, "winning touchdown")]
    assert classify_late_score(frontdoor, "away", -3.5, 14, 10)["classification"] == "LATE_FRONTDOOR_COVER"
    assert classify_late_score([], "away", -3.5, 7, 10)["classification"] == "NOT_EVALUATED_NO_PBP"
    early_only = [_play(0, 10, 3, 60, "early touchdown")]
    assert classify_late_score(early_only, "away", -3.5, 0, 10)["classification"] == "NOT_APPLICABLE"
    nondeterminative = [_play(0, 20, 3, 60, "earlier"), _play(7, 20, 4, 60, "late touchdown")]
    assert classify_late_score(nondeterminative, "away", -3.5, 7, 20)["classification"] == "LATE_SCORE_NONDETERMINATIVE"


def test_final_score_capture_fails_closed_on_missing_game():
    card = _csv(V4 / "week5_ats_full_card.csv")
    capture = _json(EVIDENCE / "capture-manifest.json")
    results, _ = _score_reconciliation(card, capture)
    assert len(results) == len({row["game_id"] for row in results}) == 56
    assert all(row["game_status"] == "STATUS_FINAL" and row["official_completion_status"] == "COMPLETED" for row in results)
    missing = dict(capture)
    missing["summaries"] = capture["summaries"][:-1]
    with pytest.raises(ValueError, match="does not cover every locked game"):
        _score_reconciliation(card, missing)


def test_final_score_capture_fails_closed_on_independent_source_conflict(monkeypatch):
    original = audit_builder._load_captured

    def conflicting_ncaa_score(entry):
        payload = original(entry)
        if entry["provider"] == "NCAA_DATA_VIA_HENRYGD_PROXY":
            payload["games"][0]["game"]["home"]["score"] = "999"
        return payload

    monkeypatch.setattr(audit_builder, "_load_captured", conflicting_ncaa_score)
    with pytest.raises(ValueError, match="ESPN/NCAA-derived score or completion conflict"):
        _score_reconciliation(_csv(V4 / "week5_ats_full_card.csv"),
                              _json(EVIDENCE / "capture-manifest.json"))


def test_audit_is_complete_and_never_rewrites_frozen_week5_inputs():
    ats = _csv(OUTPUT / "week5_ats_audit.csv")
    totals = _csv(OUTPUT / "week5_totals_audit.csv")
    decisions = _csv(OUTPUT / "week5_decision_shortlist_audit.csv")
    clv = _csv(OUTPUT / "week5_clv_audit.csv")
    late = _csv(OUTPUT / "week5_late_score_audit.csv")
    results = _csv(OUTPUT / "week5_final_results.csv")
    assert len(ats) == len(totals) == len(results) == 56
    assert len({row["game_id"] for row in ats}) == 56
    assert len(decisions) == 5 and len(clv) == 112
    assert len(late) == 56
    assert len({(row["game_id"], row["market"]) for row in clv}) == 112
    partial_sequence = next(row for row in late if row["game_id"] == "401864514")
    assert partial_sequence["classification"] == "NOT_EVALUATED_NO_PBP"
    assert partial_sequence["scoring_sequence_status"] == "PARTIAL_OR_UNAVAILABLE_FINAL_SCORE_MISMATCH"
    assert {row["game_id"] for row in ats} == {row["game_id"] for row in totals}
    assert all(row["score_source"] and row["score_retrieved_at_utc"] for row in ats + totals)
    assert all(row["clv_points"] == "" and row["clv_direction"] == "UNAVAILABLE" for row in clv)
    for row in ats:
        expected, margin = grade_ats(row["selected_side"], row["locked_home_spread"],
                                     int(row["actual_home_margin"]))
        assert (row["ats_result"], row["ats_grading_margin"]) == (expected, str(margin))
    for row in totals:
        expected, margin = grade_total(row["selected_total"], row["locked_splash_total"],
                                       int(row["actual_total"]))
        assert (row["total_result"], row["total_grading_margin"]) == (expected, str(margin))
    assert [(row["pick"], row["locked_spread"]) for row in decisions] == [
        ("Pittsburgh", "3.5"), ("Mississippi State", "5.5"),
        ("Cincinnati", "7.5"), ("Northwestern", "2.5"), ("Delaware", "7.5"),
    ]
    assert decisions[-1]["pregame_expected_home_qb"] == "Nick Minicucci"
    assert decisions[-1]["postgame_home_passing_leader"] == "EJ Archield Jr."
    assert decisions[-1]["qb_role_comparison"] == "EXPECTED_HOME_QB_NOT_POSTGAME_PASSING_LEADER"
    custody = json.loads((ROOT / "outputs/2026-week5-review-20261001/v4-custody-manifest.json").read_text())
    for item in custody["v4_files"]:
        path = ROOT / item["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    assert hashlib.sha256((ROOT / "data/cfb.db").read_bytes()).hexdigest() == custody["source_database_sha256"]
    manifest = json.loads((OUTPUT / "week5_postgame_manifest.json").read_text())
    assert manifest["locked_games"] == manifest["ats_rows"] == manifest["shadow_totals_rows"] == 56
    assert manifest["qualified_clv_rows"] == 0
    for name, expected_hash in manifest["pregame_review_file_hashes"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected_hash
    for name, expected_hash in manifest["output_sha256"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected_hash
