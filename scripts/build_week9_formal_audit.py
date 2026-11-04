"""Build an additive formal Week 9 audit, or verify its bytes without writing."""
from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
from pathlib import Path

from scripts.week9_audit_sources import ROOT, BOARD, BASELINE, DEPENDENCY, captures, reconcile, read_json, sha
from scripts.week9_audit_grading import build_grades, cohort_membership
from scripts.week9_audit_diagnostics import analyze
from scripts.week9_audit_game_process import analyze_process

OUT = ROOT / 'outputs/2026-week9-postgame-audit/v1'
FIXTURE = ROOT / 'tests/fixtures/week9_formal_audit/input-custody-v1.json'
INPUT_FIXTURE_SHA256 = 'df58c3e13192bb4c95568ceb01e72f3f741184ae9647301ec363eaade6387dbe'
CODE = ('scripts/week9_audit_sources.py', 'scripts/week9_audit_grading.py',
        'scripts/week9_audit_diagnostics.py', 'scripts/week9_audit_game_process.py',
        'scripts/build_week9_formal_audit.py', 'scripts/week9_audit_report.py')


def serialized(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + '\n').encode('utf-8')


def csv_bytes(rows) -> bytes:
    fields = list(dict.fromkeys(k for row in rows for k in row))
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator='\n')
    writer.writeheader()
    writer.writerows({k: json.dumps(v, ensure_ascii=False, sort_keys=True) if isinstance(v, (dict, list)) else v for k, v in row.items()} for row in rows)
    return stream.getvalue().encode('utf-8')


def custody():
    raw = FIXTURE.read_bytes()
    if sha(raw) != INPUT_FIXTURE_SHA256:
        raise ValueError('input checksum coverage fixture changed')
    manifest = json.loads(raw)
    if manifest['historical_artifacts_changed'] is not False or manifest['baseline_commit'] != BASELINE or manifest['dependency_commit'] != DEPENDENCY:
        raise ValueError('input custody status contradiction')
    for relative, expected in manifest['sha256_by_path'].items():
        path = (ROOT / relative).resolve()
        if not path.is_relative_to(ROOT) or sha(path.read_bytes()) != expected:
            raise ValueError('protected input checksum mismatch: ' + relative)
    database = ROOT / 'data/cfb.db'
    with sqlite3.connect(database.as_uri() + '?mode=ro&immutable=1', uri=True) as connection:
        integrity = connection.execute('PRAGMA integrity_check').fetchall()
        foreign_keys = connection.execute('PRAGMA foreign_key_check').fetchall()
        counts = {name: connection.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0]
                  for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
    if integrity != [('ok',)] or foreign_keys:
        raise ValueError('source database integrity failure')
    if sha(database.read_bytes()) != manifest['source_database_sha256']:
        raise ValueError('database changed during readonly verification')
    return dict(input_files_verified=len(manifest['sha256_by_path']), original_protected_files_verified=manifest['original_protected_files_verified'],
                fixture_sha256=INPUT_FIXTURE_SHA256, source_database_sha256=manifest['source_database_sha256'],
                database_integrity='ok', database_foreign_key_violations=0, source_database_row_counts=counts)


def clv_evidence(finals):
    observations = []
    for path in sorted((ROOT/'outputs/2026-week9-context').glob('*/market-observations.json')):
        value = read_json(path)
        for observation in value['observations']:
            if observation['closing_line_qualified'] or observation.get('provider_quote_timestamp'):
                raise ValueError('unexpected closing evidence requires explicit versioned adjudication')
            observations.append(dict(observation, evidence_file=path.relative_to(ROOT).as_posix()))
    return dict(status='INCOMPLETE', qualified_closes=0, timestamped_pregame_observations=len(observations),
                reason='Archived observations have pregame receipt times but no provider quote timestamps or qualified final pre-kickoff close. Postgame pickcenter/odds labels are excluded.',
                games=[dict(game_id=f['game_id'], status='INCOMPLETE', qualified_closing_spread=None, qualified_closing_total=None,
                            ats_clv=None, total_clv=None, pregame_observation_count=sum(str(o['game_id']) == f['game_id'] for o in observations)) for f in finals],
                observations=observations, blocks_unrelated_code_merges=False)


def build():
    from scripts.week9_audit_report import report
    verified = custody()
    capture, records, data = captures()
    finals, supersession = reconcile(data, records)
    grades, comparisons, sequences = build_grades(finals, data)
    members = cohort_membership(grades)
    diagnostics = analyze(grades, members)
    process = analyze_process(finals, grades, data)
    clv = clv_evidence(finals)
    supersession['grade_reconciliations'] = comparisons
    supersession['grade_discrepancy_count'] = sum(not all(r['matches'].values()) for r in comparisons)
    tables = {
        'week9_final_scores.csv': finals,
        'week9_ats_audit.csv': [r for r in grades if r['market'] == 'ATS'],
        'week9_totals_audit.csv': [r for r in grades if r['market'] == 'TOTAL'],
        'frozen_cohort_membership.csv': members,
        'frozen_cohort_results.csv': diagnostics['frozen_cohorts'],
        'cross_week_results.csv': diagnostics['weekly'],
        'nonoverlapping_rank_segments.csv': diagnostics['nonoverlapping_rank_segments'],
        'all_diagnostic_segments.csv': diagnostics['segments'],
        'confidence_calibration.csv': diagnostics['confidence_calibration'],
        'game_process.csv': process['games'], 'team_process.csv': process['teams'],
        'observed_passers.csv': process['observed_passers'],
        'walk_forward_research.csv': diagnostics['walk_forward_candidates'],
    }
    output = {name: csv_bytes(rows) for name, rows in tables.items()}
    output.update({name: serialized(value) for name, value in {
        'supersession.json': supersession, 'cross_week_diagnostics.json': diagnostics,
        'game_process_evidence.json': process, 'scoring_sequence_review.json': sequences,
        'clv_evidence.json': clv, 'custody_verification.json': verified,
    }.items()})
    output['WEEK9_FORMAL_AUDIT.md'] = report(finals, grades, diagnostics, process, sequences, clv, verified).encode('utf-8')
    manifest = dict(version='week9-formal-audit-v1', season=2026, week=9,
                    audit_status='FORMAL_GRADING_COMPLETE', game_count=54, ats_count=54, totals_count=54,
                    clv_status='INCOMPLETE', owner_approval='PENDING', policy='Master Prompt v2.8 UNCHANGED',
                    historical_artifacts_changed=False, model_or_policy_changes=False,
                    preliminary_baseline_commit=BASELINE, required_dependency_pr=47, required_dependency_commit=DEPENDENCY,
                    source_capture_manifest='outputs/2026-week9-postgame-evidence/20261104T150801Z/capture-manifest.json',
                    optional_capture_failure='Original /games/advanced 404 preserved; /stats/game/advanced captured separately in supplemental version.',
                    captured_through_utc=max(r['received_at_utc'] for r in records.values()),
                    input_custody_sha256=INPUT_FIXTURE_SHA256,
                    code_sha256_lf={p: sha((ROOT/p).read_bytes().replace(b'\r\n', b'\n')) for p in CODE},
                    output_sha256={name: sha(raw) for name, raw in sorted(output.items())},
                    merge_gate='HOLD_UNTIL_EXACT_TREE_CI_AND_INDEPENDENT_REVIEW',
                    research_status='ALL_NEW_DIAGNOSTICS_AND_NUMERIC_PROPOSALS_RESEARCH_ONLY')
    output['audit_manifest.json'] = serialized(manifest)
    return output


def write_new(output: Path, files: dict[str, bytes]):
    output = output.resolve()
    if not output.is_relative_to(ROOT/'outputs/2026-week9-postgame-audit') or output.exists():
        raise ValueError('audit writer requires a new version directory; overwrite forbidden')
    for name, raw in files.items():
        if Path(name).name != name:
            raise ValueError('invalid output filename')
        if not isinstance(raw, bytes):
            raise ValueError('output bytes required')
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        with (output/name).open('xb') as stream:
            stream.write(raw)


def verify_files(output: Path, expected: dict[str, bytes]):
    names = {p.name for p in output.iterdir() if p.is_file()}
    if names != set(expected) or any(p.is_dir() for p in output.iterdir()):
        raise ValueError('exact audit output checksum coverage mismatch')
    actual_manifest = read_json(output/'audit_manifest.json')
    if actual_manifest != json.loads(expected['audit_manifest.json']):
        raise ValueError('manifest checksum coverage or audit status contradiction')
    for name, raw in expected.items():
        if (output/name).read_bytes() != raw:
            raise ValueError('formal replay mismatch: ' + name)


def main(verify=False, output=OUT):
    if not verify and output.exists():
        raise ValueError('audit writer requires a new version directory; overwrite forbidden')
    files = build()
    if verify:
        verify_files(output, files)
    else:
        write_new(output, files)
    return dict(status='VERIFIED_READ_ONLY' if verify else 'ADDITIVE_AUDIT_WRITTEN', games=54, selections=108,
                files=len(files), exact_replay=True, clv_status='INCOMPLETE', owner_approval='PENDING', policy_changed=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--output', type=Path, default=OUT)
    args = parser.parse_args()
    print(json.dumps(main(args.verify, args.output), sort_keys=True))
