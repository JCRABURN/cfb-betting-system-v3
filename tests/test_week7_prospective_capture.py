"""Failure-mode checks for timestamped prospective provider custody."""

import hashlib
import json

import pytest

from scripts import capture_week7_core as core


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Session:
    def __init__(self, payloads):
        self.payloads = iter(payloads)

    def get(self, url, *, headers, params, timeout):
        assert headers == {"Authorization": "Bearer TEST-SECRET"}
        assert timeout == 40
        return Response(next(self.payloads))


def test_capture_seals_raw_responses_and_refuses_overwrite(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ROOT", tmp_path)
    monkeypatch.setattr(core, "_key", lambda: "TEST-SECRET")
    monkeypatch.setattr(core.subprocess, "check_output", lambda *a, **k: "a" * 40)
    output = tmp_path / "new-capture"
    result = core.capture(output, session=Session([[{"week": 7}], [{"school": "A"}], [{"epa": 1}]]))
    assert result["status"] == "COMPLETE"
    assert result["code_commit_sha"] == "a" * 40
    assert all(item["requested_at_utc"] <= item["received_at_utc"] for item in result["requests"])
    for item in result["requests"]:
        assert hashlib.sha256((output / item["path"]).read_bytes()).hexdigest() == item["sha256"]
    assert "TEST-SECRET" not in (output / "capture-manifest.json").read_text()
    with pytest.raises(ValueError, match="new directory"):
        core.capture(output, session=Session([]))


def test_incomplete_capture_fails_closed_and_preserves_partial_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "ROOT", tmp_path)
    monkeypatch.setattr(core, "_key", lambda: "TEST-SECRET")
    monkeypatch.setattr(core.subprocess, "check_output", lambda *a, **k: "b" * 40)
    with pytest.raises(ValueError, match="non-list"):
        core.capture(tmp_path / "incomplete", session=Session([[{"week": 7}], {}]))
    manifest = json.loads((tmp_path / "incomplete" / "capture-manifest.json").read_text())
    assert manifest["status"] == "INCOMPLETE"
    assert len(manifest["requests"]) == 1
