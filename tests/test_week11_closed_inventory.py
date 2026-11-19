from pathlib import Path
import pytest
from scripts import build_week11_formal_audit as audit

def test_future_outputs_are_not_silently_added_to_original_inventory(monkeypatch):
    # A directory scan would admit unrelated future evidence; the closed list never scans.
    def forbidden(*args,**kwargs):raise AssertionError('unbounded inventory scan')
    monkeypatch.setattr(Path,'rglob',forbidden)
    inputs,_=audit.pinned_inputs()
    assert inputs and not any('week12' in name for name in inputs)

def test_changed_original_evidence_is_rejected(monkeypatch):
    inputs,_=audit.pinned_inputs();name=next(iter(inputs));target=audit.ROOT/name
    original=Path.read_bytes
    monkeypatch.setattr(Path,'read_bytes',lambda path: b'corrupt' if path==target else original(path))
    with pytest.raises(ValueError,match='pinned audit input'):audit.pinned_inputs()

def test_original_manifest_cannot_redefine_evidence(monkeypatch):
    original=Path.read_bytes;target=audit.V1/'audit_manifest.json'
    monkeypatch.setattr(Path,'read_bytes',lambda path: b'{}' if path==target else original(path))
    with pytest.raises(ValueError,match='inventory'):audit.pinned_inputs()
