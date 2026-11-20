"""Append-only evidence comparison; unchanged forecasts require unchanged statistics."""
from __future__ import annotations
import argparse
import gzip
import json
from pathlib import Path
from scripts.prepare_week12_source import ROOT,digest,serialized
from scripts.review_week12_thursday import read,table

def feature_comparison(previous,current):
    old={r['name']:r for r in previous['records']}
    expected={name for name in old if name.startswith('cfbd-prior-')}
    actual=[r['name'] for r in current['records'] if r['name'].startswith('cfbd-prior-')]
    if len(expected)!=7 or len(actual)!=7 or set(actual)!=expected:
        raise ValueError('seven unique matching prior-week statistical payloads required')
    rows=[dict(name=r['name'],previous_sha256=old[r['name']]['raw_sha256'],
        current_sha256=r['raw_sha256'],unchanged=old[r['name']]['raw_sha256']==r['raw_sha256'])
        for r in current['records'] if r['name'].startswith('cfbd-prior-')]
    if len(rows)!=7 or not all(r['unchanged'] for r in rows):
        raise ValueError('evidence-only refresh requires seven unchanged prior-week statistical payloads')
    return rows

def build(previous_context,previous_capture,context,capture,previous_card):
    if previous_card.name!='full-card-66.csv':raise ValueError('named complete prior card required')
    prior_manifest=read(previous_card.parent/'manifest.json')
    for name in ('full-card-66.csv','all-132-markets.csv'):
        if digest((previous_card.parent/name).read_bytes())!=prior_manifest['files'][name]:
            raise ValueError('previous card custody')
    m=read(capture/'manifest.json');review=read(context/'manifest.json')
    for name,expected in review['input_manifests'].items():
        if digest((ROOT/name).read_bytes())!=expected:raise ValueError('review input changed')
    if review['input_manifests'].get((capture/'manifest.json').relative_to(ROOT).as_posix())!=digest((capture/'manifest.json').read_bytes()):
        raise ValueError('wrong reviewed capture')
    readiness=ROOT/m['eligibility_capture']/'capture-manifest.json'
    prior=ROOT/'outputs/2026-week12-readiness/execution-gate-20261118/capture-manifest.json'
    comparisons=feature_comparison(read(prior),read(readiness))
    old={r['game_id']:r for r in table(previous_context/'all-game-context.csv')}
    fresh=table(context/'all-game-context.csv')
    ids={r['game_id'] for r in m['eligibility'] if r['status']=='UPCOMING'}
    if len(m['eligibility'])!=66 or len(ids)!=len(fresh) or ids!={int(r['game_id']) for r in fresh}:
        raise ValueError('future eligibility coverage mismatch')
    changes=[dict(game_id=r['game_id'],away=r['away'],home=r['home'],field=k,previous=old[r['game_id']][k],current=v)
             for r in fresh for k,v in r.items() if old[r['game_id']][k]!=v]
    old_people={(r['team'],r['name']):r for r in table(previous_context/'conference-personnel.csv')}
    people=[]
    for row in table(context/'conference-personnel.csv'):
        previous=old_people.get((row['team'],row['name']))
        if previous is None or previous['status']!=row['status']:
            people.append(dict(**row,previous_status=previous['status'] if previous else 'UNAVAILABLE_IN_PRIOR_CAPTURE'))
    def market(folder):
        rec=next(r for r in read(folder/'manifest.json')['records'] if r.get('name')=='market-separate')
        stored=(folder/rec['path']).read_bytes();raw=gzip.decompress(stored)
        if digest(stored)!=rec['stored_sha256'] or digest(raw)!=rec['raw_sha256']:raise ValueError('market custody')
        return {r['id']:r for r in json.loads(raw)}
    before=market(previous_capture);after=market(capture)
    markets=[dict(game_id=gid,previous=before.get(gid),current=after.get(gid),changed=before.get(gid)!=after.get(gid)) for gid in sorted(ids)]
    outputs={name:(previous_card.parent/name).read_bytes() for name in ('full-card-66.csv','all-132-markets.csv')}
    if len(table(previous_card))!=66:raise ValueError('complete prior card required')
    outputs.update({'context-changes.json':serialized(changes),'personnel-changes.json':serialized(people),
        'market-observations-separate.json':serialized(markets),'feature-comparison.json':serialized(comparisons),
        'eligibility.json':serialized(m['eligibility'])})
    inputs=[prior,readiness,previous_context/'manifest.json',context/'manifest.json',
        previous_capture/'manifest.json',capture/'manifest.json',previous_card,previous_card.parent/'all-132-markets.csv']
    outputs['manifest.json']=serialized(dict(version='week12-daily-evidence-review-v1',evidence_as_of_utc=review['as_of_utc'],
        eligible_games=len(ids),started_games_unchanged=66-len(ids),full_card_rows=66,market_rows=132,
        model_rerun=False,numeric_adjustments=0,forecast_changes=0,official_common_calibrated_top_five=False,
        external_week11_submissions_used=False,context_changes=len(changes),personnel_changes=len(people),
        market_games_changed=sum(r['changed'] for r in markets),
        reason='Seven prior-week statistical payloads unchanged; context risks remain separate without approved numeric adjustment or calibration.',
        inputs={p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in inputs},
        files={name:digest(raw) for name,raw in outputs.items()}))
    return outputs

def main():
    p=argparse.ArgumentParser()
    for name in ('previous-context','previous-capture','context','capture','previous-card','output'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--verify',action='store_true');a=p.parse_args()
    for name in ('previous_context','previous_capture','context','capture'):
        path=getattr(a,name).resolve()
        if not path.is_relative_to(ROOT/'outputs/2026-week12-context'):raise ValueError('context boundary')
        setattr(a,name,path)
    a.output=a.output.resolve();a.previous_card=a.previous_card.resolve()
    if not a.output.is_relative_to(ROOT/'outputs/2026-week12-refresh') or not a.previous_card.is_relative_to(ROOT/'outputs/2026-week12-refresh'):
        raise ValueError('refresh boundary')
    outputs=build(a.previous_context,a.previous_capture,a.context,a.capture,a.previous_card)
    if a.verify:
        for name,raw in outputs.items():
            if (a.output/name).read_bytes()!=raw:raise ValueError('daily refresh replay mismatch: '+name)
    else:
        a.output.mkdir(exist_ok=False)
        for name,raw in outputs.items():
            with (a.output/name).open('xb') as stream:stream.write(raw)
    print(outputs['manifest.json'].decode())

if __name__=='__main__':main()
