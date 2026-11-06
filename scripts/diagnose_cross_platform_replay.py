"""Read-only native-runtime comparisons. Never writes archived artifacts."""
from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.metadata
import io
import json
import math
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import TZPATH

ROOT = Path(__file__).resolve().parents[1]

def digest(raw):
    return hashlib.sha256(raw).hexdigest()

def difference(expected, actual, path='$'):
    """All unequal leaves, including exact type changes; no numeric tolerance."""
    if type(expected) is type(actual) and isinstance(expected, dict):
        rows=[]
        for key in sorted(set(expected)|set(actual)):
            if key not in expected or key not in actual:
                rows.append(dict(path=path+'/'+key,expected=expected.get(key),actual=actual.get(key),
                    expected_type=type(expected.get(key)).__name__ if key in expected else 'MISSING',
                    actual_type=type(actual.get(key)).__name__ if key in actual else 'MISSING'))
            else:rows.extend(difference(expected[key],actual[key],path+'/'+key))
        return rows
    if type(expected) is type(actual) and isinstance(expected,list) and len(expected)==len(actual):
        return [r for i,(e,a) in enumerate(zip(expected,actual)) for r in difference(e,a,path+'/'+str(i))]
    if type(expected) is not type(actual) or expected!=actual:
        r=dict(path=path,expected=expected,actual=actual,expected_type=type(expected).__name__,actual_type=type(actual).__name__)
        if type(expected) is float and type(actual) is float:
            r.update(expected_hex=expected.hex(),actual_hex=actual.hex(),absolute_difference=abs(expected-actual),
                     ulps=abs(expected-actual)/math.ulp(expected))
        return [r]
    return []

def compare(path,raw):
    old=path.read_bytes();suffix=path.suffix
    result={'path':path.relative_to(ROOT).as_posix(),'archived_sha256':digest(old),
            'computed_sha256':digest(raw),'byte_identical':old==raw,
            'first_different_byte':next((i for i,(a,b) in enumerate(zip(old,raw)) if a!=b),min(len(old),len(raw)) if old!=raw else None)}
    if suffix=='.json':result['differences']=difference(json.loads(old),json.loads(raw))
    elif suffix=='.csv':result['differences']=difference(list(csv.DictReader(io.StringIO(old.decode('utf-8-sig')))),list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))))
    else:result['differences']=[] if old==raw else [{'path':'$text','expected':old.decode('utf-8'),'actual':raw.decode('utf-8'),'expected_type':'str','actual_type':'str'}]
    return result

def compensated(values,start=0):
    """Diagnostic Neumaier control; explicit arithmetic, independent of builtin sum."""
    total=start;correction=0.0
    for value in values:
        if type(total) is int and type(value) in (int,bool):total+=value;continue
        x=float(value);t=total+x
        correction += (total-t)+x if abs(total)>=abs(x) else (x-t)+total
        total=t
    return total+correction if correction and math.isfinite(correction) else total

def run(output):
    from scripts import build_week7_postgame_audit as w7
    from scripts import build_week8_postgame_audit as w8
    from scripts import week8_numerical_research as research
    output=output.resolve()
    if output.exists():raise FileExistsError('diagnostic output exists')
    output.mkdir(parents=True)
    records=[];native={}
    def add(path,raw):
        r=compare(path,raw);records.append(r)
        name=path.parent.name+'--'+path.name
        (output/name).write_bytes(raw)
        native[r['path']]=raw
    d,tables=w7.evaluate()
    add(w7.OUTPUT/'week7_diagnostics.json',(json.dumps(d,indent=2,sort_keys=True)+'\n').encode())
    for name,rows in tables.items():
        fields=list(dict.fromkeys(k for r in rows for k in r));s=io.StringIO(newline='')
        writer=csv.DictWriter(s,fieldnames=fields,lineterminator='\n');writer.writeheader();writer.writerows(rows)
        add(w7.OUTPUT/name,s.getvalue().encode())
    add(w7.OUTPUT/'week7_postgame_report.md',w7.report(d,tables).encode())
    data,files=w8.payloads()
    for name,raw in files.items():add(w8.OUTPUT/name,raw)
    expected_manifest=w8.read_json(w8.OUTPUT/'week8_postgame_manifest.json')
    manifest={'audit_version':'week8-postgame-v1','grading_status':data['grading_status'],
      'formal_audit_status':data['formal_audit_status'],'clv_status':'INCOMPLETE',
      'owner_approval_status':data['custody']['owner_approval_status'],
      'output_sha256':{n:digest(b) for n,b in files.items()},
      'evidence_sha256':{p.relative_to(w8.OUTPUT).as_posix():w8.sha(p) for p in sorted(w8.EVIDENCE.rglob('*')) if p.is_file()},
      'audit_code_sha256_lf':{n:w8.source_sha(ROOT/n) for n in w8.CODE_FILES},'protected_sha256':data['custody']['protected_sha256']}
    add(w8.OUTPUT/'week8_postgame_manifest.json',w8.serialized(manifest))
    add(ROOT/'outputs/2026-week8-audit-research/numerical_research_candidates.json',w8.serialized(research.calculate()))
    if (ROOT/'scripts/review_week9_context.py').exists():
        from scripts import review_week9_context as context
        folder=ROOT/'outputs/2026-week9-context/20261028T1320Z'
        add(folder/'derived_context_board.json',(json.dumps(context.build(folder),indent=2,sort_keys=True,allow_nan=False)+'\n').encode())
    controls=[]
    for module,func,path in [(w7,lambda:w7.evaluate()[0],w7.OUTPUT/'week7_diagnostics.json'),
                             (w8,lambda:w8.evaluate()[0],w8.OUTPUT/'week8_diagnostics.json'),
                             (research,research.calculate,ROOT/'outputs/2026-week8-audit-research/numerical_research_candidates.json')]:
        module.sum=compensated
        try:controls.append({'module':module.__name__,'intervention':'Only module-local sum replaced with explicit Neumaier arithmetic','differences':difference(json.loads(path.read_bytes()),func())})
        finally:del module.sum
    env={'utc':datetime.now(timezone.utc).isoformat(),'python':sys.version,'platform':platform.platform(),
      'machine':platform.machine(),'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
      'parents':subprocess.check_output(['git','show','-s','--format=%P','HEAD'],cwd=ROOT,text=True).strip(),
      'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()},
      'requirements_sha256':{n:digest((ROOT/n).read_bytes()) for n in ['requirements.txt','requirements-dev.txt']},
      'tzpath':[str(x) for x in TZPATH], 'sum_probe':sum([1e16,1.0,-1e16]),'compensated_probe':compensated([1e16,1.0,-1e16]),
      'math_log_probe':math.log(.7).hex(),'float_format':repr(sys.float_info),
      'git_status':subprocess.check_output(['git','status','--porcelain','--untracked-files=no'],cwd=ROOT,text=True)}
    result={'environment':env,'comparisons':records,'controls':controls,'week8_manifest_differences':difference(expected_manifest,manifest)}
    (output/'comparison.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'output':str(output),'different_files':[(r['path'],len(r['differences'])) for r in records if not r['byte_identical']]}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',required=True,type=Path);run(p.parse_args().output)
