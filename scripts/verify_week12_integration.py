"""Verify inherited immutable evidence from the approved audit and Week12 parents."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PARENTS={
    'approved_main':'217600fe1445edc7c0f2a51c04246e5ba38ea0cb',
    'original_week12':'880d3f9f7b87313aebb2425efafe5318525eb53e',
}
# Freeze historical evidence, not unrelated application development. Approved
# model/policy hashes and audit code are checked by their existing sealed gates.
EVIDENCE_PREFIXES=('outputs/','data/ingest/','production-weeks/')

def git(*args: str) -> str:
    return subprocess.check_output(['git',*args],cwd=ROOT).decode('utf-8')

def inherited_changes(previous: dict[str,str],current: dict[str,str]) -> list[str]:
    return sorted(name for name,blob in previous.items()
                  if current.get(name)!=blob)

def protected_inventory(tree: dict[str,str]) -> dict[str,str]:
    return {name:blob for name,blob in tree.items() if name.startswith(EVIDENCE_PREFIXES)}

def verify() -> dict:
    if git('diff','--name-only').strip():
        raise ValueError('tracked working tree differs from the verified index')
    current={}
    for entry in git('ls-files','--stage','-z').split('\0'):
        if not entry:continue
        info,name=entry.split('\t',1);mode,blob,stage=info.split()
        if stage!='0':raise ValueError('unresolved integration conflict: '+name)
        current[name]=mode+' '+blob
    result={}
    for label,ref in PARENTS.items():
        previous={}
        for entry in git('ls-tree','-r','-z',ref).split('\0'):
            if not entry:continue
            info,name=entry.split('\t',1);mode,kind,blob=info.split()
            previous[name]=mode+' '+blob
        protected=protected_inventory(previous)
        changed=inherited_changes(protected,current)
        if changed:raise ValueError(label+' inherited file changed: '+', '.join(changed))
        result[label]=dict(commit=ref,inherited_files=len(previous),protected_evidence_files=len(protected),changed_evidence_files=0)
    return dict(status='VERIFIED_BOTH_PARENT_INVENTORIES',parents=result,
                evidence_prefixes=EVIDENCE_PREFIXES,
                model_policy_validation='Separate original Week12 seal and Week11 audit code checks')

if __name__=='__main__':print(json.dumps(verify(),indent=2))
