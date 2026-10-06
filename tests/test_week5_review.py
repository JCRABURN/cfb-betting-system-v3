"""Control checks for the review-only Week 5 decision packet."""

import csv
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "outputs/2026-week5-execution-20260930-v4"
REVIEW = ROOT / "outputs/2026-week5-review-20261001"


def records(path):
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_v4_hash_custody_and_locked_snapshot_unchanged():
    manifest = json.loads((REVIEW / "v4-custody-manifest.json").read_text(encoding="utf-8"))
    assert manifest["v4_pr_head"] == "417b77e7ffbc0ae8e8bda793a9ee3822a2ca8f79"
    assert manifest["file_count"] == len(manifest["v4_files"]) == 91
    for entry in manifest["v4_files"]:
        content = (ROOT / entry["path"]).read_bytes()
        assert hashlib.sha256(content).hexdigest() == entry["sha256"]
        assert len(content) == entry["bytes"]
    archived_db = ROOT / manifest["archived_execution_database_path"]
    assert manifest["archived_execution_database_sha256"] == "e5d00e33e68a7ed2f20160fdb62fd808bf735ac0ee9009b6e643cfb74f197baa"
    # The archived execution DB is deliberately ignored by Git. Verify its bytes
    # when the original local worktree exists; CI checks the recorded custody hash.
    if archived_db.is_file():
        assert hashlib.sha256(archived_db.read_bytes()).hexdigest() == manifest["archived_execution_database_sha256"]
    assert hashlib.sha256((ROOT / "data/cfb.db").read_bytes()).hexdigest() == manifest["source_database_sha256"]
    v4_card = json.loads((V4 / "week5_card_manifest.json").read_text(encoding="utf-8"))
    assert manifest["locked_line_snapshot_sha256"] == v4_card["ats_card"]["locked_line_snapshot_sha256"]
    assert v4_card["ats_report"]["locked_line_snapshot_matches"]


def test_complete_review_and_stale_injuries_not_treated_as_healthy():
    ats = records(V4 / "week5_ats_full_card.csv")
    qb = records(REVIEW / "week5_qb_injury_review.csv")
    market = records(REVIEW / "week5_market_weather_review.csv")
    ids = {row["game_id"] for row in ats}
    assert len(ids) == len(ats) == len(qb) == len(market) == 56
    assert ids == {row["game_id"] for row in qb} == {row["game_id"] for row in market}
    assert {row["confidence"] for row in ats} == {"1"}
    assert all(row["away_qb_status"] in {"CONFIRMED", "PROBABLE", "UNCERTAIN", "UNAVAILABLE"}
               and row["home_qb_status"] in {"CONFIRMED", "PROBABLE", "UNCERTAIN", "UNAVAILABLE"}
               for row in qb)
    assert all(row["material_away_injuries"] and row["material_home_injuries"] for row in qb)
    injuries = json.loads((REVIEW / "provider-evidence/espn-injuries.json").read_text(encoding="utf-8"))
    dates = [item["date"] for team in injuries["injuries"] for item in team["injuries"]]
    assert dates and all(date[:4] in {"2020", "2022"} for date in dates)
    assert any("UNVERIFIED" in row["material_away_injuries"] for row in qb)


def test_market_adversarial_moves_and_decision_separation():
    market = {row["game_id"]: row for row in records(REVIEW / "week5_market_weather_review.csv")}
    assert sum(row["spread_move_flag_ge_1_5"] == "True" for row in market.values()) == 2
    assert sum(row["total_move_flag_ge_2_5"] == "True" for row in market.values()) == 0
    tulsa = market["401862786"]
    assert float(tulsa["locked_home_spread"]) == -1.5
    assert float(tulsa["current_dk_home_spread"]) == 1.5
    assert float(tulsa["ats_selected_locked_advantage"]) == -3.0
    decision = records(REVIEW / "week5_decision_shortlist.csv")
    assert len(decision) == len({row["game_id"] for row in decision}) == 5
    assert all(row["selection_status"] == "WEEK_5_DECISION_SHORTLIST" for row in decision)
    assert all("probability" not in column for column in decision[0])
    assert all(row["data_completeness"] and row["weather_sensitivity"] for row in decision)
    assert "401862786" not in {row["game_id"] for row in decision}
    mississippi_state = next(row for row in decision if row["game_id"] == "401856707")
    assert "FCS" not in mississippi_state["sample_quality_warning"]


def test_all_large_edges_and_original_top_fives_reviewed():
    ats = records(V4 / "week5_ats_full_card.csv")
    expected = {row["game_id"] for row in ats if abs(float(row["home_ats_edge"])) >= 7}
    audited = records(REVIEW / "week5_large_ats_edge_adjudication.csv")
    assert len(expected) == len(audited) == 23
    assert expected == {row["game_id"] for row in audited}
    assert all(row["structural_credibility"] and row["human_review_reason"] for row in audited)
    reviewed = records(REVIEW / "week5_top5_adversarial_review.csv")
    assert len(reviewed) == 15
    assert len({(row["game_id"], row["case"]) for row in reviewed}) == 15
    watchlist = records(REVIEW / "week5_shadow_totals_watchlist.csv")
    assert len(watchlist) == 5
    assert all(row["classification"] in {"RESEARCH SIGNAL", "WEAK SIGNAL", "REJECT"} for row in watchlist)
    assert all("-1.62%" in row["historical_model_status"] for row in watchlist)
