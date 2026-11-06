"""Ensure Sack labels cannot hide or fabricate defensive return touchdowns."""
import copy
import json

import pytest

from scripts import week9_scoring_process_v2 as review
from scripts.week9_audit_sources import captures, reconcile


@pytest.fixture(scope='module')
def event():
    _, records, data = captures()
    finals, _ = reconcile(data, records)
    final = next(g for g in finals if g['game_id']=='401856734')
    seq = data['espn-'+final['game_id']]['scoringPlays']
    index = next(i for i,p in enumerate(seq) if p['id']=='401856734354')
    p = seq[index]
    cfbd = next(c for c in data['cfbd-plays'] if c['id']==p['id'])
    return p, cfbd, final, (seq[index-1]['awayScore'],seq[index-1]['homeScore'])


def test_sack_label_return_requires_verified_semantics(event):
    result = review.defensive_sack_touchdown(*event)
    assert result['type']=='DERIVED_DEFENSIVE_FUMBLE_RETURN_TOUCHDOWN'
    assert result['original_espn_type']==result['original_cfbd_type']=='Sack'
    assert result['points_including_bundled_conversion']==7
    assert result['scoring_team']=='Georgia'


@pytest.mark.parametrize('change',['wrong_team','wrong_score','wrong_clock','wrong_id','wrong_description','not_scoring','offensive_recovery','ordinary_sack'])
def test_return_corroboration_fails_closed(event,change):
    p,c,f,previous = copy.deepcopy(event)
    if change=='wrong_team':p['team']['id']='999'
    elif change=='wrong_score':c['defenseScore']+=1
    elif change=='wrong_clock':c['clock']['seconds']+=1
    elif change=='wrong_id':c['id']='another'
    elif change=='wrong_description':c['playText']='sacked; punt'
    elif change=='not_scoring':c['scoring']=False
    elif change=='offensive_recovery':c['defense'],c['offense']=c['offense'],c['defense']
    elif change=='ordinary_sack':p['text']='Quarterback sacked for a loss'
    with pytest.raises(ValueError):review.defensive_sack_touchdown(p,c,f,previous)


def test_versioned_replay_preserves_original_grades_and_detects_four_returns():
    files = review.build()
    review.audit.verify_files(review.OUT,files)
    supersession = json.loads(files['supersession.json'])
    assert supersession['score_or_grade_changes']==0
    assert len(supersession['added_events'])==4
    assert sum(r['points_including_bundled_conversion'] for r in supersession['added_events'])==28
    assert {r['game_id'] for r in supersession['changed_games']}=={'401856734','401856737','401862816'}
    process=json.loads(files['game_process_evidence.json'])
    fau=next(r for r in process['games'] if r['game_id']=='401862812')
    assert fau['non_offensive_scoring_events']==0
