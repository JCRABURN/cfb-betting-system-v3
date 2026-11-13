import copy
import json
import pytest
from scripts import verify_week11_acceptance as acceptance
from scripts import seal_week11_board as board
from scripts import review_week11_context as review
from scripts import week11_context as context
from research.week11_validation import forward_shadow as shadow

def test_complete_acceptance_replays_with_late_custody_and_pending_approval():
    result=acceptance.verify()
    assert result['board']['ats_selections']==result['board']['total_selections']==64
    assert result['shadow']['games']==61
    assert result['owner_review']['owner_approval']=='PENDING'

@pytest.mark.parametrize('mutation',['source_coverage','output_coverage','status','timestamp'])
def test_seal_rejects_omissions_contradictions_and_backdating(monkeypatch,mutation):
    original=board.read
    def altered(path):
        value=original(path)
        if path==board.SEAL:
            value=copy.deepcopy(value)
            if mutation=='source_coverage':value['source_sha256'].pop(next(iter(value['source_sha256'])))
            if mutation=='output_coverage':value['output_sha256'].pop(next(iter(value['output_sha256'])))
            if mutation=='status':value['validation']['status']='SEALED_PROSPECTIVE_RESEARCH_BOARD'
            if mutation=='timestamp':value['sealed_at_utc']='2026-11-10T00:00:00Z'
        return value
    monkeypatch.setattr(board,'read',altered)
    with pytest.raises(ValueError):board.main(True)

def test_independent_pin_rejects_rehashed_evidence(monkeypatch):
    monkeypatch.setattr(acceptance,'sha',lambda path:'0'*64)
    with pytest.raises(ValueError,match='frozen evidence'):acceptance.verify()

def test_context_missing_raw_file_fails_before_health_claim(tmp_path):
    m=board.read(review.CONTEXT/'manifest.json')
    (tmp_path/'manifest.json').write_text(json.dumps(m))
    with pytest.raises(ValueError,match='coverage'):context.verify(tmp_path)

def test_started_game_never_gets_new_human_recommendation():
    with pytest.raises(ValueError,match='after kickoff'):
        review.build('2026-11-16T12:00:00Z')

def test_forward_all_methods_retained_and_material_change_rejected(tmp_path,monkeypatch):
    saved=board.read(shadow.OUT)
    assert set(saved['methods'])==set(shadow.METHODS)
    assert len(saved['predictions'])==610
    assert saved['training_max_week']==10
    assert saved['excluded_already_started_ids']==['401866461','401866462','401866463']
    assert len(saved['original_ats_research_top5'])==5
    saved['predictions'][0]['candidate_forecast']+=.001
    path=tmp_path/'shadow.json';path.write_text(json.dumps(saved));monkeypatch.setattr(shadow,'OUT',path)
    with pytest.raises(ValueError,match='exact replay'):shadow.main(True)

def test_bad_drive_scores_are_quarantined_without_imputation():
    teams,_,_,bad=shadow.drive_summary()
    assert len(bad)==147
    assert not ({r[s] for r in bad for s in ('offense','defense')} & set(teams))
    saved=board.read(shadow.OUT)
    assert sum(r['status']=='UNVALIDATED_FORWARD_PROTOTYPE' for r in saved['drive_predictions'])==14
    assert all('projected_total' not in r for r in saved['drive_predictions'] if r['status']!='UNVALIDATED_FORWARD_PROTOTYPE')

def test_human_review_preserves_every_selected_original_number():
    saved=board.read(review.OUT/'review.json');games={r['game_id']:r for r in saved['candidates']}
    for r in saved['choices']:
        source=games[r['game_id']]['frozen_ats' if r['market']=='ATS' else 'frozen_total']
        assert r['pick']==source['pick']
        assert r['contest_line']==float(source['pick_spread' if r['market']=='ATS' else 'locked_total'])
        assert games[r['game_id']]['numeric_adjustments']==[]
    assert max(r['human_confidence'] for r in saved['choices'])==2
