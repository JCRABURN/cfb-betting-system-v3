"""Fixed seal identity and independently recomputed Week10 selection controls."""
import csv
import json
import shutil
import pytest
from scripts import seal_week10_board as board
from scripts import verify_week10_acceptance as acceptance


def test_original_sealed_week10_read_only_replay():
    result = acceptance.verify()
    assert result["ats_selections"] == result["total_selections"] == 57
    assert result["excluded_elapsed_games"] == 5
    assert result["model_policy_change"] is False


@pytest.mark.parametrize("mutation", ["missing_output", "missing_source", "missing_code", "status"])
def test_seal_declaration_tampering_rejected(tmp_path, monkeypatch, mutation):
    value = board.read(board.SEAL)
    if mutation == "status":
        value["validation"]["clv_status"] = "COMPLETE"
    else:
        key = {"missing_output": "output_sha256", "missing_source": "source_sha256", "missing_code": "code_sha256_lf"}[mutation]
        value[key].pop(next(iter(value[key])))
    altered = tmp_path / "seal.json"
    altered.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(board, "SEAL", altered)
    with pytest.raises(ValueError, match="seal identity changed"):
        acceptance.verify()


@pytest.mark.parametrize("filename,field,delta,message", [
    ("week10_ats_full_card.csv", "locked_home_spread", 1, "ATS forecast/line"),
    ("week10_ats_full_card.csv", "projected_home_margin", 1, "ATS forecast/line"),
    ("week10_ats_full_card.csv", "confidence", 1, "confidence"),
    ("week10_totals_full_card.csv", "locked_total", 1, "total forecast/line"),
    ("week10_totals_full_card.csv", "projected_total", 1, "total forecast/line"),
])
def test_substantive_changes_rejected_even_without_checksum_gate(tmp_path, monkeypatch, filename, field, delta, message):
    seal = board.read(board.SEAL)
    output = tmp_path / "board"
    shutil.copytree(board.OUT, output)
    target = output / filename
    with target.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0][field] = str(float(rows[0][field]) + delta)
    with target.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    monkeypatch.setattr(board, "OUT", output)
    with pytest.raises(ValueError, match=message):
        board.validate(sealed_at=seal["sealed_at_utc"])
