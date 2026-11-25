"""Verify the sealed Week 13 outputs offline and render the readable full board."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

from models import baseline_epa
from scripts import prepare_week13_source as source

OUT = source.ROOT / 'outputs/2026-week13-prospective'


def load(name: str):
    return json.loads((OUT / name).read_bytes())


def read_csv(name: str) -> list[dict]:
    with (OUT / name).open(newline='', encoding='utf-8') as stream:
        return list(csv.DictReader(stream))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify() -> dict:
    source.main(True)
    card = load('week13_card_manifest.json')
    model = load('week13_model_manifest.json')
    lock = load('week13_locked_line_snapshot.json')
    raw = load('week13_raw_model_components.json')
    ats = read_csv('week13_ats_full_card.csv')
    totals = read_csv('week13_totals_full_card.csv')
    require(len(lock['lines']) == len(ats) == len(totals) == len(raw['games']) == 67, 'forecast coverage')
    require(len(lock['excluded']) == 2 and all(r['status'] == 'ELAPSED_NO_PROSPECTIVE_FORECAST' for r in lock['excluded']), 'elapsed games')
    ids = {int(r['game_id']) for r in lock['lines']}
    require(len(ids) == 67 and not ids.intersection(r['game_id'] for r in lock['excluded']), 'duplicate or elapsed prediction')
    for rows in (ats, totals, raw['games']):
        require({int(r['game_id']) for r in rows} == ids, 'market game coverage')
    require(card['ats_report']['fallback_pick_count'] == 0, 'unexpected fallback')
    require(all(r['confidence'] == '1' and r['fallback_code'] == '' for r in ats), 'governed confidence or fallback changed')
    top = [r for r in ats if r['top_five'] == 'True']
    require(len(top) == 5 and {int(r['rank']) for r in top} == set(range(1, 6)), 'Top 5 coverage')
    require(raw['status'] == 'PREGAME_COMPONENT_REPLAY_VERIFIED', 'component replay missing')
    require(raw['code_commit_sha'] == model['code_commit_sha'], 'model identity changed')
    require(hashlib.sha256((OUT/'week13_raw_model_components.json').read_bytes()).hexdigest() == card['raw_model_components_sha256'], 'component hash')
    require(lock['locked_line_snapshot_sha256'] == model['locked_line_snapshot_sha256'] == card['ats_card']['locked_line_snapshot_sha256'], 'locked-line hash')
    original = source.parse_pages(json.loads((source.SOURCE/'extracted-pages.json').read_bytes()))
    by_source = {r['source_row']: r for r in original}
    by_ats = {int(r['game_id']): r for r in ats}
    by_total = {int(r['game_id']): r for r in totals}
    by_lock = {r['game_id']: r for r in lock['lines']}
    for row in lock['lines'] + lock['excluded']:
        r = by_source[row['source_row']]
        require(all(row[k] == r[k] for k in ('raw_away', 'raw_home', 'home_spread', 'locked_total', 'source_kickoff_utc')), 'PDF line changed')
    require(raw['ats_model']['training_seasons'] == list(range(2019, 2026)), 'ATS training cutoff')
    for game in raw['games']:
        gid = game['game_id']; a = by_ats[gid]; t = by_total[gid]; line = by_lock[gid]
        kickoff = datetime.fromisoformat(game['kickoff_utc'])
        for when in (raw['card_generated_at_utc'], game['ats']['prediction_generated_at'], game['totals']['prediction_generated_at']):
            require(datetime.fromisoformat(when) < kickoff, 'late forecast')
        package = game['raw_point_in_time_package']
        for side in ('home_stats', 'away_stats'):
            require((package[side]['as_of_season'], package[side]['as_of_week']) == (2026, 12), 'feature cutoff')
            require(package[side]['is_prior_season_fallback'] is False, 'unreported feature fallback')
        prediction = baseline_epa.predict_margin(package, raw['ats_model']['intercept'], raw['ats_model']['coefficients'])
        require(math.isclose(prediction, float(a['projected_home_margin']), abs_tol=1e-10), 'ATS numerical replay')
        require(float(a['locked_home_spread']) == line['home_spread'], 'ATS spread changed')
        signed = prediction + line['home_spread']
        require(a['selected_side'] == ('home' if signed > 0 else 'away'), 'ATS selected side')
        require(float(a['pick_spread']) == (line['home_spread'] if a['selected_side']=='home' else -line['home_spread']), 'selected spread sign')
        fitted = raw['totals_model']['fitted']; features = game['totals']['features']
        score = sum(fitted[s+'_intercept'] + sum(c*x for c,x in zip(fitted[s+'_coefficients'], features)) for s in ('home','away'))
        require(math.isclose(score, float(t['projected_total']), abs_tol=1e-10), 'total numerical replay')
        require(float(t['locked_total']) == line['locked_total'], 'total line changed')
        require(t['pick'] == ('over' if score > line['locked_total'] else 'under'), 'total selected direction')
    return dict(original_games=69, upcoming_forecasts=67, elapsed_exclusions=2,
                model_fallbacks=0, feature_fallbacks=0, top_five_count=5,
                confidence_counts={'1':67}, raw_component_replay='PASS',
                locked_line_preservation='PASS', status='LOCAL_DRAFT_MODEL_RUN_COMPLETE')


def report() -> str:
    summary = verify()
    model = load('week13_model_manifest.json')
    lock = load('week13_locked_line_snapshot.json')
    ats = {int(r['game_id']):r for r in read_csv('week13_ats_full_card.csv')}
    totals = {int(r['game_id']):r for r in read_csv('week13_totals_full_card.csv')}
    lines = [
        '# Week 13 model results - 2026', '',
        f"Model generated {model['generated_at_utc']}; code `{model['code_commit_sha']}`.", '',
        'Loaded all 69 SplashSports games. Both models produced forecasts for all 67 upcoming games; the two Tuesday games are preserved below as elapsed. All PDF spreads and totals remain unchanged. Statistics stop at Week 12.', '',
        '**Local draft.** No card was submitted or published. ATS confidence remains 1 for every game because the unchanged policy lacks per-game calibrated uncertainty. Its governed Top 5 uses deterministic tie-breaks and does not distinguish the strongest five forecasts. Research rankings below are separate and unvalidated; no sportsbook wagers or stakes are recommended.', '',
        'Injury, quarterback, weather, coaching and market context have not been applied. Raw and adjusted spread projections are identical; manual adjustments: 0.', '',
        '## ATS research shortlist', '',
        'Ordered by the existing within-market research score, not validated confidence.', '',
        '| Research rank | Pick at locked line | Model home margin | Model edge |',
        '|---:|---|---:|---:|',
    ]
    for r in read_csv('week13_ats_research_top5.csv'):
        lines.append(f"| {r['ats_research_rank']} | {r['pick']} {float(r['pick_spread']):+.1f} | {float(r['projected_home_margin']):+.2f} | {float(r['ats_shadow_selected_edge_points']):.2f} |")
    lines += ['', '## Totals research shortlist', '', 'Totals confidence and probability are shadow-model outputs, not calibrated reliability.', '',
              '| Research rank | Matchup | Selection | Model total |', '|---:|---|---|---:|']
    for r in read_csv('week13_totals_research_top5.csv'):
        lines.append(f"| {r['totals_research_rank']} | {r['away']} @ {r['home']} | {r['pick'].title()} {float(r['locked_total']):.1f} | {float(r['projected_total']):.2f} |")
    lines += ['', '## Governed Top 5', '', 'Tie-break order only; every pick has Confidence 1. The stored rank is retained exactly.', '',
              '| Stored rank | Pick | Confidence |', '|---:|---|---:|']
    for r in sorted(read_csv('week13_v28_governed_top5.csv'),key=lambda x:int(x['rank'])):
        lines.append(f"| {r['rank']} | {r['pick']} {float(r['pick_spread']):+.1f} | 1 |")
    lines += ['', '## Complete 69-game intake', '', 'Model margin is home minus away; positive favors home. Total selections are research outputs. Confidence is the governed ATS confidence.', '',
              '| # | Matchup | ATS pick | Model margin | Confidence | Total pick | Model total | Status |',
              '|---:|---|---|---:|---:|---|---:|---|']
    for row in sorted(lock['lines']+lock['excluded'], key=lambda x:x['source_row']):
        gid = row['game_id']; matchup = f"{row['away']} @ {row['home']}"
        if gid not in ats:
            lines.append(f"| {row['source_row']} | {matchup} | -- | -- | -- | -- | -- | Elapsed before intake |")
        else:
            a=ats[gid];t=totals[gid]
            lines.append(f"| {row['source_row']} | {matchup} | {a['pick']} {float(a['pick_spread']):+.1f} | {float(a['projected_home_margin']):+.2f} | {a['confidence']} | {t['pick'].title()} {float(t['locked_total']):.1f} | {float(t['projected_total']):.2f} | Upcoming |")
    lines += ['', '## Verification', '',
              '69 canonical matches; 0 duplicate games; 0 unresolved teams; 0 kickoff conflicts; 67/67 ATS and totals forecasts; 0 model or feature fallbacks; 5 governed Top 5 picks. Every forecast replays numerically from the saved point-in-time components. SQLite integrity is OK with 0 foreign-key violations, and every original row is preserved in the disposable database.', '',
              'The source database remains unchanged. See `week13_database_verification.json`, `week13_model_manifest.json`, `week13_ingestion_manifest.json`, and `week13_raw_model_components.json` in this directory for hashes, policies, counts and reproducibility evidence.', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--write-report',action='store_true')
    args = parser.parse_args()
    if args.write_report:
        value = report()
        with (OUT/'week13_model_report.md').open('x',encoding='utf-8',newline='\n') as stream:
            stream.write(value)
    else:
        print(json.dumps(verify(),sort_keys=True))
