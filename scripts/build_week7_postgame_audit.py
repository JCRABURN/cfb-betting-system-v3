"""Offline Week 7 evaluation; preserve all prospective inputs and both approvals."""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from scripts.capture_week7_postgame_evidence import final_competition
from scripts.week5_postgame_core import grade_ats, grade_total, hook_key_classification, record, spread_bucket

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "outputs/2026-week7-prospective-corrected-v2"
OLD = ROOT / "outputs/2026-week7-prospective"
APPROVAL = ROOT / "outputs/2026-week7-owner-review/OWNER-APPROVED-WEEK-7-CONTEST-FIVE-CORRECTED-V2.json"
OUTPUT = ROOT / "outputs/2026-week7-postgame-audit"
EVIDENCE = OUTPUT / "provider-evidence"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_sha(path: Path) -> str:
    """Code identity ignores checkout EOL conversion; evidence identity does not."""
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed


def frozen_gate() -> dict:
    seal = read_json(FROZEN / "week7_corrected_v2_seal_manifest.json")
    old_seal = read_json(OLD / "week7_initial_seal_manifest.json")
    expected = {FROZEN / name: digest for name, digest in seal["output_files"].items()}
    expected.update({ROOT / name: digest for name, digest in seal["source_files"].items()})
    expected.update({OLD / name: digest for name, digest in old_seal["files"].items()})
    expected[APPROVAL] = "31dd412b3e6c16f3f871e4dc0276c3b2c84c2faae95715ac20eb39d648042568"
    expected[ROOT / "data/cfb.db"] = seal["source_database_sha256"]
    for path, digest in expected.items():
        if sha(path) != digest:
            raise ValueError(f"frozen input checksum mismatch: {path}")
    approved = read_json(APPROVAL)
    if approved["corrected_v2_seal_sha256"] != sha(FROZEN / "week7_corrected_v2_seal_manifest.json"):
        raise ValueError("approval/seal identity mismatch")
    model = read_json(FROZEN / "week7_model_manifest.json")
    card = read_json(FROZEN / "week7_card_manifest.json")
    if not (approved["corrected_locked_card_sha256"] == seal["corrected_locked_card_sha256"]
            == model["locked_line_snapshot_sha256"] == card["ats_card"]["locked_line_snapshot_sha256"]
            == card["totals_card"]["locked_line_snapshot_sha256"]):
        raise ValueError("cross-artifact locked-line identity mismatch")
    pregame = read_json(FROZEN / "provider-evidence/cfbd-week7-games.derived.json")
    if any(g["completed"] or g["homePoints"] is not None or g["awayPoints"] is not None for g in pregame):
        raise ValueError("target-game outcome in pregame inputs")
    first_kickoff = min(instant(g["startDate"]) for g in pregame)
    if instant(seal["sealed_at_utc"]) >= first_kickoff or instant(card["generated_at"]) >= first_kickoff:
        raise ValueError("post-kickoff card or seal")
    with sqlite3.connect((ROOT / "data/cfb.db").resolve().as_uri() + "?mode=ro", uri=True) as conn:
        conn.execute("PRAGMA query_only=ON")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    if integrity != "ok" or fk:
        raise ValueError("source database integrity failure")
    return {"original_seal_files": len(old_seal["files"]), "corrected_output_files": len(seal["output_files"]),
            "corrected_source_files": len(seal["source_files"]), "source_database_sha256": seal["source_database_sha256"],
            "source_database_integrity": integrity, "source_database_foreign_key_violations": fk,
            "locked_card_sha256": seal["corrected_locked_card_sha256"], "owner_approval_sha256": sha(APPROVAL),
            "pregame_result_free": True, "model_versions": seal["model_versions"],
            "model_research_code_commit_sha": seal["model_research_code_commit_sha"],
            "ats_policy_version": card["ats_card"]["policy_version"],
            "protected_sha256": {str(p.relative_to(ROOT)).replace("\\", "/"): h for p, h in expected.items()}}


def load_raw(entry: dict) -> dict:
    raw = gzip.decompress((ROOT / entry["stored_gzip_path"]).read_bytes())
    if hashlib.sha256(raw).hexdigest() != entry["raw_sha256"]:
        raise ValueError("provider evidence checksum mismatch")
    return json.loads(raw)


def unique(rows: list[dict], size: int) -> dict[str, dict]:
    result = {str(row["game_id"]): row for row in rows}
    if len(result) != len(rows) or len(result) != size:
        raise ValueError(f"expected {size} unique games")
    return result


def reconcile(card: list[dict], capture: dict) -> tuple[list[dict], dict]:
    unique(card, 59)
    scoreboard = load_raw(capture["scoreboard"])
    if scoreboard["season"]["year"] != 2026 or scoreboard["week"]["number"] != 7:
        raise ValueError("wrong scoreboard season/week")
    events = {str(e["id"]): e for e in scoreboard["events"]}
    entries = {e["endpoint"].split("event=")[-1]: e for e in capture["summaries"]}
    if len(events) != len(scoreboard["events"]) or len(entries) != len(capture["summaries"]):
        raise ValueError("duplicate provider event")
    if set(entries) != set(row["game_id"] for row in card) or set(entries) - events.keys():
        raise ValueError("missing or unexpected provider game")
    pregame = {str(g["id"]): g for g in read_json(FROZEN / "provider-evidence/cfbd-week7-games.derived.json")}
    if set(pregame) != set(entries):
        raise ValueError("pregame/postgame game sets differ")
    results, summaries = [], {}
    for row in card:
        gid = row["game_id"]
        summary = load_raw(entries[gid])
        comp = final_competition(events[gid], gid, summary=False)
        other = final_competition(summary, gid, summary=True)
        teams = {t["homeAway"]: t for t in comp["competitors"]}
        summary_teams = {t["homeAway"]: t for t in other["competitors"]}
        for side in ("away", "home"):
            if teams[side]["team"]["location"] != row[side]:
                raise ValueError(f"matchup orientation conflict: {gid}")
            if str(teams[side]["id"]) != str(pregame[gid][side + "Id"]) or teams[side]["id"] != summary_teams[side]["id"]:
                raise ValueError(f"provider team identity conflict: {gid}")
            if int(teams[side]["score"]) != int(summary_teams[side]["score"]):
                raise ValueError(f"scoreboard/summary conflict: {gid}")
        if instant(comp["date"]) != instant(pregame[gid]["startDate"]):
            raise ValueError(f"kickoff changed; explicit reconciliation required: {gid}")
        summaries[gid] = summary
        results.append({"game_id": gid, "away": row["away"], "home": row["home"],
                        "away_score": int(teams["away"]["score"]), "home_score": int(teams["home"]["score"]),
                        "kickoff_utc": comp["date"], "neutral_site": pregame[gid]["neutralSite"],
                        "status": "FINAL", "summary_sha256": entries[gid]["raw_sha256"],
                        "source_url": f"https://www.espn.com/college-football/game/_/gameId/{gid}"})
    return results, summaries


def quoted_close(summary: dict, market: str) -> dict:
    # A postgame 'close' field is retained as a provider observation only.
    quotes = [q for q in summary.get("pickcenter", []) if q.get("provider", {}).get("name") == "DraftKings"]
    quote = quotes[0] if len(quotes) == 1 else {}
    value = (quote.get("pointSpread", {}).get("home", {}).get("close", {}).get("line") if market == "ATS"
             else quote.get("total", {}).get("over", {}).get("close", {}).get("line"))
    return {"close_provider": "DraftKings" if quote else "", "postgame_provider_labeled_close": value,
            "qualified_closing_line": None, "qualified_clv": None, "quote_timestamp": None,
            "clv_status": "CLV UNVERIFIABLE", "key_number_crossing": "UNVERIFIABLE_NO_QUALIFIED_CLOSE"}


def summary(rows: list[dict]) -> dict:
    return record(row["result"] for row in rows)


def segments(rows: list[dict], field: str) -> dict:
    groups = defaultdict(list)
    for row in rows:
        groups[str(row[field])].append(row)
    return {label: summary(group) for label, group in sorted(groups.items())}


def projection_metrics(rows: list[dict]) -> dict:
    errors = [r["actual_model_target"] - r["raw_projection"] for r in rows]
    decided = [r for r in rows if r["result"] != "PUSH"]
    return {"n": len(rows), "mae": sum(abs(e) for e in errors) / len(errors),
            "rmse": math.sqrt(sum(e*e for e in errors) / len(errors)), "actual_minus_forecast_mean": sum(errors)/len(errors),
            "brier_descriptive_uncalibrated": sum((r["research_score_not_calibrated"] - (r["result"] == "WIN"))**2 for r in decided)/len(decided),
            "log_loss_descriptive_uncalibrated": -sum(math.log(r["research_score_not_calibrated"] if r["result"] == "WIN" else 1-r["research_score_not_calibrated"]) for r in decided)/len(decided),
            "probability_status": "UNCALIBRATED_RESEARCH_SCORES_NOT_VALIDATED_PROBABILITIES"}


def evaluate() -> tuple[dict, dict[str, list[dict]]]:
    custody = frozen_gate()
    capture = read_json(EVIDENCE / "capture-manifest.json")
    ats = read_csv(FROZEN / "week7_ats_research_full_board.csv")
    totals = read_csv(FROZEN / "week7_totals_research_full_board.csv")
    if set(unique(ats, 59)) != set(unique(totals, 59)):
        raise ValueError("ATS/totals coverage mismatch")
    if {int(r["ats_research_rank"]) for r in ats} != set(range(1, 60)) or {int(r["totals_research_rank"]) for r in totals} != set(range(1, 60)):
        raise ValueError("incomplete frozen research ranks")
    ats.sort(key=lambda row: int(row["ats_research_rank"]))
    totals.sort(key=lambda row: int(row["totals_research_rank"]))
    results, summaries = reconcile(ats, capture)
    result_map = unique(results, 59)
    graded = {}
    for market, board in (("ATS", ats), ("TOTAL", totals)):
        ledger = []
        for row in board:
            gid = row["game_id"]
            final = result_map[gid]
            home_margin = final["home_score"] - final["away_score"]
            total_points = final["home_score"] + final["away_score"]
            if market == "ATS":
                result, margin = grade_ats(row["selected_side"], row["locked_home_spread"], home_margin)
                line, rank = float(row["pick_spread"]), int(row["ats_research_rank"])
                score, projection = float(row["ats_shadow_score_not_calibrated"]), float(row["projected_home_margin"])
                raw_side = "home" if projection + float(row["locked_home_spread"]) >= 0 else "away"
                raw_result = grade_ats(raw_side, row["locked_home_spread"], home_margin)[0]
                boundary = hook_key_classification(line, home_margin, margin)
                extra = {"locked_home_spread": float(row["locked_home_spread"]), "selected_side": row["selected_side"],
                         "favorite_dog": "FAVORITE" if line < 0 else "UNDERDOG" if line > 0 else "PICKEM",
                         "location": "NEUTRAL" if final["neutral_site"] else row["selected_side"].upper(),
                         "spread_bucket": spread_bucket(line), "raw_result": raw_result,
                         "adjustment_points": float(row["context_adjustment_points"]),
                         "final_adjusted_projection": float(row["adjusted_home_margin"]),
                         "governed_top5": row["top_five"], "governed_rank": row["rank"], **boundary}
            else:
                result, margin = grade_total(row["pick"], row["locked_total"], total_points)
                line, rank = float(row["locked_total"]), int(row["totals_research_rank"])
                score, projection = float(row["raw_selected_probability"]), float(row["projected_total"])
                extra = {"actual_total": total_points, "total_bucket": "60+" if line >= 60 else "50-59.5" if line >= 50 else "<50",
                         "raw_result": result, "adjustment_points": 0, "final_adjusted_projection": projection,
                         "hook_classification": "HOOK_WIN" if float(margin) == 0.5 else "HOOK_LOSS" if float(margin) == -0.5 else "NOT_APPLICABLE"}
            confidence = int(row["confidence"])
            if not 1 <= confidence <= 5 or not 0 < score < 1:
                raise ValueError("invalid confidence/research score")
            ledger.append({**final, "market": market, "selection": row["pick"], "locked_line": line,
                           "result": result, "margin_vs_locked": float(margin), "research_rank": rank,
                           "rank_band": "1-5" if rank <= 5 else "6-10" if rank <= 10 else "11-20" if rank <= 20 else "21-40" if rank <= 40 else "41-59",
                           "confidence": confidence, "research_score_not_calibrated": score,
                           "raw_projection": projection, "actual_model_target": home_margin if market == "ATS" else total_points,
                           "backdoor_status": "NOT_EVALUATED_REQUIRES_VALIDATED_SCORING_SEQUENCE",
                           "failure_taxonomy": "FORECAST_SIDE_LOSS" if result == "LOSS" else "NO_SELECTION_LOSS",
                           **extra, **quoted_close(summaries[gid], market)})
        graded[market] = ledger
    lookup = {(r["market"], r["game_id"]): r for board in graded.values() for r in board}
    owner = []
    approval = read_json(APPROVAL)
    for selection in approval["selections"]:
        row = lookup[selection["market"], str(selection["game_id"])].copy()
        if selection["selection"].lower() != row["selection"].lower() or selection["correct_splashsports_locked_line"] != row["locked_line"]:
            raise ValueError("owner selection differs from frozen board")
        if instant(selection["owner_approval_timestamp_utc"]) >= instant(row["kickoff_utc"]):
            raise ValueError("owner approval after kickoff")
        row.update(owner_rank=selection["rank"], human_confidence=selection["human_confidence_1_to_5"])
        owner.append(row)
    unique(owner, 5)
    cohorts = {"owner_approved_five": owner,
               "governed_v28_top5": [r for r in graded["ATS"] if r["governed_top5"] == "True"]}
    for market in ("ATS", "TOTAL"):
        board = graded[market]
        cohorts.update({f"{market.lower()}_full": board,
                        f"{market.lower()}_research_top5": board[:5],
                        f"{market.lower()}_research_top10": board[:10],
                        f"{market.lower()}_research_remaining54": board[5:]})
    mixed = read_csv(FROZEN / "week7_legacy_mixed_research_top5.csv")
    cohorts["legacy_mixed_research_top5"] = [lookup[r["market"], r["game_id"]] for r in mixed]
    human = read_csv(FROZEN / "week7_corrected_human_decision_board.csv")
    cohorts["human_review_candidate_board"] = [lookup[r["market"], r["game_id"]] for r in human]
    if len(cohorts["governed_v28_top5"]) != 5 or len(cohorts["legacy_mixed_research_top5"]) != 5 or len(cohorts["human_review_candidate_board"]) != 12:
        raise ValueError("cohort coverage mismatch")
    diagnostics = {market: {"projection_metrics": projection_metrics(board), "research_rank_bands": segments(board, "rank_band"),
                            "confidence": segments(board, "confidence"), "hooks": segments(board, "hook_classification"),
                            "raw_vs_adjusted": {"raw": record(r["raw_result"] for r in board), "adjusted": summary(board),
                                                "numeric_adjustment_count": sum(r["adjustment_points"] != 0 for r in board)},
                            "qualified_clv_positive": None, "qualified_clv_negative": None}
                   for market, board in graded.items()}
    diagnostics["ATS"].update({field: segments(graded["ATS"], field) for field in ("favorite_dog", "location", "spread_bucket")})
    diagnostics["ATS"]["road_favorites"] = summary([r for r in graded["ATS"] if r["favorite_dog"] == "FAVORITE" and r["location"] == "AWAY"])
    diagnostics["ATS"]["governed_remaining54"] = summary([r for r in graded["ATS"] if r["governed_top5"] != "True"])
    diagnostics["TOTAL"].update({field: segments(graded["TOTAL"], field) for field in ("selection", "total_bucket")})
    diagnostics["owner_human_confidence"] = segments(owner, "human_confidence")
    old_totals = {r["game_id"]: r for r in read_csv(OLD / "week7_totals_full_card.csv")}
    correction_impact = []
    for row in graded["TOTAL"]:
        old = old_totals[row["game_id"]]
        if float(old["locked_total"]) != row["locked_line"]:
            correction_impact.append({"game_id": row["game_id"], "away": row["away"], "home": row["home"],
                                      "original_line_invalidated": old["locked_total"], "original_selection": old["pick"],
                                      "original_result_counterfactual_only": grade_total(old["pick"], old["locked_total"], row["actual_total"])[0],
                                      "corrected_line": row["locked_line"], "corrected_selection": row["selection"],
                                      "corrected_result": row["result"], "actual_total": row["actual_total"]})
    if len(correction_impact) != 6:
        raise ValueError("expected six preserved total corrections")
    if frozen_gate() != custody:
        raise ValueError("frozen input changed during audit")
    data = {"audit_version": "week7-postgame-v1", "grading_status": "COMPLETE_59_ATS_59_TOTALS",
            "formal_audit_status": "INCOMPLETE_CLV_CUSTODY", "qualified_clv_rows": 0,
            "capture_manifest_sha256": sha(EVIDENCE / "capture-manifest.json"), "custody": custody,
            "cohorts": {name: summary(rows) for name, rows in cohorts.items()}, "diagnostics": diagnostics,
            "limitations": ["CLV and key-number crossing unavailable: no timestamp-qualified pre-kickoff close captured.",
                            "Backdoor classifications not evaluated; final scores alone are insufficient.",
                            "Scoreboard and game summaries share ESPN as provider; no full-card independent-provider reconciliation.",
                            "Research scores are uncalibrated; Brier/log loss are descriptive only; one week cannot validate ranking.",
                            "All units and ROI assume hypothetical one-unit risk at -110; no wager prices, stakes, or realized profits are asserted.",
                            "Twelve overlapping cohorts are comparisons, not twelve independent samples; human review is selection, not a numeric adjustment.",
                            "Governed ATS confidence is uniformly 1 with missing uncertainty; its Top 5 is not evidence of reliability discrimination."],
            "policy_action": "HOLD_NO_MODEL_OR_POLICY_CHANGE"}
    membership = [{"cohort": name, "market": r["market"], "game_id": r["game_id"], "selection": r["selection"],
                   "locked_line": r["locked_line"], "result": r["result"], "research_rank": r["research_rank"]}
                  for name, rows in cohorts.items() for r in rows]
    return data, {"week7_final_results.csv": results, "week7_ats_audit.csv": graded["ATS"],
                  "week7_totals_audit.csv": graded["TOTAL"], "week7_owner_approved_five_audit.csv": owner,
                  "week7_cohort_membership.csv": membership, "week7_source_correction_impact.csv": correction_impact}


def report(data: dict, tables: dict) -> str:
    owner = data["cohorts"]["owner_approved_five"]
    lines = ["# 2026 Week 7 evaluation", "", f"Corrected owner-approved contest five: **{owner['win']} wins, {owner['loss']} losses, {owner['push']} pushes ({100*owner['win_rate_ex_push']:.0f}%)**.", "",
             "All 59 locked matchups have final scores; all 59 ATS and 59 totals selections are graded against the corrected immutable contest lines. Formal audit remains **INCOMPLETE — CLV CUSTODY**.", "",
             "## Owner-approved five", "", "| Selection | Final (away–home) | Result | Cover margin | Human confidence |", "|---|---|---|---:|---:|"]
    for r in tables["week7_owner_approved_five_audit.csv"]:
        line = f"{r['selection']} {r['locked_line']:+g}" if r["market"] == "ATS" else f"Colorado State–Texas State UNDER {r['locked_line']:g}"
        lines.append(f"| {line} | {r['away']} {r['away_score']}–{r['home_score']} {r['home']} | {r['result']} | {r['margin_vs_locked']:+g} | {r['human_confidence']}/5 |")
    lines += ["", "## Frozen cohort comparison", "", "| Cohort | W–L–P | Win rate, pushes excluded | Hypothetical units at -110 |", "|---|---:|---:|---:|"]
    for name, s in data["cohorts"].items():
        lines.append(f"| {name} | {s['win']}–{s['loss']}–{s['push']} | {100*s['win_rate_ex_push']:.1f}% | {s['units_minus110']:+.2f} |")
    lines += ["", "## What the results support", "",
              "Indiana was a half-point ATS loss: a four-point defeat against +3.5. Air Force won outright by 10; Nebraska covered in a three-point defeat. Georgia State missed its line by 14.5 points. The Under missed by 23.5 points: 93 actual points versus a 59.345 projection, a 33.655-point forecast error. The original erroneous Under 72.5 would also have lost; correcting it to 69.5 did not change that outcome.", "",
              "Compare each research Top 5/Top 10 only with its own market. The owner five, governed five, legacy mixed five and human candidate board are distinct frozen selections. The legacy mixed score has no validated common probability scale. Human confidence 3 went 1–2; confidence 2 went 1–1. These small samples do not establish calibrated reliability.", "",
              "ATS research Top 5 went 3–2 versus 23–31 for the remaining 54. Totals research Top 5 went 2–3 versus 31–23 for the remaining 54; its Top 10 went 4–6. The totals scores did not concentrate winners at the top this week. ATS rank-band results were also not monotonic. The human five omitted Massachusetts (loss) and Syracuse (win) from the ATS research five and added Georgia State (loss) and Under 69.5 (loss), finishing one win behind that ATS cohort. This is a descriptive comparison, not proof that contextual review helps or hurts generally.", "",
              "## Forecast and ranking diagnostics", ""]
    for market, d in data["diagnostics"].items():
        if market not in {"ATS", "TOTAL"}:
            continue
        m = d["projection_metrics"]
        lines += ["", f"### {market}", "", f"MAE {m['mae']:.3f}; RMSE {m['rmse']:.3f}; actual-minus-forecast mean {m['actual_minus_forecast_mean']:+.3f} points.", "",
                  "| Pregame research rank | W–L–P |", "|---|---:|"]
        for band in ("1-5", "6-10", "11-20", "21-40", "41-59"):
            s = d["research_rank_bands"][band]
            lines.append(f"| {band} | {s['win']}–{s['loss']}–{s['push']} |")
    lines += ["", "Full diagnostics JSON includes favorites/underdogs, home/away/neutral, spread buckets, road favorites, confidence, Top 5 versus remainder, raw versus adjusted results, and explicit missing CLV comparisons. Raw projections and separately frozen numeric adjustments were preserved. No new model run or retrospective rank was generated.", "",
              "## Custody and limitations", ""]
    lines += [f"- {value}" for value in data["limitations"]]
    c = data["custody"]
    lines += ["", f"Verified {c['original_seal_files']} original sealed outputs, {c['corrected_output_files']} corrected sealed outputs and {c['corrected_source_files']} source files; owner-approval hash, pregame timestamps, result-free inputs, distinct game IDs, complete coverage and confidence bounds. Source DB opened read-only: integrity OK, zero foreign-key violations, SHA-256 unchanged before/after.", "",
              "**Decision: hold existing model and policy versions.** CLV custody is incomplete, so this evaluation does not satisfy the completed-audit gate for a policy proposal. One week's results do not establish profitability or justify a new ranking rule.", "",
              "## Reproduce", "", "Run `python -m scripts.build_week7_postgame_audit --verify` offline. The verifier recomputes every table and diagnostic and checks all output hashes. Initial capture is separate: `python -m scripts.capture_week7_postgame_evidence`; it refuses to replace an existing capture. Initial generation: `python -m scripts.build_week7_postgame_audit`.", "",
              "ESPN game URLs and raw-summary SHA-256 values are in the results and per-pick ledgers; compressed exact payloads and request timestamps are in provider-evidence. Postgame provider-labeled closes remain separate observations and never replace contest lines."]
    return "\n".join(lines) + "\n"


def main(verify: bool = False) -> dict:
    data, tables = evaluate()
    report_text = report(data, tables)
    manifest_path = OUTPUT / "week7_postgame_manifest.json"
    if verify:
        manifest = read_json(manifest_path)
        if read_json(OUTPUT / "week7_diagnostics.json") != data:
            raise ValueError("diagnostics replay mismatch")
        for name, rows in tables.items():
            fields = list(dict.fromkeys(k for r in rows for k in r))
            expected = [{k: "" if r.get(k) is None else str(r[k]) for k in fields} for r in rows]
            if read_csv(OUTPUT / name) != expected:
                raise ValueError(f"ledger replay mismatch: {name}")
        if (OUTPUT / "week7_postgame_report.md").read_text(encoding="utf-8") != report_text:
            raise ValueError("report replay mismatch")
        for name, digest in manifest["output_sha256"].items():
            if sha(OUTPUT / name) != digest:
                raise ValueError(f"output checksum mismatch: {name}")
        for name, digest in manifest["audit_code_sha256"].items():
            if source_sha(ROOT / name) != digest:
                raise ValueError(f"audit code changed: {name}")
        return data
    if manifest_path.exists() or any((OUTPUT / n).exists() for n in tables):
        raise FileExistsError("audit already exists; use --verify or create a new version")
    for name, rows in tables.items():
        fields = list(dict.fromkeys(k for r in rows for k in r))
        with (OUTPUT / name).open("x", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    (OUTPUT / "week7_diagnostics.json").write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (OUTPUT / "week7_postgame_report.md").write_text(report_text, encoding="utf-8", newline="\n")
    paths = sorted(p for p in OUTPUT.rglob("*") if p.is_file())
    manifest = {"audit_version": data["audit_version"], "grading_status": data["grading_status"],
                "formal_audit_status": data["formal_audit_status"], "qualified_clv_rows": 0,
                "output_sha256": {p.relative_to(OUTPUT).as_posix(): sha(p) for p in paths},
                "audit_code_hash_encoding": "SHA256_LF_NORMALIZED_CODE_ONLY",
                "audit_code_sha256": {name: source_sha(ROOT / name) for name in (
                    "scripts/build_week7_postgame_audit.py", "scripts/capture_week7_postgame_evidence.py", "scripts/week5_postgame_core.py")}}
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return data


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify", action="store_true", help="replay read-only and check sealed outputs")
    result = main(parser.parse_args().verify)
    print(json.dumps({"grading": result["grading_status"], "formal_audit": result["formal_audit_status"], "cohorts": result["cohorts"]}, indent=2))
