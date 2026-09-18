"""Replay the owner's 2026 Week 3 execution into a preserved development snapshot.

No network, publication, policy promotion, or authoritative database replacement.
Uses the existing custody, EPA, component totals, selection, and ranking services.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import shutil
import sqlite3
import subprocess
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from business_entities import (
    ConfidenceRankingPolicy, FullCardPolicy, ManualAdjustmentPolicy,
    generate_full_card, generate_total_shadow_card, run_component_totals_shadow_model,
)
from business_entities.audits import record_pick_audit
from business_entities.common import BusinessEntityError
from business_entities.complete_audits import _ats_result, _spread_bucket
from business_entities.full_card import _rank_selections, _select_side, locked_line_snapshot_sha256
from business_entities.modeling import get_model_prediction
from business_entities.totals import (
    _normal_cdf, _symmetric_calibration, confidence_for_total_probability,
    get_total_reliability_policy,
)
from business_entities.totals_audits import (
    TotalPostgameAuditPolicy, audit_total_shadow_card,
    register_total_postgame_audit_policy,
)
from business_entities.weekly_controller import run_epa_only_model
from contest_lines import create_contest, list_effective_locked_lines, lock_contest_line
from ingestion import CanonicalTeamResolver, IngestionRequest, ProviderIngestionService
from migrations.runner import apply_migrations, table_row_counts
from operations.context import ContextEvidenceParser, write_context_evidence
from operations.providers import (
    CfbdGamesParser, CfbdTeamStatsParser, _write_games, _write_team_stats,
)
from scripts.run_week2_limited_shadow import _target_feature_custody, _totals_rows

ROOT = Path(__file__).resolve().parents[1]
PROVENANCE = "owner-request://2026-week3-execution/2026-09-18"
CENTRAL = timezone(timedelta(hours=-5))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def moment(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone is required")
    return parsed.astimezone(timezone.utc)


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str, allow_nan=False) + "\n", encoding="utf-8")


def reconcile(rows: list[dict], games: list[dict], resolver: CanonicalTeamResolver) -> list[dict]:
    if len(rows) != 57 or Counter(r["game_date_local"] for r in rows) != {
        "2026-09-17": 1, "2026-09-18": 2, "2026-09-19": 54,
    }:
        raise ValueError("CSV must reconcile to Thursday 1, Friday 2, Saturday 54")
    seen: set[int] = set()
    result = []
    for index, row in enumerate(rows, 1):
        if int(row["week"]) != 3:
            raise ValueError("wrong CSV week")
        names = [resolver.resolve("SplashSports", row[field]) for field in ("team_1", "team_2")]
        if any(n.status != "resolved" for n in names):
            raise ValueError(f"unresolved row {index}: {names}")
        pair = {n.canonical_name for n in names}
        matches = [g for g in games if {g["homeTeam"], g["awayTeam"]} == pair]
        if len(matches) != 1:
            raise ValueError(f"ambiguous/missing schedule pairing on row {index}")
        game = matches[0]
        if game["id"] in seen:
            raise ValueError(f"duplicate game on row {index}")
        seen.add(game["id"])
        spreads = [float(row[field]) for field in ("team_1_spread", "team_2_spread")]
        total = float(row["total"])
        if not all(math.isfinite(v) for v in (*spreads, total)) or sum(spreads) != 0 or total <= 0:
            raise ValueError(f"invalid spread pair or total on row {index}")
        kickoff = moment(row["game_date_local"] + "T" + row["kickoff_local"] + "-05:00")
        if game.get("startTimeTBD") or kickoff != moment(game["startDate"]):
            raise ValueError(f"kickoff discrepancy on row {index}")
        home_index = next(i for i, n in enumerate(names) if n.canonical_name == game["homeTeam"])
        result.append({
            "csv_row": index, "raw": row, "game_id": game["id"],
            "home": game["homeTeam"], "away": game["awayTeam"],
            "raw_home": row[f"team_{home_index + 1}"],
            "raw_away": row[f"team_{2 - home_index}"],
            "home_spread": spreads[home_index], "total": total,
            "kickoff_utc": kickoff.isoformat(), "display_timezone": "America/Chicago",
            "orientation_source": "CFBD /games, independent of screenshot display order",
            "captured_at_utc": moment(row["captured_at_local"]).isoformat(),
            "status": "MATCHED",
        })
    expected = {g["id"] for g in games if g["homeClassification"] == g["awayClassification"] == "fbs"}
    if seen != expected:
        raise ValueError("CSV and official FBS-vs-FBS schedule inventories differ")
    return result


def ingest(conn, payload, *, evidence: Path, metadata: dict, parser, writer, data_type: str, provider="collegefootballdata"):
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return asdict(ProviderIngestionService().ingest_payload(
        conn, IngestionRequest(
            provider=provider, endpoint=metadata["endpoint"],
            request_parameters=metadata.get("parameters", {}),
            requested_at=moment(metadata["requested_at"]), parser_version=parser.version,
            raw_payload_reference=str(evidence), data_type=data_type,
            expected_payload_sha256=hashlib.sha256(raw).hexdigest(),
        ), raw, parser, accepted_writer=writer,
    ))


def result_writer(conn, records):
    """Bind provider results to one existing matchup; preserve its schedule and IDs."""
    for record in records:
        rows = conn.execute(
            "SELECT game_id, start_date, completed, home_points, away_points FROM games "
            "WHERE season=? AND week=? AND home_team=? AND away_team=?",
            (record.season, record.week, record.home_team, record.away_team),
        ).fetchall()
        if len(rows) != 1 or not record.completed:
            raise ValueError("result requires one completed canonical matchup")
        game_id, start, completed, home, away = rows[0]
        if moment(start).date() != moment(record.start_date).date():
            raise ValueError("result date conflicts with canonical matchup")
        if completed and (home, away) != (record.home_points, record.away_points):
            raise ValueError("result conflicts with prior final score")
        if not completed:
            conn.execute(
                "UPDATE games SET home_points=?, away_points=?, completed=1 WHERE game_id=? AND completed=0",
                (record.home_points, record.away_points, game_id),
            )


def week2_audit(conn, games: list[dict], metadata: dict, evidence: Path, generated_at: datetime) -> dict:
    canonical = conn.execute("SELECT game_id,home_team,away_team,start_date FROM games WHERE season=2026 AND week=2").fetchall()
    mappings, selected = [], []
    for game_id, home, away, kickoff in canonical:
        matches = [g for g in games if g["homeTeam"] == home and g["awayTeam"] == away]
        if len(matches) != 1 or not matches[0].get("completed"):
            raise ValueError(f"Week 2 final result missing/ambiguous for {away} @ {home}")
        g = matches[0]
        mappings.append({"canonical_game_id": game_id, "provider_game_id": g["id"], "game": f"{away} @ {home}",
                         "canonical_kickoff": kickoff, "provider_kickoff": g["startDate"],
                         "kickoff_discrepancy": moment(kickoff) != moment(g["startDate"]),
                         "resolution": "unique season/week/home/away and same UTC date; original schedule preserved"})
        selected.append(g)
    ingestion = ingest(conn, selected, evidence=evidence, metadata=metadata, parser=CfbdGamesParser(), writer=result_writer, data_type="game_status")
    if ingestion["rows_rejected"]:
        raise ValueError("Week 2 results were quarantined")
    rows = []
    for pick_id, line_id, side, confidence, rank, top, spread, home, away, hp, ap, predicted, neutral in conn.execute(
        "SELECT p.id,p.locked_line_id,p.selected_side,p.confidence,p.rank,p.is_top_five,l.home_spread,"
        "g.home_team,g.away_team,g.home_points,g.away_points,m.predicted_home_margin,g.neutral_site "
        "FROM contest_picks p JOIN contest_locked_lines l ON l.id=p.locked_line_id "
        "JOIN games g ON g.game_id=l.game_id LEFT JOIN model_predictions m ON m.id=p.model_prediction_id "
        "WHERE l.season=2026 AND l.week=2 ORDER BY p.id"
    ):
        covered, result = _ats_result(side, hp-ap, spread)
        previous = conn.execute("SELECT id FROM pick_audits WHERE contest_pick_id=?", (pick_id,)).fetchall()
        if previous:
            raise ValueError("Week 2 already has audit records; inspect and reuse instead of duplicating")
        audit = record_pick_audit(conn, audit_key=f"week2-results-20260918:{pick_id}", contest_pick_id=pick_id,
            audit_status="final", result=result, policy_version="ats_locked_line_v1", source="collegefootballdata",
            final_home_points=hp, final_away_points=ap, audited_at=generated_at,
            provenance=f"{PROVENANCE};result_only;CLV_missing;backdoor_not_evaluated;payload={digest(evidence)}")
        selected_spread = spread if side == "home" else -spread
        rows.append({"pick_id": pick_id, "audit_id": audit.id, "game": f"{away} @ {home}",
            "pick": home if side == "home" else away, "locked_spread": selected_spread,
            "final_home_points": hp, "final_away_points": ap, "result": result,
            "covered_margin": covered, "confidence": confidence, "rank": rank, "top_five": bool(top),
            "favorite_status": "favorite" if selected_spread < 0 else "underdog" if selected_spread > 0 else "pickem",
            "location": "neutral" if neutral else side, "road_favorite": side == "away" and selected_spread < 0 and not neutral,
            "spread_bucket": _spread_bucket(spread),
            "hook_outcome": ("won_by_hook" if result == "win" else "lost_by_hook") if abs(covered) == .5 and abs(spread*2)%2 == 1 else "not_hook",
            "model_margin_error": None if predicted is None else predicted-(hp-ap),
            "clv": None, "backdoor": "not_evaluated", "causal_failure": "not_evaluated"})
    total_policy = register_total_postgame_audit_policy(conn, TotalPostgameAuditPolicy(
        policy_version="total-postgame-audit-v1", effective_at=generated_at,
        created_by="Codex", provenance=PROVENANCE))
    totals = audit_total_shadow_card(conn, audit_run_key="week2-total-results-20260918", total_shadow_card_id=1,
        total_postgame_audit_policy_id=total_policy.id, audited_at=generated_at, source="collegefootballdata", provenance=PROVENANCE)
    wlp = lambda items: {key: sum(r["result"] == key for r in items) for key in ("win", "loss", "push")}
    segments = {}
    for dimension in ("favorite_status", "location", "road_favorite", "spread_bucket", "confidence", "top_five", "hook_outcome"):
        segments[dimension] = {str(value): wlp([r for r in rows if r[dimension] == value]) for value in sorted({r[dimension] for r in rows}, key=str)}
    return {"status": "RESULTS_GRADED_FULL_ATS_AUDIT_BLOCKED_MISSING_CLOSING_CUSTODY", "ingestion": ingestion,
        "mapping": mappings, "ats": wlp(rows), "ats_top_five": wlp([r for r in rows if r["top_five"]]),
        "ats_rows": rows, "ats_segments": segments, "totals": asdict(totals),
        "totals_directions": {direction: wlp([asdict(r) for r in totals.details if r.selected_direction == direction]) for direction in ("over", "under")},
        "complete_audit_blockers": ["49 ATS closing lines unavailable", "49 totals closing lines unavailable", "Scoring-sequence evidence absent: backdoor/late-score causes not evaluated", "Week 2 model-support defect is documented; no model-policy change is approved by this partial audit"],
        "statistical_note": "Observed one-week results are descriptive, not evidence of a profitable edge.",
        "model_margin_mae": sum(abs(r["model_margin_error"]) for r in rows)/len(rows),
        "model_margin_rmse": math.sqrt(sum(r["model_margin_error"]**2 for r in rows)/len(rows))}


def table(headers: list[str], rows: list[list[object]]) -> str:
    fmt = lambda v: "—" if v is None else f"{v:.2f}" if isinstance(v, float) else str(v).replace("|", "/")
    return "\n".join(["| " + " | ".join(headers) + " |", "|" + "---|"*len(headers)] + ["| " + " | ".join(fmt(v) for v in row) + " |" for row in rows])


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database", type=Path, default=ROOT/"data/cfb.db")
    parser.add_argument("--execution-database", type=Path, required=True)
    args = parser.parse_args(argv)
    output, target, source = args.output.resolve(), args.execution_database.resolve(), args.database.resolve()
    if output.exists() or target.exists() or target == source or not target.is_relative_to(ROOT) or not output.is_relative_to(ROOT):
        parser.error("output and execution database must be new, isolated paths inside this worktree")
    evidence = args.evidence.resolve()
    manifest = json.loads((evidence/"capture-manifest.json").read_text())
    specs = {r["name"]: r for r in manifest["requests"]}
    for spec in specs.values():
        if spec["status"] == "captured" and digest(evidence/spec["path"]) != spec["sha256"]:
            raise ValueError("provider evidence checksum mismatch")
    generated_at = datetime.now(timezone.utc)
    if any(moment(r["requested_at"]) > generated_at for r in specs.values()):
        raise ValueError("future provider capture")
    output.mkdir(parents=True)
    target.parent.mkdir(parents=True, exist_ok=True)
    backup = target.with_name("source-before-week3.db")
    if backup.exists():
        raise ValueError("backup already exists")
    source_hash = digest(source)
    shutil.copy2(source, backup)
    shutil.copy2(source, target)
    shutil.copy2(args.input, output/"week3_splash_lines_2026.original.csv")
    source_csv_sha = digest(args.input)
    conn = sqlite3.connect(target)
    conn.execute("PRAGMA foreign_keys=ON")
    before = table_row_counts(conn)
    if conn.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or conn.execute("PRAGMA foreign_key_check").fetchall():
        raise ValueError("pre-import database integrity failed")
    before_rows = {t: conn.execute(f'SELECT * FROM "{t}"').fetchall() for t in before if t != "sqlite_sequence"}
    migrations = apply_migrations(conn)
    read = lambda name: json.loads((evidence/specs[name]["path"]).read_text())
    teams = read("cfbd-fbs-teams")
    additions = []
    for team in teams:
        if conn.execute("SELECT 1 FROM teams WHERE school=?", (team["school"],)).fetchone():
            continue
        if team["classification"] != "fbs":
            raise ValueError("non-FBS team in FBS identity capture")
        conn.execute("INSERT INTO teams(team_id,school,conference,division) VALUES(?,?,?,?)",
                     (team["id"],team["school"],team["conference"],team["division"]))
        additions.append({"team_id": team["id"], "school": team["school"], "source": specs["cfbd-fbs-teams"]})
    games = read("cfbd-week3-games")
    with args.input.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    reconciliation = reconcile(rows, games, CanonicalTeamResolver.from_connection(conn))
    exclusions = [g for g in games if g["homeClassification"] != "fbs" or g["awayClassification"] != "fbs"]
    fbs = [g for g in games if g not in exclusions]
    conn.commit()  # Custody owns its independent transaction in this disposable copy.
    summaries = [ingest(conn, fbs, evidence=evidence/specs["cfbd-week3-games"]["path"], metadata=specs["cfbd-week3-games"], parser=CfbdGamesParser(), writer=_write_games, data_type="game_status")]
    summaries.append(ingest(conn, read("cfbd-week2-stats"), evidence=evidence/specs["cfbd-week2-stats"]["path"], metadata=specs["cfbd-week2-stats"], parser=CfbdTeamStatsParser(), writer=_write_team_stats, data_type="contextual"))
    if any(s["rows_rejected"] for s in summaries):
        raise ValueError("schedule/stats ingestion rejected records")
    for name, provider in (("weather", "open_meteo"), ("travel_rest", "collegefootballdata")):
        path = evidence/(name+".normalized.json")
        payload = json.loads(path.read_text())
        metadata = {"endpoint": "https://api.open-meteo.com/v1/forecast" if name == "weather" else "https://api.collegefootballdata.com/games",
                    "parameters": {"year":2026,"week":3,"derived_context_batch":True},
                    "requested_at": max(item["observed_at"] for item in payload)}
        summaries.append(ingest(conn, payload, evidence=path, metadata=metadata, parser=ContextEvidenceParser(), writer=write_context_evidence, data_type="weather" if name == "weather" else "contextual", provider=provider))
    contest = create_contest(conn, contest_key="splashsports-2026-week-3", name="SplashSports 2026 Week 3",
        season=2026, week=3, source="SplashSports", source_contest_id="splashsports-2026-week-3",
        created_at=generated_at, provenance=PROVENANCE)
    lock_results = []
    for row in reconciliation:
        result = lock_contest_line(conn, contest_id=contest.id, raw_home_team=row["raw_home"], raw_away_team=row["raw_away"],
            normalized_home_team=row["home"], normalized_away_team=row["away"], home_spread=row["home_spread"], total=row["total"],
            source="SplashSports", source_line_id=f"csv-row:{row['csv_row']}", payload_sha256=source_csv_sha,
            game_id=row["game_id"], locked_at=generated_at,
            provenance=f"{PROVENANCE};screenshot_capture_claim={row['captured_at_utc']};ingestion_lock={generated_at.isoformat()};csv_sha256={source_csv_sha};screenshot_not_attached")
        row["locked_line_id"] = result.line.id
        row["locked_at_utc"] = result.line.locked_at
        row["pregame_eligible"] = moment(row["kickoff_utc"]) > generated_at
        lock_results.append(asdict(result))
    lines = list_effective_locked_lines(conn, contest.id, as_of=generated_at)
    audit = week2_audit(conn, read("cfbd-week2-games"), specs["cfbd-week2-games"], evidence/specs["cfbd-week2-games"]["path"], generated_at)
    commit = subprocess.check_output(["git","rev-parse","HEAD"],cwd=ROOT,text=True).strip()
    model = run_epa_only_model(conn, contest_id=contest.id, model_run_key="week3-20260918:epa", code_commit_sha=commit,
        generated_at=generated_at, provenance=PROVENANCE)
    total_model = run_component_totals_shadow_model(conn, contest_id=contest.id, model_run_key="week3-20260918:component-totals",
        code_commit_sha=commit, generated_at=generated_at, provenance=PROVENANCE)
    policy_row = conn.execute("SELECT * FROM contest_ranking_policies WHERE id=1").fetchone()
    columns = [r[1] for r in conn.execute("PRAGMA table_info(contest_ranking_policies)")]
    policy_values = dict(zip(columns,policy_row))
    cp = ConfidenceRankingPolicy(**{k: moment(policy_values[k]) if k=="effective_at" else policy_values[k] for k in ConfidenceRankingPolicy.__dataclass_fields__})
    sp = FullCardPolicy(version="production-selection-v1",market_books=(),model_tie_side="away",pickem_tiebreak_side="home")
    ap = ManualAdjustmentPolicy(policy_version="production-adjustment-v1",effective_at=moment("2026-08-01T00:00:00+00:00"),created_by="repository-owner",provenance=policy_values["provenance"])
    blockers = []
    try:
        generate_full_card(conn,card_key="week3-20260918:full-card",contest_id=contest.id,model_run_id=model.id,version=1,
            policy=sp,confidence_policy=cp,adjustment_policy=ap,created_by="Codex",provenance=PROVENANCE,generated_at=generated_at)
    except BusinessEntityError as exc:
        blockers.append("Official ATS card/Top 5 blocked: "+str(exc))
    total_policy = get_total_reliability_policy(conn, 1)
    try:
        generate_total_shadow_card(conn,card_key="week3-20260918:total-card",contest_id=contest.id,total_model_run_id=total_model.id,
            total_reliability_policy_id=1,version=1,generated_at=generated_at,created_by="Codex",provenance=PROVENANCE)
    except BusinessEntityError as exc:
        blockers.append("Sealed totals shadow card blocked: "+str(exc))
    blockers.append("Combined Top 5 cannot execute: generate_unified_top_five requires same-contest ATS and sealed totals cards; both reject the elapsed Syracuse-Pittsburgh kickoff. No combined ranking was invented.")
    eligible_lines = tuple(line for line in lines if next(r for r in reconciliation if r["game_id"]==line.game_id)["pregame_eligible"])
    selections = _rank_selections(tuple(_select_side(conn,line=line,model_run_id=model.id,policy=sp,adjustment_policy=ap,
        generated_at=generated_at.isoformat(),provenance=PROVENANCE+";PROVISIONAL_REMAINING_GAMES_ONLY") for line in eligible_lines),cp)
    by_line = {s.line.locked_line_id:s for s in selections}
    ats_rows = []
    for row in reconciliation:
        s = by_line.get(row["locked_line_id"])
        p = get_model_prediction(conn,s.model_prediction_id) if s and s.model_prediction_id else None
        pick = row[s.selected_side] if s else None
        selected_spread = (row["home_spread"] if s.selected_side=="home" else -row["home_spread"]) if s else None
        ats_rows.append({"game":f"{row['away']} @ {row['home']}","game_id":row["game_id"],"locked_line_id":row["locked_line_id"],
            "home_spread":row["home_spread"],"prediction_home_margin":None if p is None else p.predicted_home_margin,
            "pick":pick,"pick_spread":selected_spread,"edge":None if p is None else abs(p.predicted_home_margin+row["home_spread"]),
            "confidence":None if s is None else s.confidence,"uncertainty":None if p is None else p.uncertainty_points,
            "provisional_rank":None if s is None else s.rank,"provisional_top_five":False if s is None else s.is_top_five,
            "fallback":None if s is None else s.fallback_code,"status":"PROVISIONAL" if s else "SKIP_KICKOFF_PASSED",
            "explanation":"EPA-only through Week 2; unchanged reliability policy; context unadjusted" if p else "Kickoff passed before import; no retrospective pick" if not s else s.fallback_code})
    _, features, _, _ = _target_feature_custody(conn,season=2026,week=3,lines=eligible_lines)
    candidate_views = []
    skip_views = []
    for line in eligible_lines:
        row = conn.execute("SELECT id,projected_total,uncertainty_points FROM total_model_predictions WHERE total_model_run_id=? AND game_id=?",(total_model.id,line.game_id)).fetchone()
        if row is None:
            skip_views.append(SimpleNamespace(locked_line_id=line.locked_line_id,reason_code="missing_total_prediction"))
            continue
        pid,projection,uncertainty = row
        direction = "over" if projection > line.total else "under"
        raw = _normal_cdf((projection-line.total)/uncertainty)
        probability = _symmetric_calibration(raw,total_policy.calibration_slope)
        selected = max(.5,probability if direction=="over" else 1-probability)
        candidate_views.append(SimpleNamespace(id=None,locked_line_id=line.locked_line_id,game_id=line.game_id,
            total_model_prediction_id=pid,projected_total=projection,exact_locked_total=line.total,uncertainty_points=uncertainty,
            selected_direction=direction,raw_over_probability=raw,confidence=confidence_for_total_probability(total_policy,selected)))
    # These report-only views reuse existing diagnostics; no candidate ledger or calibration seal is fabricated.
    total_report = _totals_rows(conn,total_card=SimpleNamespace(candidates=candidate_views,skips=skip_views),lines=eligible_lines,
        features=features,diagnostic=json.loads((ROOT/"outputs/totals-historical-custody-correction-2026-09-09.json").read_text()))
    for row in reconciliation:
        if not row["pregame_eligible"]:
            total_report.insert(row["csv_row"]-1,{"game_id":row["game_id"],"home":row["home"],"away":row["away"],"locked_total":row["total"],"record_type":"explicit_skip","skip_reason":"kickoff_not_in_future","projected_total":None,"selected_direction":None,"shadow_confidence":None,"eligibility":"SKIPPED"})
    after = table_row_counts(conn)
    preserved = {}
    for name, previous in before_rows.items():
        current = conn.execute(f'SELECT * FROM "{name}"').fetchall()
        if name == "games":
            allowed_ids = {r["canonical_game_id"] for r in audit["mapping"]}
            by_id = {r[0]:r for r in current}
            game_columns = [r[1] for r in conn.execute("PRAGMA table_info(games)")]
            retained_indices = [i for i,c in enumerate(game_columns) if c not in ("home_points","away_points","completed")]
            if any(tuple(old[i] for i in retained_indices) != tuple(by_id[old[0]][i] for i in retained_indices) for old in previous):
                raise ValueError("result import changed a non-result game field")
            previous = [r for r in previous if r[0] not in allowed_ids]
        preserved[name] = set(previous).issubset(set(current))
    if not all(preserved.values()):
        raise ValueError("unrelated existing records changed")
    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    conn.commit()
    conn.close()
    if digest(source) != source_hash or digest(backup) != source_hash:
        raise ValueError("source/backup changed")
    blockers += ["Master Prompt v2.8 was not present in supplied files or this worktree", "Original screenshots unavailable for independent transcription verification", "Native SplashSports contest identifier was not supplied; source_contest_id uses the repository weekly key", "ODDS provider connection failed before an HTTP response; no current or closing sportsbook line captured", "ESPN injury capture succeeded but its team-group shape fails the existing parser; QB availability unverified", "Opponent adjustment and pace are absent from the baseline; early-season shrinkage remains unapproved research", "Coaching/motivation evidence was not asserted; no manual adjustments applied", "Managed authoritative PostgreSQL stream unavailable: CFB_V3_DATABASE_URL absent; locks are durable in isolated development snapshot only", "Week 2 full audit remains incomplete; no model promotion performed"]
    report = {"status":"PARTIAL_EXECUTION_NOT_OFFICIAL", "generated_at":generated_at.isoformat(),"code_commit_sha":commit,
        "counts":{"imported":57,"locally_locked":57,"authoritative_stream_locked":0,"ats_modeled":sum(r["prediction_home_margin"] is not None for r in ats_rows),"totals_modeled":len(candidate_views),"postkickoff_skipped":57-len(selections),"csv_excluded":0,"schedule_non_fbs_excluded":len(exclusions)},
        "database":str(target),"backup":str(backup),"source_database":str(source),"source_sha256":source_hash,"source_unchanged":True,
        "execution_database_sha256":digest(target),"source_csv_sha256":source_csv_sha,"migrations_applied":[m.version for m in migrations],
        "counts_before":before,"counts_after":after,"existing_records_preserved":preserved,"integrity":integrity,"foreign_key_violations":foreign_keys,
        "ats_model":asdict(model),"totals_model":asdict(total_model),"production_totals_eligible":False,
        "ranking_policy":policy_values,"locked_line_snapshot_sha256":locked_line_snapshot_sha256(lines),"locks":lock_results,
        "added_team_identities":additions,"provider_ingestion":summaries,"blockers":blockers,
        "official_ats_top_five":{"status":"BLOCKED","rows":[]},"combined_top_five":{"status":"BLOCKED_SHADOW_ONLY","ats_count":0,"totals_count":0,"rows":[]},
        "ats_fallback_count":sum(bool(r["fallback"]) for r in ats_rows),"manual_adjustments":[],
        "evidence_file_sha256":{p.name:digest(p) for p in evidence.iterdir() if p.is_file()},
        "code_file_sha256":{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),ROOT/"business_entities/weekly_controller.py",ROOT/"business_entities/totals_weekly_model.py"]}}
    write_json(output/"ingestion-reconciliation.json",{"rows":reconciliation,"excluded_schedule_games":exclusions,"csv_sha256":source_csv_sha})
    write_json(output/"ats-card.json",ats_rows)
    write_json(output/"totals-research-card.json",total_report)
    write_json(output/"official-ats-top5.json",report["official_ats_top_five"])
    write_json(output/"combined-shadow-top5.json",report["combined_top_five"])
    write_json(output/"week2-audit.json",audit)
    write_json(output/"execution-report.json",report)
    top = sorted([r for r in ats_rows if r["provisional_top_five"]],key=lambda r:-r["provisional_rank"])
    md = "# WEEK 3 — MODEL EXECUTION RESULTS\n\n**PARTIAL / PROVISIONAL — NOT AN OFFICIAL CARD.**\n\n"+json.dumps(report["counts"])+"\n\n"
    md += "Home-margin projections use home minus away. Every supplied row is shown; Thursday is explicitly skipped. All modeled ATS Confidence values remain 1 under the unchanged policy.\n\n"
    md += table(["Game","Home spread","Home margin","ATS pick","Edge","Confidence","Status"],[[r["game"],r["home_spread"],r["prediction_home_margin"],None if r["pick"] is None else f"{r['pick']} {r['pick_spread']:+g}",r["edge"],r["confidence"],r["status"]] for r in ats_rows])
    md += "\n\n## Official ATS Top 5\n\nBLOCKED: the complete-week card cannot pass its pre-kickoff gate.\n\n## Provisional remaining-game ATS Top 5\n\nExisting reliability ordering; not official or a wager recommendation. Repository priority 5 is strongest.\n\n"
    md += table(["Display rank","Game","Pick","Home projection","Edge","Confidence"],[[i,r["game"],f"{r['pick']} {r['pick_spread']:+g}",r["prediction_home_margin"],r["edge"],r["confidence"]] for i,r in enumerate(top,1)])
    md += "\n\n## Combined ATS/O/U Top 5\n\nBLOCKED, SHADOW ONLY. No unified run or ranking was generated; ATS 0 / totals 0.\n\n## Totals research report\n\nAll probabilities are raw, not empirically calibrated. Production eligibility: NO. Existing quarantine diagnostics retained.\n\n"
    md += table(["Game","Locked total","Projection","Direction","Confidence","Reliability"],[[f"{r['away']} @ {r['home']}",r["locked_total"],r["projected_total"],r["selected_direction"],r["shadow_confidence"],r["eligibility"]] for r in total_report])
    md += "\n\n## Week 2 audit\n\nATS "+json.dumps(audit["ats"])+"; ATS Top 5 "+json.dumps(audit["ats_top_five"])+". Totals "+json.dumps({k:audit['totals']['completion'][k] for k in ('win_count','loss_count','push_count')})+".\n\nFull CLV/causal audit is incomplete. See week2-audit.json for every pick, score, hook, bucket and segment. No rules changed.\n\n## Blockers and limitations\n\n"+"\n".join("- "+b for b in blockers)+"\n"
    (output/"RESULTS.md").write_text(md,encoding="utf-8")
    print(json.dumps({"output":str(output),"database":str(target),"counts":report["counts"],"ats_week2":audit["ats"],"integrity":integrity},indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
