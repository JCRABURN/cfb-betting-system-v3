"""Read-only descriptive research; run from the repository root. Prints JSON."""
import csv
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(rows):
    errors = [r['error_actual_minus_forecast'] for r in rows]
    return {'n': len(rows), 'bias_actual_minus_forecast': sum(errors)/len(errors),
            'mae': sum(abs(e) for e in errors)/len(errors),
            'rmse': math.sqrt(sum(e*e for e in errors)/len(errors)),
            'results': dict(Counter(r['result'] for r in rows))}


all_rows, sources = [], []
for week in range(5, 9):
    path = Path(f'outputs/2026-week{week}-postgame-audit/week{week}_totals_audit.csv')
    sources.append({'path': path.as_posix(), 'sha256': digest(path)})
    for r in csv.DictReader(path.open(encoding='utf-8-sig')):
        forecast = float(r.get('raw_projection', r.get('projected_total')))
        actual = float(r['actual_total'])
        all_rows.append({'week': week, 'game_id': int(r['game_id']), 'away': r['away'],
                         'home': r['home'], 'forecast': forecast, 'actual': actual,
                         'error_actual_minus_forecast': actual-forecast,
                         'selection': r.get('selection', r.get('selected_total')).lower(),
                         'result': r.get('result', r.get('total_result'))})
selected = [r for r in all_rows if {'Florida Atlantic', 'North Texas'} & {r['away'], r['home']}]
assert len(selected) == 5 and len({r['game_id'] for r in selected}) == 5

games = []
for gid in (401862809, 401862810):
    path = Path(f'outputs/2026-week8-postgame-audit/provider-evidence/espn-game-{gid}.json.gz')
    raw = gzip.decompress(path.read_bytes())
    data = json.loads(raw)
    assert data['header']['competitions'][0]['status']['type']['completed']
    drives = data['drives']['previous']
    assert len({d['id'] for d in drives}) == len(drives)
    teams = []
    for box in data['boxscore']['teams']:
        team = box['team']; tid = team['id']
        stats = {s['name']: s['displayValue'] for s in box['statistics']}
        snaps = int(stats['rushingAttempts']) + int(stats['completionAttempts'].split('/')[1])
        team_drives = [d for d in drives if d['team']['id'] == tid]
        observed = {}
        for drive in team_drives:
            for play in drive['plays']:
                assert play['id'] not in observed, 'Duplicate play in drive feed'
                observed[play['id']] = play
        explosive = [p for p in observed.values()
                     if p['type']['text'] in {'Rush', 'Rushing Touchdown', 'Pass Reception', 'Passing Touchdown'}
                     and float(p.get('statYardage', 0)) >= 20
                     and 'NO PLAY' not in p.get('text', '').upper()
                     and 'NULLIFIED' not in p.get('text', '').upper()]
        teams.append({'team': team['displayName'], 'provider_drive_records': len(team_drives),
                      'end_half_or_game_drive_records': sum(d.get('result') in {'END OF HALF', 'END OF GAME'} for d in team_drives),
                      'boxscore_scrimmage_plays': snaps, 'boxscore_yards': int(stats['totalYards']),
                      'yards_per_scrimmage_play': int(stats['totalYards'])/snaps,
                      'possession_time': stats['possessionTime'],
                      'observed_20plus_rush_or_completion_plays': len(explosive),
                      'observed_20plus_per_boxscore_play': len(explosive)/snaps,
                      'explosive_evidence': [{'id': p['id'], 'type': p['type']['text'], 'yards': p['statYardage'], 'text': p['text']} for p in explosive]})
    scoring = [{'type': p['type']['text'], 'text': p['text']} for p in data['scoringPlays']
               if p['type']['text'] in {'Punt Return Touchdown', 'Kickoff Return Touchdown', 'Fumble Return Touchdown', 'Interception Return Touchdown', 'Safety'}]
    games.append({'game_id': gid, 'source': path.as_posix(), 'compressed_sha256': digest(path),
                  'raw_sha256': hashlib.sha256(raw).hexdigest(), 'teams': teams,
                  'combined_provider_drive_records': len(drives),
                  'combined_boxscore_scrimmage_plays': sum(t['boxscore_scrimmage_plays'] for t in teams),
                  'non_offensive_scoring_events': scoring})

result = {'status': 'DESCRIPTIVE_RESEARCH_NOT_CALIBRATION_OR_NUMERIC_ADJUSTMENT',
          'source_hashes': sources, 'all_weeks5_to8_totals': metrics(all_rows),
          'week8_totals': metrics([r for r in all_rows if r['week'] == 8]),
          'fau_or_unt_audited_games': selected, 'fau_or_unt_metrics': metrics(selected),
          'fau_or_unt_under_metrics': metrics([r for r in selected if r['selection'] == 'under']),
          'week8_possession_and_explosive_review': games,
          'limitations': ['Five team-associated games are an outcome-informed diagnostic sample, not validation.',
                         'Games and opponents are not independent; one Tulsa game included overtime.',
                         'Drive counts include end-of-half/game possessions; no guessed kneel-only exclusion.',
                         'Scrimmage plays use rush attempts plus pass attempts from the box score; NCAA sacks count as rushing.',
                         '20+ numerator uses recorded rushes/completions only, excluding special teams and explicit nullified plays.',
                         'Provider drive/clock labels may be imperfect; no tempo forecast is inferred from two games.',
                         'Team-published season explosive definitions differ and must not be pooled.',
                         'No hypothetical subtraction of non-offensive scores is treated as a counterfactual final total.']}
print(json.dumps(result, indent=2))
