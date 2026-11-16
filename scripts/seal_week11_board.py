"""Seal and independently replay the Week 11 prospective board without a live API."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/2026-week11-prospective"
SEAL = OUT / "week11_initial_seal_manifest.json"
SOURCE = OUT / "eligible-lines.csv"
METADATA = OUT / "eligible-line-metadata.json"


def read(path: Path): return json.loads(path.read_text(encoding="utf-8"))
def sha(path: Path): return hashlib.sha256(path.read_bytes()).hexdigest()
def instant(value: str): return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
def csv_rows(name: str):
    with (OUT / name).open(encoding="utf-8", newline="") as stream: return list(csv.DictReader(stream))
def require(condition: bool, message: str):
    if not condition: raise ValueError(message)
def close(a, b): return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-8)


def execution_code_hashes(commit: str) -> dict:
    names = subprocess.check_output(["git", "ls-tree", "-r", "--name-only", commit, "models", "business_entities", "ingestion", "contest_lines", "config", "migrations", "operations", "scripts/run_week11_execution.py", "scripts/run_week6_execution.py", "scripts/finalize_week11_card.py", "scripts/seal_week11_components.py", "scripts/prepare_week11_source.py", "scripts/week11_eligibility.py", "scripts/prepare_week11_readiness.py", "scripts/verify_week11_transcription.py"], cwd=ROOT, text=True).splitlines()
    result = {}
    for name in names:
        if not name.endswith((".py", ".json")): continue
        original = subprocess.check_output(["git", "show", f"{commit}:{name}"], cwd=ROOT).replace(b"\r\n", b"\n")
        current = (ROOT / name).read_bytes().replace(b"\r\n", b"\n")
        require(current == original, f"execution code/config changed: {name}")
        result[name] = hashlib.sha256(original).hexdigest()
    return result


def validate(*, sealed_at: str, custody_mode: str = "pregame") -> dict:
    require(custody_mode in {"pregame", "late_capture"}, "unknown custody mode")
    model = read(OUT / "week11_model_manifest.json"); card = read(OUT / "week11_card_manifest.json")
    ingestion = read(OUT / "week11_ingestion_manifest.json"); locked = read(OUT / "week11_locked_line_snapshot.json")
    raw = read(OUT / "week11_raw_model_components.json"); metadata = read(METADATA)
    ats = csv_rows("week11_ats_full_card.csv"); totals = csv_rows("week11_totals_full_card.csv")
    games = {str(g["game_id"]): g for g in raw["games"]}
    lines = {str(g["game_id"]): g for g in locked["lines"]}
    require(len(games) == len(lines) == len(ats) == len(totals) == 64, "64-game coverage required")
    require(set(games) == set(lines) == {r["game_id"] for r in ats} == {r["game_id"] for r in totals}, "game identity mismatch")
    require(sha(SOURCE) == metadata["raw_file_sha256"] == model["locked_source_csv_sha256"], "immutable source changed")
    require(sha(ROOT / "data/cfb.db") == model["source_database_sha256"], "source database changed")
    require(sha(OUT / "week11_raw_model_components.json") == card["raw_model_components_sha256"], "component checksum changed")
    require(model["locked_line_snapshot_sha256"] == ingestion["locked_line_snapshot_sha256"] == locked["locked_line_snapshot_sha256"], "lock identities differ")
    require(raw["code_commit_sha"] == model["code_commit_sha"] == ingestion["code_commit_sha"], "execution code identities differ")
    require(model["manual_adjustment_count"] == 0 and not card["totals_production_eligible"] and not card["legacy_mixed_production_eligible"], "policy status changed")
    earliest = min(instant(g["kickoff_utc"]) for g in games.values())
    if custody_mode == "pregame":
        require(instant(sealed_at) < earliest, "pregame custody timestamp violation")
    require(instant(sealed_at) >= instant(card["generated_at"]), "seal precedes card generation")
    for value in (card["generated_at"], model["generated_at_utc"], raw["generated_at_utc"], locked["locked_at_utc"], metadata["source_received_at_utc"]):
        require(instant(value) < earliest, "pregame custody timestamp violation")
    custody = read(OUT / "source-evidence/screenshot-custody.json")
    require(instant(custody["recovered_at_utc"]) < earliest, "screenshot recovery after kickoff")
    require(len(custody["images"]) == 8, "eight original screenshots required")
    for image in custody["images"]:
        require(sha(OUT / "source-evidence" / image["path"]) == image["sha256"], "screenshot bytes changed")
    from scripts.prepare_week11_source import verify_images
    from scripts import prepare_week11_readiness as readiness
    from scripts.week11_eligibility import verify as verify_eligibility
    verify_images()
    readiness.main(True)
    live = verify_eligibility(ROOT / metadata["eligibility_capture"])
    require(live["upcoming_schedule_only"] == 64 and live["excluded_started_or_elapsed"] == 3, "live eligibility coverage")
    require(metadata["image_custody_status"] == "COMPLETE_8_ORIGINAL_IMAGES_67_VISUALLY_RECONCILED_ROWS", "recovered custody status")
    require(sha(ROOT / metadata["eligibility_capture"] / "capture-manifest.json") == metadata["eligibility_manifest_sha256"], "eligibility capture changed")
    require(instant(live["as_of_utc"]) <= instant(ingestion["generated_at_utc"]) < earliest, "eligibility timing")
    original = read(ROOT / "production-weeks/2026-week11-splashsports-lock-metadata.json")
    require(sha(ROOT / original["production_csv_path"]) == metadata["original_source_sha256"] == original["production_csv_sha256"], "original67 line custody")
    from scripts.verify_week11_transcription import load as load_original
    from scripts.prepare_week11_source import read_csv as source_csv
    all_rows, _, _, mapping = load_original()
    expected_rows = [r for r, m in zip(all_rows, mapping) if m["game_id"] in games]
    require(source_csv(SOURCE) == expected_rows, "eligible source must exactly preserve original rows")
    original_by_game = {m["game_id"]: r for r, m in zip(all_rows, mapping)}
    require(set(games) | {str(g["game_id"]) for g in metadata["excluded_completed_games"]} == set(original_by_game), "all67 original rows accounted")
    for gid, line in lines.items():
        require(float(original_by_game[gid]["Spread"]) == line["home_spread"] and float(original_by_game[gid]["Total"]) == line["locked_total"], "original contest number replaced")
    targets = read(OUT / "provider-evidence/cfbd-week11-games.derived.json")
    require({str(g["id"]) for g in targets} == set(games), "ingested target coverage mismatch")
    require(all(not g["completed"] and g["homePoints"] is None and g["awayPoints"] is None for g in targets), "target outcome contamination")
    require(not ({str(g["game_id"]) for g in metadata["excluded_completed_games"]} & set(games)), "elapsed game entered board")
    fit = raw["totals_model"]["fitted"]
    for game in games.values():
        for side in ("home", "away"):
            stats = game["raw_point_in_time_package"][side + "_stats"]
            require((stats["as_of_season"], stats["as_of_week"]) <= (2026, 10), "feature lookahead")
            estimate = fit[side + "_intercept"] + sum(a*b for a,b in zip(fit[side + "_coefficients"], game["totals"]["features"]))
            require(close(estimate, game["totals"]["projected_" + side + "_points"]), "total component replay mismatch")
        a = game["ats"]; t = game["totals"]
        require(close(a["intercept"] + a["coefficients"][0]*a["epa_differential"], a["projected_home_margin"]), "ATS component replay mismatch")
        require(close(t["projected_total"], t["projected_home_points"] + t["projected_away_points"]), "total sum mismatch")
        for prediction in (a, t): require(instant(prediction["prediction_generated_at"]) < instant(game["kickoff_utc"]), "late prediction")
    for r in ats:
        g = games[r["game_id"]]; line = lines[r["game_id"]]; edge = float(r["projected_home_margin"]) + float(r["locked_home_spread"])
        require(close(r["projected_home_margin"], g["ats"]["projected_home_margin"]) and close(r["locked_home_spread"], line["home_spread"]), "ATS forecast/line changed")
        require(close(edge, r["home_ats_edge"]) and r["selected_side"] == ("home" if edge >= 0 else "away"), "ATS selection replay mismatch")
        require(close(r["pick_spread"], float(r["locked_home_spread"]) * (1 if r["selected_side"] == "home" else -1)), "selected spread orientation mismatch")
        require(r["confidence"] == "1" and close(r["context_adjustment_points"], 0), "governed confidence or adjustments changed")
        require(close(r["ats_shadow_score_not_calibrated"], min(.6, .5+.005*abs(edge))), "ATS score replay mismatch")
    for r in totals:
        g = games[r["game_id"]]; edge = float(r["projected_total"]) - float(r["locked_total"])
        require(close(r["projected_total"], g["totals"]["projected_total"]) and close(r["locked_total"], lines[r["game_id"]]["locked_total"]), "total forecast/line changed")
        probability = .5*(1+math.erf(abs(edge)/float(r["uncertainty_points"])/math.sqrt(2)))
        require(r["pick"] == ("over" if edge >= 0 else "under") and close(r["raw_selected_probability"], probability), "total selection/score mismatch")
        confidence = 1 + sum(probability >= threshold for threshold in (.55, .60, .70, .80))
        require(int(r["confidence"]) == confidence, "total confidence replay mismatch")
    for rows, field, filename in ((ats, "ats_shadow_score_not_calibrated", "week11_ats_research_full_board.csv"), (totals, "raw_selected_probability", "week11_totals_research_full_board.csv")):
        expected = sorted(rows, key=lambda r: (-float(r[field]), int(r["locked_line_id"])))
        require(csv_rows(filename) == expected, "within-market ranking replay mismatch")
    pool = [(float(r["ats_shadow_score_not_calibrated"]), "ATS", int(r["locked_line_id"]), r["game_id"]) for r in ats]
    pool += [(float(r["raw_selected_probability"]), "TOTAL", int(r["locked_line_id"]), r["game_id"]) for r in totals]
    selected = []
    for entry in sorted(pool, key=lambda p: (-p[0], p[1], p[2])):
        if entry[3] not in [p[3] for p in selected]: selected.append(entry)
        if len(selected) == 5: break
    combined = csv_rows("week11_legacy_mixed_research_top5.csv")
    require([(r["market"], r["game_id"]) for r in combined] == [(p[1], p[3]) for p in selected], "combined ranking replay mismatch")
    require(all(r["status"] == "INVALID_FOR_PRODUCTION_RESEARCH_TRACKING_ONLY" for r in combined), "research ranking promoted")
    timing = [{"game_id": gid, "kickoff_utc": game["kickoff_utc"],
               "forecast_timestamp_before_kickoff": True,
               "seal_before_recorded_kickoff": instant(sealed_at) < instant(game["kickoff_utc"]),
               "pregame_external_seal_proven": False}
              for gid, game in sorted(games.items())]
    late = [r["game_id"] for r in timing if not r["seal_before_recorded_kickoff"]]
    return {"status": "LATE_CUSTODY_CAPTURE_NOT_FULL_PREGAME_SEAL" if late else "SEALED_PROSPECTIVE_RESEARCH_BOARD", "eligible_games": 64, "ats_selections": 64,
            "custody_mode": custody_mode, "capture_after_recorded_kickoff_game_ids": late,
            "capture_before_recorded_kickoff_count": 64 - len(late), "game_custody_timing": timing,
            "timestamp_evidence_limit": "Local recorded generation timestamps are not independent proof of pregame external sealing. Recorded kickoff comparison does not refresh live eligibility.",
            "total_selections": 64, "excluded_elapsed_games": len(metadata["excluded_completed_games"]),
            "first_eligible_kickoff_utc": earliest.isoformat(), "model_code_commit": model["code_commit_sha"],
            "clv_status": "INCOMPLETE", "model_policy_change": False, "combined_top5": "UNCALIBRATED_RESEARCH_ONLY"}


def board_markdown() -> str:
    ats = csv_rows("week11_ats_full_card.csv"); total = {r["game_id"]: r for r in csv_rows("week11_totals_full_card.csv")}
    locked = {str(r["game_id"]): r for r in read(OUT / "week11_locked_line_snapshot.json")["lines"]}
    text = ["# Week 11 prospective board — 64 games / 128 selections", "",
        "Generated 2026-11-11 America/Chicago before the first eligible kickoff. Original SplashSports lines preserved. Three elapsed games excluded; no retroactive predictions. v2.8 and existing policies unchanged.", "",
        "Custody limitation: recorded local forecast timestamps precede kickoff, but the first cryptographic custody capture was delayed until November 12. Three Wednesday games had already reached their recorded kickoff. See the seal manifest for actual capture time and per-game timing. No independent pregame external seal is claimed for those games. Their original forecasts remain unchanged.", "",
        "ATS Confidence is uniformly 1 under the existing governed policy. Totals Confidence uses existing uncalibrated research-score buckets. These labels are not validated winning probabilities. Injury, QB and weather review remains pending; no numeric contextual adjustments were applied.", "",
        "## Combined Top 5 — existing research ordering only", "",
        "The scores have no validated common ATS/totals probability scale. This is the existing legacy research list, not an owner-approved final five or sportsbook recommendation.", "",
        "| Rank | Matchup | Research selection | Projection | Confidence | Uncalibrated score |", "|---:|---|---|---:|---:|---:|"]
    for r in csv_rows("week11_legacy_mixed_research_top5.csv"):
        text.append(f"| {r['rank']} | {r['away']} at {r['home']} | {r['pick'].title()} {float(r['locked_line']):g} | {float(r['projection']):.2f} | {r['confidence']}/5 | {float(r['legacy_score_not_comparable']):.4f} |")
    text += ["", "## Complete prospective board", "", "| Kickoff UTC | Matchup | ATS pick | ATS C | Projected home margin | Total pick | Total C | Projected total |", "|---|---|---|---:|---:|---|---:|---:|"]
    for r in sorted(ats, key=lambda r: (locked[r["game_id"]]["source_kickoff_utc"], int(r["locked_line_id"]))):
        t = total[r["game_id"]]
        text.append(f"| {locked[r['game_id']]['source_kickoff_utc']} | {r['away']} at {r['home']} | {r['pick']} {float(r['pick_spread']):+g} | {r['confidence']} | {float(r['projected_home_margin']):+.2f} | {t['pick'].title()} {float(t['locked_total']):g} | {t['confidence']} | {float(t['projected_total']):.2f} |")
    return "\n".join(text) + "\n"


def source_paths() -> list[Path]:
    from scripts import prepare_week11_readiness as readiness
    from scripts.verify_week11_transcription import HASHES
    result = [SOURCE, METADATA] + [ROOT / name for name in HASHES]
    result += sorted((OUT / "source-evidence").iterdir())
    for folder in (readiness.CAPTURE, readiness.SUPPLEMENT, ROOT / read(METADATA)["eligibility_capture"]):
        result += sorted(folder.iterdir())
    result += [readiness.OUT / "schedule.json", readiness.OUT / "resolver-aliases.json", readiness.OUT / "manifest.json"]
    # Earlier cumulative snapshots are immutable dependencies verified by the
    # unchanged historical custody gates and by each derived ingestion hash.
    return result


def main(verify: bool = False, *, late_capture: bool = False) -> dict:
    if verify:
        sealed = read(SEAL)
        require(set(sealed["source_sha256"]) == {p.relative_to(ROOT).as_posix() for p in source_paths()}, "exact source checksum coverage required")
        actual = {p.relative_to(OUT).as_posix() for p in OUT.rglob("*") if p.is_file() and p != SEAL}
        require(actual == set(sealed["output_sha256"]), "exact output checksum coverage required")
        for name, digest in sealed["output_sha256"].items(): require(sha(OUT / name) == digest, f"output checksum mismatch: {name}")
        for name, digest in sealed["source_sha256"].items(): require(sha(ROOT / name) == digest, f"source checksum mismatch: {name}")
        expected_code = set(execution_code_hashes(read(OUT / "week11_model_manifest.json")["code_commit_sha"])) | {"scripts/seal_week11_board.py"}
        require(set(sealed["code_sha256_lf"]) == expected_code, "exact code checksum coverage required")
        for name, digest in sealed["code_sha256_lf"].items():
            require(hashlib.sha256((ROOT / name).read_bytes().replace(b"\r\n", b"\n")).hexdigest() == digest, f"code checksum mismatch: {name}")
        result = validate(sealed_at=sealed["sealed_at_utc"], custody_mode=sealed["custody_mode"])
        require(result == sealed["validation"], "sealed status contradiction")
        require((OUT / "WEEK11_BOARD.md").read_text(encoding="utf-8") == board_markdown(), "board replay mismatch")
        return result
    require(not SEAL.exists() and not (OUT / "WEEK11_BOARD.md").exists(), "seal or board already exists; never overwrite")
    now = datetime.now(timezone.utc).isoformat()
    mode = "late_capture" if late_capture else "pregame"
    result = validate(sealed_at=now, custody_mode=mode)
    code = execution_code_hashes(result["model_code_commit"])
    code["scripts/seal_week11_board.py"] = hashlib.sha256(Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
    with (OUT / "WEEK11_BOARD.md").open("x", encoding="utf-8", newline="\n") as stream: stream.write(board_markdown())
    sources = source_paths()
    payload = {"seal_version": "week11-board-custody-v1", "custody_mode": mode, "sealed_at_utc": now, "validation": result,
        "sealing_code_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "output_sha256": {p.relative_to(OUT).as_posix(): sha(p) for p in sorted(OUT.rglob("*")) if p.is_file()},
        "source_sha256": {p.relative_to(ROOT).as_posix(): sha(p) for p in sources}, "code_sha256_lf": code}
    with SEAL.open("x", encoding="utf-8", newline="\n") as stream: stream.write(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--verify", action="store_true")
    parser.add_argument("--late-capture", action="store_true", help="Record late custody honestly; never qualifies elapsed games as pregame sealed")
    args = parser.parse_args()
    print(json.dumps(main(args.verify, late_capture=args.late_capture), indent=2))
