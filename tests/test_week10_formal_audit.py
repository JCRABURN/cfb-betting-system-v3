"""Forensic audit failure modes; never change frozen cards or use live providers."""
import copy
import json
import shutil
from decimal import Decimal
import pytest
from scripts import build_week10_formal_audit as audit
from scripts import week10_audit_sources as sources
from scripts.week10_audit_grading import build_grades,cohort_membership
from scripts.week9_audit_grading import grade_selection
from scripts.week10_audit_game_process import defensive_sack_score
from scripts import week10_research_audit as research


@pytest.fixture(scope='module')
def captured():
    return sources.captures()


@pytest.fixture(scope='module')
def finals(captured):
    return sources.reconcile(captured[2],captured[1])[0]


@pytest.fixture(scope='module')
def payloads():
    return audit.build()


def test_full_exact_readonly_replay(payloads):
    audit.verify_files(audit.OUT,payloads)
    m=json.loads(payloads['audit_manifest.json'])
    assert (m['game_count'],m['ats_count'],m['totals_count'])==(57,57,57)
    assert m['score_discrepancies']==m['independent_grading_discrepancies']==0
    assert not m['model_or_policy_changes'] and not m['historical_artifacts_changed']
    assert m['clv_status']=='INCOMPLETE' and m['owner_approval']=='NO_APPROVAL_ARTIFACT_IDENTIFIED'


@pytest.mark.parametrize('mutation',['missing','duplicate','score','nonfinal','week','orientation','negative','bool','future_capture'])
def test_score_reconciliation_fail_closed(captured,mutation):
    _,records,data=captured;data=copy.deepcopy(data);records=copy.deepcopy(records)
    gid=next(iter(sources.unique(sources.read_csv(sources.BOARD/'week10_ats_full_card.csv'))))
    game=next(g for g in data['cfbd-games'] if str(g['id'])==gid)
    if mutation=='missing':data['cfbd-games'].remove(game)
    elif mutation=='duplicate':data['cfbd-games'].append(copy.deepcopy(game))
    elif mutation=='score':game['homePoints']+=1
    elif mutation=='nonfinal':game['completed']=False
    elif mutation=='week':game['week']=9
    elif mutation=='orientation':game['homeId']=game['awayId']
    elif mutation=='negative':game['homePoints']=-1
    elif mutation=='bool':game['homePoints']=True
    elif mutation=='future_capture':records['espn-'+gid]['requested_at_utc']='2026-01-01T00:00:00Z'
    with pytest.raises((ValueError,KeyError)):sources.reconcile(data,records)


@pytest.mark.parametrize('market,field',[('ATS','locked_home_spread'),('ATS','pick_spread'),('TOTAL','locked_total')])
def test_locked_line_replacement_rejected(finals,market,field):
    name='ats' if market=='ATS' else 'totals';row=sources.read_csv(sources.BOARD/f'week10_{name}_full_card.csv')[0]
    lock=sources.unique(sources.read_json(sources.BOARD/'week10_locked_line_snapshot.json')['lines'])[row['game_id']]
    final=sources.unique(finals)[row['game_id']];row[field]=str(Decimal(row[field])+Decimal('.5'))
    with pytest.raises(ValueError):grade_selection(row,market,final,lock)


@pytest.mark.parametrize('mutation',['missing','extra','status','metric','line'])
def test_audit_output_coverage_status_and_numbers_rejected(payloads,tmp_path,mutation):
    for name,raw in payloads.items():(tmp_path/name).write_bytes(raw)
    if mutation=='missing':(tmp_path/'week10_ats_audit.csv').unlink()
    elif mutation=='extra':(tmp_path/'extra.json').write_text('{}')
    elif mutation=='status':
        path=tmp_path/'audit_manifest.json';m=json.loads(path.read_bytes());m['owner_approval']='APPROVED';path.write_text(json.dumps(m))
    elif mutation=='metric':
        path=tmp_path/'cross_week_diagnostics.json';m=json.loads(path.read_bytes());m['weekly'][0]['mae']+=1;path.write_text(json.dumps(m))
    else:(tmp_path/'week10_ats_audit.csv').write_bytes(payloads['week10_ats_audit.csv'].replace(b'2.5',b'3.5',1))
    with pytest.raises(ValueError):audit.verify_files(tmp_path,payloads)


def test_writer_refuses_existing_directory_before_build(monkeypatch):
    monkeypatch.setattr(audit,'build',lambda:pytest.fail('overwrite attempted expensive build'))
    with pytest.raises(ValueError,match='overwrite'):audit.main(False,audit.OUT)


def test_writer_refuses_outside_custody(tmp_path,payloads):
    with pytest.raises(ValueError):audit.write_new(tmp_path/'outside',payloads)


@pytest.mark.parametrize('mutation',['missing','hash','status'])
def test_input_checksum_fixture_cannot_be_relaxed(tmp_path,monkeypatch,mutation):
    m=json.loads(audit.FIXTURE.read_bytes())
    if mutation=='missing':m['sha256_by_path'].pop(next(iter(m['sha256_by_path'])))
    elif mutation=='hash':m['sha256_by_path'][next(iter(m['sha256_by_path']))]='0'*64
    else:m['historical_artifacts_changed']=True
    path=tmp_path/'fixture.json';path.write_text(json.dumps(m));monkeypatch.setattr(audit,'FIXTURE',path)
    with pytest.raises(ValueError,match='identity'):audit.custody()


@pytest.mark.parametrize('mutation',['line','probability','membership','timestamp','approval'])
def test_sealed_experiment_cannot_be_replaced(monkeypatch,mutation):
    original=research.read_original
    raw=json.loads(original('holdout/20261106-v1/prospective.json'))
    if mutation=='line':raw['selections'][0]['line']+=1
    elif mutation=='probability':raw['selections'][0]['probability']=.99
    elif mutation=='membership':raw['selections'].pop()
    elif mutation=='timestamp':raw['generated_at_utc']='2026-11-09T00:00:00Z'
    else:raw['owner_approval']='APPROVED'
    monkeypatch.setattr(research,'read_original',lambda suffix:json.dumps(raw).encode() if suffix.endswith('prospective.json') else original(suffix))
    with pytest.raises(ValueError,match='seal identity'):research.frozen()


@pytest.mark.parametrize('mutation',['none','not_endzone','clock','scoring_team','wrong_score','not_defense'])
def test_zero_yard_defensive_recovery_requires_full_corroboration(captured,finals,mutation):
    data=captured[2];final=sources.unique(finals)['401871098']
    p=copy.deepcopy(next(p for p in data['espn-401871098']['scoringPlays'] if str(p['id'])=='401871098507'))
    c=copy.deepcopy(next(p for p in data['cfbd-plays'] if str(p['id'])=='401871098507'))
    if mutation=='not_endzone':c['playText']=c['playText'].replace('at LT00 TOUCHDOWN','at LT10 TOUCHDOWN')
    elif mutation=='clock':c['clock']['seconds']+=1
    elif mutation=='scoring_team':p['team']['id']='2348'
    elif mutation=='wrong_score':c['defenseScore']+=1
    elif mutation=='not_defense':c['defense']='Louisiana Tech'
    if mutation=='none':
        r=defensive_sack_score(p,c,final,(20,10));assert r['points_including_bundled_conversion']==7 and 'RECOVERY' in r['type']
    else:
        with pytest.raises(ValueError):defensive_sack_score(p,c,final,(20,10))


def test_no_retrospective_candidate_selection_or_training(payloads):
    r=json.loads(payloads['research_audit.json'])
    assert len(r['all_candidate_rows'])==798 and len(r['cohorts'])==21
    assert not r['policy_gate_passed'] and r['prospective_weeks']==1
    comparison=r['primary_paired'][0]
    assert comparison['unit_difference']==0 and len(comparison['shared'])==4
    assert comparison['added'][0]['candidate_result']==comparison['removed'][0]['candidate_result']=='WIN'
    assert all(x['actual'] is None for x in research.frozen()[0]['selections'])


def test_original62_exclusions_and_owner_review_not_approved(payloads):
    c=json.loads(payloads['custody_verification.json'])['source_reconciliation']
    assert c['original_matchups']==62 and len(c['excluded'])==5
    assert sum(r['reason']=='FINAL_AT_SCREENSHOT_RECEIPT_NOT_PROSPECTIVE' for r in c['excluded'])==2
    assert sum(r['reason']=='KICKOFF_ELAPSED_BEFORE_GENERATION' for r in c['excluded'])==3
    r=json.loads(payloads['forensic_findings.json'])['human_value']
    assert all(x['owner_approval']=='NO_APPROVAL_ARTIFACT_IDENTIFIED' for x in r)
