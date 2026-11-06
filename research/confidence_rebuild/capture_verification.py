"""Append-only local verification receipts with exact source-commit identity."""
import argparse
import hashlib
import json
import platform
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from .data import HERE


def capture(destination):
    root = HERE.parents[1]
    if destination.exists(): raise ValueError('verification destination exists')
    destination.mkdir(parents=True)
    db = root/'data/cfb.db'
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    connection = sqlite3.connect(db.as_uri()+'?mode=ro&immutable=1', uri=True)
    integrity = connection.execute('PRAGMA integrity_check').fetchall()
    connection.close()
    receipt = dict(started_at_utc=datetime.now(timezone.utc).isoformat(), source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip(),
                   python=sys.version, platform=platform.platform(), database_before=before,
                   database_integrity=integrity, commands=[])
    commands = [['-m', 'research.confidence_rebuild.verify'], ['-m', 'research.confidence_rebuild.cohorts'],
                ['-m', 'research.confidence_rebuild.supplement', '--verify'], ['-m', 'research.confidence_rebuild.tables', '--verify'],
                ['scripts/verify_repo_safety.py'], ['-m', 'scripts.verify_migrations'],
                ['-m', 'scripts.verify_cloud_migrations'], ['-m', 'pytest', '-q']]
    for number, command in enumerate(commands, 1):
        start = datetime.now(timezone.utc)
        result = subprocess.run([sys.executable, '-X', 'utf8']+command, cwd=root, capture_output=True)
        log = result.stdout+result.stderr; name = f'{number:02d}.log'
        (destination/name).write_bytes(log)
        receipt['commands'].append(dict(command=[sys.executable, '-X', 'utf8']+command, exit_code=result.returncode,
                                        started_at_utc=start.isoformat(), finished_at_utc=datetime.now(timezone.utc).isoformat(),
                                        log=name, log_sha256=hashlib.sha256(log).hexdigest()))
        print(json.dumps(receipt['commands'][-1]), flush=True)
    receipt['database_after'] = hashlib.sha256(db.read_bytes()).hexdigest()
    receipt['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
    receipt['status'] = 'PASS' if before == receipt['database_after'] and integrity == [('ok',)] and all(c['exit_code'] == 0 for c in receipt['commands']) else 'FAIL'
    (destination/'receipt.json').write_bytes((json.dumps(receipt, indent=2, sort_keys=True)+'\n').encode())
    print(json.dumps({'status': receipt['status'], 'source_commit': receipt['source_commit']}))
    return receipt['status']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--output', type=Path, required=True)
    raise SystemExit(0 if capture(parser.parse_args().output) == 'PASS' else 1)
