"""Publish complete coverage with explicit unavailable calibration, never invented probabilities."""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
from scripts import prepare_week12_source as source
from scripts.prepare_week11_readiness import serialized, timestamp

ROOT=source.ROOT
BOARD=ROOT/'outputs/2026-week12-prospective'
OUT=ROOT/'outputs/2026-week12-delivery/v1'


def read_csv(path):
    return list(csv.DictReader(path.open(encoding='utf-8-sig',newline='')))


def build():
    source.main(True)
    ats_rows=read_csv(BOARD/'week12_ats_full_card.csv');total_rows=read_csv(BOARD/'week12_totals_full_card.csv')
    ats={int(r['game_id']):r for r in ats_rows}
    totals={int(r['game_id']):r for r in total_rows}
    if len(ats)!=len(ats_rows) or len(totals)!=len(total_rows):raise ValueError('duplicate market rows')
    intake=read_csv(source.OUT/'provider-reconciliation.csv')
    lock=json.loads((BOARD/'week12_locked_line_snapshot.json').read_bytes())
    model=json.loads((BOARD/'week12_model_manifest.json').read_bytes())
    expected={r['game_id'] for r in lock['lines']}
    excluded={r['game_id'] for r in lock['excluded']}
    if set(ats)!=expected or set(totals)!=expected or expected&excluded or len(expected|excluded)!=66:
        raise ValueError('full market coverage or elapsed-game contamination')
    if len(expected)!=63 or len(excluded)!=3:
        raise ValueError('initial sealed cohort changed')
    card=[]; pool=[]
    for raw in intake:
        gid=int(raw['game_id']); a=ats.get(gid); t=totals.get(gid)
        if a and (float(a['locked_home_spread'])!=float(raw['home_spread']) or float(t['locked_total'])!=float(raw['locked_total'])):
            raise ValueError('model card altered original source lines')
        if a and (timestamp(model['generated_at_utc'])>=timestamp(raw['source_kickoff_utc']) or not 1<=int(a['confidence'])<=5):
            raise ValueError('late forecast or invalid confidence')
        row=dict(game_id=gid,away=raw['away'],home=raw['home'],pdf_page=int(raw['pdf_page']),source_row=int(raw['source_row']),
                 kickoff_utc=raw['source_kickoff_utc'],locked_home_spread=float(raw['home_spread']),locked_total=float(raw['locked_total']),
                 status='PREGAME_FORECAST' if a else 'ELAPSED_NO_PROSPECTIVE_FORECAST',
                 ats_selection=a['pick'] if a else '',ats_selected_spread=a['pick_spread'] if a else '',
                 projected_home_margin=a['projected_home_margin'] if a else '',ats_confidence=a['confidence'] if a else '',
                 home_ats_edge=a['home_ats_edge'] if a else '',ats_raw_score_not_probability=a['ats_shadow_score_not_calibrated'] if a else '',
                 totals_selection=t['pick'] if t else '',projected_total=t['projected_total'] if t else '',
                 total_edge=t['raw_point_edge'] if t else '',totals_raw_normal_probability=t['raw_selected_probability'] if t else '',
                 totals_legacy_confidence=t['confidence'] if t else '',calibrated_probability='',common_calibrated_rank='',
                 reliability='WEAK_UNVALIDATED_NO_COMMON_CALIBRATION' if a else 'NO_FORECAST',
                 original_pdf_sha256=source.PDF_SHA)
        card.append(row)
        for market in ('ATS','TOTAL'):
            current=a if market=='ATS' else t
            pool.append(dict(game_id=gid,away=raw['away'],home=raw['home'],market=market,status=row['status'],
                             pick=(a['pick'] if market=='ATS' else t['pick']) if current else '',
                             locked_line=(a['pick_spread'] if market=='ATS' else t['locked_total']) if current else (raw['home_spread'] if market=='ATS' else raw['locked_total']),
                             projection=(a['projected_home_margin'] if market=='ATS' else t['projected_total']) if current else '',
                             raw_score=(a['ats_shadow_score_not_calibrated'] if market=='ATS' else t['raw_selected_probability']) if current else '',
                             score_kind='HEURISTIC_ATS_SCORE_NOT_EMPIRICAL_PROBABILITY' if market=='ATS' else 'UNCALIBRATED_NORMAL_TOTAL_PROBABILITY',
                             calibrated_probability='',calibrated_rank='',legacy_research_rank='',production_rank_status='BLOCKED_COMMON_CALIBRATION_UNAVAILABLE'))
    ranked=sorted((r for r in pool if r['raw_score']!=''),key=lambda r:(-float(r['raw_score']),next(x['locked_line_id'] for x in lock['lines'] if x['game_id']==r['game_id']),r['market']))
    for rank,row in enumerate(ranked,1):row['legacy_research_rank']=rank
    five=read_csv(BOARD/'week12_legacy_mixed_research_top5.csv')
    if len(five)!=5 or len({r['game_id'] for r in five})!=5:
        raise ValueError('five distinct games required')
    for row in five:
        row['contest_chip']=6-int(row['rank'])
        row['calibrated_probability']=''
        row['recommendation_status']='RESEARCH_ONLY_NOT_CERTIFIED_CONTEST_RECOMMENDATION'
    if sorted(r['contest_chip'] for r in five)!=[1,2,3,4,5]:
        raise ValueError('chip allocation')
    files={'full-card-66.csv':source.csv_bytes(card),'all-132-markets.csv':source.csv_bytes(pool),
           'provisional-research-five.csv':source.csv_bytes(five)}
    report=dict(status='DRAFT_FORECASTS_COMPLETE_FOR_ELIGIBLE_GAMES_OFFICIAL_COMBINED_SELECTION_BLOCKED',
                intake_games=66,intake_markets=132,prospective_ats=63,prospective_totals=63,
                elapsed_games=3,elapsed_markets=6,eligible_missing_forecasts=0,duplicate_games=0,
                calibrated_cross_market_probability_available=False,official_combined_top_five_available=False,
                provisional_research_five_games=5,provisional_chips=[5,4,3,2,1],no_market_allocation_quota=True,
                limitation='Unchanged v2.8 ATS returns null governed uncertainty; ATS score is a capped linear heuristic. Totals use an uncalibrated normal residual CDF. These scales cannot certify the strongest combined five. No policy was promoted to manufacture calibration.',
                frozen_code_commit=model['code_commit_sha'],model_generated_at_utc=model['generated_at_utc'],
                source_print_timestamp='2026-11-17T14:22:00-06:00',actual_lock_timestamp=lock['locked_at_utc'],
                external_week11_submissions_used=False,production_database_modified=False,
                context_status='SEPARATE_APPEND_ONLY_CONTEXT_REVIEW_REQUIRED',
                files={name:source.digest(raw) for name,raw in files.items()})
    files['diagnostics.json']=serialized(report)
    return files


def main(verify=False):
    files=build()
    if verify:
        for name,raw in files.items():
            if (OUT/name).read_bytes()!=raw:raise ValueError('delivery replay changed: '+name)
    else:
        OUT.mkdir(parents=True,exist_ok=False)
        for name,raw in files.items():(OUT/name).write_bytes(raw)
    print(files['diagnostics.json'].decode())


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');main(p.parse_args().verify)
