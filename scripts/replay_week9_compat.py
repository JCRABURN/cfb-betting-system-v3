"""Exact replay of hash-qualified historical context with original TZ provenance.

This verifier cannot generate new context. Each supported capture records that
timezone data was unavailable at generation. A later machine's TZ database is
not historical evidence and must not silently populate those original nulls.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from scripts.replay_compat_v1 import ROOT, clone

PROFILE = ROOT/'tests/fixtures/replay_compat/week9_context_profiles.json'
PROFILE_SHA256_LF = 'e8c76ee27de15737d6c2e063f4d1be0fdcd790ca2f62da2eed2b5ac5fdbf3480'
_historical=clone('review_week9_context')
_historical.timezone_shift=lambda kickoff,origin,destination: None
distance=_historical.distance

def profile_for(folder):
    raw=PROFILE.read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(raw).hexdigest()!=PROFILE_SHA256_LF:
        raise ValueError('historical context profile changed')
    profiles=json.loads(raw)
    code=(ROOT/'scripts/review_week9_context.py').read_bytes().replace(b'\r\n',b'\n')
    if hashlib.sha256(code).hexdigest()!=profiles['source_code_sha256_lf']:
        raise ValueError('historical context source changed')
    folder=Path(folder).resolve()
    if not folder.is_relative_to(ROOT/'outputs/2026-week9-context'):
        raise ValueError('context outside custody directory')
    candidates=[p for p in profiles['captures'] if p['capture_path']==folder.relative_to(ROOT).as_posix()]
    if len(candidates)!=1:raise ValueError('unregistered historical capture; explicit provenance profile required')
    profile=candidates[0]
    if profile['timezone_provider']!='UNAVAILABLE_AT_ORIGINAL_GENERATION' or profile['model_adjustments']!=0:
        raise ValueError('contradictory historical context profile')
    for filename,key in [('capture-manifest.json','capture_manifest_sha256'),('derived_context_board.json','derived_context_sha256')]:
        if hashlib.sha256((folder/filename).read_bytes()).hexdigest()!=profile[key]:
            raise ValueError('historical context exact-byte custody changed: '+filename)
    return profile

def build(folder):
    folder=Path(folder).resolve();profile_for(folder)
    return _historical.build(folder)

def main(folder,verify=True):
    if not verify:raise ValueError('compatibility entry point is read-only; no historical regeneration')
    folder=Path(folder).resolve()
    actual=(json.dumps(build(folder),indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    if (folder/'derived_context_board.json').read_bytes()!=actual:
        raise ValueError('context exact replay mismatch')
    return {'context_games':54,'owner_approval':'PENDING','model_adjustments':0,
            'replay_profile':'historical-context-replay-v1','timezone_provider':'UNAVAILABLE_AT_ORIGINAL_GENERATION'}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--capture',type=Path,required=True)
    print(json.dumps(main(p.parse_args().capture),indent=2))
