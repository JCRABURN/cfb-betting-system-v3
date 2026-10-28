import copy
import json
import pytest
from scripts import build_week8_postgame_audit as audit
from scripts import week8_scoring_sequence_review as scoring

def test_full_104_grades_read_only_replay():
    assert audit.main(True)['grading_status']=='COMPLETE_52_ATS_52_TOTALS'

@pytest.mark.parametrize('filename',sorted(audit.EXPECTED_OUTPUTS))
def test_any_partial_output_fails_closed(tmp_path,monkeypatch,filename):
    monkeypatch.setattr(audit,'OUTPUT',tmp_path)
    p=tmp_path/filename;p.write_bytes(b'original')
    with pytest.raises(FileExistsError):audit.main()
    assert p.read_bytes()==b'original'

@pytest.mark.parametrize('kind',['missing_checksum','extra_checksum','contradictory_status','fabricated_approval'])
def test_manifest_adversaries_fail_closed(monkeypatch,kind):
    original=audit.read_json
    def corrupt(path):
        d=original(path)
        if path.name=='week8_postgame_manifest.json':
            d=copy.deepcopy(d)
            if kind=='missing_checksum':d['output_sha256'].pop('week8_ats_audit.csv')
            if kind=='extra_checksum':d['output_sha256']['invented']='0'*64
            if kind=='contradictory_status':d['clv_status']='COMPLETE'
            if kind=='fabricated_approval':d['owner_approval_status']='APPROVED'
        return d
    monkeypatch.setattr(audit,'read_json',corrupt)
    with pytest.raises(ValueError,match='contradiction'):audit.main(True)

@pytest.mark.parametrize('kind',['orientation','score','not_final'])
def test_provider_conflicts_rejected(monkeypatch,kind):
    original=audit.load_raw
    def corrupt(entry):
        d=copy.deepcopy(original(entry))
        if 'scoreboard' in entry['endpoint']:
            event=next(e for e in d['events'] if str(e['id'])=='401860905');team=event['competitions'][0]['competitors'][0]
            if kind=='orientation':team['team']['location']='Wrong team'
            if kind=='score':team['score']='999'
            if kind=='not_final':event['status']['type']['completed']=False
        return d
    monkeypatch.setattr(audit,'load_raw',corrupt)
    with pytest.raises(ValueError):audit.evaluate()

def test_postgame_close_is_not_timestamp_qualified_clv():
    q=audit.quoted_close({'pickcenter':[{'provider':{'name':'DraftKings'},'total':{'over':{'close':{'line':'55.5'}}}}]},'TOTAL')
    assert q['postgame_provider_labeled_close']=='55.5'
    assert q['qualified_clv'] is None and q['clv_status']=='INCOMPLETE'

def test_scoring_sequence_cannot_use_final_alone_or_reversed_order():
    with pytest.raises(ValueError):scoring.validate_sequence([],14,7)
    plays=[{'id':'a','awayScore':7,'homeScore':0,'period':{'number':1},'clock':{'value':400}},
           {'id':'b','awayScore':7,'homeScore':7,'period':{'number':2},'clock':{'value':300}}]
    scoring.validate_sequence(plays,7,7)
    with pytest.raises(ValueError):scoring.validate_sequence(plays[::-1],7,7)
    with pytest.raises(ValueError):scoring.validate_sequence(plays,7,14)

def test_numerical_research_replays_and_prior_folds_exclude_test_week():
    from scripts.week8_numerical_research import main
    data=main(True)
    assert data['status']=='RESEARCH_ONLY_NOT_DEPLOYED'
    assert [(r['prior_training_n'],r['test_n']) for r in data['prior_week_bias_correction']]==[(56,58),(114,59),(173,52)]
    assert data['prior_week_bias_correction'][0]['candidate_mae']>data['prior_week_bias_correction'][0]['baseline_mae']
