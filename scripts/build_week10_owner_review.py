"""Join documented human judgments to exact frozen fields; never alter the board."""
from __future__ import annotations
import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from scripts.verify_week10_owner_review import ROOT, BOARD, CONTEXT, REVIEWS, sha, records, instant, validate
from scripts.verify_week10_acceptance import EXPECTED_SEAL_SHA256


def write_new(path, data):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def build(brief_path, output):
    output = output.resolve()
    if not output.is_relative_to(REVIEWS) or output.exists():
        raise ValueError('new owner review directory required')
    when = datetime.now(timezone.utc).isoformat()
    brief = json.loads(brief_path.read_text(encoding='utf-8'))
    locked = {g['game_id']: g for g in json.loads((BOARD/'week10_locked_line_snapshot.json').read_text())['lines']}
    if any(instant(when) >= instant(locked[r['game_id']]['source_kickoff_utc']) for r in brief['candidates']):
        raise ValueError('initial review cannot include a started game')
    originals = {}
    for market, filename in [('ATS','week10_ats_research_top5.csv'),('TOTAL','week10_totals_research_top5.csv')]:
        with (BOARD/filename).open(encoding='utf-8', newline='') as stream:
            originals.update({(int(r['game_id']),market):r for r in csv.DictReader(stream)})
    manifests = sorted(CONTEXT.glob('*/capture-manifest.json'))
    directories = [p.parent.relative_to(ROOT).as_posix() for p in manifests]
    files = sorted(p for d in directories for p in (ROOT/d).rglob('*') if p.is_file() and p.suffix != '.pdf')
    inventory = CONTEXT/(output.name+'-evidence-inventory.json')
    if inventory.exists():
        raise ValueError('inventory already exists')
    source_map = {}
    for path in manifests:
        for source in records(json.loads(path.read_text(encoding='utf-8'))):
            source_map[source['name']] = dict(manifest=path.relative_to(ROOT).as_posix(), name=source['name'])
    source_map['SEC']['published_at_utc']='2026-11-05T01:10:00Z'
    source_map['ACC']['published_at_utc']='2026-11-05T01:00:00Z'
    source_map['sunbelt-availability-data']['published_at_utc']='2026-11-05T15:33:29.6618971Z'
    rows = []
    for rank, judgment in enumerate(brief['candidates'],1):
        original=originals[judgment['game_id'],judgment['market']]; ats=judgment['market']=='ATS'
        rows.append(dict(game_id=judgment['game_id'],market=judgment['market'],owner_review_rank=rank,
                         recommended_five=rank<=5,created_at_utc=when,owner_approval='PENDING',
                         away=original['away'],home=original['home'],selection=original['pick'],
                         locked_line=float(original['pick_spread' if ats else 'locked_total']),
                         frozen_projection_home_margin_or_total=float(original['projected_home_margin' if ats else 'projected_total']),
                         frozen_confidence=int(original['confidence']),
                         frozen_uncertainty_points=float(original['shadow_uncertainty_points' if ats else 'uncertainty_points']),
                         original_market_research_rank=int(original['ats_research_rank' if ats else 'totals_research_rank']),
                         research_score_not_calibrated=float(original['ats_shadow_score_not_calibrated' if ats else 'raw_selected_probability']),
                         selected_forecast_edge=abs(float(original['home_ats_edge' if ats else 'raw_point_edge'])),
                         human_review_confidence_1_to_5=judgment['human_confidence'],numeric_projection_adjustment=0,
                         rationale=judgment['rationale'],risks=judgment['risks'],
                         sources=[source_map[name] for name in judgment['sources']]+[source_map['weather-hourly-'+str(judgment['game_id'])]]))
    write_new(inventory,dict(sha256={p.relative_to(ROOT).as_posix():sha(p) for p in files},
                            note='Exact captured gzip bytes and derived reading copies; redundant decompressed PDFs remain local and are reproducible from gzip. Raw payload hashes are verified separately.'))
    review=dict(created_at_utc=when,source_delivery_commit='bf3e359ba25c3013e6ecb5574c26306eaceddba9',
                sealed_board_sha256=EXPECTED_SEAL_SHA256,owner_approval='PENDING',model_policy_changed=False,
                evidence_inventory_path=inventory.relative_to(ROOT).as_posix(),evidence_inventory_sha256=sha(inventory),
                evidence_directories=directories,previous_review_path=None,previous_review_sha256=None,
                human_brief_path=brief_path.resolve().relative_to(ROOT).as_posix(),human_brief_sha256=sha(brief_path),
                method=brief['method'],limitations=brief['limitations'],selections=rows)
    result=validate(review)
    output.mkdir(parents=True)
    write_new(output/'owner-review.json',review)
    write_new(output/'verification.json',result)
    print(json.dumps(dict(path=str(output),**result)))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--brief',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();build(args.brief,args.output)
