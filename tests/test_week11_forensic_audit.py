"""Adversarial grading, custody, leakage and probability evaluation controls."""
import copy
import math
import pytest
from scripts import week11_audit_grading as grading
from scripts.week11_audit_inputs import BOARD, source_json, board_csv, sha, DB_SHA, ROOT
from scripts.week11_audit_metrics import summary, historical
from scripts.week11_audit_research import evaluate, probability_metrics, confidence_candidate
from scripts.week11_v29_research import fit, run
from scripts.build_week11_formal_audit import custody, main


@pytest.fixture(scope='module')
def audit():
    manifest,records,data=grading.load_capture()
    finals=grading.reconcile(data,records)
    rows=grading.grades(finals,data)
    return records,data,finals,rows


def test_exact_original_custody_and_no_database_writes():
    before=sha((ROOT/'data/cfb.db').read_bytes())
    result=custody()
    assert result['archived_files']==870 and result['original_screenshots']==8
    assert result['historical']['input_files_verified']==2729
    assert sha((ROOT/'data/cfb.db').read_bytes())==before==DB_SHA


def test_no_retrospective_tuesday_forecasts_and_late_wednesday_excluded(audit):
    _,_,finals,rows=audit
    tuesday={r['game_id'] for r in finals if r['custody']=='NO_ORIGINAL_FORECAST_TUESDAY'}
    assert len(finals)==67 and len(tuesday)==3 and len(rows)==128
    assert not tuesday & {r['game_id'] for r in rows}
    assert sum(r['custody']=='FORWARD_SEALED_61' for r in rows)==122
    assert sum(r['custody'].startswith('LATE_') for r in rows)==6


@pytest.mark.parametrize('mutation',['nonfinal','score','orientation','season','week'])
def test_cross_provider_reconciliation_rejects_corruption(audit,mutation):
    records,data,_,_=audit
    changed=copy.deepcopy(data);g=changed['cfbd-games'][0]
    if mutation=='nonfinal':g['completed']=False
    if mutation=='score':g['awayPoints']+=1
    if mutation=='orientation':g['homeTeam'],g['awayTeam']=g['awayTeam'],g['homeTeam']
    if mutation=='season':g['season']=2025
    if mutation=='week':g['week']=12
    with pytest.raises(ValueError):grading.reconcile(changed,records)


def test_duplicate_game_rejected(audit):
    records,data,_,_=audit;changed=dict(data,**{'cfbd-games':data['cfbd-games']+[data['cfbd-games'][0]]})
    with pytest.raises(ValueError,match='duplicate'):grading.reconcile(changed,records)


@pytest.mark.parametrize('field',['locked_home_spread','pick_spread'])
def test_locked_spread_cannot_be_replaced(audit,field):
    _,_,finals,_=audit;row=copy.deepcopy(board_csv('ats_full_card')[0]);row[field]=str(float(row[field])+1)
    final=next(f for f in finals if f['game_id']==row['game_id'])
    lock=next(r for r in source_json(BOARD+'week11_locked_line_snapshot.json')['lines'] if str(r['game_id'])==row['game_id'])
    with pytest.raises(ValueError,match='unauthorized'):grading.grade_selection(row,'ATS',final,lock)


def test_locked_total_cannot_be_replaced(audit):
    _,_,finals,_=audit;row=copy.deepcopy(board_csv('totals_full_card')[0]);row['locked_total']='99.5'
    final=next(f for f in finals if f['game_id']==row['game_id'])
    lock=next(r for r in source_json(BOARD+'week11_locked_line_snapshot.json')['lines'] if str(r['game_id'])==row['game_id'])
    with pytest.raises(ValueError,match='unauthorized'):grading.grade_selection(row,'TOTAL',final,lock)


def test_grade_signs_pushes_and_negative_margin(audit):
    _,_,finals,_=audit;row=copy.deepcopy(board_csv('ats_full_card')[0])
    final=copy.deepcopy(next(f for f in finals if f['game_id']==row['game_id']))
    lock=copy.deepcopy(next(r for r in source_json(BOARD+'week11_locked_line_snapshot.json')['lines'] if str(r['game_id'])==row['game_id']))
    row.update(locked_home_spread='-3',pick_spread='3',selected_side='away',pick=row['away']);lock['home_spread']=-3
    final.update(home_score=20,away_score=17)
    assert grading.grade_selection(row,'ATS',final,lock)['result']=='PUSH'
    final['away_score']=18
    assert grading.grade_selection(row,'ATS',final,lock)['result']=='WIN'
    final['away_score']=16
    assert grading.grade_selection(row,'ATS',final,lock)['result']=='LOSS'


def test_null_uncertainty_not_zero_and_cohorts_not_submissions(audit):
    *_,rows=audit;groups=grading.cohorts(rows)
    ats=[r for r in rows if r['market']=='ATS']
    assert all(r['production_uncertainty_points'] is None and r['confidence']==1 for r in ats)
    assert all(r['owner_approval']=='PENDING' for r in rows)
    assert summary(groups['HUMAN_20261113-v2'])['wins']==2
    assert summary(groups['ORIGINAL_COMBINED_RESEARCH_TOP5'])['wins']==3
    assert summary(groups['GOVERNED_ATS_TOP5'])['losses']==5


def test_human_revision_membership_cannot_be_changed(audit,monkeypatch):
    *_,rows=audit;original=grading.source_json
    def changed(path):
        result=copy.deepcopy(original(path))
        if path.endswith('/review.json'):result['choices'][0]['contest_line']+=1
        return result
    monkeypatch.setattr(grading,'source_json',changed)
    with pytest.raises(ValueError,match='cohort'):grading.cohorts(rows)


@pytest.mark.parametrize('probability,confidence',[(.524999,1),(.525,2),(.55,3),(.58,4),(.62,5),(1,5)])
def test_research_confidence_boundaries(probability,confidence):
    assert confidence_candidate(probability)==confidence


@pytest.mark.parametrize('probability',[float('nan'),float('inf'),-.01,1.01])
def test_nonfinite_or_invalid_probability_rejected(probability):
    with pytest.raises(ValueError):confidence_candidate(probability)


def test_push_excluded_from_probability_metrics():
    r=probability_metrics([{'result':'WIN','probability':.6},{'result':'PUSH','probability':.99}])
    assert r['n_probability']==1 and math.isclose(r['brier'],.16)


def test_frozen_research_has_no_baseline_bets_or_late_games(audit):
    *_,rows=audit;result=evaluate(rows)
    assert len(result['all_rows'])==610
    assert all(r['custody']=='FORWARD_SEALED_61' for r in result['all_rows'])
    assert all(r['wins']==r['losses']==0 and r['roi'] is None for r in result['full'] if r['method']=='LOCKED_LINE')
    assert len(result['drive'])==28
    assert all(math.isclose(float(r['forecast_error_actual_minus_predicted']),float(r['actual_model_target'])-r['candidate_forecast'],abs_tol=1e-10) for r in result['all_rows'])
    assert all(r['units_exact']=='0' for r in result['full'] if r['method']=='LOCKED_LINE')


def test_training_and_calibration_cannot_see_evaluation_week(audit):
    *_,current=audit;rows=historical()+current
    with pytest.raises(ValueError,match='leaks'):fit(rows,11)
    candidate=run(rows)
    assert all(r['fit']['train_max_week']<r['week'] and (r['calibration_max_week'] is None or r['calibration_max_week']<r['week']) for r in candidate['predictions'])
    assert all(r['confidence']==1 for r in candidate['predictions'])
    changed=[dict(r,actual_model_target=float(r['actual_model_target'])+1000,result='LOSS') if int(r['week'])==11 else r for r in rows]
    rerun=run(changed)
    fields=('raw_projection','probability','selection','candidate_confidence_research_only')
    assert [[r[k] for k in fields] for r in candidate['predictions']]==[[r[k] for k in fields] for r in rerun['predictions']]


def test_output_path_and_overwrite_protection(tmp_path):
    with pytest.raises(ValueError,match='boundary'):main(output=tmp_path/'invalid')
    from scripts.build_week11_formal_audit import OUT
    if OUT.exists():
        with pytest.raises(FileExistsError):main(output=OUT)
