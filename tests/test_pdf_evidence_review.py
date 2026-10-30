import hashlib
import json

import pytest

from scripts import pdf_evidence_review as review


def test_recorded_reading_copies_preserve_sealed_source_bytes():
    assert review.run()["verified_reading_copies"] == 3


@pytest.fixture
def evidence(tmp_path, monkeypatch):
    source = tmp_path / review.SOURCE
    source.mkdir(parents=True)
    raw = b"interior  spacing\tkept  \r\nsecond row\t\r\n\r\n"
    pins = {}
    for school in review.PINS:
        (source / f"{school}-notes-plain.txt").write_bytes(raw)
        pdf = b"unchanged source PDF " + school.encode()
        (source / f"{school}-notes.pdf").write_bytes(pdf)
        pins[school] = (hashlib.sha256(raw).hexdigest(), hashlib.sha256(pdf).hexdigest())
    monkeypatch.setattr(review, "PINS", pins)
    return tmp_path


@pytest.mark.parametrize("suffix", ["plain.txt", "pdf"])
def test_source_tampering_is_rejected_before_any_output(evidence, suffix):
    source = evidence / review.SOURCE / f"fau-notes-{suffix}"
    if suffix == "pdf":
        source = evidence / review.SOURCE / "fau-notes.pdf"
    source.write_bytes(source.read_bytes() + b"altered")
    with pytest.raises(ValueError, match="immutable evidence changed"):
        review.run(evidence, verify=False)
    assert not (evidence / review.OUTPUT).exists()


@pytest.mark.parametrize("kind", ["reading_copy", "manifest", "extra", "missing"])
def test_review_copy_adversaries_fail_closed(evidence, kind):
    review.run(evidence, verify=False)
    folder = evidence / review.OUTPUT
    if kind == "reading_copy":
        (folder / "fau-notes-review.txt").write_bytes(b"invented forecast\n")
    elif kind == "manifest":
        path = folder / "manifest.json"
        data = json.loads(path.read_text())
        data["records"].pop()
        path.write_text(json.dumps(data))
    elif kind == "extra":
        (folder / "unreviewed.txt").write_bytes(b"extra")
    else:
        (folder / "unt-notes-review.txt").unlink()
    with pytest.raises(ValueError):
        review.run(evidence)


def test_existing_partial_version_is_never_overwritten(evidence):
    folder = evidence / review.OUTPUT
    folder.mkdir(parents=True)
    sentinel = folder / "fau-notes-review.txt"
    sentinel.write_bytes(b"original")
    with pytest.raises(FileExistsError):
        review.run(evidence, verify=False)
    assert sentinel.read_bytes() == b"original"


def test_only_documented_whitespace_changes_are_allowed(evidence):
    source = evidence / review.SOURCE / "fau-notes-plain.txt"
    before = source.read_bytes()
    review.run(evidence, verify=False)
    assert source.read_bytes() == before
    assert (evidence / review.OUTPUT / "fau-notes-review.txt").read_bytes() == (
        b"interior  spacing\tkept\nsecond row\n"
    )
    assert review.run(evidence)["original_whitespace_findings_remain_visible"]
