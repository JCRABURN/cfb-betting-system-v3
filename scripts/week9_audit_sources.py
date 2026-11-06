"""Strict offline evidence reader for the separately versioned Week 9 audit."""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOARD = ROOT / 'outputs/2026-week9-prospective'
PRELIMINARY = ROOT / 'outputs/2026-week9-postgame-preliminary'
CAPTURE = ROOT / 'outputs/2026-week9-postgame-evidence/20261104T150801Z'
ADVANCED = ROOT / 'outputs/2026-week9-postgame-evidence/20261104T151428Z-advanced'
BASELINE = '190c8949edcf8da806908b567d4daa59b605f1cd'
DEPENDENCY = '0d9a4b56bd49e3fbef4326aa7a5bd6eec9d13e29'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def read_json(path: Path):
    return json.loads(path.read_bytes())


def read_csv(path: Path) -> list[dict]:
    return list(csv.DictReader(io.StringIO(path.read_bytes().decode('utf-8-sig'))))


def instant(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('timezone required')
    return result


def unique(rows, key='game_id') -> dict:
    result = {str(r[key]): r for r in rows}
    if len(result) != len(rows):
        raise ValueError('duplicate identity: ' + key)
    return result


def load_response(folder: Path, record: dict):
    path = (folder / record['path']).resolve()
    if not path.is_relative_to(folder.resolve()):
        raise ValueError('response outside evidence directory')
    stored = path.read_bytes()
    raw = gzip.decompress(stored)
    if sha(stored) != record['stored_sha256'] or sha(raw) != record['raw_sha256'] or len(raw) != record['raw_bytes']:
        raise ValueError('raw response checksum mismatch')
    if record['status'] != 'CAPTURED' or record['http_status'] != 200:
        raise ValueError('unsuccessful required response')
    if instant(record['received_at_utc']) < instant(record['requested_at_utc']):
        raise ValueError('capture time contradiction')
    return json.loads(raw)


def captures():
    manifest = read_json(CAPTURE / 'capture-manifest.json')
    records = unique(manifest['records'], 'name')
    ids = set(unique(read_csv(BOARD / 'week9_ats_full_card.csv')))
    expected = {'espn-scoreboard', 'cfbd-games', 'cfbd-team-stats', 'cfbd-player-stats', 'cfbd-advanced', 'cfbd-drives', 'cfbd-plays'} | {'espn-' + gid for gid in ids}
    if len(ids) != 54 or set(records) != expected or manifest['required_game_ids'] != sorted(ids):
        raise ValueError('exact source capture coverage required')
    if sha((ROOT/'scripts/capture_week9_postgame.py').read_bytes().replace(b'\r\n', b'\n')) != manifest['capture_code_sha256_lf']:
        raise ValueError('original capture code identity changed')
    if manifest['status'] != 'CAPTURED_REQUIRES_RECONCILIATION' or manifest['required_request_failures']:
        raise ValueError('capture status contradiction')
    data = {name: load_response(CAPTURE, row) for name, row in records.items() if name != 'cfbd-advanced'}
    supplement = read_json(ADVANCED / 'capture-manifest.json')
    if sha((ROOT/'scripts/capture_week9_advanced_supplement.py').read_bytes().replace(b'\r\n', b'\n')) != supplement['capture_code_sha256_lf']:
        raise ValueError('supplement capture code identity changed')
    data['cfbd-advanced'] = load_response(ADVANCED, supplement)
    records['cfbd-advanced-supplement'] = supplement
    return manifest, records, data


def nonnegative_score(value) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ValueError('invalid score type')
    result = int(value)
    if str(result) != str(value) or result < 0:
        raise ValueError('invalid score')
    return result


def espn_final(event: dict, schedule: dict) -> tuple[int, int]:
    week = event['week']['number'] if isinstance(event['week'], dict) else event['week']
    if str(event['id']) != str(schedule['id']) or event['season']['year'] != 2026 or type(week) is not int or week != 9:
        raise ValueError('ESPN game/season/week mismatch')
    competitions = event['competitions']
    if len(competitions) != 1:
        raise ValueError('ambiguous competition')
    game = competitions[0]
    if game['status']['type']['completed'] is not True:
        raise ValueError('ESPN game not final')
    competitors = unique(game['competitors'], 'homeAway')
    if set(competitors) != {'home', 'away'}:
        raise ValueError('ESPN orientation coverage')
    for side in ('home', 'away'):
        if str(competitors[side]['team']['id']) != str(schedule[side + 'Id']):
            raise ValueError('ESPN team orientation mismatch')
    return tuple(nonnegative_score(competitors[side]['score']) for side in ('away', 'home'))


def reconcile(data: dict, records: dict) -> tuple[list[dict], dict]:
    ats = unique(read_csv(BOARD / 'week9_ats_full_card.csv'))
    totals = unique(read_csv(BOARD / 'week9_totals_full_card.csv'))
    schedule = unique(read_json(BOARD / 'provider-evidence/cfbd-week9-games.derived.json'), 'id')
    locks = unique(read_json(BOARD / 'week9_locked_line_snapshot.json')['lines'])
    if len(ats) != 54 or not set(ats) == set(totals) == set(schedule) == set(locks):
        raise ValueError('exact 54-game frozen coverage required')
    cfbd = unique(data['cfbd-games'], 'id')
    scoreboard = unique(data['espn-scoreboard']['events'], 'id')
    preliminary = unique(read_csv(PRELIMINARY / 'week9_final_scoreboard_secondary.csv'))
    if set(preliminary) != set(ats):
        raise ValueError('preliminary coverage mismatch')
    generation = instant(read_json(BOARD / 'week9_model_manifest.json')['generated_at_utc'])
    rows, discrepancies = [], []
    for gid in sorted(ats):
        g, old = cfbd[gid], schedule[gid]
        if g['season'] != 2026 or g['week'] != 9 or g['seasonType'] != 'regular' or g['completed'] is not True:
            raise ValueError('CFBD game identity or final status')
        if old['completed'] or old['homePoints'] is not None or old['awayPoints'] is not None or generation >= instant(old['startDate']):
            raise ValueError('postgame contamination of frozen schedule')
        for side in ('home', 'away'):
            if g[side + 'Id'] != old[side + 'Id'] or g[side + 'Team'] != old[side + 'Team'] or ats[gid][side] != totals[gid][side]:
                raise ValueError('CFBD team orientation mismatch')
        scores = (nonnegative_score(g['awayPoints']), nonnegative_score(g['homePoints']))
        summary = data['espn-' + gid]['header']
        if espn_final(summary, old) != scores or espn_final(scoreboard[gid], old) != scores:
            raise ValueError('cross-provider final score conflict')
        receipt = records['espn-' + gid]
        if instant(receipt['requested_at_utc']) <= instant(g['startDate']):
            raise ValueError('postgame evidence capture predates kickoff')
        before = tuple(nonnegative_score(preliminary[gid][side + '_final']) for side in ('away', 'home'))
        if before != scores:
            discrepancies.append(dict(game_id=gid, preliminary=list(before), independently_verified=list(scores)))
        rows.append(dict(game_id=gid, away=ats[gid]['away'], home=ats[gid]['home'],
                         away_id=g['awayId'], home_id=g['homeId'], away_score=scores[0], home_score=scores[1],
                         cfbd_game_id=g['id'], espn_event_id=summary['id'], final_status='FINAL_BOTH_PROVIDERS',
                         frozen_kickoff_utc=locks[gid]['source_kickoff_utc'], cfbd_kickoff_utc=g['startDate'],
                         espn_kickoff_utc=summary['competitions'][0]['date'], neutral_site=g['neutralSite'],
                         preliminary_score_matches=(before == scores),
                         espn_raw_sha256=receipt['raw_sha256'], cfbd_raw_sha256=records['cfbd-games']['raw_sha256'],
                         espn_captured_at_utc=receipt['received_at_utc'], cfbd_captured_at_utc=records['cfbd-games']['received_at_utc'],
                         espn_source_url=receipt['resolved_url'], cfbd_source_url=records['cfbd-games']['resolved_url']))
    return rows, dict(version='week9-formal-supersession-v1', baseline_commit=BASELINE,
                      baseline_status='PRELIMINARY_SECONDARY_SCOREBOARD_ONLY_NOT_FORMAL_AUDIT',
                      disposition='ADDITIVE_INDEPENDENT_RECONCILIATION', games=54, score_discrepancies=discrepancies,
                      original_evidence_preserved=True, prior_scores_not_used_as_authority=True)
