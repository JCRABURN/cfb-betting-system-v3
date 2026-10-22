"""Adversarial checks for sealed Week 6 postgame grading and custody."""

from __future__ import annotations

import copy
import csv
import json

import pytest

from scripts import build_week6_postgame_audit as audit
from scripts import capture_week6_postgame_evidence as capture


def rows(name: str) -> list[dict[str, str]]:
    with (audit.OUTPUT / name).open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def test_week6_frozen_and_full_card_coverage() -> None:
    frozen = audit.frozen_gate()
    assert frozen["frozen_files_verified"] == 41
    assert frozen["locked_line_snapshot_sha256"] == "f2723f75d94c2c3e4edaadf618cbb71866f3cf2d8b59c62fe48ab84bad6c2c75"
    assert len(rows("week6_ats_audit.csv")) == len(rows("week6_totals_audit.csv")) == 58
    assert len(rows("week6_combined_board_audit.csv")) == 116
    assert {r["game_id"] for r in rows("week6_ats_audit.csv")} == {r["game_id"] for r in rows("week6_totals_audit.csv")}
    assert {r["ats_result"] for r in rows("week6_ats_audit.csv")} <= {"WIN", "LOSS", "PUSH"}
    assert {r["total_result"] for r in rows("week6_totals_audit.csv")} <= {"WIN", "LOSS", "PUSH"}


def test_captured_provider_payloads_cannot_be_silently_overwritten() -> None:
    with pytest.raises(FileExistsError, match="already captured"):
        capture.capture()


def test_reconciliation_rejects_scoreboard_summary_disagreement(monkeypatch: pytest.MonkeyPatch) -> None:
    capture = audit.read_json(audit.EVIDENCE / "capture-manifest.json")
    card = audit.read_csv(audit.FROZEN / "week6_ats_full_card.csv")
    first_id = card[0]["game_id"]
    original = audit.load_raw

    def conflicting_load(entry: dict) -> dict:
        payload = original(entry)
        if entry["endpoint"].endswith(f"event={first_id}"):
            payload = copy.deepcopy(payload)
            payload["header"]["competitions"][0]["competitors"][0]["score"] = "999"
        return payload

    monkeypatch.setattr(audit, "load_raw", conflicting_load)
    with pytest.raises(ValueError, match="scoreboard/summary conflict"):
        audit.reconcile(card, capture)


def test_close_proxy_cannot_be_promoted_to_qualified_clv() -> None:
    clv = rows("week6_clv_audit.csv")
    assert len(clv) == 116
    assert all(row["qualified_clv"] == "" and row["provider_quote_timestamp"] == "" for row in clv)
    assert all(row["status"] == "UNAVAILABLE_NO_TIMESTAMPED_CLOSE" for row in clv)
    manifest = json.loads((audit.OUTPUT / "week6_postgame_manifest.json").read_text(encoding="utf-8"))
    assert manifest["qualified_clv_rows"] == 0
    assert manifest["audit_status"] == "FAIL_INCOMPLETE_CLV_CUSTODY_AND_RAW_COMPONENTS"


def test_distinct_top_fives_and_locked_grading() -> None:
    ats = rows("week6_ats_audit.csv")
    totals = rows("week6_totals_audit.csv")
    official = rows("week6_governed_ats_top5_audit.csv")
    mixed = rows("week6_mixed_shadow_top5_audit.csv")
    decision = rows("week6_decision_review_audit.csv")
    assert [row["ats_result"] for row in official] == ["LOSS"] * 5
    assert sum(row["result"] == "WIN" for row in mixed) == 1
    assert sum(row["result"] == "WIN" for row in decision) == 0
    assert sum(row["ats_result"] == "WIN" for row in ats) == 28
    assert sum(row["total_result"] == "WIN" for row in totals) == 33
    for row in ats:
        result, margin = audit.grade_ats(row["selected_side"], row["locked_home_spread"],
                                         int(row["home_score"]) - int(row["away_score"]))
        assert result == row["ats_result"]
        assert float(margin) == float(row["ats_margin_vs_locked"])
    for row in totals:
        result, margin = audit.grade_total(row["selection"].lower(), row["locked_total"],
                                           int(row["away_score"]) + int(row["home_score"]))
        assert result == row["total_result"]
        assert float(margin) == float(row["total_margin_vs_locked"])


def test_postgame_manifest_covers_current_output_hashes() -> None:
    manifest = json.loads((audit.OUTPUT / "week6_postgame_manifest.json").read_text(encoding="utf-8"))
    for relative, digest in manifest["output_sha256"].items():
        assert audit.sha(audit.ROOT / relative) == digest, relative


def test_calibration_tail_matches_exact_two_coin_case() -> None:
    assert audit.poisson_binomial_lower_tail([0.5, 0.5], 0) == 0.25
    assert audit.poisson_binomial_lower_tail([0.5, 0.5], 1) == 0.75
