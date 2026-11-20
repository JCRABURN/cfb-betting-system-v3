import copy
import csv
import io
import json
from datetime import datetime,timezone
import pytest
from scripts import build_week12_delivery as delivery
from scripts import review_week12_context as context
from scripts import verify_week12_acceptance as acceptance
from scripts.week12_revision_ledger import changes
from scripts import qualify_week12_delivery as qualified

@pytest.fixture(scope='module')
def outputs():return delivery.build()

@pytest.fixture(scope='module')
def card(outputs):return list(csv.DictReader(io.StringIO(outputs['full-card-66.csv'].decode())))

def test_complete_coverage_does_not_fabricate_elapsed_forecasts(outputs,card):
    pool=list(csv.DictReader(io.StringIO(outputs['all-132-markets.csv'].decode())))
    assert len(card)==66 and len(pool)==132
    assert sum(bool(r['pick']) for r in pool)==126
    assert all(not r['calibrated_probability'] and not r['calibrated_rank'] for r in pool)
    assert sum(r['status']=='ELAPSED_NO_PROSPECTIVE_FORECAST' for r in card)==3
    assert not json.loads(outputs['diagnostics.json'])['official_combined_top_five_available']

def test_late_custody_is_visible_on_both_full_delivery_tables():
    assert qualified.main(True)['late_games']==2
    rows=list(csv.DictReader(io.StringIO(qualified.build()['all-132-markets.csv'].decode())))
    assert sum(r['custody']=='FORWARD_SEALED' for r in rows)==122
    assert sum(r['custody'].startswith('LATE_CUSTODY') for r in rows)==4
    assert sum(r['custody']=='NO_ORIGINAL_FORECAST' for r in rows)==6

def test_duplicate_board_rejected(monkeypatch):
    original=delivery.read_csv
    def changed(path):
        rows=original(path)
        return rows+[rows[0]] if path.name=='week12_ats_full_card.csv' else rows
    monkeypatch.setattr(delivery,'read_csv',changed)
    with pytest.raises(ValueError,match='duplicate'):delivery.build()

def test_initial_replay_and_source_receipt():assert acceptance.main()['eligible_predictions']==126

def test_tampered_receipt_rejected():
    receipt=json.loads(acceptance.SEAL.read_bytes());receipt['files_sha256'].pop(next(iter(receipt['files_sha256'])))
    with pytest.raises(ValueError,match='coverage'):acceptance.validate_receipt(receipt)

def test_late_seal_rejected():
    receipt=json.loads(acceptance.SEAL.read_bytes());receipt['late_custody_game_ids']=[]
    with pytest.raises(ValueError,match='late custody'):acceptance.validate_receipt(receipt)

def test_context_uses_passing_leader_without_claiming_starter():
    rows=list(csv.DictReader((context.OUT/'all-game-context.csv').open(encoding='utf-8-sig')))
    assert len(rows)==63
    assert sum(bool(r['away_passing_leader_not_confirmed_starter']) for r in rows)>50
    assert all(r['away_starting_qb'].startswith('UNCONFIRMED') for r in rows)

NOW=datetime(2026,11,18,20,tzinfo=timezone.utc)
def revision(a,b):return changes(a,b,NOW,'official source refresh','v2.8','recorded-capture/manifest.json')

def test_no_change_refresh_is_explicit(card):assert revision(card,copy.deepcopy(card))==[]

@pytest.mark.parametrize('field,value',[('locked_total','99'),('locked_home_spread','99'),('away','Other')])
def test_refresh_cannot_replace_source(card,field,value):
    new=copy.deepcopy(card);new[8][field]=value
    with pytest.raises(ValueError,match='frozen'):revision(card,new)

def test_refresh_cannot_change_started_rank(card):
    new=copy.deepcopy(card);new[0]['review_rank']='1'
    with pytest.raises(ValueError,match='started'):revision(card,new)

def test_refresh_requires_common_calibration_policy(card):
    new=copy.deepcopy(card);new[8]['calibrated_probability']='0.80'
    with pytest.raises(ValueError,match='calibration'):revision(card,new)

def test_refresh_records_before_after_and_provenance(card):
    new=copy.deepcopy(card);new[8]['ats_confidence']='2'
    result=revision(card,new)
    assert len(result)==1 and result[0]['previous']=='1' and result[0]['current']=='2'
    assert result[0]['reason'] and result[0]['evidence'] and result[0]['model_version']=='v2.8'

def test_refresh_rejects_duplicate_chips(card):
    new=copy.deepcopy(card)
    for r in new[8:13]:r['contest_chip']='5'
    with pytest.raises(ValueError,match='chips'):revision(card,new)

@pytest.mark.parametrize('field,value,message',[
    ('ats_selected_spread','99','selected ATS'),('ats_selection','Other','invalid ATS'),
    ('ats_confidence','6','confidence'),('projected_total','nan','nonfinite')])
def test_invalid_refresh_market_values_rejected(card,field,value,message):
    new=copy.deepcopy(card);new[8][field]=value
    with pytest.raises(ValueError,match=message):revision(card,new)

def test_side_change_retains_exact_opposite_frozen_spread(card):
    new=copy.deepcopy(card);r=new[8]
    r['ats_selection']=r['home'] if r['ats_selection']==r['away'] else r['away']
    r['ats_selected_spread']=str(-float(r['ats_selected_spread']))
    assert {r['field'] for r in revision(card,new)}=={'ats_selection','ats_selected_spread'}
