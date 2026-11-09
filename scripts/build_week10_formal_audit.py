"""Append-only forensic Week10 audit, with exact read-only replay."""
import argparse
import json
from pathlib import Path
from scripts.week10_audit_sources import ROOT, BOARD, CAPTURE, DEPENDENCY, read_json, read_csv, sha, captures, reconcile
from scripts.week10_audit_grading import build_grades, cohort_membership
from scripts.week10_audit_diagnostics import analyze
from scripts.week10_audit_game_process import analyze_process
from scripts.week10_research_audit import analyze as analyze_research
from scripts.week10_audit_forensics import analyze as forensics, clv, source_reconciliation
from scripts.build_week9_formal_audit import csv_bytes, serialized, verify_files, custody as historical_custody
from scripts.verify_week10_acceptance import verify as verify_board

OUT=ROOT/'outputs/2026-week10-postgame-audit/v2'
FIXTURE=ROOT/'tests/fixtures/week10_formal_audit/input-custody-v1.json'
INPUT_SHA='c6cef583b6a7968977dda89d61163ba830e9b11ee7a8db96e37e8c3e5346528a'
CODE=['scripts/'+name+'.py' for name in ('build_week10_formal_audit','week10_audit_sources','week10_audit_grading','week10_audit_diagnostics','week10_audit_game_process','week10_audit_forensics','week10_research_audit','week10_research_metrics','week10_audit_report','capture_week10_postgame')]


def custody():
    raw=FIXTURE.read_bytes()
    if sha(raw)!=INPUT_SHA:raise ValueError('Week10 custody fixture identity')
    fixture=json.loads(raw)
    if fixture['historical_artifacts_changed'] is not False or fixture['dependency_commit']!=DEPENDENCY:raise ValueError('custody status contradiction')
    for name,digest in fixture['sha256_by_path'].items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or sha(path.read_bytes())!=digest:raise ValueError('protected input changed: '+name)
    old=historical_custody();board=verify_board()
    return dict(input_files_verified=len(fixture['sha256_by_path']),input_fixture_sha256=INPUT_SHA,historical=old,week10_board=board,
                source_database_sha256=fixture['source_database_sha256'],source_reconciliation=source_reconciliation())


def canonical(value):
    if isinstance(value,float):return round(value,10)
    if isinstance(value,dict):return {k:canonical(v) for k,v in value.items()}
    if isinstance(value,list):return [canonical(v) for v in value]
    return value


def build():
    from scripts.week10_audit_report import report
    verified=custody();manifest,records,data=captures();finals,reconciliation=reconcile(data,records)
    grades,_,sequences=build_grades(finals,data);members=cohort_membership(grades)
    diagnostics=analyze(grades,members);process=analyze_process(finals,grades,data);research=analyze_research(finals)
    # Round derived statistics only. Original source and candidate prediction rows retain all frozen precision.
    for name in ('full_card','cohorts','primary_paired','week_by_week_primary'):research[name]=canonical(research[name])
    findings=forensics(grades,members,process,diagnostics)
    for name in ('forecast_distributions','paired_forecast_uncertainty'):findings[name]=canonical(findings[name])
    closing=clv(finals)
    # Independently computed frozen shadow grades must agree with the official-card grader.
    frozen={(r['market'],r['game_id']):r for r in research['all_candidate_rows'] if r['candidate']=='FROZEN_V28'}
    if any(frozen[r['market'],r['game_id']]['candidate_result']!=r['result'] for r in grades):raise ValueError('independent graders disagree')
    tables={'week10_final_scores.csv':finals,'week10_ats_audit.csv':[r for r in grades if r['market']=='ATS'],
            'week10_totals_audit.csv':[r for r in grades if r['market']=='TOTAL'],
            'frozen_cohort_membership.csv':members,'frozen_cohort_results.csv':diagnostics['frozen_cohorts'],
            'cross_week_results.csv':diagnostics['weekly'],'nonoverlapping_rank_segments.csv':diagnostics['nonoverlapping_rank_segments'],
            'all_diagnostic_segments.csv':diagnostics['segments'],'confidence_calibration.csv':diagnostics['confidence_calibration'],
            'predictive_discrimination.csv':diagnostics['predictive_discrimination'],
            'game_process.csv':process['games'],'team_process.csv':process['teams'],'observed_passers.csv':process['observed_passers'],
            'research_full_card_metrics.csv':research['full_card'],'research_top5_metrics.csv':research['cohorts'],
            'research_all_candidate_grades.csv':research['all_candidate_rows'],'research_top5_membership.csv':research['cohort_selections'],
            'research_week_by_week.csv':research['week_by_week_primary'],'walk_forward_research.csv':diagnostics['walk_forward_candidates']}
    files={name:csv_bytes(rows) for name,rows in tables.items()}
    files.update({name:serialized(value) for name,value in {'custody_verification.json':verified,'score_reconciliation.json':reconciliation,
        'cross_week_diagnostics.json':diagnostics,'game_process_evidence.json':process,'scoring_sequence_review.json':sequences,
        'research_audit.json':research,'forensic_findings.json':findings,'clv_evidence.json':closing}.items()})
    files['WEEK10_FORMAL_AUDIT.md']=report(verified,grades,members,diagnostics,process,research,findings,closing,sequences).encode('utf8')
    files['audit_manifest.json']=serialized(dict(version='week10-forensic-audit-v2',audit_status='FORMAL_GRADING_COMPLETE',season=2026,week=10,
        supersedes_verification_only='v1; stricter capture status and file coverage, original audit and generating source retained',
        previous_manifest_sha256=sha((ROOT/'outputs/2026-week10-postgame-audit/v1/audit_manifest.json').read_bytes()),
        game_count=57,ats_count=57,totals_count=57,score_discrepancies=0,independent_grading_discrepancies=0,
        owner_approval='NO_APPROVAL_ARTIFACT_IDENTIFIED',clv_status='INCOMPLETE',historical_artifacts_changed=False,model_or_policy_changes=False,
        policy='Master Prompt v2.8 UNCHANGED',dependency_pr=49,dependency_commit=DEPENDENCY,research_source_pr=50,research_source_commit='8b6ee3b5c7b32113587c8d8ce730ff7750e2c0a8',
        capture_manifest=CAPTURE.relative_to(ROOT).as_posix()+'/capture-manifest.json',capture_manifest_sha256=sha((CAPTURE/'capture-manifest.json').read_bytes()),
        captured_through_utc=max(r['received_at_utc'] for r in records.values()),input_custody_sha256=INPUT_SHA,
        code_sha256_lf={p:sha((ROOT/p).read_bytes().replace(b'\r\n',b'\n')) for p in CODE},output_sha256={p:sha(raw) for p,raw in sorted(files.items())},
        merge_gate='REQUIRES_EXACT_TREE_CI_AND_TECHNICAL_REVIEW;NO_AUTOMATIC_MERGE',research_status='RESEARCH_ONLY_NO_PROMOTION'))
    return files


def write_new(output,files):
    output=output.resolve()
    if output.exists() or not output.is_relative_to(ROOT/'outputs/2026-week10-postgame-audit'):raise ValueError('new audit version required; overwrite forbidden')
    if any(Path(name).name!=name or not isinstance(raw,bytes) for name,raw in files.items()):raise ValueError('invalid output')
    output.mkdir(parents=True,exist_ok=False)
    for name,raw in files.items():
        with (output/name).open('xb') as stream:stream.write(raw)


def main(verify=False,output=OUT):
    if not verify and output.exists():raise ValueError('new audit version required; overwrite forbidden')
    files=build()
    if verify:verify_files(output,files)
    else:write_new(output,files)
    return dict(status='VERIFIED_READ_ONLY' if verify else 'AUDIT_WRITTEN',games=57,selections=114,files=len(files),clv='INCOMPLETE',policy_changed=False)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');p.add_argument('--output',type=Path,default=OUT);a=p.parse_args()
    print(json.dumps(main(a.verify,a.output)))
