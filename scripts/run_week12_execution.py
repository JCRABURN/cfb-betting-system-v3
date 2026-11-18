"""Execute unchanged models for upcoming Week 12 games in a disposable copy."""
from __future__ import annotations
import argparse
import csv
import json
import sqlite3
import subprocess
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from business_entities.full_card import locked_line_snapshot_sha256
from business_entities.totals_weekly_model import run_component_totals_shadow_model
from business_entities.weekly_controller import run_epa_only_model
from contest_lines import create_contest, list_effective_locked_lines, lock_contest_line
from migrations.runner import apply_migrations, table_row_counts
from operations.providers import CfbdGamesParser, CfbdTeamStatsParser, _write_games, _write_team_stats
from scripts import prepare_week12_source as source
from scripts.prepare_week11_readiness import read_payload, serialized, timestamp, unique
from scripts.run_week11_execution import prior_stats
from scripts.run_week6_execution import ingest

ROOT = source.ROOT
OUT = ROOT/'outputs/2026-week12-prospective'
SOURCE_DB = ROOT/'data/cfb.db'
CONTEST_KEY = 'splashsports-cfb-2026-w12'


def eligibility(rows: list[dict], data: dict, as_of: datetime, now: datetime) -> tuple[list[dict], list[dict]]:
    if not timedelta(0) <= now-as_of <= timedelta(minutes=5):
        raise ValueError('live eligibility must be at most five minutes old')
    reconciled, _ = source.reconcile(rows, data, now)
    if any(r['status']=='BLOCKED_PROVIDER_CONFLICT' for r in reconciled):
        raise ValueError('unresolved upcoming provider conflicts')
    return [r for r in reconciled if r['status']=='UPCOMING'], [r for r in reconciled if r['status']!='UPCOMING']


def run(database: Path, capture: Path) -> dict:
    source.main(True)
    database = database.resolve(); capture = capture.resolve()
    if not database.is_relative_to(ROOT) or database == SOURCE_DB or database.exists() or OUT.exists():
        raise ValueError('new disposable DB and append-only execution output required')
    if not capture.is_relative_to(ROOT/'outputs/2026-week12-readiness'):
        raise ValueError('capture outside isolated Week 12 scope')
    manifest, records, data = source.load_capture(capture)
    now = datetime.now(timezone.utc)
    as_of = max(timestamp(r['received_at_utc']) for r in records.values())
    if any(timestamp(r['received_at_utc'])>now for r in records.values()):
        raise ValueError('future feature receipt')
    rows = source.parse_pages(json.loads((source.SOURCE/'extracted-pages.json').read_bytes()))
    locked, excluded = eligibility(rows, data, as_of, now)
    if len(locked)+len(excluded)!=66 or not locked:
        raise ValueError('intake coverage')
    target_ids = {r['game_id'] for r in locked}
    games = data['cfbd-games-all']
    targets = [g for g in games if g['id'] in target_ids]
    if len(targets)!=len(locked) or any(g['week']!=12 or g['completed'] or g['homePoints'] is not None or g['awayPoints'] is not None for g in targets):
        raise ValueError('target result contamination')
    def adapter(r):
        return {**r,'requested_at':r['requested_at_utc'],'sha256':r['raw_sha256']}
    stats = [(w,*prior_stats(w)) for w in range(4,10)]
    old = ROOT/'outputs/2026-week11-readiness/20261110T193209Z'
    old_records = unique(json.loads((old/'capture-manifest.json').read_bytes())['records'],'name')
    old_item = old_records['cfbd-prior-season-advanced']
    if old_item['parameters'] != {'year':2026,'endWeek':10,'excludeGarbageTime':'true'}:
        raise ValueError('historical feature cutoff')
    stats.append((10, read_payload(old,old_item),adapter(old_item)))
    stats.append((11,data['cfbd-prior-season-advanced'],adapter(records['cfbd-prior-season-advanced'])))
    if any(timestamp(item['requested_at'])>now for _,_,item in stats):
        raise ValueError('future training feature receipt')
    source_hash = source.digest(SOURCE_DB.read_bytes())
    database.parent.mkdir(parents=True,exist_ok=True)
    with database.open('xb') as stream:
        stream.write(SOURCE_DB.read_bytes())
    conn = sqlite3.connect(database); conn.execute('PRAGMA foreign_keys=ON')
    before = table_row_counts(conn)
    if conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('source-copy integrity')
    migrations = apply_migrations(conn)
    for team in data['cfbd-fbs-teams']:
        if team['classification']!='fbs':
            raise ValueError('FBS registry')
        if not conn.execute('SELECT 1 FROM teams WHERE school=?',(team['school'],)).fetchone():
            conn.execute('INSERT INTO teams(team_id,school,conference,division) VALUES(?,?,?,?)',
                         (team['id'],team['school'],team.get('conference'),team.get('division')))
    conn.commit(); OUT.mkdir(exist_ok=False); (OUT/'provider-evidence').mkdir()
    ingestions = []
    for week in range(2,13):
        batch = targets if week==12 else [g for g in games if g['season']==2026 and g['week']==week and g['homeClassification']==g['awayClassification']=='fbs']
        if week<12 and any(not g['completed'] or timestamp(g['startDate'])>=now for g in batch):
            raise ValueError('prior week incomplete or future outcome')
        ingestions.append(ingest(conn,OUT,batch,name=f'cfbd-week{week}-games',item=adapter(records['cfbd-games-all']),
                                 parameters={'year':2026,'week':week,'classification':'fbs'},parser=CfbdGamesParser(),writer=_write_games))
    for week,values,item in stats:
        ingestions.append(ingest(conn,OUT,values,name=f'cfbd-week{week}-advanced',item=item,
                                 parameters={'year':2026,'endWeek':week,'excludeGarbageTime':'true'},parser=CfbdTeamStatsParser(),writer=_write_team_stats))
    contest = create_contest(conn,contest_key=CONTEST_KEY,name='SplashSports 2026 Week12',season=2026,week=12,
                             source='SplashSports',source_contest_id=CONTEST_KEY,created_at=now,provenance='original November17 PDF; isolated disposable copy')
    for row in locked:
        record = lock_contest_line(conn,contest_id=contest.id,game_id=row['game_id'],raw_home_team=row['raw_home'],raw_away_team=row['raw_away'],
            normalized_home_team=row['home'],normalized_away_team=row['away'],home_spread=row['home_spread'],total=row['locked_total'],
            source='SplashSports',source_line_id=f"pdf-page:{row['pdf_page']}:row:{row['source_row']}",payload_sha256=source.PDF_SHA,
            locked_at=now,provenance='PDF printed 2026-11-17T14:22-06:00; actual database lock time recorded separately')
        row['locked_line_id']=record.line.id
    conn.commit()
    lines = list_effective_locked_lines(conn,contest.id,as_of=now)
    if len(lines)!=len(locked):
        raise ValueError('lock coverage')
    csv_raw = source.csv_bytes(locked)
    (OUT/'eligible-lines.csv').write_bytes(csv_raw)
    lock_hash = locked_line_snapshot_sha256(lines)
    (OUT/'week12_locked_line_snapshot.json').write_bytes(serialized(dict(contest_key=CONTEST_KEY,locked_at_utc=now.isoformat(),source_print_time='2026-11-17T14:22:00-06:00',pdf_sha256=source.PDF_SHA,locked_line_snapshot_sha256=lock_hash,lines=locked,excluded=excluded)))
    commit = subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    ats = run_epa_only_model(conn,contest_id=contest.id,model_run_key='week12-20261118:epa',code_commit_sha=commit,generated_at=now,provenance='owner-request://2026-week12-prospective')
    totals = run_component_totals_shadow_model(conn,contest_id=contest.id,model_run_key='week12-20261118:component-totals',code_commit_sha=commit,generated_at=now,provenance='owner-request://2026-week12-prospective')
    conn.commit()
    counts = [conn.execute(f'SELECT COUNT(*) FROM {table} WHERE {field}=?',(run.id,)).fetchone()[0]
              for table,field,run in [('model_predictions','model_run_id',ats),('total_model_predictions','total_model_run_id',totals)]]
    if counts != [len(lines),len(lines)] or conn.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or conn.execute('PRAGMA foreign_key_check').fetchall():
        raise ValueError('prediction coverage or execution integrity')
    if source.digest(SOURCE_DB.read_bytes())!=source_hash:
        raise ValueError('protected database changed')
    if datetime.now(timezone.utc)>=min(timestamp(r['source_kickoff_utc']) for r in locked):
        raise ValueError('execution reached kickoff')
    result = dict(generated_at_utc=now.isoformat(),code_commit_sha=commit,source_database_sha256=source_hash,
                  source_csv_sha256=source.digest(csv_raw),original_source_sha256=source.PDF_SHA,
                  locked_line_snapshot_sha256=lock_hash,provider_capture=str(capture.relative_to(ROOT)).replace('\\','/'),
                  provider_capture_manifest_sha256=source.digest((capture/'capture-manifest.json').read_bytes()),provider_ingestion=ingestions,
                  before_counts=before,after_counts=table_row_counts(conn),migration_versions=[m.version for m in migrations],
                  locked_games=len(lines),ats_predictions=counts[0],totals_predictions=counts[1],
                  original_contest_games=66,excluded_completed_games=excluded,ats_run=asdict(ats),totals_run=asdict(totals),
                  integrity='ok',foreign_key_violations=0,external_week11_submissions_used=False)
    (OUT/'week12_ingestion_manifest.json').write_bytes(serialized(result)); conn.close()
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--database',type=Path,required=True); p.add_argument('--capture',type=Path,required=True)
    args=p.parse_args(); result=run(args.database,args.capture)
    print(json.dumps({k:result[k] for k in ('locked_games','ats_predictions','totals_predictions')}))
