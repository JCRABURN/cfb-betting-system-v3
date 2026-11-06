"""Run the suite in a disposable copy with exact recorded Week 5 byte variants.

This diagnoses the pre-existing checkout EOL problem; it does not repair the
repository, revise checksums, or suppress failing tests. Run from the repo root.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]


def main() -> int:
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0')
    added=['scripts/research_week7_acceptance.py','scripts/verify_week7_acceptance_copy.py','tests/test_week7_acceptance_research.py']
    added += [p.relative_to(ROOT).as_posix() for p in (ROOT/'outputs/2026-week7-acceptance-research').rglob('*') if p.is_file()]
    with tempfile.TemporaryDirectory(prefix='cfb-acceptance-') as temporary:
        destination=Path(temporary).resolve()
        if destination==ROOT or ROOT in destination.parents:
            raise ValueError('verification copy must be separate from repository')
        for name in sorted(set(tracked+added)-{''}):
            source=ROOT/name;target=destination/name
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        custody=json.loads((destination/'outputs/2026-week5-review-20261001/v4-custody-manifest.json').read_text())
        audit=json.loads((destination/'outputs/2026-week5-postgame-audit/week5_postgame_manifest.json').read_text())
        required={r['path']:r['sha256'] for r in custody['v4_files']}
        required.update(audit['pregame_review_file_hashes']);required.update(audit['output_sha256'])
        changed=[]
        for name,expected in required.items():
            path=destination/name;data=path.read_bytes()
            if hashlib.sha256(data).hexdigest()==expected:continue
            lf=data.replace(b'\r\n',b'\n');variants=[lf,lf.replace(b'\n',b'\r\n')]
            matches=[b for b in variants if hashlib.sha256(b).hexdigest()==expected]
            if len(matches)!=1:raise ValueError(f'not an EOL-only mismatch: {name}')
            path.write_bytes(matches[0]);changed.append(name)
        print(json.dumps({'disposable_copy':str(destination),'week5_exact_byte_variants_restored':len(changed),'original_files_modified':0}),flush=True)
        result=subprocess.run([sys.executable,'-m','pytest','-q'],cwd=destination,check=False)
        return result.returncode


if __name__=='__main__':
    raise SystemExit(main())
