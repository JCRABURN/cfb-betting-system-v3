"""Strict 67-game reconciliation, original forecast grading and immutable cohorts."""
from __future__ import annotations

import json
from decimal import Decimal
from scripts.week11_audit_inputs import EVIDENCE, BOARD, board_csv, source_csv, source_json, source_files
from scripts.week10_audit_sources import unique, instant, load_response, nonnegative_score
from scripts.week9_audit_grading import grade_selection, decimal
from scripts.week8_scoring_sequence_review import validate_sequence
from scripts.week5_postgame_core import classify_late_score

CAPTURE = EVIDENCE / '20261116-v1'


def load_capture():
    manifest = json.loads((CAPTURE / 'capture-manifest.json').read_bytes())
    records = unique(manifest['records'], 'name')
    expected_ids = sorted(r['game_id'] for r in source_csv('data/ingest/2026-week11-splashsports-schedule-reconciliation.csv'))
    expected = {'espn-' + gid for gid in expected_ids} | {'espn-scoreboard', 'cfbd-games', 'cfbd-team-stats', 'cfbd-player-stats', 'cfbd-advanced', 'cfbd-drives', 'cfbd-plays', 'cfbd-lines'}
    if manifest['required_game_ids'] != expected_ids or set(records) != expected or manifest['request_failures'] or manifest['season'] != 2026 or manifest['week'] != 11:
        raise ValueError('Capture identity or coverage mismatch')
    if manifest['status'] != 'CAPTURED_REQUIRES_RECONCILIATION' or manifest['postgame_only'] is not True or manifest['prediction_or_database_writes'] is not False:
        raise ValueError('Capture status contradiction')
    data = {k: load_response(CAPTURE, v) for k, v in records.items()}
    return manifest, records, data


def espn_score(event, game):
    week = event['week']['number'] if isinstance(event['week'], dict) else event['week']
    if str(event['id']) != str(game['id']) or event['season']['year'] != 2026 or week != 11:
        raise ValueError('ESPN event season/week/identity mismatch')
    if len(event['competitions']) != 1:
        raise ValueError('Ambiguous competition')
    match = event['competitions'][0]
    if match['status']['type']['completed'] is not True:
        raise ValueError('ESPN not final')
    sides = unique(match['competitors'], 'homeAway')
    if set(sides) != {'home', 'away'} or any(str(sides[s]['team']['id']) != str(game[s + 'Id']) for s in sides):
        raise ValueError('ESPN orientation mismatch')
    return tuple(nonnegative_score(sides[s]['score']) for s in ('away', 'home'))


def reconcile(data, records):
    schedule = source_csv('data/ingest/2026-week11-splashsports-schedule-reconciliation.csv')
    games = unique(data['cfbd-games'], 'id')
    events = unique(data['espn-scoreboard']['events'], 'id')
    predicted = unique(board_csv('ats_full_card'))
    totals = unique(board_csv('totals_full_card'))
    if len(schedule) != 67 or len(predicted) != 64 or set(predicted) != set(totals):
        raise ValueError('67 original / 64 recorded game coverage')
    seal = source_json(BOARD + 'week11_initial_seal_manifest.json')
    rows = []
    for s in schedule:
        gid = s['game_id']
        g = games[gid]
        if g['season'] != 2026 or g['week'] != 11 or g['seasonType'] != 'regular' or g['completed'] is not True:
            raise ValueError('CFBD final identity mismatch')
        if any(g[side + 'Team'] != s['canonical_' + side] for side in ('away', 'home')):
            raise ValueError('Archived canonical matchup mismatch')
        scores = tuple(nonnegative_score(g[side + 'Points']) for side in ('away', 'home'))
        summary = data['espn-' + gid]['header']
        if espn_score(summary, g) != scores or espn_score(events[gid], g) != scores:
            raise ValueError('Provider score discrepancy: ' + gid)
        if instant(records['espn-' + gid]['requested_at_utc']) <= instant(g['startDate']):
            raise ValueError('Postgame capture must follow kickoff')
        classification = ('NO_ORIGINAL_FORECAST_TUESDAY' if gid not in predicted else
                          'FORWARD_SEALED_61' if instant(s['provider_utc_kickoff']) > instant(seal['sealed_at_utc']) else
                          'LATE_WEDNESDAY_CUSTODY_NOT_INDEPENDENTLY_VERIFIED_PREGAME')
        rows.append(dict(week=11, game_id=gid, away=s['canonical_away'], home=s['canonical_home'],
                         away_id=g['awayId'], home_id=g['homeId'], away_score=scores[0], home_score=scores[1],
                         cfbd_game_id=g['id'], espn_game_id=summary['id'], final_status='FINAL_BOTH_PROVIDERS',
                         locked_home_spread=s['home_spread'], locked_total=s['locked_total'],
                         source_order=int(s['source_order']), kickoff_utc=s['provider_utc_kickoff'],
                         actual_kickoff_utc=g['startDate'], neutral_site=g['neutralSite'],
                         conference_game=g.get('conferenceGame'), custody=classification,
                         espn_raw_sha256=records['espn-' + gid]['raw_sha256'], cfbd_raw_sha256=records['cfbd-games']['raw_sha256'],
                         espn_source_url=records['espn-' + gid]['resolved_url'], cfbd_source_url=records['cfbd-games']['resolved_url'],
                         espn_retrieved_at_utc=records['espn-' + gid]['received_at_utc'], cfbd_retrieved_at_utc=records['cfbd-games']['received_at_utc']))
    if sum(r['custody'] == 'FORWARD_SEALED_61' for r in rows) != 61 or len(set(r['game_id'] for r in rows) - set(predicted)) != 3:
        raise ValueError('Custody subset coverage mismatch')
    return rows


def grades(finals, data):
    final = unique(finals)
    locks = unique(source_json(BOARD + 'week11_locked_line_snapshot.json')['lines'])
    result = []
    for market, name in [('ATS', 'ats'), ('TOTAL', 'totals')]:
        for original in board_csv(name + '_full_card'):
            gid = original['game_id']
            f = final[gid]
            row = grade_selection(original, market, f, locks[gid])
            row.update(week=11, custody=f['custody'], conference_game=f['conference_game'], kickoff_utc=f['kickoff_utc'])
            error = decimal(row['forecast_error_actual_minus_predicted'])
            row.update(absolute_forecast_error=str(abs(error)), squared_forecast_error=str(error * error),
                       production_uncertainty_points=original.get('uncertainty_points') or None)
            row['line_implied_forecast'] = -float(original['locked_home_spread']) if market == 'ATS' else float(original['locked_total'])
            row['actual_relative_to_locked_line'] = str(decimal(row['actual_model_target']) - decimal(row['line_implied_forecast']))
            seq = data['espn-' + gid].get('scoringPlays', [])
            try:
                validate_sequence(seq, f['away_score'], f['home_score'])
                row['scoring_sequence_status'] = 'VALIDATED'
            except (ValueError, KeyError, TypeError):
                row['scoring_sequence_status'] = 'UNAVAILABLE_OR_CONTRADICTORY'
            boundary = abs(decimal(row['cover_margin'])) == Decimal('.5') and abs(decimal(row['locked_line'])) % 1 == Decimal('.5')
            row['hook_classification'] = ('WINNING_HOOK' if row['result'] == 'WIN' else 'LOSING_HOOK') if boundary else 'NOT_APPLICABLE'
            row['backdoor_details'] = (classify_late_score(seq, original['selected_side'], original['locked_home_spread'], f['away_score'], f['home_score'])
                                       if market == 'ATS' and row['scoring_sequence_status'] == 'VALIDATED' else {'classification': 'NOT_APPLICABLE_TOTAL' if market == 'TOTAL' else 'UNVERIFIABLE'})
            result.append(row)
    return result


def cohorts(rows):
    lookup = {(r['market'], r['game_id']): r for r in rows}
    groups = {}
    for market in ('ATS', 'TOTAL'):
        for count in (5, 10):
            groups[f'{market}_RESEARCH_TOP{count}'] = sorted([r for r in rows if r['market'] == market and r['research_rank'] <= count], key=lambda r:r['research_rank'])
    groups['GOVERNED_ATS_TOP5'] = [lookup['ATS',r['game_id']] for r in board_csv('v28_governed_top5')]
    groups['ORIGINAL_COMBINED_RESEARCH_TOP5'] = []
    for r in board_csv('legacy_mixed_research_top5'):
        row = lookup[r['market'], r['game_id']]
        if row['selection'] != r['pick'] or decimal(row['locked_line']) != decimal(r['locked_line']) or decimal(row['raw_projection']) != decimal(r['projection']):
            raise ValueError('Original combined cohort changed')
        groups['ORIGINAL_COMBINED_RESEARCH_TOP5'].append(row)
    for path in sorted(p for p in source_files() if p.startswith('outputs/2026-week11-owner-review/') and p.endswith('/review.json')):
        review = source_json(path)
        group = []
        for choice in review['choices']:
            row = lookup[choice['market'], str(choice['game_id'])]
            if choice['pick'].lower() != row['selection'].lower() or decimal(choice['contest_line']) != decimal(row['locked_line']) or decimal(choice['frozen_projection']) != decimal(row['raw_projection']):
                raise ValueError('Contextual cohort identity/projection mismatch')
            if instant(review['created_at_utc']) >= instant(row['kickoff_utc']):
                raise ValueError('Postkickoff contextual selection')
            group.append(dict(row, confidence=choice['human_confidence'], review_created_at_utc=review['created_at_utc'], source_review=path))
        groups['HUMAN_' + path.split('/')[-2]] = group
    if any(len(v) != (10 if k.endswith('TOP10') else 5) for k, v in groups.items()):
        raise ValueError('Frozen cohort membership count')
    return groups
