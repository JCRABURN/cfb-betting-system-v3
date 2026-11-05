"""Read-only custody and point-in-time verification of separate human judgments."""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path

from scripts.verify_week10_acceptance import verify as verify_board, EXPECTED_SEAL_SHA256

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'outputs/2026-week10-prospective'
CONTEXT = ROOT / 'outputs/2026-week10-context'
REVIEWS = ROOT / 'outputs/2026-week10-owner-review'


def instant(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.utcoffset() is None:
        raise ValueError('timezone required')
    return result


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def confined(name, parent):
    path = (ROOT / name).resolve()
    if not path.is_relative_to(parent):
        raise ValueError('path outside custody directory')
    return path


def records(manifest):
    result = list(manifest['records'])
    for weather in manifest.get('weather', []):
        result.extend(weather.get('requests', []))
    return result


def verify_team_metrics(path):
    """Recompute descriptive context using sealed inputs strictly through Week9."""
    core = BOARD / 'core-initial'
    advanced = {r['team']: r for r in json.loads((core/'week9-advanced.raw.json').read_text())}
    games = json.loads((core/'games.raw.json').read_text())
    rows = json.loads(path.read_text(encoding='utf-8'))['rows']
    if len(rows) != 20 or len({r['team'] for r in rows}) != 20:
        raise ValueError('team metric coverage')
    for row in rows:
        prior = sorted((g for g in games if g['week'] <= 9 and g['completed'] and
                        row['team'] in (g['homeTeam'], g['awayTeam'])), key=lambda g:g['startDate'])
        offense = advanced[row['team']]['offense']; defense = advanced[row['team']]['defense']
        expected = dict(team=row['team'], games=len(prior),
                        off_ppa=round(offense['ppa'],3), def_ppa=round(defense['ppa'],3),
                        off_success=round(offense['successRate'],3), def_success=round(defense['successRate'],3),
                        off_explosiveness=round(offense['explosiveness'],3), def_explosiveness=round(defense['explosiveness'],3),
                        off_eligible_plays_per_game=round(offense['plays']/len(prior),1),
                        off_eligible_drives_per_game=round(offense['drives']/len(prior),2),
                        rush_rate=round(offense['rushingPlays']['rate'],3),
                        recent_totals=[g['homePoints']+g['awayPoints'] for g in prior[-3:]])
        if expected != row:
            raise ValueError('context metric replay mismatch')


def validate(review, *, check_board=True):
    if check_board:
        verify_board()
    if review['sealed_board_sha256'] != EXPECTED_SEAL_SHA256:
        raise ValueError('seal identity')
    if review['owner_approval'] != 'PENDING' or review['model_policy_changed'] is not False:
        raise ValueError('approval or policy contradiction')
    if sha(confined(review['human_brief_path'], ROOT/'docs')) != review['human_brief_sha256']:
        raise ValueError('human brief identity')
    when = instant(review['created_at_utc'])
    inventory_path = confined(review['evidence_inventory_path'], CONTEXT)
    if sha(inventory_path) != review['evidence_inventory_sha256']:
        raise ValueError('inventory identity')
    inventory = json.loads(inventory_path.read_text(encoding='utf-8'))
    expected_paths = set(inventory['sha256'])
    scope = set(review['evidence_directories'])
    actual_paths = {p.relative_to(ROOT).as_posix() for directory in scope
                    for p in confined(directory, CONTEXT).rglob('*')
                    if p.is_file() and p.suffix != '.pdf'}
    if actual_paths != expected_paths:
        raise ValueError('exact evidence checksum coverage')
    for name, digest in inventory['sha256'].items():
        if sha(confined(name, CONTEXT)) != digest:
            raise ValueError('evidence bytes changed: ' + name)
        if name.endswith('/derived-team-metrics.json'):
            verify_team_metrics(ROOT / name)
    sources = {}
    for name in sorted(expected_paths):
        if not name.endswith('/capture-manifest.json'):
            continue
        path = ROOT / name
        for record in records(json.loads(path.read_text(encoding='utf-8'))):
            if not record.get('path'):
                continue
            raw_path = (path.parent / record['path']).resolve()
            if not raw_path.is_relative_to(path.parent):
                raise ValueError('raw source path escape')
            raw = gzip.decompress(raw_path.read_bytes())
            if hashlib.sha256(raw).hexdigest() != record['sha256']:
                raise ValueError('raw response checksum')
            if not instant(record['requested_at_utc']) <= instant(record['received_at_utc']) <= when:
                raise ValueError('future or reversed source retrieval')
            if record['name'].startswith('weather-hourly-'):
                generated = json.loads(raw)['properties']['generatedAt']
                if instant(generated) > instant(record['received_at_utc']):
                    raise ValueError('weather published after retrieval')
            if record['name'] == 'sunbelt-availability-data':
                game = next(g for g in json.loads(raw)['games'] if g['gameId'] == '2026-11-05-Southern Miss-James Madison')
                if instant(game['updatedAtUTC']) > instant(record['received_at_utc']):
                    raise ValueError('availability published after retrieval')
            sources[(name, record['name'])] = record
    originals = {}
    for market, filename in [('ATS', 'week10_ats_research_top5.csv'), ('TOTAL', 'week10_totals_research_top5.csv')]:
        with (BOARD / filename).open(encoding='utf-8', newline='') as stream:
            originals.update({(int(r['game_id']), market): r for r in csv.DictReader(stream)})
    locked = {r['game_id']: r for r in json.loads((BOARD / 'week10_locked_line_snapshot.json').read_text())['lines']}
    previous = {}
    if review.get('previous_review_path'):
        path = confined(review['previous_review_path'], REVIEWS)
        if sha(path) != review['previous_review_sha256']:
            raise ValueError('previous review identity')
        prior = json.loads(path.read_text(encoding='utf-8'))
        if instant(prior['created_at_utc']) >= when:
            raise ValueError('previous review chronology')
        validate(prior, check_board=False)
        previous = {(r['game_id'], r['market']): r for r in prior['selections']}
    rows = review['selections']
    if len(rows) != 10 or {(r['game_id'], r['market']) for r in rows} != set(originals):
        raise ValueError('exact ten-candidate coverage')
    for rank, row in enumerate(rows, 1):
        key = row['game_id'], row['market']
        original = originals[key]
        cutoff = instant(locked[row['game_id']]['source_kickoff_utc'])
        created = instant(row['created_at_utc'])
        if row['owner_review_rank'] != rank or row['recommended_five'] is not (rank <= 5):
            raise ValueError('rank or membership')
        confidence = row['human_review_confidence_1_to_5']
        if type(confidence) is not int or not 1 <= confidence <= 5:
            raise ValueError('human confidence bounds/type')
        if row['numeric_projection_adjustment'] != 0 or row['owner_approval'] != 'PENDING':
            raise ValueError('adjustment or approval')
        if not created <= when or created >= cutoff:
            raise ValueError('late recommendation')
        if when >= cutoff and previous.get(key) != row:
            raise ValueError('started row must equal previous version including rank/membership')
        ats = row['market'] == 'ATS'
        mapping = {'locked_line': 'pick_spread' if ats else 'locked_total',
                   'frozen_projection_home_margin_or_total': 'projected_home_margin' if ats else 'projected_total',
                   'frozen_confidence': 'confidence',
                   'original_market_research_rank': 'ats_research_rank' if ats else 'totals_research_rank',
                   'research_score_not_calibrated': 'ats_shadow_score_not_calibrated' if ats else 'raw_selected_probability',
                   'frozen_uncertainty_points': 'shadow_uncertainty_points' if ats else 'uncertainty_points'}
        for target, field in mapping.items():
            value = row[target]
            if type(value) not in (int, float) or not math.isfinite(value) or value != float(original[field]):
                raise ValueError('frozen value mismatch: ' + target)
        edge = abs(float(original['home_ats_edge' if ats else 'raw_point_edge']))
        if row['selected_forecast_edge'] != edge or any(row[k] != original[k] for k in ('away', 'home')) or row['selection'] != original['pick']:
            raise ValueError('selection identity or edge')
        if not row['sources'] or not row['rationale'] or not row['risks']:
            raise ValueError('review evidence missing')
        for reference in row['sources']:
            source = sources[(reference['manifest'], reference['name'])]
            if source.get('http_status') != 200 or source.get('status', 'CAPTURED') != 'CAPTURED':
                raise ValueError('unusable source')
            if instant(source['received_at_utc']) > created:
                raise ValueError('source after row decision')
            if reference.get('published_at_utc') and instant(reference['published_at_utc']) > instant(source['received_at_utc']):
                raise ValueError('publication after capture')
    return dict(verified_candidates=10, recommended_five=5, owner_approval='PENDING',
                frozen_values_unchanged=True, evidence_files=len(expected_paths),
                numeric_adjustments=0, clv_status='INCOMPLETE')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('path', type=Path)
    print(json.dumps(validate(json.loads(parser.parse_args().path.read_text(encoding='utf-8'))), indent=2))
