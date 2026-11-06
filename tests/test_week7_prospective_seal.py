"""The prospective seal must reject exact kickoff and never overwrite custody."""

from datetime import datetime

import pytest

from scripts import seal_week7_snapshot as snapshot
from scripts.seal_week7_components import seal as seal_components


def test_seal_cutoff_is_strict_at_exact_kickoff():
    kickoff = snapshot.timestamp("2026-10-13T23:00:00Z")
    snapshot.require_strictly_before("seal", snapshot.timestamp("2026-10-13T22:59:59Z"), kickoff)
    for value in ("2026-10-13T23:00:00Z", "2026-10-13T23:00:01Z"):
        with pytest.raises(ValueError, match="strictly before"):
            snapshot.require_strictly_before("seal", snapshot.timestamp(value), kickoff)


def test_existing_seal_cannot_be_overwritten(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "DEFAULT_OUTPUT", tmp_path)
    target = tmp_path / "week7_initial_seal_manifest.json"
    target.write_text("frozen")
    with pytest.raises(ValueError, match="never overwrite"):
        snapshot.seal(tmp_path, now=datetime.fromisoformat("2026-10-13T22:00:00+00:00"))
    assert target.read_text() == "frozen"


def test_raw_component_custody_is_append_only(tmp_path):
    target = tmp_path / "components.json"
    first = seal_components(target, {"status": "PREGAME_COMPONENT_REPLAY_VERIFIED", "games": []})
    assert len(first) == 64
    with pytest.raises(ValueError, match="never overwrite"):
        seal_components(target, {"games": ["changed"]})
