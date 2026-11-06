"""Additive validated scoring-sequence review; frozen audit and card stay unchanged."""
import argparse
import hashlib
import json
from pathlib import Path
from scripts.build_week8_postgame_audit import ROOT, EVIDENCE, read_json, read_csv, load_raw, serialized
from scripts.week5_postgame_core import classify_late_score

OUT=ROOT/'outputs/2026-week8-audit-research'

def validate_sequence(plays,away,home):
    if not plays or len({p['id'] for p in plays})!=len(plays):raise ValueError('missing or duplicate scoring sequence')
    previous=(0,0); last_time=(0,0)
    for p in plays:
        score=(int(p['awayScore']),int(p['homeScore']));period=int(p['period']['number']);clock=float(p['clock']['value'])
        order=(period,-clock)
        if order<last_time or any(a<b for a,b in zip(score,previous)) or sum(a!=b for a,b in zip(score,previous))!=1:
            raise ValueError('contradictory scoring progression')
        if not 0<=clock<=900:raise ValueError('invalid clock')
        previous=score;last_time=order
    if previous!=(away,home):raise ValueError('sequence final differs')

def build():
    manifest=read_json(EVIDENCE/'capture-manifest.json')
    entries={x['endpoint'].split('event=')[-1]:x for x in manifest['summaries']}
    rows=[]
    for r in read_csv(ROOT/'outputs/2026-week8-postgame-audit/week8_ats_audit.csv'):
        entry=entries[r['game_id']];summary=load_raw(entry);plays=summary.get('scoringPlays',[])
        row={'game_id':r['game_id'],'away':r['away'],'home':r['home'],'source_sha256':entry['raw_sha256'],
             'definition':'Selected-team score in final five minutes or overtime changes non-cover to final cover; backdoor additionally requires trailing then and losing outright.',
             'evidence_type':'ESPN_SCORING_SEQUENCE;NOT_AN_INFERENCE_FROM_FINAL_SCORE'}
        try:
            validate_sequence(plays,int(r['away_score']),int(r['home_score']))
            row.update(sequence_status='VALIDATED',**classify_late_score(plays,r['selected_side'],r['locked_home_spread'],int(r['away_score']),int(r['home_score'])))
        except (ValueError,KeyError,TypeError):row.update(sequence_status='UNAVAILABLE_OR_CONTRADICTORY',classification='UNVERIFIABLE')
        rows.append(row)
    return {'status':'SUPPLEMENTAL_SCORING_SEQUENCE_REVIEW','rows':rows,'no_historical_edits':True}

def main(verify=False):
    path=OUT/'week8_scoring_sequence_review.json';raw=serialized(build())
    if verify:
        if path.read_bytes()!=raw:raise ValueError('scoring replay mismatch')
    else:
        OUT.mkdir(exist_ok=True)
        with path.open('xb') as f:f.write(raw)
    result=json.loads(raw);return {'games':len(result['rows']),'validated':sum(r['sequence_status']=='VALIDATED' for r in result['rows']),'backdoor_covers':[r['game_id'] for r in result['rows'] if r['classification']=='BACKDOOR_COVER']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');print(json.dumps(main(p.parse_args().verify)))
