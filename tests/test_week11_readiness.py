import copy
import json
from datetime import timedelta
import pytest
from scripts import prepare_week11_readiness as audit


@pytest.fixture(scope='module')
def captured():
    manifest,records,data,extra=audit.load()
    as_of=max(audit.timestamp(r['received_at_utc']) for r in list(records.values())+[extra])
    return data,as_of


def test_all_capture_bytes_including_partial_and_failed_responses_preserved():
    path=audit.ROOT/'tests/fixtures/week11_readiness/input-custody.json'
    assert audit.digest(path.read_bytes())=='6b784ac384c679023c76e1c676154eedb320a4ae2e15f538947a815357a6bb72'
    expected=json.loads(path.read_bytes())['sha256_by_path']
    for name,digest in expected.items():assert audit.digest((audit.ROOT/name).read_bytes())==digest
    actual={p.relative_to(audit.ROOT).as_posix() for folder in (audit.CAPTURE,audit.SUPPLEMENT,audit.PARENT/'20261110T193338Z-schedule') for p in folder.iterdir()}
    assert actual|{'outputs/2026-week11-readiness/repository-baseline.json'}==set(expected)


def test_exact_readiness_replay_and_no_fabricated_locks():
    result=audit.main(True)
    assert result=={'status':'VERIFIED_READ_ONLY','files':7,'locked_games':0,'predictions':0}
    summary=json.loads((audit.OUT/'readiness.json').read_bytes())
    assert summary['scheduled_fbs_games']==summary['upcoming_at_capture']==67
    assert summary['fbs_vs_fcs_or_other']==0 and not summary['missing_model_features']
    assert not summary['owner_screenshots_received'] and not summary['top5_generated']
    assert summary['market_observations']==134 and summary['locked_games']==0


@pytest.mark.parametrize('mutation',['missing_cfbd','duplicate_cfbd','missing_espn','orientation','kickoff','classification','future_advanced','future_drive','market_orientation','pregame_score'])
def test_coverage_and_point_in_time_conflicts_fail_closed(captured,mutation):
    data,as_of=captured;data=copy.deepcopy(data)
    event=data['espn-complete']['events'][0];gid=event['id'];g=next(g for g in data['cfbd-games-all'] if str(g['id'])==gid)
    if mutation=='missing_cfbd':data['cfbd-games-all'].remove(g)
    elif mutation=='duplicate_cfbd':data['cfbd-games-all'].append(copy.deepcopy(g))
    elif mutation=='missing_espn':data['espn-complete']['events'].pop()
    elif mutation=='orientation':event['competitions'][0]['competitors'][0]['team']['id']='999999'
    elif mutation=='kickoff':event['competitions'][0]['date']='2026-11-15T00:00Z'
    elif mutation=='classification':g['homeClassification']='fcs'
    elif mutation=='future_advanced':data['cfbd-prior-week10-advanced'][0]['week']=11
    elif mutation=='future_drive':data['cfbd-prior-week10-drives'][0]['gameId']=int(gid)
    elif mutation=='market_orientation':data['cfbd-market-observations'][0]['awayTeamId']=999999
    elif mutation=='pregame_score':g['homePoints']=7
    with pytest.raises((ValueError,KeyError)):audit.reconcile(data,as_of)


def test_fcs_game_is_retained_and_missing_model_input_is_explicit(captured):
    data,as_of=captured;data=copy.deepcopy(data)
    gid=data['espn-complete']['events'][0]['id'];g=next(g for g in data['cfbd-games-all'] if str(g['id'])==gid)
    data['cfbd-fbs-teams']=[t for t in data['cfbd-fbs-teams'] if t['id']!=g['awayId']]
    g['awayClassification']='fcs'
    data['cfbd-prior-season-advanced']=[t for t in data['cfbd-prior-season-advanced'] if t['team']!=g['awayTeam']]
    rows,_,_,_=audit.reconcile(data,as_of);r=next(r for r in rows if r['game_id']==gid)
    assert len(rows)==67 and r['matchup_class']=='FBS_VS_FCS_OR_OTHER'
    assert r['model_feature_status']=='UNSUPPORTED_MISSING_EPA_NO_APPROVED_FALLBACK'
    assert r['missing_feature_teams']==[g['awayTeam']] and r['locked_spread'] is None


def test_missing_market_is_not_invented_contest_exclusion(captured):
    data,as_of=captured;data=copy.deepcopy(data);gid=str(data['cfbd-market-observations'].pop()['id'])
    rows,_,_,_=audit.reconcile(data,as_of);r=next(r for r in rows if r['game_id']==gid)
    assert len(rows)==67 and r['market_status']=='NO_CAPTURED_MARKET_LINES_NOT_PROOF_CONTEST_UNLINED'
    assert r['contest_coverage']=='UNKNOWN_OWNER_SCREENSHOTS_NOT_RECEIVED'


def test_elapsed_games_are_not_represented_as_prospective(captured):
    data,as_of=captured
    first=min(audit.timestamp(e['date']) for e in data['espn-complete']['events'])
    rows,_,_,_=audit.reconcile(data,first+timedelta(minutes=1))
    assert sum(r['status_at_capture']=='ELAPSED_NO_PROSPECTIVE_PICK' for r in rows)==2
    assert all(r['locked_spread'] is None and r['locked_total'] is None for r in rows)


@pytest.mark.parametrize('source',[None,{}, {'source':'CFBD','original_screenshots':['market'],'independent_transcription_reconciled':True},
                                 {'source':'SplashSports','original_screenshots':['unverified'],'independent_transcription_reconciled':False},
                                 {'source':'SplashSports','original_screenshots':['claimed'],'independent_transcription_reconciled':True}])
def test_readiness_cannot_execute_or_create_locks(source):
    with pytest.raises(ValueError):audit.require_contest_source(source)


def test_existing_output_is_never_overwritten(monkeypatch):
    monkeypatch.setattr(audit,'build',lambda:pytest.fail('attempted overwrite'))
    with pytest.raises(ValueError,match='overwrite'):audit.main(False)


def test_raw_payload_tampering_rejected(tmp_path):
    manifest=json.loads((audit.CAPTURE/'capture-manifest.json').read_bytes());record=manifest['records'][0]
    (tmp_path/record['path']).write_bytes((audit.CAPTURE/record['path']).read_bytes()+b'changed')
    with pytest.raises((ValueError,OSError,EOFError)):audit.read_payload(tmp_path,record)


def test_later_kickoff_gate_preserves_earlier_readiness_and_blocks_backfill():
    gate=json.loads((audit.PARENT/'kickoff-gate-20261111T014028Z.json').read_bytes())
    schedule_raw=(audit.OUT/'schedule.json').read_bytes()
    assert audit.digest(schedule_raw)==gate['archived_schedule_sha256']
    assert gate['observed_at_utc']=='2026-11-11T01:40:28.406171+00:00'
    rows=json.loads(schedule_raw)
    elapsed=[{k:r[k] for k in ('game_id','away','home','kickoff_utc')} for r in rows
             if audit.timestamp(r['kickoff_utc'])<=audit.timestamp(gate['observed_at_utc'])]
    assert elapsed==gate['elapsed_by_archived_schedule'] and len(elapsed)==3
    assert gate['not_yet_started_by_archived_schedule']==64
    assert not any(gate[k] for k in ('screenshots_received','contest_lines_locked','predictions_generated'))
