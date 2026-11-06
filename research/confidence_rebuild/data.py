"""Fail-closed offline custody and independent row-to-source reconciliation."""
import csv
import gzip
import hashlib
import io
import json
import math
from pathlib import Path
from datetime import datetime

HERE=Path(__file__).resolve().parent
EXPECTED_INPUT_SEAL_SHA256='ee8ee179bdfc20f1445ed082da64bb25e618ea3aca0dc631cec820e945302bf6'


def sha(raw):return hashlib.sha256(raw).hexdigest()
def instant(s):
    result=datetime.fromisoformat(s.replace('Z','+00:00'))
    if result.utcoffset() is None:raise ValueError('timezone required')
    return result


def load():
    seal_raw=(HERE/'input_seal.json').read_bytes()
    if sha(seal_raw)!=EXPECTED_INPUT_SEAL_SHA256:raise ValueError('input seal identity changed')
    seal=json.loads(seal_raw)
    expected={'protocol.json','source_manifest.json','observations.json'}|{'sources/'+p.name for p in (HERE/'sources').iterdir() if p.is_file()}
    if set(seal['sha256'])!=expected:raise ValueError('exact input coverage')
    for name,digest in seal['sha256'].items():
        if sha((HERE/name).read_bytes())!=digest:raise ValueError('protected research input changed: '+name)
    manifests=json.loads((HERE/'source_manifest.json').read_text())['sources'];cache={}
    for alias,entry in manifests.items():
        packed=(HERE/'sources'/entry['storage']).read_bytes();raw=gzip.decompress(packed)
        if sha(raw)!=entry['sha256'] or sha(packed)!=entry['stored_sha256']:raise ValueError('source raw checksum')
        cache[alias]=raw
    rows=json.loads((HERE/'observations.json').read_text())['rows'];validate_rows(rows)
    for w in range(5,11):
        for market,name in [('ATS','ats'),('TOTAL','totals')]:
            originals={r['game_id']:r for r in csv.DictReader(io.StringIO(cache[f'w{w}_{name}_card'].decode('utf-8-sig')))}
            selected=[r for r in rows if r['week']==w and r['market']==market]
            if {r['game_id'] for r in selected}!=set(originals):raise ValueError('frozen coverage')
            for r in selected:
                source=originals[r['game_id']];ats=market=='ATS'
                if r['forecast']!=float(source['projected_home_margin' if ats else 'projected_total']) or r['line']!=float(source['pick_spread' if ats else 'locked_total']) or r['original_selection']!=source['pick'] or r['confidence']!=int(source['confidence']):raise ValueError('frozen row differs from original source')
    return rows,json.loads((HERE/'protocol.json').read_text())


def validate_rows(rows):
    expected={5:56,6:58,7:59,8:52,9:54,10:57}
    keys=[(r['week'],r['market'],r['game_id']) for r in rows]
    if len(keys)!=len(set(keys)):raise ValueError('duplicate observation')
    for week,count in expected.items():
        for market in ('ATS','TOTAL'):
            if sum(r['week']==week and r['market']==market for r in rows)!=count:raise ValueError('observation coverage')
    for r in rows:
        if instant(r['generated_at'])>=instant(r['kickoff']) or r['source_stats_through_week']>=r['week']:raise ValueError('lookahead input')
        if not all(math.isfinite(r[k]) for k in ('line','forecast','market_forecast','sigma','edge','score')) or r['sigma']<=0:raise ValueError('nonfinite forecast')
        if r['week']==10 and any(r[k] is not None for k in ('actual','result','cover')):raise ValueError('prospective outcome contamination')
        if r['week']<10:
            cover=(r['actual']-r['market_forecast'])*r['sign'];grade='WIN' if cover>0 else 'LOSS' if cover<0 else 'PUSH'
            if grade!=r['result'] or cover!=r['cover']:raise ValueError('grading disagreement')
        if r['edge']!=abs(r['forecast']-r['market_forecast']):raise ValueError('line/projection edge mismatch')
