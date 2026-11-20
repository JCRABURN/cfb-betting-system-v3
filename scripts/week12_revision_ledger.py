"""Append-only review revisions; started rows and source lines cannot change."""
from __future__ import annotations
import argparse
import csv
import json
import math
from pathlib import Path
from scripts.prepare_week12_source import ROOT, digest, serialized, timestamp

FIELDS=('ats_selection','projected_home_margin','ats_confidence','ats_raw_score_not_probability',
        'totals_selection','projected_total','totals_raw_normal_probability','totals_legacy_confidence',
        'calibrated_probability','common_calibrated_rank','review_rank','contest_chip',
        'ats_selected_spread','home_ats_edge','total_edge')
IDENTITY=('away','home','kickoff_utc','locked_home_spread','locked_total','original_pdf_sha256')

def changes(previous, current, as_of, reason, model_version, evidence):
    if not reason.strip() or not evidence or not model_version:raise ValueError('revision provenance required')
    old={int(r['game_id']):r for r in previous};new={int(r['game_id']):r for r in current}
    if len(old)!=len(previous) or len(new)!=len(current) or set(old)!=set(new) or len(old)!=66:
        raise ValueError('exact 66-game revision coverage required')
    result=[]
    for gid,a in old.items():
        b=new[gid]
        if any(a[k]!=b[k] for k in IDENTITY):raise ValueError('frozen source identity or line changed')
        if timestamp(a['kickoff_utc'])<=as_of and a!=b:raise ValueError('started-game row changed')
        if b.get('calibrated_probability') or b.get('common_calibrated_rank'):
            raise ValueError('no approved common calibration policy')
        if b.get('ats_selection'):
            if b['ats_selection'] not in (b['home'],b['away']):raise ValueError('invalid ATS selection')
            selected=float(b['locked_home_spread'])*(1 if b['ats_selection']==b['home'] else -1)
            if float(b['ats_selected_spread'])!=selected:raise ValueError('selected ATS line does not match frozen source')
            if b['totals_selection'] not in ('over','under'):raise ValueError('invalid total selection')
            if any(not 1<=int(b[k])<=5 for k in ('ats_confidence','totals_legacy_confidence')):
                raise ValueError('confidence outside 1-5')
            for field in ('projected_home_margin','projected_total','ats_raw_score_not_probability','totals_raw_normal_probability'):
                if not math.isfinite(float(b[field])):raise ValueError('nonfinite model value')
        if any(a.get(k)!=b.get(k) for k in set(a)|set(b) if k not in FIELDS):
            raise ValueError('untracked revision field changed')
        for field in FIELDS:
            if a.get(field)!=b.get(field):
                result.append(dict(game_id=gid,field=field,previous=a.get(field),current=b.get(field),
                                   timestamp_utc=as_of.isoformat(),reason=reason,model_version=model_version,evidence=evidence))
    chips=[int(r['contest_chip']) for r in current if r.get('contest_chip')]
    if chips and sorted(chips)!=[1,2,3,4,5]:raise ValueError('five distinct games and chips 1-5 required')
    return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--previous',type=Path,required=True);p.add_argument('--current',type=Path,required=True)
    p.add_argument('--as-of',required=True);p.add_argument('--reason',required=True);p.add_argument('--model-version',required=True)
    p.add_argument('--evidence',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    as_of=timestamp(a.as_of)
    from datetime import datetime,timezone,timedelta
    now=datetime.now(timezone.utc)
    if not timedelta(0)<=now-as_of<=timedelta(minutes=5):raise ValueError('revision timestamp must be current, never backdated')
    out=a.output.resolve()
    if not out.is_relative_to(ROOT/'outputs/2026-week12-refresh'):raise ValueError('revision boundary')
    from scripts.verify_week12_acceptance import main as verify_initial
    verify_initial()
    evidence=(ROOT/a.evidence).resolve()
    if not evidence.is_relative_to(ROOT) or not evidence.is_file():raise ValueError('recorded evidence file required')
    read=lambda path:list(csv.DictReader(path.open(encoding='utf-8-sig',newline='')))
    previous,current=read(a.previous),read(a.current)
    # Use the actual execution time too: a supplied earlier timestamp cannot revive a started game.
    changes(previous,current,now,a.reason,a.model_version,a.evidence)
    rows=changes(previous,current,as_of,a.reason,a.model_version,a.evidence)
    payload=dict(as_of_utc=as_of.isoformat(),previous_sha256=digest(a.previous.read_bytes()),current_sha256=digest(a.current.read_bytes()),
                 changes=rows,reason=a.reason,evidence=a.evidence,evidence_sha256=digest(evidence.read_bytes()),model_version=a.model_version)
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('xb') as f:f.write(serialized(payload))
    print(json.dumps(dict(changes=len(rows),output=str(out))))

if __name__=='__main__':main()
