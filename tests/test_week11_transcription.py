import copy
import json
import pytest
from scripts import verify_week11_transcription as review


def test_all_owner_transcriptions_preserved_and_custody_gap_explicit():
    result=review.verify()
    assert result['source_rows']==result['spread_rows']==result['total_rows']==67
    assert len(result['elapsed_by_archived_schedule'])==3 and result['remaining_by_archived_schedule']==64
    assert result['screenshot_images_independently_verified_here']==0
    assert not result['model_lock_or_seal_created'] and result['ats_picks']==result['totals_picks']==0


@pytest.mark.parametrize('mutation',['missing','line','away_sign','orientation','kickoff','order','status','outside_date_window'])
def test_transcription_discrepancies_fail_closed(mutation):
    source,metadata,transcription,reconciliation=copy.deepcopy(review.load())
    if mutation=='missing':source.pop()
    elif mutation=='line':source[0]['Spread']='-6.5'
    elif mutation=='away_sign':transcription[0]['away_spread']='-5.5'
    elif mutation=='orientation':reconciliation[0]['canonical_home']='Akron'
    elif mutation=='kickoff':source[0]['Game Time']=transcription[0]['time_displayed']='5:00 PM'
    elif mutation=='order':transcription[0]['source_order']='2'
    elif mutation=='status':metadata['model_predictions_generated']=True
    elif mutation=='outside_date_window':source[0]['Game Date']=transcription[0]['date_displayed']='2026-10-10'
    schedule=json.loads((review.readiness.OUT/'schedule.json').read_bytes())
    with pytest.raises(ValueError):review.reconcile(source,metadata,transcription,reconciliation,schedule)


def test_equivalent_numeric_edit_still_breaks_original_byte_custody(tmp_path):
    for name in review.HASHES:
        target=tmp_path/name;target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes((review.ROOT/name).read_bytes())
    source=tmp_path/'production-weeks/2026-week11-splashsports.csv'
    source.write_bytes(source.read_bytes().replace(b'-5.5,',b'-5.50,',1))
    with pytest.raises(ValueError,match='byte custody'):review.load(tmp_path)
