import copy
import pytest
from scripts.build_week12_daily_refresh import feature_comparison

@pytest.fixture
def payload():
    return {'records':[{'name':'cfbd-prior-'+str(i),'raw_sha256':str(i)} for i in range(7)]}

def test_unchanged_prior_features_allow_evidence_only_refresh(payload):
    assert all(r['unchanged'] for r in feature_comparison(payload,payload))

def test_changed_features_require_a_separate_model_rerun_decision(payload):
    fresh=copy.deepcopy(payload);fresh['records'][0]['raw_sha256']='changed'
    with pytest.raises(ValueError,match='unchanged'):feature_comparison(payload,fresh)

def test_missing_prior_features_are_rejected(payload):
    fresh=copy.deepcopy(payload);fresh['records'].pop()
    with pytest.raises(ValueError,match='seven'):feature_comparison(payload,fresh)

def test_duplicate_prior_feature_payload_is_rejected(payload):
    fresh=copy.deepcopy(payload);fresh['records'][-1]=fresh['records'][0]
    with pytest.raises(ValueError,match='unique'):feature_comparison(payload,fresh)

def test_friday_replay_preserves_all_historical_rows():
    from scripts.build_week12_daily_refresh import ROOT,build
    context=ROOT/'outputs/2026-week12-context';out=ROOT/'outputs/2026-week12-refresh/20261120-morning'
    outputs=build(context/'20261119-review-v2',context/'20261119-morning',
        context/'20261120-review',context/'20261120-morning',
        ROOT/'outputs/2026-week12-refresh/20261119-morning/full-card-66.csv')
    for name,raw in outputs.items():assert raw==(out/name).read_bytes()
