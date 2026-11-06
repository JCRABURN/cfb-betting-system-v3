"""Fail-closed byte-exact historical replay acceptance across supported runtimes."""
from __future__ import annotations
import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
from scripts import replay_compat_v1 as compat

def exact(path,raw):
    archived=path.read_bytes()
    if archived!=raw:raise ValueError('byte-exact compatibility replay mismatch: '+str(path))
    return {'path':path.relative_to(compat.ROOT).as_posix(),'archived_sha256':hashlib.sha256(archived).hexdigest(),
            'computed_sha256':hashlib.sha256(raw).hexdigest(),'exact':True}

def verify():
    compat.verify_legacy_code()
    w7=compat.strict.verify();research=compat.strict.verify_research()
    data,tables=compat.week7.evaluate()
    identities=[exact(compat.week7.OUTPUT/'week7_diagnostics.json',(json.dumps(data,indent=2,sort_keys=True)+'\n').encode()),
                exact(compat.week7.OUTPUT/'week7_postgame_report.md',compat.week7.report(data,tables).encode())]
    for name,rows in tables.items():
        fields=list(dict.fromkeys(k for row in rows for k in row));s=io.StringIO(newline='')
        writer=csv.DictWriter(s,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)
        identities.append(exact(compat.week7.OUTPUT/name,s.getvalue().encode()))
    w8=compat.week8.main(True)
    _,files=compat.week8.payloads()
    identities.extend(exact(compat.week8.OUTPUT/name,raw) for name,raw in sorted(files.items()))
    compat.week8_research.main(True)
    identities.append(exact(compat.ROOT/'outputs/2026-week8-audit-research/numerical_research_candidates.json',
                            compat.week8.serialized(compat.week8_research.calculate())))
    context=[]
    # PR44 predates Week 9: no Week 9 gate is applicable to that tree.
    # When present, every archived derived context must have a pinned profile.
    if (compat.ROOT/'scripts/review_week9_context.py').exists():
        from scripts import replay_week9_compat as week9
        from scripts.seal_week9_board import main as seal
        seal(True)
        for path in sorted((compat.ROOT/'outputs/2026-week9-context').glob('*/derived_context_board.json')):
            result=week9.main(path.parent);context.append({'capture':path.parent.name,**result})
            identities.append(exact(path,(json.dumps(week9.build(path.parent),indent=2,sort_keys=True,allow_nan=False)+'\n').encode()))
    return {'version':compat.VERSION,'week7_grading':w7['grading_status'],'week7_formal_status':w7['formal_audit_status'],
       'research_custody':research,'week8':w8,'week9_context':context,'exact_output_identities':identities,
       'model_policy_change':False,'historical_artifacts_rewritten':False,'clv_status':'INCOMPLETE'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path);args=p.parse_args();result=verify()
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8',newline='\n') as stream:stream.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps({'version':result['version'],'exact_outputs':len(result['exact_output_identities']),
      'week7':result['week7_grading'],'week8':result['week8']['grading_status'],'week9_contexts':len(result['week9_context']),
      'clv_status':'INCOMPLETE'}))
