"""Acceptance regressions for overwrite, checksum coverage, and checkout custody."""
import copy
import hashlib
import json
import subprocess
import shutil
import tempfile
from pathlib import Path

import pytest

from scripts import build_week6_postgame_audit as week6
from scripts.replay_compat_v1 import strict


@pytest.mark.parametrize("name", week6.AUDIT_OUTPUTS)
def test_partial_week6_audit_fails_before_any_processing(tmp_path, monkeypatch, name):
    monkeypatch.setattr(week6, "OUTPUT", tmp_path)
    original = b"sealed original\r\n"
    (tmp_path / name).write_bytes(original)
    monkeypatch.setattr(week6, "frozen_gate", lambda: pytest.fail("preflight must run first"))
    with pytest.raises(FileExistsError):
        week6.grade()
    assert {p.name for p in tmp_path.iterdir()} == {name}
    assert (tmp_path / name).read_bytes() == original


@pytest.mark.parametrize("writer,payload", [("write_csv", [{"a": 1}]), ("write_json", {"a": 1}), ("write_text", "new")])
def test_exclusive_writers_reject_destination_created_after_preflight(tmp_path, monkeypatch, writer, payload):
    monkeypatch.setattr(week6, "OUTPUT", tmp_path)
    week6.require_new_outputs()
    path = tmp_path / "raced-output"
    path.write_bytes(b"preserve")
    with pytest.raises(FileExistsError):
        getattr(week6, writer)(path.name, payload)
    assert path.read_bytes() == b"preserve"


def test_week6_new_outputs_and_captured_inputs_are_allowed(tmp_path, monkeypatch):
    monkeypatch.setattr(week6, "OUTPUT", tmp_path)
    evidence = tmp_path / "provider-evidence"
    evidence.mkdir()
    (evidence / "capture-manifest.json").write_bytes(b"preserve")
    week6.require_new_outputs()
    week6.write_csv("new.csv", [{"result": "WIN"}])
    week6.write_json("new.json", {"result": "WIN"})
    week6.write_text("new.md", "report\n")
    assert (tmp_path / "new.csv").read_bytes() == b"result\nWIN\n"
    assert (evidence / "capture-manifest.json").read_bytes() == b"preserve"


@pytest.mark.parametrize("field", ["output_sha256", "audit_code_sha256"])
@pytest.mark.parametrize("kind", ["empty", "missing", "extra", "changed"])
def test_checksum_inventory_cannot_be_redefined(field, kind):
    expected = json.loads(strict.EXPECTED.read_text())
    bad = copy.deepcopy(expected)
    if kind == "empty": bad[field] = {}
    if kind == "missing": bad[field].pop(next(iter(bad[field])))
    if kind == "extra": bad[field]["../unrelated"] = "0" * 64
    if kind == "changed": bad[field][next(iter(bad[field]))] = "0" * 64
    with pytest.raises(ValueError, match="checksum"):
        strict.validate_manifest(bad, expected)


@pytest.mark.parametrize("field,value", [("formal_audit_status", "COMPLETE"), ("grading_status", "INCOMPLETE"),
    ("qualified_clv_rows", 118), ("qualified_clv_rows", False), ("audit_version", "unknown"),
    ("audit_code_hash_encoding", "unqualified")])
def test_contradictory_status_and_identity_are_rejected(field, value):
    expected = json.loads(strict.EXPECTED.read_text())
    bad = copy.deepcopy(expected); bad[field] = value
    with pytest.raises(ValueError, match="status"):
        strict.validate_manifest(bad, expected)


def test_manifest_and_corresponding_file_cannot_both_disappear(tmp_path, monkeypatch):
    expected = json.loads(strict.EXPECTED.read_text())
    bad = copy.deepcopy(expected); bad["output_sha256"].pop(next(iter(bad["output_sha256"])))
    monkeypatch.setattr(strict.replay, "OUTPUT", tmp_path)
    monkeypatch.setattr(strict.replay, "read_json", lambda p: bad)
    with pytest.raises(ValueError, match="coverage"):
        strict.verify()


def test_strict_full_replay_and_exact_current_custody():
    assert strict.verify()["formal_audit_status"] == "INCOMPLETE_CLV_CUSTODY"
    assert strict.verify_research()["exact_custody_checks"] == 419


@pytest.mark.parametrize("autocrlf", ["true", "false"])
def test_git_checkout_reproduces_original_week5_hashes_on_both_eol_settings(tmp_path, autocrlf):
    checks = [r for r in strict.research.custody()["checks"] if r["group"].startswith("week5")]
    names = sorted({r["path"] for r in checks})
    subprocess.run(["git", "-c", f"core.autocrlf={autocrlf}", "checkout-index",
                    "--prefix=" + tmp_path.as_posix() + "/", "--force", "-z", "--stdin"],
                   cwd=strict.ROOT, input=("\0".join(names) + "\0").encode(), check=True)
    for row in checks:
        assert hashlib.sha256((tmp_path / row["path"]).read_bytes()).hexdigest() == row["expected_sha256"]


def test_week6_deterministic_replay_to_new_output_matches_all_original_bytes(monkeypatch):
    original = week6.OUTPUT
    manifest = week6.read_json(original / "week6_postgame_manifest.json")
    with tempfile.TemporaryDirectory(prefix="audit-replay-", dir=week6.ROOT) as directory:
        target = Path(directory)
        shutil.copytree(week6.EVIDENCE, target / "provider-evidence")
        monkeypatch.setattr(week6, "OUTPUT", target)
        week6.grade()
        for name in week6.AUDIT_OUTPUTS[:-1]:
            assert (target / name).read_bytes() == (original / name).read_bytes(), name
        replayed = week6.read_json(target / "week6_postgame_manifest.json")
        prefix = target.relative_to(week6.ROOT).as_posix()
        old_prefix = original.relative_to(week6.ROOT).as_posix()
        replayed["output_sha256"] = {old_prefix + k[len(prefix):]: v for k, v in replayed["output_sha256"].items()}
        assert replayed == manifest


def test_original_expected_manifest_and_historical_git_blobs_are_preserved():
    payload = strict.EXPECTED.read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(payload).hexdigest() == "5192ebeac49e6a999af1af48c78f084b3574882468466e9df4e62195df6031a1"
    expected = json.loads((strict.EXPECTED.parent / "protected_git_blobs.json").read_text())
    # Index comparison catches staged changes; diff catches unstaged content.
    entries = subprocess.check_output(["git", "ls-files", "--stage", "-z"], cwd=strict.ROOT).decode().split("\0")
    indexed = {e.split("\t", 1)[1]: e.split()[1] for e in entries if e}
    assert all(indexed.get(name) == digest for name, digest in expected.items())
    dirty = subprocess.check_output(["git", "diff", "--name-only"], cwd=strict.ROOT, text=True).splitlines()
    assert not set(dirty) & set(expected)


def test_approval_correction_keeps_parent_and_containing_commit_distinct():
    correction = json.loads((strict.ROOT / "docs/evidence/week7-approval-identification-correction.json").read_text())
    original = strict.replay.read_json(strict.replay.APPROVAL)
    assert correction["original_field_value"] == original["approval_source_commit_sha"]
    assert correction["approval_containing_commit"] == "cfbe724fc9687dea24bd50409bcc4a4c2214aec4"
    assert correction["approval_containing_commit"] != correction["original_field_value"]
    assert hashlib.sha256(strict.replay.APPROVAL.read_bytes()).hexdigest() == correction["original_artifact_sha256"]
