"""Replay the November 19 evidence-only refresh without changing forecasts."""
from __future__ import annotations
import argparse
import csv
import gzip
import json
from scripts.prepare_week12_source import ROOT, digest, serialized

OUT=ROOT/'outputs/2026-week12-refresh/20261119-morning'
CONTEXT=ROOT/'outputs/2026-week12-context'
OLD=CONTEXT/'review-v2'
NEW=CONTEXT/'20261119-review-v2'
READINESS=ROOT/'outputs/2026-week12-readiness'

def read(path):return json.loads(path.read_bytes())
def table(path):return list(csv.DictReader(path.open(encoding='utf-8-sig',newline='')))

def build():
    old_context={r['game_id']:r for r in table(OLD/'all-game-context.csv')}
    fresh=table(NEW/'all-game-context.csv')
    delta=[dict(game_id=r['game_id'],away=r['away'],home=r['home'],field=k,
                previous=old_context[r['game_id']][k],current=v)
           for r in fresh for k,v in r.items() if v!=old_context[r['game_id']][k]]
    old_people={(r['team'],r['name']):r for r in table(OLD/'conference-personnel.csv')}
    personnel=[]
    for r in table(NEW/'conference-personnel.csv'):
        previous=old_people.get((r['team'],r['name']))
        if previous is None or previous['status']!=r['status']:
            personnel.append(dict(**r,previous_status=previous['status'] if previous else 'UNAVAILABLE_IN_PRIOR_CAPTURE'))
    prior=READINESS/'execution-gate-20261118/capture-manifest.json'
    current=READINESS/'20261119-morning/capture-manifest.json'
    records={r['name']:r for r in read(prior)['records']}
    comparisons=[dict(name=r['name'],previous_sha256=records[r['name']]['raw_sha256'],
        current_sha256=r['raw_sha256'],unchanged=records[r['name']]['raw_sha256']==r['raw_sha256'])
        for r in read(current)['records'] if r['name'].startswith('cfbd-prior-')]
    if len(comparisons)!=7 or not all(r['unchanged'] for r in comparisons):
        raise ValueError('evidence-only refresh requires unchanged prior-week model statistics')
    m=read(CONTEXT/'20261119-morning/manifest.json')
    if len(fresh)!=61 or len(m['eligibility'])!=66:raise ValueError('Thursday eligibility coverage')
    if {int(r['game_id']) for r in fresh}!={r['game_id'] for r in m['eligibility'] if r['status']=='UPCOMING'}:
        raise ValueError('future game coverage mismatch')
    def market(folder):
        receipt=next(r for r in read(folder/'manifest.json')['records'] if r.get('name')=='market-separate')
        stored=(folder/receipt['path']).read_bytes();raw=gzip.decompress(stored)
        if digest(stored)!=receipt['stored_sha256'] or digest(raw)!=receipt['raw_sha256']:raise ValueError('market custody')
        return {r['id']:r for r in json.loads(raw)}
    previous_market=market(CONTEXT/'20261118-initial');current_market=market(CONTEXT/'20261119-morning')
    markets=[dict(game_id=gid,previous=previous_market.get(gid),current=current_market.get(gid),
                  changed=previous_market.get(gid)!=current_market.get(gid)) for gid in m['game_ids']]
    inputs=[OLD/'manifest.json',NEW/'manifest.json',prior,current,
            ROOT/'outputs/2026-week12-delivery/initial-seal.json']
    sources=ROOT/'outputs/2026-week12-delivery/v2'
    outputs={name:(sources/name).read_bytes() for name in ('full-card-66.csv','all-132-markets.csv')}
    outputs.update({'context-changes.json':serialized(delta),'personnel-changes.json':serialized(personnel),
                    'market-observations-separate.json':serialized(markets),'feature-comparison.json':serialized(comparisons),
                    'eligibility.json':serialized(m['eligibility'])})
    inputs.extend(sources/name for name in ('full-card-66.csv','all-132-markets.csv'))
    outputs['manifest.json']=serialized(dict(version='week12-thursday-evidence-review-v1',
        evidence_as_of_utc=read(NEW/'manifest.json')['as_of_utc'],eligible_games=61,started_games_unchanged=5,
        full_card_rows=66,market_rows=132,model_rerun=False,numeric_adjustments=0,forecast_changes=0,
        reason='All seven prior-week statistical payloads unchanged; no approved numeric contextual adjustment or common calibration.',
        official_common_calibrated_top_five=False,external_week11_submissions_used=False,
        context_changes=len(delta),personnel_changes=len(personnel),
        market_games_changed=sum(r['changed'] for r in markets),
        inputs={p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in inputs},
        files={name:digest(raw) for name,raw in outputs.items()}))
    return outputs

def main(verify=False):
    outputs=build()
    if verify:
        for name,raw in outputs.items():
            if (OUT/name).read_bytes()!=raw:raise ValueError('refresh replay mismatch: '+name)
    else:
        OUT.mkdir(exist_ok=False)
        for name,raw in outputs.items():
            with (OUT/name).open('xb') as stream:stream.write(raw)
    print(outputs['manifest.json'].decode())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');main(p.parse_args().verify)
