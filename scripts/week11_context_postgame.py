"""Join frozen pregame context to audited postgame process without causal inference."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from scripts.week11_audit_inputs import ROOT, source_json, source_files, sha
from scripts.week10_audit_sources import instant
from scripts.build_week9_formal_audit import csv_bytes

OUT = ROOT/'outputs/2026-week11-postgame-audit/context-v2'
FIRST = 'outputs/2026-week11-owner-review/20261112-v1/review.json'
LAST = 'outputs/2026-week11-owner-review/20261113-v2/review.json'


def join_context(process, first, last):
    initial = {r['game_id']:r for r in first['candidates']}
    updates = {r['game_id']:r for r in last['candidate_updates']}
    result=[]
    for failure in process['failures']:
        gid=failure['game_id']; a=initial.get(gid); b=updates.get(gid)
        # A Friday refresh may include an already elapsed Thursday matchup.
        # Keep the earlier eligible review; never relabel the refresh as pregame.
        if a:
            if b and instant(last['created_at_utc'])>=instant(a['kickoff_utc']):b=None
            if instant(first['created_at_utc'])>=instant(a['kickoff_utc']):a=None;b=None
        personnel=[]
        if a:
            for team in a['team_context']:
                original=team.get('availability') or {}
                if not isinstance(original,dict):original={}
                entries={x['name']:x['status'] for x in original.get('entries',[])}
                updated=next((t for t in b.get('teams',[]) if t['team']==team['team']),{}) if b else {}
                report=updated.get('official_report') or {}
                if isinstance(report,dict) and report.get('rows'):entries=report['rows']
                selected={name:status for name,status in entries.items() if name.startswith('QB ') or
                          (name.split(' ',1)[0] in {'OL','OT','OG','C','DL','DT','DE','LB','DB','CB','S','N/S'} and status not in {'Available','Exempt'})}
                personnel.append(team['team']+': '+('; '.join(f'{k}={v}' for k,v in sorted(selected.items())) or 'No usable archived position-status entries'))
        p=failure['process']
        result.append(dict(game_id=gid,away=p['away'],home=p['home'],market=failure['market'],
            selection=failure['selection'],result=failure['result'],taxonomy=failure['taxonomy'],
            context_status='ARCHIVED_PREGAME_REVIEW' if a else 'NO_ELIGIBLE_PREGAME_REVIEW_RECOVERED',
            initial_review_utc=first['created_at_utc'] if a else None,
            final_review_utc=last['created_at_utc'] if b else None,
            pregame_support=a.get('evidence_support') if a else None,
            pregame_risks=a.get('risks') if a else None,
            latest_archived_qb_ol_defense=' | '.join(personnel) if a else None,
            pregame_weather=json.dumps((b or a or {}).get('weather'),sort_keys=True),
            observed_passers='; '.join(f"{x['team']}: {x['name']} ({x.get('C/ATT','attempt count unavailable')}; {x.get('YDS','yards unavailable')} yards)" for x in failure['observed_passers']),
            actual_provider_drives=p['provider_drives'],actual_provider_plays=p['provider_plays'],
            actual_points_per_provider_drive=p['combined_points_per_provider_drive'],
            inference_limit='Available is not starter confirmation; exempt is not medical clearance. No validated snap-share, actual-weather or causal injury adjustment. Points/drive includes nonoffensive scores.',
            source_review=LAST if b else FIRST if a else None,
            original_numeric_adjustments=json.dumps((b or a or {}).get('numeric_adjustments'),sort_keys=True)))
    return result


def build():
    source=ROOT/'outputs/2026-week11-postgame-audit/v1/game_process_evidence.json'
    process=json.loads(source.read_bytes())
    rows=join_context(process,source_json(FIRST),source_json(LAST))
    paragraphs=['# Pregame expectations and observed game process','',
        'This supplement links every priority forecast to its original pregame review, when one exists. It does not manufacture missing personnel reports or reinterpret postgame participation as pregame knowledge. The A–H taxonomy remains the original audit classification.', '',
        'The frozen review contained qualitative injury, matchup and coaching concerns but no numeric projection adjustments. A subsequent loss does not identify the size or direction of a valid adjustment. Conversely, the removed extreme Unders went 3–1: cautionary context did not reliably rank this week’s outcomes.', '']
    for r in rows:
        paragraphs.extend([f"## {r['away']} at {r['home']} — {r['market']} {r['selection']}",'',
            f"Grade {r['result']}; taxonomy {r['taxonomy']}; evidence {r['context_status']}.",'',
            '**Before kickoff — supporting case:** '+str(r['pregame_support'] or 'No game-specific review recovered.'),'',
            '**Before kickoff — risks:** '+str(r['pregame_risks'] or 'Unavailable.'),'',
            '**Latest archived availability:** '+str(r['latest_archived_qb_ol_defense'] or 'Unavailable.'),'',
            '**Observed postgame passers:** '+r['observed_passers'],'',
            f"Observed {r['actual_provider_plays']} plays and {r['actual_provider_drives']} provider drives; combined points per provider drive {r['actual_points_per_provider_drive']:.3f}.",'',r['inference_limit'],'',
            'Frozen review: '+str(r['source_review'] or 'None')+'. Complete forecast weather and timestamps are retained in the companion CSV.',''])
    files={'pregame_context_comparison.csv':csv_bytes(rows),'PREGAME_CONTEXT_COMPARISON.md':'\n'.join(paragraphs).encode('utf-8')}
    manifest=dict(rows=len(rows),status='POSTGAME_COMPARISON_ONLY',
        input_sha256={FIRST:sha(source_files()[FIRST]),LAST:sha(source_files()[LAST]),source.relative_to(ROOT).as_posix():sha(source.read_bytes())},
        code_sha256_lf=sha(Path(__file__).read_bytes().replace(b'\r\n',b'\n')),
        output_sha256={name:sha(raw) for name,raw in files.items()})
    files['manifest.json']=(json.dumps(manifest,indent=2,sort_keys=True)+'\n').encode()
    return files


def main(verify=False):
    if not verify and OUT.exists():raise FileExistsError('Immutable supplement already exists')
    files=build()
    if verify:
        if {p.name for p in OUT.iterdir()}!=set(files):raise ValueError('Context file inventory differs')
        for name,raw in files.items():
            if (OUT/name).read_bytes()!=raw:raise ValueError('Context replay mismatch: '+name)
    else:
        OUT.mkdir(parents=True)
        for name,raw in files.items():(OUT/name).write_bytes(raw)
    return dict(status='VERIFIED_READ_ONLY' if verify else 'WRITTEN',files=len(files))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--verify',action='store_true')
    print(json.dumps(main(parser.parse_args().verify)))
