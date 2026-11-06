"""Additive, offline audit diagnostics. Never imports a prediction/grading engine.

All fitted comparisons are retrospective research. No policy or historical card is
changed. Input checksums distinguish exact custody from diagnosed EOL differences.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import random
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/2026-week7-acceptance-research"
PRE = {5: "2026-week5-execution-20260930-v4", 6: "2026-week6-execution-20261006T2133Z",
       7: "2026-week7-prospective-corrected-v2"}
INPUTS: dict[str, str] = {}


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read(path: str | Path):
    path = ROOT / path
    data = path.read_bytes()
    INPUTS[path.relative_to(ROOT).as_posix()] = sha(data.replace(b"\r\n", b"\n"))
    if path.suffix == ".csv":
        return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))
    return json.loads(data)


def instant(value: str) -> datetime:
    value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("timezone required")
    return value


def grade(margin: float) -> str:
    return "WIN" if margin > 0 else "LOSS" if margin < 0 else "PUSH"


@dataclass(frozen=True)
class Pick:
    week: int
    game_id: str
    market: str
    game: str
    selection: str
    line: float
    projection: float
    actual: float
    cover: float
    result: str
    edge: float | None
    score: float | None
    sigma: float | None
    confidence: int
    rank: int | None
    governed_top5: bool
    location: str
    favorite: str
    provenance: str

    @property
    def error(self) -> float:
        return self.actual - self.projection


def unique(rows: list[dict], key: str = "game_id") -> dict[str, dict]:
    result = {str(r[key]): r for r in rows}
    if len(result) != len(rows):
        raise ValueError("duplicate game identity")
    return result


def numeric(value) -> float | None:
    return None if value in (None, "") else float(value)


def load_modern(week: int) -> list[Pick]:
    pre = Path("outputs") / PRE[week]
    audit = Path(f"outputs/2026-week{week}-postgame-audit")
    ats, totals = read(pre / f"week{week}_ats_full_card.csv"), read(pre / f"week{week}_totals_full_card.csv")
    size = {5: 56, 6: 58, 7: 59}[week]
    if len(ats) != size or set(unique(ats)) != set(unique(totals)):
        raise ValueError("card coverage mismatch")
    model = read(pre / f"week{week}_model_manifest.json")
    games = unique(read(pre / f"provider-evidence/cfbd-week{week}-games.derived.json"), "id")
    for row in ats:
        g = games[row["game_id"]]
        if instant(model["generated_at_utc"]) >= instant(g["startDate"]):
            raise ValueError("postkickoff forecast")
        if g["completed"] or g["homePoints"] is not None or g["awayPoints"] is not None:
            raise ValueError("outcome in pregame schedule")
    result = []
    for market, card, name in (("ATS", ats, "ats"), ("TOTAL", totals, "totals")):
        grades = unique(read(audit / f"week{week}_{name}_audit.csv"))
        if set(grades) != set(unique(card)):
            raise ValueError("grade/card mismatch")
        rank_order = sorted(card, key=lambda r: (-float(r["raw_selected_probability"]), int(r["game_id"]))) if market == "TOTAL" else sorted(card, key=lambda r: (-abs(float(r["home_ats_edge"])), int(r["locked_line_id"])))
        ranks = {r["game_id"]: i for i, r in enumerate(rank_order, 1)}
        for r in card:
            gid, a = r["game_id"], grades[r["game_id"]]
            home, away = int(a.get("home_score", a.get("final_home_score"))), int(a.get("away_score", a.get("final_away_score")))
            if market == "ATS":
                line, projection = float(r["pick_spread"]), float(r["projected_home_margin"])
                actual = home - away
                cover = (actual if r["selected_side"] == "home" else -actual) + line
                edge, score = abs(float(r["home_ats_edge"])), min(.60, .50 + .005 * abs(float(r["home_ats_edge"])))
                sigma = float(r["shadow_uncertainty_points"])
                top = r["top_five"] == "True"
                location = "NEUTRAL" if games[gid]["neutralSite"] else r["selected_side"].upper()
                favorite = "FAVORITE" if line < 0 else "UNDERDOG" if line > 0 else "PICKEM"
                if week == 7 and not math.isclose(score, float(r["ats_shadow_score_not_calibrated"]), abs_tol=1e-12):
                    raise ValueError("score differs from archive")
                if not math.isclose(projection, float(a.get("projected_home_margin", a.get("raw_projection"))), abs_tol=1e-10):
                    raise ValueError("projection differs from audit")
            else:
                line, projection = float(r["locked_total"]), float(r["projected_total"])
                actual = home + away
                cover = (actual - line) * (1 if r["pick"].lower() == "over" else -1)
                edge, score, sigma = abs(projection-line), float(r["raw_selected_probability"]), float(r["uncertainty_points"])
                top, location, favorite = False, "NOT_APPLICABLE", "NOT_APPLICABLE"
            expected = a.get("result", a.get("ats_result" if market == "ATS" else "total_result"))
            if grade(cover) != expected:
                raise ValueError(f"independent grade mismatch {week}/{market}/{gid}")
            archived_line = a.get("locked_line", a.get("selected_spread" if market == "ATS" else "locked_splash_total", a.get("locked_total")))
            if float(archived_line) != line:
                raise ValueError("locked line differs from audit")
            rank = int(r[f"{name}_research_rank"]) if week == 7 else ranks[gid]
            if rank != ranks[gid]:
                raise ValueError("rank differs from frozen ordering")
            result.append(Pick(week, gid, market, f"{r['away']} @ {r['home']}", r["pick"], line, projection, actual, cover, expected, edge, score, sigma, int(r["confidence"]), rank, top, location, favorite,
                               "SEALED_PREGAME_RANK" if week == 7 else "PREGAME_FORECAST_RETROSPECTIVE_SCORE_ORDER"))
    return result


def load_earlier() -> list[Pick]:
    folder = Path("outputs/2026-week5-execution-20260930-v4/prior-evidence")
    result = []
    for r in read(folder / "week1-postgame-audit.csv"):
        if r["ats_result"] not in {"WIN", "LOSS", "PUSH"} or not r["model_projected_home_margin"]:
            continue
        result.append(Pick(1, r["game_id"], "ATS", f"{r['away_team']} @ {r['home_team']}", r["selected_team"], float(r["selected_spread"]), float(r["model_projected_home_margin"]), float(r["actual_home_margin"]), float(r["selected_cover_margin"]), r["ats_result"], abs(float(r["model_ats_edge"])), None, numeric(r["model_uncertainty_points"]), int(r["confidence"]), None, r["is_top_five"] == "YES", r["location_status"].upper(), r["favorite_status"].upper(), "AUDIT_AND_UNSEALED_LOCAL_PREVIEW_NO_PREGAME_HASH"))
    pre = read(OUT / "source-evidence/week2-pregame.json")
    locks=unique(read(OUT / 'source-evidence/week2-lock-manifest.json')['lines'])
    if any(instant(pre['generated_at']).date()>=datetime.fromisoformat(r['game_date']).date() for r in locks.values()):
        raise ValueError('Week 2 pregame date not established')
    audits = read(folder / "week2-audit.json")
    a2 = {r["game"]: r for r in audits["ats_rows"]}
    t2 = unique(audits["totals"]["details"])
    for r in pre["official_ats"]["full_card"]:
        game = f"{r['away']} @ {r['home']}"
        a, gid = a2[game], str(r["game_id"])
        if locks[gid]['home_spread']!=r['locked_home_spread'] or locks[gid]['total']!=r['locked_total']:
            raise ValueError('Week 2 lock identity mismatch')
        actual = a["final_home_points"]-a["final_away_points"]
        cover = (actual if r["ats_selected_side"] == "home" else -actual)+r["selected_spread"]
        if grade(cover) != a["result"].upper() or a["pick"] != r["ats_selected_team"]:
            raise ValueError("Week 2 ATS reconciliation failure")
        result.append(Pick(2,gid,"ATS",game,r["ats_selected_team"],r["selected_spread"],r["projected_home_margin"],actual,cover,grade(cover),r["ats_edge_magnitude"],None,numeric(r["model_uncertainty_points"]),r["confidence"],None,r["official_top_five"],a["location"].upper(),a["favorite_status"].upper(),"RECOVERED_PREGAME_GIT_COMMIT_NO_COMMON_ATS_SCORE"))
    for r in pre["totals_shadow"]["full_ledger"]:
        a=t2[str(r["game_id"])]; cover=(a["actual_total"]-r["locked_total"])*(1 if r["selected_direction"].lower()=="over" else -1)
        if grade(cover)!=a["result"].upper() or r["projected_total"]!=a["projected_total"] or r["locked_total"]!=a["exact_locked_total"]:
            raise ValueError("Week 2 total reconciliation failure")
        result.append(Pick(2,str(r["game_id"]),"TOTAL",f"{r['away']} @ {r['home']}",r["selected_direction"],r["locked_total"],r["projected_total"],a["actual_total"],cover,grade(cover),abs(r["raw_disagreement_points"]),r["raw_model_probability"],r["uncertainty_points"],r["shadow_confidence"],None,False,"NOT_APPLICABLE","NOT_APPLICABLE","RECOVERED_PREGAME_LIMITED_SHADOW_NOT_COMMON_RANK"))
    finals=unique(read("outputs/2026-week5-execution-20260930-v4/provider-evidence/cfbd-week3-games.derived.json"),"id")
    report=read(OUT / "source-evidence/week3-execution.json")
    for market, name in (("ATS","ats"),("TOTAL","totals")):
        archived=read(folder / f"week3-{name}-card.json")
        if archived!=read(OUT / f'source-evidence/week3-pregame-{name}.json'):
            raise ValueError('Week 3 differs from pregame Git blob')
        for r in archived:
            projection=r.get("prediction_home_margin" if market=="ATS" else "projected_total")
            if projection is None:
                continue  # Original explicit kickoff skip remains excluded.
            gid=str(r["game_id"]); f=finals[gid]
            if not f["completed"] or instant(report["generated_at"])>=instant(f["startDate"]):
                raise ValueError("invalid provisional Week 3 timing/final")
            game=f"{f['awayTeam']} @ {f['homeTeam']}"
            if market=="ATS":
                selection=r["pick"];line=r["pick_spread"];actual=f["homePoints"]-f["awayPoints"]
                location="HOME" if selection==f["homeTeam"] else "AWAY"
                cover=(actual if location=="HOME" else -actual)+line
                edge,score,sigma,conf,top=abs(r["edge"]),None,r["uncertainty"],r["confidence"],r["provisional_top_five"]
                favorite="FAVORITE" if line<0 else "UNDERDOG" if line>0 else "PICKEM"
                if f["neutralSite"]:location="NEUTRAL"
            else:
                selection=r["selected_direction"];line=r["locked_total"];actual=f["homePoints"]+f["awayPoints"]
                cover=(actual-line)*(1 if selection.lower()=="over" else -1)
                edge,score,sigma,conf,top=abs(projection-line),r["raw_model_probability"],r["uncertainty_points"],r["shadow_confidence"],False
                location=favorite="NOT_APPLICABLE"
            result.append(Pick(3,gid,market,game,selection,line,projection,actual,cover,grade(cover),edge,score,sigma,conf,None,top,location,favorite,"PREGAME_PROVISIONAL_ONE_KICKOFF_SKIP_NOT_OFFICIAL"))
    # Earlier ranks are explicitly retrospective ordering of pregame fields.
    for week in (2,3):
        for market in ('ATS','TOTAL'):
            group=[r for r in result if r.week==week and r.market==market]
            order=sorted(group,key=lambda r: (-(r.edge if market=='ATS' else r.score),r.game_id))
            ranks={r.game_id:i for i,r in enumerate(order,1)}
            result=[replace(r,rank=ranks[r.game_id]) if r.week==week and r.market==market else r for r in result]
    return result


def metrics(rows: list[Pick]) -> dict:
    c=Counter(r.result for r in rows); n=len(rows); decided=c['WIN']+c['LOSS']
    units=c['WIN']*10/11-c['LOSS']
    if decided:
        z=1.959963984540054;p=c['WIN']/decided;d=1+z*z/decided
        radius=z*math.sqrt(p*(1-p)/decided+z*z/(4*decided**2))/d
        interval=[(p+z*z/(2*decided))/d-radius,(p+z*z/(2*decided))/d+radius]
    else:interval=None
    return dict(n=n,wins=c['WIN'],losses=c['LOSS'],pushes=c['PUSH'],hit_rate=c['WIN']/decided if decided else None,
                units_minus110=units,roi=units/n if n else None,wilson95=interval,
                mae=sum(abs(r.error) for r in rows)/n if n else None,
                rmse=math.sqrt(sum(r.error**2 for r in rows)/n) if n else None,
                bias_actual_minus_prediction=sum(r.error for r in rows)/n if n else None)


def pearson(x: list[float],y: list[float]) -> float | None:
    if len(x)!=len(y):raise ValueError("unpaired vectors")
    if len(x)<2:return None
    mx,my=sum(x)/len(x),sum(y)/len(y)
    den=math.sqrt(sum((a-mx)**2 for a in x)*sum((b-my)**2 for b in y))
    return sum((a-mx)*(b-my) for a,b in zip(x,y))/den if den else None


def auc(scores: list[float], wins: list[bool]) -> float | None:
    yes=[s for s,w in zip(scores,wins) if w];no=[s for s,w in zip(scores,wins) if not w]
    return sum((a>b)+.5*(a==b) for a in yes for b in no)/(len(yes)*len(no)) if yes and no else None


def predictive(rows: list[Pick], field: str, permutations: int=4999) -> dict:
    rows=[r for r in rows if r.result!='PUSH' and getattr(r,field) is not None]
    scores=[getattr(r,field) for r in rows]; wins=[r.result=='WIN' for r in rows]
    observed=auc(scores,wins); rng=random.Random(71021); extreme=0
    groups=[[i for i,r in enumerate(rows) if r.week==week] for week in sorted({r.week for r in rows})]
    for _ in range(permutations):
        perm=wins.copy()
        for group in groups:
            labels=[wins[i] for i in group];rng.shuffle(labels)
            for i,label in zip(group,labels):perm[i]=label
        a=auc(scores,perm)
        extreme+=a is not None and observed is not None and abs(a-.5)>=abs(observed-.5)-1e-12
    result=dict(n=len(rows),auc=observed,pearson_win=pearson(scores,[float(w) for w in wins]),
                permutation_two_sided_p=(extreme+1)/(permutations+1),permutations=permutations,
                inference="EXPLORATORY_WITHIN_WEEK_LABEL_PERMUTATION_NOT_TEAM_CLUSTER_ROBUST")
    if field=='score':
        result.update(brier=sum((s-w)**2 for s,w in zip(scores,wins))/len(rows),
                      log_loss=-sum(math.log(s if w else 1-s) for s,w in zip(scores,wins))/len(rows),
                      expected_wins=sum(scores),actual_wins=sum(wins))
    return result


def segment(rank: int) -> str:
    return '1-5' if rank<=5 else '6-10' if rank<=10 else '11+'


def top5_test(rows: list[Pick]) -> dict:
    """Exact random-five null conditional on each week's observed win count."""
    distribution={0:1.0}
    for week in sorted({r.week for r in rows}):
        group=[r for r in rows if r.week==week];n=len(group);wins=sum(r.result=='WIN' for r in group)
        fold={k:math.comb(wins,k)*math.comb(n-wins,5-k)/math.comb(n,5) for k in range(6) if k<=wins and 5-k<=n-wins}
        combined={}
        for a,p in distribution.items():
            for b,q in fold.items():combined[a+b]=combined.get(a+b,0)+p*q
        distribution=combined
    top=metrics([r for r in rows if r.rank<=5]);remaining=metrics([r for r in rows if r.rank>5]);observed=top['wins']
    lower=sum(p for k,p in distribution.items() if k<=observed);upper=sum(p for k,p in distribution.items() if k>=observed)
    return dict(top5=top,remaining=remaining,hit_rate_difference=top['hit_rate']-remaining['hit_rate'],two_sided_conditional_p=min(1,2*min(lower,upper)),inference='RETROSPECTIVE_RANDOM_FIVE_NULL_NOT_INDEPENDENT_PROSPECTIVE_VALIDATION')


def spread_bucket(line: float) -> str:
    v=abs(line)
    return '0-2.5' if v<3 else '3-6.5' if v<7 else '7-13.5' if v<14 else '14-20.5' if v<21 else '21+'


def eol_identity(data: bytes, expected: str) -> str:
    if sha(data)==expected:return 'EXACT'
    lf=data.replace(b'\r\n',b'\n')
    if sha(lf)==expected:return 'LF_VARIANT_ONLY'
    if sha(lf.replace(b'\n',b'\r\n'))==expected:return 'CRLF_VARIANT_ONLY'
    return 'CONTENT_MISMATCH'


def custody() -> dict:
    c=read('outputs/2026-week5-review-20261001/v4-custody-manifest.json')
    m=read('outputs/2026-week5-postgame-audit/week5_postgame_manifest.json')
    groups={'week5_pregame':{r['path']:r['sha256'] for r in c['v4_files']},'week5_review':m['pregame_review_file_hashes'],'week5_postgame':m['output_sha256']}
    w6=Path('outputs')/PRE[6];groups['week6_pregame']={(w6/k).as_posix():v for k,v in read(w6/'week6_artifact_checksums.json')['files'].items()}
    old=Path('outputs/2026-week7-prospective');new=Path('outputs')/PRE[7]
    seal=read(new/'week7_corrected_v2_seal_manifest.json')
    groups['week7_original']={(old/k).as_posix():v for k,v in read(old/'week7_initial_seal_manifest.json')['files'].items()}
    groups['week7_corrected']={(new/k).as_posix():v for k,v in seal['output_files'].items()}
    groups['week7_sources']=seal['source_files']
    rows=[]
    for group, entries in groups.items():
        for path,expected in sorted(entries.items()):
            data=(ROOT/path).read_bytes(); status=eol_identity(data,expected)
            if status=='CONTENT_MISMATCH':raise ValueError(f'unresolved custody mismatch {path}')
            if not group.startswith('week5') and status!='EXACT':raise ValueError(f'exact custody failed {path}')
            rows.append(dict(group=group,path=path,expected_sha256=expected,status=status,
                             canonical_lf_sha256=sha(data.replace(b'\r\n',b'\n'))))
    return {'checks':rows,'counts':{g:dict(Counter(r['status'] for r in rows if r['group']==g)) for g in groups},
            'interpretation':'EOL variants diagnose custody defects; they do not repair or waive the original exact-byte gate.'}


def validate_manifest(manifest: dict, expected_outputs: set[str], expected_code: set[str]) -> None:
    if set(manifest['output_sha256'])!=expected_outputs or set(manifest['audit_code_sha256'])!=expected_code:
        raise ValueError('manifest hash coverage incomplete')
    if manifest['grading_status']!='COMPLETE_59_ATS_59_TOTALS' or manifest['formal_audit_status']!='INCOMPLETE_CLV_CUSTODY' or manifest['qualified_clv_rows']!=0:
        raise ValueError('manifest status conflicts with evidence')


def week7_custody_details() -> dict:
    pre=Path('outputs')/PRE[7]
    component=read(pre/'week7_raw_model_components.json')
    approval_path=ROOT/'outputs/2026-week7-owner-review/OWNER-APPROVED-WEEK-7-CONTEST-FIVE-CORRECTED-V2.json'
    if sha(approval_path.read_bytes())!='31dd412b3e6c16f3f871e4dc0276c3b2c84c2faae95715ac20eb39d648042568':raise ValueError('approval checksum mismatch')
    approval=read(approval_path);seal=read(pre/'week7_corrected_v2_seal_manifest.json')
    if sha((ROOT/pre/'week7_corrected_v2_seal_manifest.json').read_bytes())!=approval['corrected_v2_seal_sha256']:raise ValueError('approval/seal differs')
    if sha((ROOT/'data/cfb.db').read_bytes())!=seal['source_database_sha256']:raise ValueError('source DB checksum mismatch')
    kickoff=min(instant(r['kickoff_utc']) for r in component['games'])
    timestamps={'card':component['card_generated_at_utc'],'seal':seal['sealed_at_utc'],'owner_approval_observed':approval['owner_approval_timestamp_utc']}
    for folder in ('core-initial','context-initial'):
        manifest=read(pre/f'provider-evidence/{folder}/capture-manifest.json')
        for row in manifest['requests']:
            for key in ('requested_at','requested_at_utc','received_at_utc'):
                if key in row:timestamps[f'{folder}/{row["name"]}/{key}']=row[key]
            if folder=='core-initial' and row['name']=='cfbd-week6-advanced' and row['parameters']['endWeek']!=6:raise ValueError('feature cutoff violated')
    if any(instant(t)>=kickoff for t in timestamps.values()):raise ValueError('postkickoff custody timestamp')
    coefficients=component['totals_model']['fitted']
    for game in component['games']:
        if any((game['raw_point_in_time_package'][side+'_stats']['as_of_season'],game['raw_point_in_time_package'][side+'_stats']['as_of_week'])>(2026,6) for side in ('home','away')):raise ValueError('feature lookahead')
        a=game['ats'];t=game['totals']
        if not math.isclose(a['projected_home_margin'],a['intercept']+a['coefficients'][0]*a['epa_differential'],abs_tol=1e-10):raise ValueError('ATS component mismatch')
        for side in ('home','away'):
            prediction=coefficients[side+'_intercept']+sum(x*y for x,y in zip(coefficients[side+'_coefficients'],t['features']))
            if not math.isclose(prediction,t['projected_'+side+'_points'],abs_tol=1e-10):raise ValueError('total component mismatch')
        if instant(t['prediction_generated_at'])>=instant(game['kickoff_utc']):raise ValueError('forecast timing violation')
    return dict(timestamps=timestamps,first_kickoff_utc=kickoff.isoformat(),component_games_reproduced=len(component['games']),source_database_sha256=seal['source_database_sha256'],locked_card_sha256=seal['corrected_locked_card_sha256'],approval_sha256=sha(approval_path.read_bytes()),approval_containing_commit='cfbe724fc9687dea24bd50409bcc4a4c2214aec4',approval_parent_context_commit=approval['approval_source_commit_sha'],formal_audit_status='INCOMPLETE_CLV_CUSTODY',lookahead_conclusion='NO_CONTAMINATION_DETECTED_IN_SEALED_INPUTS;NOT_AN_INDEPENDENT_PROVIDER_HISTORY_CERTIFICATION',training_limitation='Fitted arithmetic and feature cutoffs independently checked; entire 4944-row totals training matrix not refit in this diagnostic run.')


def analysis(rows: list[Pick]) -> dict:
    modern=[r for r in rows if r.week>=5]
    weekly=[dict(week=w,market=m,**metrics([r for r in rows if r.week==w and r.market==m])) for w in (1,2,3,5,6,7) for m in ('ATS','TOTAL') if any(r.week==w and r.market==m for r in rows)]
    summary={m:metrics([r for r in modern if r.market==m]) for m in ('ATS','TOTAL')}
    cuts=[]
    for market in ('ATS','TOTAL'):
        pool=[r for r in modern if r.market==market]
        functions={'confidence':lambda r:str(r.confidence),'edge_points':lambda r:'<3' if r.edge<3 else '3-6.9' if r.edge<7 else '7-9.9' if r.edge<10 else '10+',
                   'score':lambda r:'0.60+' if r.score>=.6 else '0.55-0.60' if r.score>=.55 else '0.50-0.55',
                   'rank_nonoverlap':lambda r:segment(r.rank)}
        if market=='ATS':functions.update(favorite=lambda r:r.favorite,location=lambda r:r.location,spread=lambda r:spread_bucket(r.line),road_favorite=lambda r:str(r.location=='AWAY' and r.favorite=='FAVORITE'))
        else:functions.update(direction=lambda r:r.selection.upper(),locked_total=lambda r:'60+' if r.line>=60 else '50-59.5' if r.line>=50 else '<50')
        for axis,func in functions.items():
            for label in sorted({func(r) for r in pool}):
                cuts.append(dict(market=market,axis=axis,segment=label,**metrics([r for r in pool if func(r)==label])))
    ranking=[]
    for week in (5,6,7):
        for market in ('ATS','TOTAL'):
            for band in ('1-5','6-10','11+'):
                ranking.append(dict(week=week,market=market,segment=band,**metrics([r for r in modern if r.week==week and r.market==market and segment(r.rank)==band])))
    predict={m:{field:predictive([r for r in modern if r.market==m],field) for field in ('edge','score')} for m in ('ATS','TOTAL')}
    correlations=[]
    for week in (5,6,7,'5-7'):
        selected=[r for r in modern if week=='5-7' or r.week==week]
        aa={(r.week,r.game_id):r for r in selected if r.market=='ATS'};tt={(r.week,r.game_id):r for r in selected if r.market=='TOTAL'}
        for cohort in ('ALL','ATS_TOP5','TOTAL_TOP5','EITHER_TOP5','BOTH_TOP5'):
            pairs=[(a,tt[key]) for key,a in aa.items() if cohort=='ALL' or cohort=='ATS_TOP5' and a.rank<=5 or cohort=='TOTAL_TOP5' and tt[key].rank<=5 or cohort=='EITHER_TOP5' and min(a.rank,tt[key].rank)<=5 or cohort=='BOTH_TOP5' and max(a.rank,tt[key].rank)<=5]
            correlations.append(dict(week=week,cohort=cohort,n=len(pairs),signed_error_r=pearson([a.error for a,t in pairs],[t.error for a,t in pairs]),absolute_error_r=pearson([abs(a.error) for a,t in pairs],[abs(t.error) for a,t in pairs]),win_phi=pearson([float(a.result=='WIN') for a,t in pairs],[float(t.result=='WIN') for a,t in pairs]),both_win=sum(a.result==t.result=='WIN' for a,t in pairs),both_loss=sum(a.result==t.result=='LOSS' for a,t in pairs)))
    uncertainty=[]
    for m in ('ATS','TOTAL'):
        pool=[r for r in modern if r.market==m]; errors=sorted(abs(r.error) for r in pool)
        uncertainty.append(dict(market=m,n=len(pool),mean_sigma=sum(r.sigma for r in pool)/len(pool),within_one_sigma=sum(abs(r.error)<=r.sigma for r in pool)/len(pool),within_1_96_sigma=sum(abs(r.error)<=1.96*r.sigma for r in pool)/len(pool),empirical_abs_error_90=errors[math.ceil(.9*len(pool))-1],empirical_abs_error_95=errors[math.ceil(.95*len(pool))-1]))
    # Pure time-split replays; hypotheses were chosen after outcomes, hence not a new OOS claim.
    replay=[]
    for test_week in (6,7):
        for market in ('ATS','TOTAL'):
            train=[r for r in modern if r.market==market and r.week<test_week];test=[r for r in modern if r.market==market and r.week==test_week]
            prior_rate=sum(r.result=='WIN' for r in train)/len(train)
            bias=sum(r.error for r in train)/len(train)
            for weight in (0.0,.25,.5,1.0):
                probs=[.5+weight*(r.score-.5) for r in test]
                replay.append(dict(test_week=test_week,market=market,train_n=len(train),test_n=len(test),method=f'score_shrink_{weight}',brier=sum((p-(r.result=='WIN'))**2 for p,r in zip(probs,test))/len(test),log_loss=-sum(math.log(p if r.result=='WIN' else 1-p) for p,r in zip(probs,test))/len(test)))
            replay.append(dict(test_week=test_week,market=market,train_n=len(train),test_n=len(test),method='past_hit_rate_constant',fitted_rate=prior_rate,brier=sum((prior_rate-(r.result=='WIN'))**2 for r in test)/len(test)))
            for weight in (0.0,.5,1.0):
                err=[r.error-weight*bias for r in test]
                replay.append(dict(test_week=test_week,market=market,train_n=len(train),test_n=len(test),method=f'past_bias_correction_{weight}',train_bias=bias,mae=sum(abs(e) for e in err)/len(err),rmse=math.sqrt(sum(e*e for e in err)/len(err))))
            for weight in (0.0,.5,.75,1.0):
                # Forecast-only benchmark; fixed locked line, never a reconstructed close.
                baseline=[r.line if market=='TOTAL' else -r.line if r.selection==r.game.split(' @ ')[1] else r.line for r in test]
                err=[r.actual-(weight*r.projection+(1-weight)*line) for r,line in zip(test,baseline)]
                replay.append(dict(test_week=test_week,market=market,train_n=len(train),test_n=len(test),method=f'model_weight_vs_locked_line_{weight}',mae=sum(abs(e) for e in err)/len(err),rmse=math.sqrt(sum(e*e for e in err)/len(err))))
    human=[]
    for week in (5,6,7):
        pool=[r for r in modern if r.week==week];lookup={(r.market,r.game_id):r for r in pool}
        if week==7:
            ids=[(r['market'],str(r['game_id'])) for r in read('outputs/2026-week7-owner-review/OWNER-APPROVED-WEEK-7-CONTEST-FIVE-CORRECTED-V2.json')['selections']]
        elif week==5:
            ids=[('ATS',r['game_id']) for r in read('outputs/2026-week5-postgame-audit/week5_decision_shortlist_audit.csv')]
        else:
            by_game={(r.market,r.game):r for r in pool}
            ids=[]
            for item in read('outputs/2026-week6-postgame-audit/week6_decision_review_audit.csv'):
                pick=by_game[item['market'],item['game']]
                if pick.selection.lower()!=item['selection'].lower() or pick.line!=float(item['locked_line']):
                    raise ValueError('Week 6 review selection identity differs')
                ids.append((pick.market,pick.game_id))
        chosen=[lookup[key] for key in ids]
        for comparator in ('ATS_RESEARCH_TOP5','GOVERNED_ATS_TOP5','TOTAL_RESEARCH_TOP5'):
            base=[r for r in pool if (r.market=='ATS' and (r.governed_top5 if comparator=='GOVERNED_ATS_TOP5' else r.rank<=5))] if comparator!='TOTAL_RESEARCH_TOP5' else [r for r in pool if r.market=='TOTAL' and r.rank<=5]
            kept={(r.market,r.game_id) for r in chosen}&{(r.market,r.game_id) for r in base}
            human.append(dict(week=week,approval_status='EXPLICIT_OWNER_APPROVAL' if week==7 else 'PREGAME_REVIEW_SHORTLIST_NOT_EQUIVALENT_OWNER_APPROVAL',comparator=comparator,human=metrics(chosen),baseline=metrics(base),unit_difference=metrics(chosen)['units_minus110']-metrics(base)['units_minus110'],shared=len(kept),added=[f'{r.market}:{r.game_id}:{r.result}' for r in chosen if (r.market,r.game_id) not in kept],removed=[f'{r.market}:{r.game_id}:{r.result}' for r in base if (r.market,r.game_id) not in kept]))
    earlier=[]
    for week in (1,2,3):
        for market in ('ATS','TOTAL'):
            pool=[r for r in rows if r.week==week and r.market==market]
            if not pool:continue
            functions={'confidence':lambda r:str(r.confidence),'edge_points':lambda r:'<3' if r.edge<3 else '3-6.9' if r.edge<7 else '7-9.9' if r.edge<10 else '10+','governed_top5':lambda r:str(r.governed_top5)}
            if week>1:functions['retrospective_rank_nonoverlap']=lambda r:segment(r.rank)
            if market=='ATS':functions.update(favorite=lambda r:r.favorite,location=lambda r:r.location,spread=lambda r:spread_bucket(r.line),road_favorite=lambda r:str(r.location=='AWAY' and r.favorite=='FAVORITE'))
            else:functions['direction']=lambda r:r.selection.upper()
            for axis,func in functions.items():
                for label in sorted({func(r) for r in pool}):earlier.append(dict(week=week,market=market,axis=axis,segment=label,**metrics([r for r in pool if func(r)==label])))
    earlier_predict={f'week{week}_{m}':{field:predictive([r for r in rows if r.week==week and r.market==m],field,999) for field in (('edge',) if m=='ATS' else ('edge','score'))} for week in (2,3) for m in ('ATS','TOTAL')}
    drawdowns={}
    for market in ('ATS','TOTAL'):
        balance=peak=drawdown=0.0
        for week in (5,6,7):
            balance+=metrics([r for r in modern if r.market==market and r.week==week])['units_minus110']
            peak=max(peak,balance);drawdown=max(drawdown,peak-balance)
        drawdowns[market]=dict(weekly_settlement_max_drawdown_units=drawdown,ending_units=balance,n_weeks=3,limitation='WEEKLY_SETTLEMENT_ONLY_NOT_INTRAWEEK_BET_PATH')
    return dict(status='RESEARCH_ONLY_NO_POLICY_CHANGE',clv_status='INCOMPLETE',weekly=weekly,comparable_week5_7=summary,weekly_settlement_drawdown=drawdowns,segments=cuts,earlier_segments=earlier,earlier_predictiveness=earlier_predict,rank_nonoverlap=ranking,top5_effectiveness={m:top5_test([r for r in modern if r.market==m]) for m in ('ATS','TOTAL')},predictiveness=predict,correlations=correlations,uncertainty=uncertainty,retrospective_time_split_replay=replay,human_comparisons=human)


def serialize(value) -> bytes:
    return (json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n').encode()


def csv_bytes(rows: list[dict]) -> bytes:
    stream=io.StringIO(newline='');fields=list(dict.fromkeys(k for r in rows for k in r))
    writer=csv.DictWriter(stream,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)
    return stream.getvalue().encode()


def markdown_tables(d: dict) -> bytes:
    lines=['# Cross-week diagnostic tables — RESEARCH ONLY','',
           'Bias = actual minus forecast. One unit risked at -110: win +10/11, loss -1, push 0. These are hypothetical returns, not placed wagers. No qualified CLV. Weeks 1–3 have separate evidence limitations described in the acceptance report. Weeks 5–7 form the comparable ranking panel; no Week 4 card is reconstructed.','',
           '| Week | Market | N | W–L–P | Hit % | MAE | RMSE | Bias | Units |','|---|---|---:|---|---:|---:|---:|---:|---:|']
    for r in d['weekly']:
        lines.append(f"| {r['week']} | {r['market']} | {r['n']} | {r['wins']}–{r['losses']}–{r['pushes']} | {100*r['hit_rate']:.2f} | {r['mae']:.3f} | {r['rmse']:.3f} | {r['bias_actual_minus_prediction']:+.3f} | {r['units_minus110']:+.3f} |")
    lines+=['','## Nonoverlapping research rank segments','',
            'Ranks 1–5, 6–10, and 11+ are disjoint. Top 10 is the sum of the first two rows and is not another independent cohort. Week 5–6 orders are retrospective application of the existing score/edge ordering; Week 7 ranks were explicitly sealed pregame.','',
            '| Week | Market | Ranks | N | W–L | Hit % | Units |','|---|---|---|---:|---|---:|---:|']
    for r in d['rank_nonoverlap']:
        lines.append(f"| {r['week']} | {r['market']} | {r['segment']} | {r['n']} | {r['wins']}–{r['losses']} | {100*r['hit_rate']:.2f} | {r['units_minus110']:+.3f} |")
    lines+=['','## Week 5–7 pooled segments','', '| Market | Axis | Segment | N | W–L | Hit % | Units |','|---|---|---|---:|---|---:|---:|']
    for r in d['segments']:
        lines.append(f"| {r['market']} | {r['axis']} | {r['segment']} | {r['n']} | {r['wins']}–{r['losses']} | {100*r['hit_rate']:.2f} | {r['units_minus110']:+.3f} |")
    lines+=['','## Earlier weeks: separate descriptive cuts','',
            'Week 1 is audit-only; sealed original pregame forecast bytes were not recovered. Week 2 is a recovered local governed draft/limited shadow, with two quarantined total candidates included in grading. Week 3 is provisional, with one explicit kickoff skip. Earlier retrospective ranks are not original approved Top 5 selections.','',
            '| Week | Market | Axis | Segment | N | W–L | Hit % | Units |','|---|---|---|---|---:|---|---:|---:|']
    for r in d['earlier_segments']:
        lines.append(f"| {r['week']} | {r['market']} | {r['axis']} | {r['segment']} | {r['n']} | {r['wins']}–{r['losses']} | {100*r['hit_rate']:.2f} | {r['units_minus110']:+.3f} |")
    return ('\n'.join(lines)+'\n').encode()


def main(verify: bool=False) -> dict:
    INPUTS.clear()
    for source in sorted((OUT/'source-evidence').glob('*.json')):
        read(source)
    integrity=custody()
    audit=ROOT/'outputs/2026-week7-postgame-audit'
    manifest=read(audit/'week7_postgame_manifest.json')
    expected_outputs={p.relative_to(audit).as_posix() for p in audit.rglob('*') if p.is_file() and p.name!='week7_postgame_manifest.json'}
    validate_manifest(manifest,expected_outputs,{'scripts/build_week7_postgame_audit.py','scripts/capture_week7_postgame_evidence.py','scripts/week5_postgame_core.py'})
    for name,digest in manifest['output_sha256'].items():
        if sha((audit/name).read_bytes())!=digest:raise ValueError('Week 7 audit checksum mismatch')
    for name,digest in manifest['audit_code_sha256'].items():
        if sha((ROOT/name).read_bytes().replace(b'\r\n',b'\n'))!=digest:raise ValueError('Week 7 audit code checksum mismatch')
    for item in read(OUT/'source-evidence/git-recovery.json'):
        if sha((OUT/'source-evidence'/item['saved_as']).read_bytes())!=item['sha256']:raise ValueError('recovered Git evidence checksum mismatch')
    rows=load_earlier()+[r for week in (5,6,7) for r in load_modern(week)]
    observed=read(OUT/'source-evidence/review_observations.json')
    for final in observed['primary_final_score_reconciliation']:
        pair={r.market:r for r in rows if r.week==7 and r.game_id==final['game_id']}
        if pair['ATS'].actual!=final['home_score']-final['away_score'] or pair['TOTAL'].actual!=final['home_score']+final['away_score']:
            raise ValueError('independent official final conflicts with archive')
    result=analysis(rows)
    details=week7_custody_details()
    files={'diagnostics.json':serialize(result),'week7_custody_details.json':serialize(details),'diagnostic_tables.md':markdown_tables(result),'custody_checks.json':serialize(integrity),
           'selection_ledger.csv':csv_bytes([dict(**asdict(r),error_actual_minus_prediction=r.error) for r in rows]),
           'weekly_metrics.csv':csv_bytes(result['weekly']),'segments_week5_7.csv':csv_bytes(result['segments']),'earlier_week_segments.csv':csv_bytes(result['earlier_segments']),
           'rank_nonoverlap.csv':csv_bytes(result['rank_nonoverlap']),'correlations.csv':csv_bytes(result['correlations']),
           'time_split_replay.csv':csv_bytes(result['retrospective_time_split_replay'])}
    # Code/text identity is explicit canonical LF. Exact original custody remains above.
    source=ROOT/'scripts/research_week7_acceptance.py'
    manifest=dict(source_baseline_commit='da7381b801abee170a8b321cf77d833626230a11',status='RESEARCH_ONLY',hash_encoding='SHA256_CANONICAL_LF_TEXT;ORIGINAL_CUSTODY_SEPARATE',script_sha256=sha(source.read_bytes().replace(b'\r\n',b'\n')),inputs=INPUTS,outputs={k:sha(v) for k,v in files.items()})
    files['research_manifest.json']=serialize(manifest)
    if verify:
        for name,data in files.items():
            if (OUT/name).read_bytes().replace(b'\r\n',b'\n')!=data:raise ValueError(f'replay mismatch {name}')
    else:
        # New additive research may be explicitly regenerated; historical outputs never touched.
        OUT.mkdir(exist_ok=True,parents=True)
        for name,data in files.items():(OUT/name).write_bytes(data)
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--verify',action='store_true')
    result=main(parser.parse_args().verify)
    print(json.dumps({'status':result['status'],'weekly':result['weekly'],'predictiveness':result['predictiveness']},indent=2))
