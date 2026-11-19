"""Append-only Week11 audit and research proposal; exact offline replay available."""
from __future__ import annotations
import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from scripts.week11_audit_inputs import ROOT, BOARD, EVIDENCE, SOURCE_COMMIT, DB_SHA, LINE_SHA, SEAL_SHA, sha, source_files, source_json
from scripts.week11_audit_grading import load_capture, reconcile, grades, cohorts
from scripts.week11_audit_metrics import historical, historical_human, summary, forecast, segments, calibration, discrimination
from scripts.week11_audit_research import evaluate
from scripts.week11_audit_process import process, clv
from scripts.week11_drive_adjudication import adjudicate
from scripts.week11_v29_research import run as research_run
from scripts.build_week9_formal_audit import csv_bytes, verify_files, custody as historical_custody

OUT=ROOT/'outputs/2026-week11-postgame-audit/v2'
V1=ROOT/'outputs/2026-week11-postgame-audit/v1'
V1_MANIFEST_SHA='88b77d4daf202384d61cbd7277ad10b94866bf6e460cea6f7bf4b00463773ab1'


def pinned_inputs():
    """Verify the original closed evidence inventory; later weekly outputs are unrelated."""
    raw=(V1/'audit_manifest.json').read_bytes()
    if sha(raw)!=V1_MANIFEST_SHA:raise ValueError('original audit inventory changed')
    manifest=json.loads(raw)
    for name,digest in manifest['output_sha256'].items():
        if sha((V1/name).read_bytes())!=digest:raise ValueError('original audit output changed: '+name)
    for name,digest in manifest['input_sha256'].items():
        raw=(ROOT/name).read_bytes()
        if name.startswith('data/ingest/2026-season-splashsports-recovery/'):
            raw=raw.replace(b'\r\n',b'\n')
        if sha(raw)!=digest:raise ValueError('pinned audit input changed: '+name)
    return manifest['input_sha256'],list(manifest['code_sha256_lf'])


def canonical(value):
    if isinstance(value,float):return round(value,10)
    if isinstance(value,dict):return {k:canonical(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [canonical(v) for v in value]
    return value


def encoded(value):
    return (json.dumps(canonical(value),indent=2,sort_keys=True,allow_nan=False)+'\n').encode()


def custody():
    files=source_files(); seal=source_json(BOARD+'week11_initial_seal_manifest.json')
    for p,digest in seal['source_sha256'].items():
        if sha(files[p])!=digest:raise ValueError('Original source custody changed: '+p)
    for p,digest in seal['output_sha256'].items():
        if sha(files[BOARD+p])!=digest:raise ValueError('Original board custody changed: '+p)
    screenshots=[p for p in files if p.startswith(BOARD+'source-evidence/splashsports-') and p.endswith('.png')]
    if len(screenshots)!=8:raise ValueError('Eight original screenshots required')
    if sha((ROOT/'data/cfb.db').read_bytes())!=DB_SHA:raise ValueError('Source database changed')
    with sqlite3.connect('file:'+(ROOT/'data/cfb.db').as_posix()+'?mode=ro',uri=True) as db:
        integrity=db.execute('PRAGMA integrity_check').fetchall();fk=db.execute('PRAGMA foreign_key_check').fetchall()
    if integrity!=[('ok',)] or fk:raise ValueError('Database integrity failure')
    return dict(source_pr=53,source_commit=SOURCE_COMMIT,source_pr_status='MERGED_2026_11_16',archived_files=len(files),
                original_source_csv_sha256=LINE_SHA,original_board_seal_sha256=SEAL_SHA,source_database_sha256=DB_SHA,
                original_screenshots=len(screenshots),sealed_at_utc=seal['sealed_at_utc'],
                custody_qualification='Three Wednesday games were sealed after kickoff. Original generation timestamp is not independently verified pregame custody.',
                historical=historical_custody(),database_integrity='ok',foreign_key_violations=0,
                original_forecasts_regenerated=False,owner_approval='WEEK11_SUBMISSIONS_EXTERNAL_ORIGIN_EXCLUDED; V3_COHORTS_REMAIN_RECOMMENDATIONS')


def build():
    verified=custody();capture,records,data=load_capture();finals=reconcile(data,records)
    current=grades(finals,data);groups=cohorts(current);old=historical();all_rows=old+current
    frozen=evaluate(current);mechanisms=process(finals,current,data,groups);closing=clv(finals,data,records)
    drives=adjudicate();proposal=research_run(all_rows)
    from scripts.season_contest_audit import build as season_build
    season=season_build(all_rows,groups)
    scopes={'WEEK11_RECORDED64':current,'WEEK11_FORWARD61':[r for r in current if r['custody']=='FORWARD_SEALED_61'],
            'WEEKS5_11_COMPARABLE400':all_rows,
            'WEEKS5_11_EXCLUDE_LATE_WEDNESDAY397':[r for r in all_rows if not r['custody'].startswith('LATE_')]}
    scopes.update({f'WEEK{w}':[r for r in all_rows if int(r['week'])==w] for w in range(5,11)})
    weekly=[]; forecasts=[]; cuts=[];calibrations=[];discriminations=[]
    for name,rows in scopes.items():
        cuts += [dict(scope=name,**r) for r in segments(rows)]
        for market in ('ATS','TOTAL'):
            selected=[r for r in rows if r['market']==market]
            weekly.append(dict(scope=name,market=market,**summary(selected)))
            forecasts.append(dict(scope=name,market=market,**forecast(selected)))
            discriminations.append(dict(scope=name,market=market,**discrimination(selected)))
        for layer,market in [('GOVERNED_ATS','ATS'),('RESEARCH_ATS','ATS'),('TOTALS','TOTAL')]:
            calibrations += [dict(scope=name,**r) for r in calibration([r for r in rows if r['market']==market],layer)]
    human=historical_human(old)+groups['HUMAN_20261113-v2']
    for name,rows in [('WEEK11_LATEST_REVIEW',groups['HUMAN_20261113-v2']),('WEEKS9_11_LATEST_REVIEW_PER_WEEK',human)]:
        calibrations += [dict(scope=name,**r) for r in calibration(rows,'HUMAN_CONTEXTUAL')]
    memberships=[dict(r,cohort=name,cohort_rank=i) for name,rows in groups.items() for i,r in enumerate(rows,1)]
    cohort_results=[dict(cohort=name,**summary(rows)) for name,rows in groups.items()]
    overlap=[]
    all_groups={**groups,**{name:[r for r in frozen['memberships'] if r['cohort']==name] for name in sorted({r['cohort'] for r in frozen['memberships']})}}
    for i,(name,rows) in enumerate(all_groups.items()):
        left={(r['market'],r['game_id'],r['selection']) for r in rows}
        for other,other_rows in list(all_groups.items())[i+1:]:
            right={(r['market'],r['game_id'],r['selection']) for r in other_rows}
            overlap.append(dict(cohort_a=name,cohort_b=other,shared_selections=len(left&right),jaccard=len(left&right)/len(left|right),
                                shared_games=len({r['game_id'] for r in rows}&{r['game_id'] for r in other_rows})))
    ranked=[]
    for market in ('ATS','TOTAL'):
        for label,predicate in [('GOVERNED_TOP5',lambda r:r['governed_top5']=='True'),('RESEARCH_TOP5',lambda r:int(r['research_rank'])<=5),('RESEARCH_REST',lambda r:int(r['research_rank'])>5)]:
            if market=='TOTAL' and label=='GOVERNED_TOP5':continue
            for span,weeks in [('5-11',set(range(5,12))),('7-11_FROZEN_RANKS',set(range(7,12)))]:
                selected=[r for r in all_rows if r['market']==market and int(r['week']) in weeks and predicate(r)]
                ranked.append(dict(scope=span,market=market,cohort=label,**summary(selected)))
    # Earlier artifacts are reported separately because their coverage/rank custody differ.
    from scripts.research_week7_acceptance import load_earlier
    legacy=[]
    for week in (1,2,3):
        for market in ('ATS','TOTAL'):
            rows=[r for r in load_earlier() if r.week==week and r.market==market]
            counts=Counter(r.result for r in rows);n=len(rows);w=counts['WIN'];l=counts['LOSS']
            legacy.append(dict(week=week,market=market,n=n,wins=w,losses=l,pushes=counts['PUSH'],
                               units_minus110=w*10/11-l,hit_rate=w/(w+l) if w+l else None,
                               provenance=sorted({r.provenance for r in rows}),status='LIMITED_EARLIER_COVERAGE_NOT_POOLED_WITH_COMPARABLE_400'))
    findings=dict(custody=verified,weekly=weekly,cohorts=cohort_results,forecasts=forecasts,calibration=calibrations,
                  discrimination=discriminations,cumulative_ranks=ranked,legacy_weeks=legacy,
                  frozen_research=frozen,drive_adjudication=drives,proposal=proposal,season_contest=season,
                  source_capture_through_utc=max(r['received_at_utc'] for r in records.values()),
                  limitations=['Week11 submissions originated outside v3 and are excluded per confirmed owner scope.','Three late-sealed Wednesday games remain qualified.',
                               'No timestamp-qualified closing quotes.','Human confidence comparable latest-review ledger currently covers Weeks9-11; earlier ordinal/context systems are not pooled.',
                               'Week4 full-card predictions and Week1 full totals forecasts remain missing; actual Weeks1-10 submissions are independently graded.',
                               'Original PDF binaries are not in this checkout; PR54 extraction hashes and provenance are retained, not claimed as a fresh visual PDF verification.',
                               'Postgame personnel/OL/defensive snap shares, measured weather, rivalry labels and causal attribution remain incomplete.',
                               'Multiple overlapping methods, one prospective week and repeated teams limit inference.',
                               'Drive anomalies unresolved in part; no promoted drive features.','Nine proposed feature families lack a comparable sanctioned PIT feature ledger for validation.'])
    tables={'game_results_reconciliation.csv':finals,'week11_ats_audit.csv':[r for r in current if r['market']=='ATS'],
            'week11_totals_audit.csv':[r for r in current if r['market']=='TOTAL'],
            'cohort_membership.csv':memberships,'cohort_results.csv':cohort_results,'cohort_overlap.csv':overlap,
            'confidence_calibration.csv':calibrations,'forecast_vs_market.csv':forecasts,'segment_diagnostics.csv':cuts,
            'cumulative_performance.csv':weekly,'cumulative_rank_performance.csv':ranked,'earlier_week_qualified_records.csv':legacy,
            'cumulative_grade_ledger.csv':all_rows,'human_confidence_ledger.csv':human,'ranking_discrimination.csv':discriminations,
            'clv_observations.csv':closing['observations'],'hook_backdoor_audit.csv':[{k:r[k] for k in ('game_id','market','selection','locked_line','result','custody','hook_classification','scoring_sequence_status','backdoor_details')} for r in current],
            'game_process.csv':mechanisms['games'],'team_process.csv':mechanisms['teams'],'observed_passers.csv':mechanisms['passers'],
            'nonoffensive_scoring.csv':mechanisms['scoring'],'logic_failure_priority.csv':mechanisms['failures'],
            'frozen_research_metrics.csv':frozen['full'],'frozen_research_top5.csv':frozen['top5'],
            'frozen_research_membership.csv':frozen['memberships'],'frozen_research_all_grades.csv':frozen['all_rows'],
            'frozen_research_reliability.csv':frozen['reliability'],'frozen_drive_forecasts.csv':frozen['drive'],
            'drive_quarantine_adjudication.csv':drives['rows'],'v29_chronological_folds.csv':proposal['folds'],
            'v29_all_candidate_predictions.csv':proposal['predictions'],'v29_candidate_top5.csv':proposal['top5'],
            'v29_feature_research_catalog.csv':proposal['catalog']}
    tables.update({'season_game_reconciliation.csv':season['finals'],'actual_v3_submission_ledger.csv':season['ledger'],
                  'external_week11_records_not_graded.csv':season['excluded'],'actual_weekly_performance.csv':season['weekly'],
                  'actual_weight_performance.csv':season['weights'],'actual_market_performance.csv':season['by_market'],
                  'season_recommendation_ledger.csv':season['recommendations'],'season_recommendation_performance.csv':season['cohorts'],
                  'submission_recommendation_differences.csv':season['differences'],'historical_line_reconciliation.csv':season['locks'],
                  'week11_export_kickoff_differences.csv':season['kickoff_differences']})
    from scripts.week11_audit_report import reports
    files={name:csv_bytes(canonical(rows)) for name,rows in tables.items()}
    files.update({name:encoded(value) for name,value in {'audit_findings.json':findings,'custody_verification.json':verified,
                  'clv_audit.json':closing,'game_process_evidence.json':mechanisms,'v29_research_protocol.json':proposal['protocol'],
                  'season_contest_quality.json':season['quality']}.items()})
    files.update({name:text.encode('utf8') for name,text in reports(findings,groups,mechanisms,closing).items()})
    from scripts.season_contest_report import report
    files['SEASON_CONTEST_REPORT.md']=report(season).encode('utf8')
    inputs,code_paths=pinned_inputs()
    code={name:sha((ROOT/name).read_bytes().replace(b'\r\n',b'\n')) for name in code_paths}
    files['audit_manifest.json']=encoded(dict(version='week11-forensic-audit-v2-closed-inventory',status='GRADING_COMPLETE_RESEARCH_NOT_PROMOTED',
        original_audit_manifest_sha256=V1_MANIFEST_SHA,original_replay_commit='936352866a21a7b535c9728df7e6a8e979b3f1af',
        season=2026,week=11,prediction_source_commit=SOURCE_COMMIT,base_main_commit='79fa442a3c15d8f3f7435721b3d90db368ae55df',
        game_count=67,recorded_forecasts_per_market=64,forward_sealed_games=61,late_wednesday_games=3,no_tuesday_forecasts=3,
        score_discrepancies=0,owner_approval='WEEKS1_10_SUBMISSION_EXPORTS_CONFIRMED; WEEK11_EXTERNAL_EXCLUDED',source_database_sha256=DB_SHA,
        season_reconciled_games=621,v3_submitted_picks=50,external_ungraded_records=5,
        input_sha256=inputs,code_sha256_lf=code,output_sha256={p:sha(b) for p,b in files.items()},
        schema_changes=False,active_policy_changed=False,master_prompt='v2.8 unchanged; v2.9 proposal only',
        merge_gate='DRAFT_REQUIRES_COMPLETE_CI_AND_INDEPENDENT_REVIEW'))
    return files


def main(verify=False,output=OUT):
    output=output.resolve()
    if not output.is_relative_to(ROOT/'outputs/2026-week11-postgame-audit') and not output.is_relative_to(ROOT/'.local-week11-audit-preview'):
        raise ValueError('Output outside audit boundary')
    if not verify and output.exists():raise FileExistsError('Audit output is immutable; use a new version')
    files=build()
    if verify:verify_files(output,files)
    else:
        output.mkdir(parents=True,exist_ok=False)
        for name,raw in files.items():
            with (output/name).open('xb') as stream:stream.write(raw)
    return dict(status='VERIFIED_READ_ONLY' if verify else 'AUDIT_WRITTEN',files=len(files),games=67,forecasts=128)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--verify',action='store_true');parser.add_argument('--output',type=Path,default=OUT)
    args=parser.parse_args();print(json.dumps(main(args.verify,args.output)))
