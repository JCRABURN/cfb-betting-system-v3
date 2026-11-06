"""Reconcile research ordering with exact archived combined-five source bytes."""
import argparse
import csv
import gzip
import hashlib
import io
import json
import subprocess
from .data import HERE, load
from .prepare import PRE
from .run import replay
from .engine import select


def capture():
    rows, protocol = load()
    folder = HERE/'cohort_sources'
    if folder.exists(): raise ValueError('cohort evidence already exists')
    folder.mkdir()
    manifest = {}
    for week in range(5, 11):
        name = f'week{week}_combined_top5.csv' if week < 7 else f'week{week}_legacy_mixed_research_top5.csv'
        path = 'outputs/'+PRE[week]+'/'+name
        commit = protocol['week10_source_commit'] if week == 10 else protocol['audit_source_commit']
        raw = subprocess.check_output(['git', 'show', commit+':'+path], cwd=HERE)
        packed = gzip.compress(raw, mtime=0)
        (folder/f'week{week}.gz').write_bytes(packed)
        manifest[str(week)] = dict(commit=commit, path=path, sha256=hashlib.sha256(raw).hexdigest(),
                                  stored_sha256=hashlib.sha256(packed).hexdigest())
    (folder/'manifest.json').write_bytes((json.dumps(manifest, indent=2, sort_keys=True)+'\n').encode())


def verify():
    rows, protocol = load()
    manifest_raw = (HERE/'cohort_sources/manifest.json').read_bytes()
    if hashlib.sha256(manifest_raw).hexdigest() != '8599aa7ebeb178217dcb9f893eebe0f836be248e3508839a4cb3e3799a30deff':
        raise ValueError('archived cohort manifest identity')
    manifest = json.loads(manifest_raw)
    if set(manifest) != {str(w) for w in range(5, 11)}: raise ValueError('cohort coverage')
    predicted, _, _ = replay(rows, protocol)
    counts = {}
    for week, entry in manifest.items():
        packed = (HERE/'cohort_sources'/f'week{week}.gz').read_bytes(); raw = gzip.decompress(packed)
        if hashlib.sha256(raw).hexdigest() != entry['sha256'] or hashlib.sha256(packed).hexdigest() != entry['stored_sha256']:
            raise ValueError('archived cohort byte identity')
        source = list(csv.DictReader(io.StringIO(raw.decode('utf-8-sig'))))
        frozen = [r for r in rows if r['week'] == int(week)]
        original = select([dict(r, ranking_score=r['score'], candidate_sign=r['sign']) for r in frozen])
        if [(r['game_id'], r['market']) for r in source] != [(r['game_id'], r['market']) for r in original]:
            raise ValueError('archived combined ordering differs')
        for a, b in zip(source, original):
            if float(a['locked_line']) != b['line'] or float(a['projection']) != b['forecast'] or a['pick'].lower() != b['original_selection'].lower():
                raise ValueError('cohort line/forecast/side differs')
        counts[week] = len(source)
    return counts


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--capture', action='store_true'); args = parser.parse_args()
    if args.capture: capture()
    print(json.dumps(verify(), sort_keys=True))
