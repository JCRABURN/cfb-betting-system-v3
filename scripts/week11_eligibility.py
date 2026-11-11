"""Append-only current schedule reconciliation; never locks lines or runs models."""
from __future__ import annotations

import argparse
import gzip
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests

from scripts.capture_week6_core import _key
from scripts.capture_week11_readiness import CFBD, ESPN, PARENT, ROOT, digest, instant
from scripts.prepare_week11_readiness import OUT, read_payload, serialized, timestamp, unique
from scripts.verify_week11_transcription import HASHES, load as load_source, reconcile as reconcile_source

SPECS = (
    ('cfbd', CFBD + '/games', {'year': 2026, 'week': 11, 'seasonType': 'regular'}),
    ('espn', ESPN, {'year': 2026, 'week': 11, 'seasontype': 2, 'groups': 80, 'limit': 300}),
)


def reconcile(cfbd: list[dict], espn: dict, schedule: list[dict], source: tuple,
              as_of: str) -> dict:
    """Keep every original line; expose exclusions and conflicts without score features."""
    cutoff = timestamp(as_of)
    source_review = reconcile_source(*source, schedule, as_of=as_of)
    archived = unique(schedule, 'game_id')
    games = unique(cfbd, 'id')
    if any(g['season'] != 2026 or g['week'] != 11 for g in games.values()):
        raise ValueError('CFBD season/week conflict')
    # Include either-side FBS, including any newly discovered FCS opponent.
    fbs_games = {gid: g for gid, g in games.items()
                 if 'fbs' in (g['homeClassification'], g['awayClassification'])}
    if espn['season'] != {'type': 2, 'year': 2026} or espn['week']['number'] != 11:
        raise ValueError('ESPN season/week conflict')
    events = unique(espn['events'], 'id')
    if set(fbs_games) != set(archived) or set(events) != set(archived):
        raise ValueError('schedule coverage changed: reconcile missing or additional games before execution')
    source_rows = {r['game_id']: s for s, r in zip(source[0], source[3])}
    rows = []
    for gid, old in sorted(archived.items(), key=lambda pair: (pair[1]['kickoff_utc'], pair[0])):
        game, event = fbs_games[gid], events[gid]
        if len(event['competitions']) != 1:
            raise ValueError('ambiguous ESPN competition')
        competition = event['competitions'][0]
        sides = unique(competition['competitors'], 'homeAway')
        if set(sides) != {'home', 'away'}:
            raise ValueError('provider orientation missing')
        for side in ('home', 'away'):
            if (str(game[side + 'Id']) != str(old[side + '_id'])
                    or str(sides[side]['team']['id']) != str(old[side + '_id'])
                    or game[side + 'Team'] != old[side]
                    or game[side + 'Classification'] != old[side + '_classification']):
                raise ValueError('provider team identity/orientation/classification conflict')
        status = competition['status']['type']
        if not isinstance(game['completed'], bool) or not isinstance(status['completed'], bool):
            raise ValueError('nonboolean completion status')
        state = status['state']
        if state not in ('pre', 'in', 'post'):
            raise ValueError('unknown provider state')
        reasons = []
        old_time = timestamp(old['kickoff_utc'])
        cfbd_time, espn_time = timestamp(game['startDate']), timestamp(competition['date'])
        if old_time != cfbd_time or old_time != espn_time:
            reasons.append('KICKOFF_CHANGED_OR_CONTRADICTORY_REQUIRES_RECONCILIATION')
        if game['startTimeTBD'] or old['kickoff_tbd']:
            reasons.append('KICKOFF_TBD')
        # A later advertised kickoff must never revive a previously elapsed row.
        elapsed = min(old_time, cfbd_time, espn_time) <= cutoff
        started = state != 'pre' or game['completed'] or status['completed']
        if state == 'pre' and status['completed'] or state == 'post' and not status['completed']:
            reasons.append('ESPN_STATUS_CONTRADICTION')
        if game['completed'] != (state == 'post' and status['completed']):
            reasons.append('PROVIDER_COMPLETION_DISAGREEMENT')
        if not elapsed and not started:
            if game['homePoints'] is not None or game['awayPoints'] is not None:
                reasons.append('PREGAME_CFBD_SCORE_CONTAMINATION')
            # ESPN often represents unstarted games as 0-0. No score is a feature.
            if any(str(sides[s].get('score', '0')) not in ('0', '0.0') for s in sides):
                reasons.append('PREGAME_ESPN_SCORE_CONTAMINATION')
            if status.get('name') != 'STATUS_SCHEDULED':
                reasons.append('NOT_CONFIRMED_SCHEDULED')
        eligibility = ('EXCLUDED_STARTED_OR_ELAPSED_NO_RETROSPECTIVE_PICK' if elapsed or started
                       else 'BLOCKED_PROVIDER_CONFLICT' if reasons else 'UPCOMING_SCHEDULE_ONLY')
        original = source_rows[gid]
        rows.append(dict(game_id=gid, away=old['away'], home=old['home'],
                         original_home_spread=original['Spread'], original_total=original['Total'],
                         original_kickoff_utc=old['kickoff_utc'], cfbd_kickoff_utc=game['startDate'],
                         espn_kickoff_utc=competition['date'], cfbd_completed=game['completed'],
                         espn_state=state, espn_completed=status['completed'],
                         eligibility=eligibility, issues=reasons, model_eligible=False))
    return dict(version='week11-eligibility-v1', as_of_utc=as_of, games=rows,
                source_sha256=HASHES, source_rows=len(rows),
                upcoming_schedule_only=sum(r['eligibility'] == 'UPCOMING_SCHEDULE_ONLY' for r in rows),
                excluded_started_or_elapsed=sum(r['eligibility'].startswith('EXCLUDED') for r in rows),
                blocked_provider_conflict=sum(r['eligibility'].startswith('BLOCKED') for r in rows),
                status='OBSERVATION_ONLY_IMAGE_CUSTODY_AND_EXECUTION_PENDING',
                image_custody=source_review['original_image_custody'], original_images_verified=0,
                model_input_use='PROHIBITED: live responses may contain Week11 results; schedule/status gate only',
                freshness='Snapshot only; recheck both providers and the actual clock immediately before execution',
                predictions_generated=False, contest_lines_replaced=False, owner_approval='PENDING')


def capture(folder: Path) -> dict:
    folder = folder.resolve()
    if not folder.is_relative_to(PARENT) or folder == PARENT or folder.exists():
        raise ValueError('new timestamped readiness directory required; never overwrite')
    source = load_source()  # Verify original bytes before any network or writes.
    schedule = json.loads((OUT / 'schedule.json').read_bytes())
    key = _key()
    folder.mkdir(parents=True, exist_ok=False)
    records = []
    for name, url, params in SPECS:
        record = dict(name=name, endpoint=url, parameters=params, requested_at_utc=instant())
        headers = {'User-Agent': 'CFB-Week11-Eligibility/1.0'}
        if name == 'cfbd':
            headers['Authorization'] = 'Bearer ' + key
        try:
            response = requests.get(url, params=params, headers=headers, timeout=60)
            raw = response.content
            stored = gzip.compress(raw, mtime=0)
            path = name + '.json.gz'
            with (folder / path).open('xb') as stream:
                stream.write(stored)
            record.update(received_at_utc=instant(), path=path, http_status=response.status_code,
                          status='CAPTURED' if response.status_code == 200 else 'HTTP_ERROR',
                          raw_sha256=digest(raw), stored_sha256=digest(stored), raw_bytes=len(raw))
        except requests.RequestException as error:
            record.update(received_at_utc=instant(), status='REQUEST_FAILED', error_type=type(error).__name__)
        records.append(record)
    manifest = dict(version='week11-eligibility-capture-v1', records=records, as_of_utc=instant(),
                    source_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                    capture_code_sha256_lf=digest(Path(__file__).read_bytes().replace(b'\r\n', b'\n')),
                    status='CAPTURED' if all(r['status'] == 'CAPTURED' for r in records) else 'INCOMPLETE',
                    predictions_generated=False, model_input_use='PROHIBITED_SCHEDULE_STATUS_ONLY')
    with (folder / 'capture-manifest.json').open('xb') as stream:
        stream.write(serialized(manifest))
    # Any failed request, parse or reconciliation retains raw evidence and fails closed.
    payloads = {r['name']: read_payload(folder, r) for r in records}
    ledger = reconcile(payloads['cfbd'], payloads['espn'], schedule, source, manifest['as_of_utc'])
    with (folder / 'eligibility.json').open('xb') as stream:
        stream.write(serialized(ledger))
    verify(folder)
    return ledger


def verify(folder: Path) -> dict:
    manifest = json.loads((folder / 'capture-manifest.json').read_bytes())
    if (manifest['version'] != 'week11-eligibility-capture-v1' or manifest['status'] != 'CAPTURED'
            or manifest['predictions_generated'] is not False
            or manifest['model_input_use'] != 'PROHIBITED_SCHEDULE_STATUS_ONLY'):
        raise ValueError('capture status contradiction')
    if manifest['capture_code_sha256_lf'] != digest(Path(__file__).read_bytes().replace(b'\r\n', b'\n')):
        raise ValueError('capture code custody mismatch')
    records = unique(manifest['records'], 'name')
    if set(records) != {s[0] for s in SPECS}:
        raise ValueError('exact provider coverage required')
    if {p.name for p in folder.iterdir()} != {'capture-manifest.json', 'eligibility.json', 'cfbd.json.gz', 'espn.json.gz'}:
        raise ValueError('exact capture file coverage required')
    for name, url, params in SPECS:
        record = records[name]
        if record['endpoint'] != url or record['parameters'] != params or record['path'] != name + '.json.gz':
            raise ValueError('provider request identity mismatch')
        if timestamp(record['received_at_utc']) > timestamp(manifest['as_of_utc']):
            raise ValueError('receipt after eligibility cutoff')
    payloads = {name: read_payload(folder, r) for name, r in records.items()}
    result = reconcile(payloads['cfbd'], payloads['espn'], json.loads((OUT / 'schedule.json').read_bytes()),
                       load_source(), manifest['as_of_utc'])
    if serialized(result) != (folder / 'eligibility.json').read_bytes():
        raise ValueError('exact eligibility replay mismatch')
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', type=Path)
    args = parser.parse_args()
    folder = args.verify or PARENT / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-eligibility')
    result = verify(folder) if args.verify else capture(folder)
    print(json.dumps(dict(output=str(folder), **{k: result[k] for k in (
        'as_of_utc', 'source_rows', 'upcoming_schedule_only', 'excluded_started_or_elapsed',
        'blocked_provider_conflict', 'predictions_generated', 'status')})))


if __name__ == '__main__':
    main()
