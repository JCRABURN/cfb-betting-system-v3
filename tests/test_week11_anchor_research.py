import copy
import json
import pytest
from research.week11_validation import anchor_diagnostics as research


@pytest.fixture(scope='module')
def observations():
    return research.observations()


def split(rows):
    return ([r for r in rows if r['market']=='TOTAL' and r['week']<10],
            [r for r in rows if r['market']=='TOTAL' and r['week']==10])


def test_exact_research_replay_and_all_candidates_retained():
    expected=research.OUT.read_bytes()
    actual=(json.dumps(research.build(),indent=2,sort_keys=True,allow_nan=False)+'\n').encode()
    assert actual==expected
    report=json.loads(actual)
    assert len(report['folds'])==50 and len(report['top5'])==60
    assert report['week11_predictions']==0 and report['official_card_changed'] is False
    assert all(max(f['training']['weeks'])<f['week'] for f in report['folds'])


@pytest.mark.parametrize('method',list(research.METHODS))
def test_current_week_cannot_enter_fit(observations,method):
    train,test=split(observations)
    with pytest.raises(ValueError,match='chronological'):
        research.predict(train+[test[0]],test,method)


@pytest.mark.parametrize('method',list(research.METHODS))
def test_test_results_never_change_fitted_probabilities(observations,method):
    train,test=split(observations)
    changed=copy.deepcopy(test)
    for row in changed:
        row['actual']+=100
        row['result']='WIN' if row['result']=='LOSS' else 'LOSS'
    before,fit=research.predict(train,test,method)
    after,changed_fit=research.predict(train,changed,method)
    assert fit==changed_fit
    assert [(r['candidate_forecast'],r['probability']) for r in before]==[(r['candidate_forecast'],r['probability']) for r in after]


def test_positive_blends_cannot_create_different_full_card_winners(observations):
    train,test=split(observations)
    for method in ('MODEL_25','MODEL_50','ORIGINAL_POINT_GAUSSIAN'):
        predictions,_=research.predict(train,test,method)
        for r in predictions:
            assert (r['candidate_forecast']-r['line_forecast'])*(r['forecast']-r['line_forecast'])>=0
        stats=research.metrics(predictions)
        assert (stats['wins'],stats['losses'],stats['pushes'])==(26,31,0)
        assert stats['units']==pytest.approx(26*10/11-31)


def test_insufficient_calibration_bucket_is_explicit(observations):
    train,test=split(observations)
    predictions,_=research.predict(train[:10],test,'PRIOR_FREQUENCY')
    assert all(r['pooled_calibration_fallback'] for r in predictions)
    expected=(sum(r['result']=='WIN' for r in train[:10])+1)/(len(train[:10])+2)
    assert all(r['probability']==expected for r in predictions)


def test_locked_line_benchmark_does_not_invent_wagers(observations):
    train,test=split(observations)
    result,_=research.predict(train,test,'LOCKED_LINE')
    stats=research.metrics(result,True)
    assert stats['bets']==stats['units']==0
    assert stats['wins'] is None and stats['brier']==.25
