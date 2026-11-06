"""Offline Week 8 evaluation; preserve all prospective inputs and both approvals."""

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

from scripts.capture_week8_postgame_evidence import final_competition
from scripts.week5_postgame_core import grade_ats, grade_total, hook_key_classification, record, spread_bucket

ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "outputs/2026-week8-prospective-v2"
OLD = ROOT / "outputs/2026-week8-prospective"
APPROVAL = ROOT / "outputs/2026-week8-owner-review/OWNER-APPROVED-WEEK-8-CONTEST-FIVE-CORRECTED-V2.json"
OUTPUT = ROOT / "outputs/2026-week8-postgame-audit"
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
    from scripts import seal_week8_board as board
    expected_seal = "355e72a9a07ef3fc48891519655ab52ccd5c4283add5cd5a39f29788cf1beba2"
    if sha(board.SEAL) != expected_seal:
        raise ValueError("Week 8 original seal changed")
    board.main(verify=True)
    seal = read_json(board.SEAL)
    protected = {f"outputs/2026-week8-prospective-v2/{p}": h for p,h in seal["output_sha256"].items()}
    protected.update(seal["source_sha256"])
    protected[board.SEAL.relative_to(ROOT).as_posix()] = expected_seal
    protected["data/cfb.db"] = "09d0bcda684356001bacf8bc9e42939add56b053f405564d9be924e39c0cf842"
    for name, digest in protected.items():
        if sha(ROOT/name) != digest: raise ValueError("protected artifact changed: " + name)
    with sqlite3.connect((ROOT/"data/cfb.db").resolve().as_uri()+"?mode=ro",uri=True) as conn:
        if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("database integrity failure")
    return {"protected_sha256": protected, "original_seal_sha256": expected_seal,
            "model_code_commit": seal["validation"]["model_code_commit"],
            "owner_approval_status": "NO_RECORDED_APPROVAL_ARTIFACT;NOT_INVENTED",
            "source_database_integrity": "ok", "source_database_foreign_key_violations": 0}


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
    unique(card, 52)
    scoreboard = load_raw(capture["scoreboard"])
    if scoreboard["season"]["year"] != 2026 or scoreboard["week"]["number"] != 8:
        raise ValueError("wrong scoreboard season/week")
    events = {str(e["id"]): e for e in scoreboard["events"]}
    entries = {e["endpoint"].split("event=")[-1]: e for e in capture["summaries"]}
    if len(events) != len(scoreboard["events"]) or len(entries) != len(capture["summaries"]):
        raise ValueError("duplicate provider event")
    if set(entries) != set(row["game_id"] for row in card) or set(entries) - events.keys():
        raise ValueError("missing or unexpected provider game")
    pregame = {str(g["id"]): g for g in read_json(FROZEN / "provider-evidence/cfbd-week8-games.derived.json")}
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
            corrections = read_json(EVIDENCE / "schedule-reconciliation.json")
            match = [x for x in corrections if x["game_id"] == gid and x["frozen_scheduled_kickoff"] == pregame[gid]["startDate"] and x["postgame_espn_kickoff"] == comp["date"]]
            if len(match) != 1 or instant(read_json(FROZEN/"week8_initial_seal_manifest.json")["sealed_at_utc"]) >= min(instant(comp["date"]), instant(pregame[gid]["startDate"])):
                raise ValueError("unresolved kickoff discrepancy")
        summaries[gid] = summary
        results.append({"game_id": gid, "away": row["away"], "home": row["home"],
                        "away_score": int(teams["away"]["score"]), "home_score": int(teams["home"]["score"]),
                        "kickoff_utc": comp["date"], "neutral_site": pregame[gid]["neutralSite"],
                        "status": "FINAL", "summary_sha256": entries[gid]["raw_sha256"],
                        "source_url": f"https://www.espn.com/college-football/game/_/gameId/{gid}"})
    cfbd_manifest = read_json(EVIDENCE / "cfbd-capture-manifest.json")
    cfbd_item = next(x for x in cfbd_manifest["requests"] if x["name"] == "cfbd-2026-games")
    if sha(EVIDENCE / "cfbd-2026-games.json") != cfbd_item["sha256"]:
        raise ValueError("CFBD evidence checksum mismatch")
    cfbd = {str(g["id"]): g for g in read_json(EVIDENCE / "cfbd-2026-games.json")}
    for row in results:
        g=cfbd[row["game_id"]]
        if g["week"] != 8 or not g["completed"] or g["homePoints"] != row["home_score"] or g["awayPoints"] != row["away_score"]:
            raise ValueError("CFBD/ESPN final score disagreement")
        for side in ("home", "away"):
            if str(g[side+"Id"]) != str(pregame[row["game_id"]][side+"Id"]): raise ValueError("CFBD identity mismatch")
    return results, summaries


def quoted_close(summary: dict, market: str) -> dict:
    # A postgame 'close' field is retained as a provider observation only.
    quotes = [q for q in summary.get("pickcenter", []) if q.get("provider", {}).get("name") == "DraftKings"]
    quote = quotes[0] if len(quotes) == 1 else {}
    value = (quote.get("pointSpread", {}).get("home", {}).get("close", {}).get("line") if market == "ATS"
             else quote.get("total", {}).get("over", {}).get("close", {}).get("line"))
    return {"close_provider": "DraftKings" if quote else "", "postgame_provider_labeled_close": value,
            "qualified_closing_line": None, "qualified_clv": None, "quote_timestamp": None,
            "clv_status": "INCOMPLETE", "key_number_crossing": "UNVERIFIABLE_NO_QUALIFIED_CLOSE"}


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
    ats = read_csv(FROZEN / "week8_ats_research_full_board.csv")
    totals = read_csv(FROZEN / "week8_totals_research_full_board.csv")
    if set(unique(ats, 52)) != set(unique(totals, 52)):
        raise ValueError("ATS/totals coverage mismatch")
    if {int(r["ats_research_rank"]) for r in ats} != set(range(1, 53)) or {int(r["totals_research_rank"]) for r in totals} != set(range(1, 53)):
        raise ValueError("incomplete frozen research ranks")
    ats.sort(key=lambda row: int(row["ats_research_rank"]))
    totals.sort(key=lambda row: int(row["totals_research_rank"]))
    results, summaries = reconcile(ats, capture)
    result_map = unique(results, 52)
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
                extra = {"actual_total": total_points, "total_bucket": "60+" if line >= 60 else "50-52.5" if line >= 50 else "<50",
                         "raw_result": result, "adjustment_points": 0, "final_adjusted_projection": projection,
                         "hook_classification": "HOOK_WIN" if float(margin) == 0.5 else "HOOK_LOSS" if float(margin) == -0.5 else "NOT_APPLICABLE"}
            confidence = int(row["confidence"])
            if not 1 <= confidence <= 5 or not 0 < score < 1:
                raise ValueError("invalid confidence/research score")
            ledger.append({**final, "market": market, "selection": row["pick"], "locked_line": line,
                           "result": result, "margin_vs_locked": float(margin), "research_rank": rank,
                           "rank_band": "1-5" if rank <= 5 else "6-10" if rank <= 10 else "11-20" if rank <= 20 else "21-40" if rank <= 40 else "41-52",
                           "confidence": confidence, "research_score_not_calibrated": score,
                           "raw_projection": projection, "actual_model_target": home_margin if market == "ATS" else total_points,
                           "backdoor_status": "NOT_EVALUATED_REQUIRES_VALIDATED_SCORING_SEQUENCE",
                           "forecast_error_actual_minus_predicted": (home_margin if market == "ATS" else total_points)-projection,
                           "hypothetical_units_minus110": 10/11 if result == "WIN" else -1 if result == "LOSS" else 0,
                           "failure_taxonomy": "FORECAST_SIDE_LOSS" if result == "LOSS" else "NO_SELECTION_LOSS",
                           **extra, **quoted_close(summaries[gid], market)})
        graded[market] = ledger
    lookup = {(r["market"], r["game_id"]): r for board in graded.values() for r in board}
    cohorts = {"governed_v28_top5": [r for r in graded["ATS"] if r["governed_top5"] == "True"]}
    for market in ("ATS", "TOTAL"):
        board = graded[market]
        cohorts.update({f"{market.lower()}_full": board,
                        f"{market.lower()}_research_top5": board[:5],
                        f"{market.lower()}_research_top10": board[:10],
                        f"{market.lower()}_research_remaining47": board[5:]})
    mixed = read_csv(FROZEN / "week8_legacy_mixed_research_top5.csv")
    cohorts["legacy_mixed_research_top5"] = [lookup[r["market"], r["game_id"]] for r in mixed]
    human = read_csv(FROZEN / "week8_human_review_shortlist.csv")
    cohorts["human_review_candidate_board"] = [lookup[r["market"], r["game_id"]] for r in human]
    if len(cohorts["governed_v28_top5"]) != 5 or len(cohorts["legacy_mixed_research_top5"]) != 5 or len(cohorts["human_review_candidate_board"]) != 10:
        raise ValueError("cohort coverage mismatch")
    diagnostics = {market: {"projection_metrics": projection_metrics(board), "research_rank_bands": segments(board, "rank_band"),
                            "confidence": segments(board, "confidence"), "hooks": segments(board, "hook_classification"),
                            "raw_vs_adjusted": {"raw": record(r["raw_result"] for r in board), "adjusted": summary(board),
                                                "numeric_adjustment_count": sum(r["adjustment_points"] != 0 for r in board)},
                            "qualified_clv_positive": None, "qualified_clv_negative": None}
                   for market, board in graded.items()}
    diagnostics["ATS"].update({field: segments(graded["ATS"], field) for field in ("favorite_dog", "location", "spread_bucket")})
    diagnostics["ATS"]["road_favorites"] = summary([r for r in graded["ATS"] if r["favorite_dog"] == "FAVORITE" and r["location"] == "AWAY"])
    diagnostics["ATS"]["governed_remaining47"] = summary([r for r in graded["ATS"] if r["governed_top5"] != "True"])
    diagnostics["TOTAL"].update({field: segments(graded["TOTAL"], field) for field in ("selection", "total_bucket")})
    if frozen_gate() != custody:
        raise ValueError("frozen input changed during audit")
    data = {"audit_version": "week8-postgame-v1", "grading_status": "COMPLETE_52_ATS_52_TOTALS",
            "formal_audit_status": "GRADING_AND_CUSTODY_COMPLETE;CLV_INCOMPLETE;POLICY_UNCHANGED", "qualified_clv_rows": 0,
            "capture_manifest_sha256": sha(EVIDENCE / "capture-manifest.json"), "custody": custody,
            "cohorts": {name: summary(rows) for name, rows in cohorts.items()}, "diagnostics": diagnostics,
            "limitations": ["CLV and key-number crossing unavailable: no timestamp-qualified pre-kickoff close captured.",
                            "Backdoor classifications not evaluated; final scores alone are insufficient.",
                            "Final scores reconcile ESPN scoreboard and summaries against separately captured CFBD scores.",
                            "Research scores are uncalibrated; Brier/log loss are descriptive only; one week cannot validate ranking.",
                            "All units and ROI assume hypothetical one-unit risk at -110; no wager prices, stakes, or realized profits are asserted.",
                            "Overlapping cohorts are comparisons, not independent samples. No Week 8 owner approval or human substitution record exists.",
                            "Governed ATS confidence is uniformly 1 with missing uncertainty; its Top 5 is not evidence of reliability discrimination."],
            "policy_action": "HOLD_NO_MODEL_OR_POLICY_CHANGE"}
    membership = [{"cohort": name, "market": r["market"], "game_id": r["game_id"], "selection": r["selection"],
                   "locked_line": r["locked_line"], "result": r["result"], "research_rank": r["research_rank"]}
                  for name, rows in cohorts.items() for r in rows]
    return data, {"week8_final_results.csv": results, "week8_ats_audit.csv": graded["ATS"],
                  "week8_totals_audit.csv": graded["TOTAL"], 
                  "week8_cohort_membership.csv": membership}


def report(data: dict, tables: dict) -> str:
    lines=["# Week 8 postgame audit", "", "All 52 ATS and 52 totals picks graded from the original PR #42 seal. ESPN scoreboard and game summaries reconcile with separately captured CFBD final scores. No forecast was regenerated. CLV is INCOMPLETE; missing historical closes do not block unrelated integrity repairs.", "", "No recorded owner-approved Week 8 five exists. The unfinished contextual review is not an approved card or a pregame substitution record.", "", "| Frozen cohort | N | W-L-P | Hit rate | Hypothetical -110 units |", "|---|---:|---|---:|---:|"]
    for name,r in data['cohorts'].items():lines.append(f"| {name} | {r['n']} | {r['win']}-{r['loss']}-{r['push']} | {r['win_rate_ex_push']:.1%} | {r['units_minus110']:+.3f} |")
    lines += ["", "## Original combined research Top 5", "", "| Game | Pick | Final away-home | Forecast total | Result | Cover margin |", "|---|---|---|---:|---|---:|"]
    for r in tables['week8_totals_audit.csv'][:5]:lines.append(f"| {r['away']} at {r['home']} | {r['selection']} {r['locked_line']} | {r['away_score']}-{r['home_score']} | {r['raw_projection']:.3f} | {r['result']} | {r['margin_vs_locked']:+g} |")
    lines += ["", "## Largest totals errors", "", "| Game | Forecast | Actual | Actual minus forecast |", "|---|---:|---:|---:|"]
    for r in sorted(tables['week8_totals_audit.csv'],key=lambda r:-abs(r['forecast_error_actual_minus_predicted']))[:10]:lines.append(f"| {r['away']} at {r['home']} | {r['raw_projection']:.3f} | {r['actual_model_target']} | {r['forecast_error_actual_minus_predicted']:+.3f} |")
    lines += ["", "One postgame schedule discrepancy is retained separately: North Dakota State-New Mexico was listed at 02:00 UTC in the frozen schedule and 02:20 UTC by ESPN after the game. Generation and sealing preceded both. Team IDs and scores agree; original schedule bytes are unchanged.", "", "All numeric model adjustments remain zero. Governed ATS confidence is uniformly 1, with null uncertainty and tied ranking inputs. Research confidence and scores are uncalibrated. Backdoor classification remains unavailable unless a complete validated scoring sequence exists; a final score alone is insufficient.", "", "Replay offline with `python -m scripts.build_week8_postgame_audit --verify`. Exact file inventories, provider payload hashes, all protected source hashes, code identities and regenerated report/ledger bytes are checked. Re-running the writer against any existing output fails closed."]
    return "\n".join(lines)+"\n"


def serialized(data):
    return (json.dumps(data,indent=2,sort_keys=True,allow_nan=False)+"\n").encode()


def payloads():
    import io
    from scripts.research_week8_diagnostics import analyze, markdown
    data,tables=evaluate(); cross=analyze(tables)
    result={'week8_diagnostics.json':serialized(data),'cross_week_diagnostics.json':serialized(cross),
            'week8_postgame_report.md':report(data,tables).encode(), 'cross_week_tables.md':markdown(cross).encode()}
    for name,rows in tables.items():
        fields=list(dict.fromkeys(k for row in rows for k in row));stream=io.StringIO(newline='')
        writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)
        result[name]=stream.getvalue().encode()
    return data,result


CODE_FILES=('scripts/build_week8_postgame_audit.py','scripts/capture_week8_postgame_evidence.py','scripts/research_week8_diagnostics.py',
            'scripts/research_week7_acceptance.py','scripts/week5_postgame_core.py','scripts/seal_week8_board.py')
EXPECTED_OUTPUTS={'week8_diagnostics.json','cross_week_diagnostics.json','week8_postgame_report.md','cross_week_tables.md',
                  'week8_final_results.csv','week8_ats_audit.csv','week8_totals_audit.csv','week8_cohort_membership.csv'}


def main(verify=False):
    manifest_path=OUTPUT/'week8_postgame_manifest.json'
    if not verify and any((OUTPUT/name).exists() for name in EXPECTED_OUTPUTS|{manifest_path.name}):
        raise FileExistsError('audit output already exists; never overwrite')
    data,files=payloads()
    if set(files)!=EXPECTED_OUTPUTS:raise ValueError('expected audit output inventory mismatch')
    code={name:source_sha(ROOT/name) for name in CODE_FILES}
    evidence={p.relative_to(OUTPUT).as_posix():sha(p) for p in sorted(EVIDENCE.rglob('*')) if p.is_file()}
    manifest={'audit_version':'week8-postgame-v1','grading_status':data['grading_status'],'formal_audit_status':data['formal_audit_status'],
              'clv_status':'INCOMPLETE','owner_approval_status':data['custody']['owner_approval_status'],
              'output_sha256':{name:hashlib.sha256(raw).hexdigest() for name,raw in files.items()},
              'evidence_sha256':evidence,'audit_code_sha256_lf':code,'protected_sha256':data['custody']['protected_sha256']}
    if verify:
        actual={p.name for p in OUTPUT.iterdir() if p.is_file()}
        if actual!=EXPECTED_OUTPUTS|{manifest_path.name}:raise ValueError('exact checksum coverage required')
        if read_json(manifest_path)!=manifest:raise ValueError('manifest checksum coverage or audit status contradiction')
        for name,raw in files.items():
            if (OUTPUT/name).read_bytes()!=raw:raise ValueError('read-only deterministic replay mismatch: '+name)
    else:
        for name,raw in files.items():
            with (OUTPUT/name).open('xb') as stream:stream.write(raw)
        with manifest_path.open('xb') as stream:stream.write(serialized(manifest))
    return {'grading_status':data['grading_status'],'clv_status':'INCOMPLETE','output_files':len(files),'evidence_files':len(evidence),'protected_files':len(manifest['protected_sha256'])}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--verify',action='store_true')
    print(json.dumps(main(parser.parse_args().verify),indent=2))
