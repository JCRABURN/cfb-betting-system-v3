"""Failure-mode tests for contest recovery, provider identity and attribution."""
import copy
from fractions import Fraction

import pytest
from scripts import season_contest_audit as audit


@pytest.fixture(scope='module')
def evidence():
    manifest,lines,picks=audit.sources()
    records,data=audit.capture()
    finals,resolver=audit.reconcile(lines,records,data)
    return manifest,lines,picks,records,data,finals,resolver


def test_all_621_results_and_only_50_v3_submissions(evidence):
    m,lines,picks,_,_,finals,_=evidence
    ledger,excluded=audit.submitted(picks,finals,m)
    assert len(lines)==len(finals)==621
    assert len(ledger)==50 and len(excluded)==5
    assert all(r['week']<=10 for r in ledger)
    assert all('result' not in r and 'weighted_points' not in r for r in excluded)
    assert all(r['status']=='EXTERNAL_ORIGIN_EXCLUDED_FROM_V3_PERFORMANCE' for r in excluded)
    total=audit.metrics(ledger)
    assert (total['wins'],total['losses'],total['pushes'],total['weighted_points'],total['possible_points'])==(20,30,0,55,150)
    assert total['units_exact']=='-130/11'
    for r in ledger:
        # Independent exact rational calculation checks spread signs and totals.
        target=r['home_score']-r['away_score'] if r['market']=='ATS' else r['home_score']+r['away_score']
        line=Fraction(str(r['contest_line']))
        margin=(target if r['selected_side']=='HOME' else -target)+line if r['market']=='ATS' else (target-line)*(1 if r['selected_side']=='OVER' else -1)
        assert margin==Fraction(str(r['grading_margin']))
        assert r['result']==('WIN' if margin>0 else 'LOSS' if margin<0 else 'PUSH')


@pytest.mark.parametrize('mutation',['missing','duplicate','weight','line','marker','pdf'])
def test_source_corruption_fails(evidence,mutation):
    _,lines,picks,*_=evidence
    lines=copy.deepcopy(lines);picks=copy.deepcopy(picks)
    if mutation=='missing':lines.pop()
    if mutation=='duplicate':lines[-1]=copy.deepcopy(lines[0])
    if mutation=='weight':picks[0]['contest_weight']='4'
    if mutation=='line':picks[0]['selected_line']='0'
    if mutation=='marker':lines[0]['selected_market']='ATS'
    if mutation=='pdf':lines[0]['pdf']=''
    with pytest.raises(ValueError):audit.validate_sources(lines,picks)


@pytest.mark.parametrize('mutation',['score','nonfinal','orientation','duplicate','season','week','time'])
def test_provider_corruption_fails(evidence,mutation):
    _,lines,_,records,data,finals,_=evidence
    data=copy.deepcopy(data);records=copy.deepcopy(records)
    gid=finals[0]['game_id'];g=next(g for g in data['cfbd-week1'] if str(g['id'])==gid)
    if mutation=='score':g['awayPoints']+=1
    if mutation=='nonfinal':g['completed']=False
    if mutation=='orientation':g['homeId'],g['awayId']=g['awayId'],g['homeId']
    if mutation=='duplicate':data['cfbd-week1'].append(copy.deepcopy(g))
    if mutation=='season':g['season']=2025
    if mutation=='week':g['week']=2
    if mutation=='time':records['cfbd-week1']['requested_at_utc']='2026-01-01T00:00:00Z'
    with pytest.raises(ValueError):audit.reconcile(lines,records,data)


@pytest.mark.parametrize('market,side,line,home,away,expected',[
    ('ATS','HOME',-3,20,17,'PUSH'),('ATS','AWAY',3.5,20,17,'WIN'),
    ('ATS','HOME',-3.5,20,17,'LOSS'),('TOTAL','UNDER',37,20,17,'PUSH'),
    ('TOTAL','OVER',36.5,20,17,'WIN'),('TOTAL','UNDER',36.5,20,17,'LOSS')])
def test_grade_boundaries(market,side,line,home,away,expected):
    assert audit.grade(market,side,line,home,away)['result']==expected


@pytest.mark.parametrize('line',['NaN','Infinity','-Infinity'])
def test_nonfinite_lines_rejected(line):
    with pytest.raises(ValueError):audit.grade('ATS','HOME',line,20,17)


def test_week4_and_week5_corrections_and_weights_not_confidence(evidence):
    m,_,picks,_,_,finals,_=evidence
    ledger,_=audit.submitted(picks,finals,m)
    w4=audit.metrics([r for r in ledger if r['week']==4])
    assert (w4['wins'],w4['losses'],w4['weighted_points'])==(3,2,8)
    fifth=next(r for r in ledger if r['week']==5 and r['contest_weight']==1)
    assert (fifth['selection'],fifth['contest_line'])==('Texas Tech',-13.5)
    assert all(r['model_confidence'] is None and r['forecast_timestamp'] is None for r in ledger)


def test_canonical_unknown_team_fails(evidence):
    _,lines,_,records,data,*_=evidence
    lines=copy.deepcopy(lines);lines[0]['home_team']='Unknown University'
    with pytest.raises(ValueError,match='Unresolved'):audit.reconcile(lines,records,data)
