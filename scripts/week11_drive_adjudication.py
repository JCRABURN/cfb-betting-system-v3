"""Resolve drive-score anomalies only where scoring-play evidence corroborates them."""
import gzip
import json
from collections import defaultdict, Counter
from scripts.week11_audit_inputs import ROOT, EVIDENCE, source_json, source_files, sha
from scripts.week10_audit_sources import load_response
from scripts.week8_scoring_sequence_review import validate_sequence


def adjudicate():
    folders={8:ROOT/'outputs/2026-week8-postgame-audit/provider-evidence',
             9:ROOT/'outputs/2026-week9-postgame-evidence/20261104T150801Z',
             10:ROOT/'outputs/2026-week10-postgame-evidence/20261109T152127Z'}
    inputs={}; by_drive=defaultdict(list)
    for week,folder in folders.items():
        path=(EVIDENCE/'drive-supplement-v1/cfbd-week8-plays.json.gz') if week==8 else folder/'cfbd-plays.json.gz'
        raw=path.read_bytes();inputs[path.relative_to(ROOT).as_posix()]=sha(raw)
        if week==8:
            record=json.loads((path.parent/'capture-manifest.json').read_bytes())
        else:
            manifest=json.loads((folder/'capture-manifest.json').read_bytes())
            record=next(r for r in manifest['records'] if r['name']=='cfbd-plays')
        for p in load_response(path.parent,record):
            by_drive[str(p['driveId'])].append(p)
    quarantined=source_json('research/week11_validation/forward-v1.json')['drive_quarantine']
    outcomes=[]; sequences={}
    for q in quarantined:
        gid=str(q['game_id']);week=q['week'];drive=str(q['drive_id'])
        path=folders[week]/(('espn-game-' if week==8 else 'espn-')+gid+'.json.gz')
        if not path.exists() and (EVIDENCE/'drive-summaries-v1'/('espn-'+gid+'.json.gz')).exists():
            path=EVIDENCE/'drive-summaries-v1'/('espn-'+gid+'.json.gz')
            manifest=json.loads((path.parent/'capture-manifest.json').read_bytes())
            record=next(r for r in manifest['records'] if r['game_id']==gid)
            load_response(path.parent,record)
        row=dict(q,adjudication_status='UNRESOLVED_REMAINS_QUARANTINED',corrected_offensive_points=None,
                 correction_scope='DERIVED_POSTGAME_RESEARCH_ONLY;ORIGINAL_ROWS_AND_FORWARD_PROTOTYPE_UNCHANGED')
        if not path.exists():
            row['reason']='Missing independently archived ESPN summary';outcomes.append(row);continue
        if gid not in sequences:
            raw=path.read_bytes();inputs[path.relative_to(ROOT).as_posix()]=sha(raw)
            e=json.loads(gzip.decompress(raw));sides={x['homeAway']:x for x in e['header']['competitions'][0]['competitors']}
            seq=e.get('scoringPlays',[])
            try:
                validate_sequence(seq,int(sides['away']['score']),int(sides['home']['score']))
            except (ValueError,KeyError,TypeError):
                sequences[gid]=None
            else:
                events={};last=0
                for p in seq:
                    points=p['homeScore']+p['awayScore'];events[str(p['id'])]=(p,points-last);last=points
                sequences[gid]=(events,sides)
        if sequences[gid] is None or not by_drive[drive]:
            row['reason']='Scoring sequence invalid or drive play IDs unavailable';outcomes.append(row);continue
        events,sides=sequences[gid]
        points=0;matches=[];unresolved=False
        offense_id=next((str(t['team']['id']) for t in sides.values() if t['team'].get('displayName')==q['offense']),None)
        # Provider abbreviations differ: derive identity from validated archived CFBD play home/away names.
        sample=by_drive[drive][0]
        if q['offense'] in (sample['home'],sample['away']):
            offense_id=str(sides['home' if q['offense']==sample['home'] else 'away']['team']['id'])
        for p in by_drive[drive]:
            if not p['scoring']:
                continue
            event=events.get(str(p['id']))
            if event is None:
                unresolved=True;continue
            e,delta=event
            if p['period']!=e['period']['number']:
                unresolved=True;continue
            offensive=e['type']['text'] in {'Passing Touchdown','Rushing Touchdown','Field Goal Good'}
            if offensive and str(e.get('team',{}).get('id'))==offense_id:
                points+=delta
                matches.append(dict(play_id=p['id'],espn_type=e['type']['text'],cfbd_type=p['playType'],points_with_bundled_conversion=delta))
        allowed={6,7,8} if q['drive_result']=='TD' else {3} if q['drive_result']=='FG' else {0}
        if not unresolved and offense_id is not None and points in allowed and (matches or points==0):
            row.update(adjudication_status='RESOLVED_BY_CROSS_PROVIDER_SCORING_PLAY_IDS',corrected_offensive_points=points,
                       reason='Original drive score endpoints contradict validated scoring sequence. Derived points use exact scoring-play deltas, including documented bundled conversions; no assumed seven-point touchdowns.',scoring_evidence=matches)
        else:
            row['reason']='Drive result, offensive attribution or scoring-play coverage remains contradictory'
        outcomes.append(row)
    return dict(rows=outcomes,counts=dict(Counter(r['adjudication_status'] for r in outcomes)),input_sha256=inputs,
                usage='Resolved rows are a proposed reproducible postgame correction ledger, not repaired original data. Unresolved rows and affected team-games remain excluded. No drive-model expansion or historical pregame-availability claim.')
