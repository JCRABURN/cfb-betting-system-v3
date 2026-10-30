"""Replay and adversarial coverage for the frozen Week 7 evaluation."""

import copy

import pytest

from scripts.replay_compat_v1 import week7 as audit
from scripts import capture_week7_postgame_evidence as capture


def inputs():
    return (audit.read_csv(audit.FROZEN / "week7_ats_full_card.csv"),
            audit.read_json(audit.EVIDENCE / "capture-manifest.json"))


def test_full_replay_and_protected_inputs():
    before = audit.frozen_gate()
    data = audit.main(verify=True)
    assert audit.frozen_gate() == before
    assert (before["original_seal_files"], before["corrected_output_files"], before["corrected_source_files"]) == (89, 96, 14)
    assert len(data["cohorts"]) == 12
    assert data["cohorts"]["ats_full"]["n"] == data["cohorts"]["total_full"]["n"] == 59
    assert (data["cohorts"]["ats_full"]["win"], data["cohorts"]["ats_full"]["loss"]) == (26, 33)
    assert (data["cohorts"]["total_full"]["win"], data["cohorts"]["total_full"]["loss"]) == (33, 26)


def test_corrected_approval_hook_and_total():
    _, tables = audit.evaluate()
    rows = tables["week7_owner_approved_five_audit.csv"]
    assert [r["result"] for r in rows] == ["WIN", "LOSS", "LOSS", "WIN", "LOSS"]
    assert [r["margin_vs_locked"] for r in rows] == [11.5, -0.5, -14.5, 4.5, -23.5]
    assert rows[1]["hook_classification"] == "HOOK_LOSS"
    assert rows[-1]["locked_line"] == 69.5 and rows[-1]["actual_total"] == 93
    changes = tables["week7_source_correction_impact.csv"]
    assert len(changes) == 6
    csu = next(r for r in changes if r["game_id"] == "401860923")
    assert csu["original_result_counterfactual_only"] == csu["corrected_result"] == "LOSS"


@pytest.mark.parametrize("mutate, message", [
    (lambda p: p["header"]["competitions"][0]["competitors"][0].update(score="999"), "scoreboard/summary conflict"),
    (lambda p: p["header"]["competitions"][0]["status"]["type"].update(completed=False), "game not final"),
    (lambda p: p["header"]["competitions"][0]["competitors"][0].update(id="999999"), "team identity conflict"),
    (lambda p: p["header"]["competitions"][0]["competitors"][0].update(score=None), "missing/invalid score"),
])
def test_bad_summary_rejected(monkeypatch, mutate, message):
    card, manifest = inputs()
    target = card[0]["game_id"]
    original = audit.load_raw
    def corrupt(entry):
        payload = original(entry)
        if entry["endpoint"].endswith("event=" + target):
            payload = copy.deepcopy(payload)
            mutate(payload)
        return payload
    monkeypatch.setattr(audit, "load_raw", corrupt)
    with pytest.raises(ValueError, match=message):
        audit.reconcile(card, manifest)


def test_duplicate_or_missing_provider_game_rejected():
    card, manifest = inputs()
    duplicate = copy.deepcopy(manifest)
    duplicate["summaries"].append(duplicate["summaries"][0])
    with pytest.raises(ValueError, match="duplicate provider event"):
        audit.reconcile(card, duplicate)
    missing = copy.deepcopy(manifest)
    missing["summaries"].pop()
    with pytest.raises(ValueError, match="missing or unexpected"):
        audit.reconcile(card, missing)
    with pytest.raises(ValueError, match="59 unique"):
        audit.reconcile(card[:-1] + [card[0]], manifest)


def test_matchup_orientation_rejected():
    card, manifest = inputs()
    card[0]["home"], card[0]["away"] = card[0]["away"], card[0]["home"]
    with pytest.raises(ValueError, match="matchup orientation"):
        audit.reconcile(card, manifest)


def test_payload_checksum_cannot_be_ignored():
    _, manifest = inputs()
    entry = {**manifest["summaries"][0], "raw_sha256": "0" * 64}
    with pytest.raises(ValueError, match="evidence checksum"):
        audit.load_raw(entry)


def test_frozen_checksum_cannot_be_ignored(monkeypatch):
    original = audit.sha
    monkeypatch.setattr(audit, "sha", lambda p: "0" * 64 if p == audit.APPROVAL else original(p))
    with pytest.raises(ValueError, match="frozen input checksum"):
        audit.frozen_gate()


def test_postgame_close_never_qualifies_for_clv():
    _, manifest = inputs()
    payload = audit.load_raw(manifest["summaries"][0])
    for market in ("ATS", "TOTAL"):
        close = audit.quoted_close(payload, market)
        assert close["qualified_clv"] is None
        assert close["qualified_closing_line"] is None
        assert close["quote_timestamp"] is None
    data, _ = audit.evaluate()
    assert data["formal_audit_status"] == "INCOMPLETE_CLV_CUSTODY"
    assert data["policy_action"] == "HOLD_NO_MODEL_OR_POLICY_CHANGE"


def test_capture_and_audit_are_append_only():
    with pytest.raises(FileExistsError, match="already exists"):
        capture.capture()
    with pytest.raises(FileExistsError, match="already exists"):
        audit.main()


def test_grading_pushes_and_sign_conventions():
    assert audit.grade_ats("home", -3, 3)[0] == "PUSH"
    assert audit.grade_ats("away", -3.5, 3)[0] == "WIN"
    assert audit.grade_ats("home", 3.5, -4)[0] == "LOSS"
    assert audit.grade_total("under", 69.5, 93)[0] == "LOSS"
    assert audit.grade_total("over", 44, 44)[0] == "PUSH"


def test_code_eol_normalization_does_not_weaken_evidence_hashes(tmp_path):
    lf, crlf = tmp_path / "lf.py", tmp_path / "crlf.py"
    lf.write_bytes(b"print(1)\n")
    crlf.write_bytes(b"print(1)\r\n")
    assert audit.source_sha(lf) == audit.source_sha(crlf)
    assert audit.sha(lf) != audit.sha(crlf)
