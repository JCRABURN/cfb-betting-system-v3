import copy
import json
import pytest
from scripts.verify_week9_owner_review import ROOT, validate

def review():
    return json.loads((ROOT/'outputs/2026-week9-owner-review/20261028-morning/owner_review_shortlist.json').read_text(encoding='utf-8'))

def test_owner_review_preserves_original_values_and_pending_approval():
    assert validate(review())['verified_candidates'] == 10

@pytest.mark.parametrize('kind',['late','line','confidence','approval','future_evidence','duplicate'])
def test_owner_review_rejects_adversaries(kind):
    data=copy.deepcopy(review());row=data['selections'][0]
    if kind=='late':row['created_at_utc']='2026-11-01T00:00:00+00:00'
    if kind=='line':row['locked_line']+=1
    if kind=='confidence':row['frozen_confidence']=5
    if kind=='approval':data['owner_approval']='APPROVED'
    if kind=='future_evidence':row['sources'][0]['captured_at_utc']='2026-11-01T00:00:00+00:00'
    if kind=='duplicate':data['selections'][1]['game_id']=row['game_id']
    with pytest.raises(ValueError):validate(data)
