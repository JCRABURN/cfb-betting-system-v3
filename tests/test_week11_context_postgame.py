"""Late contextual updates must never become pregame evidence in the audit."""
from scripts.week11_context_postgame import join_context


def sample():
    process={'failures':[dict(game_id='1',market='ATS',selection='Home',result='LOSS',taxonomy='H',observed_passers=[],
        process=dict(away='Away',home='Home',provider_drives=20,provider_plays=130,combined_points_per_provider_drive=2.5))]}
    first=dict(created_at_utc='2026-11-12T12:00:00Z',candidates=[dict(game_id='1',kickoff_utc='2026-11-13T01:00:00Z',
        team_context=[],evidence_support='original',risks='original risk',weather={'forecast':'first'},numeric_adjustments=[])])
    last=dict(created_at_utc='2026-11-13T12:00:00Z',candidate_updates=[dict(game_id='1',teams=[],weather={'forecast':'late'},numeric_adjustments=[])])
    return process,first,last


def test_late_refresh_cannot_replace_pregame_context():
    p,a,b=sample();r=join_context(p,a,b)[0]
    assert r['final_review_utc'] is None and 'first' in r['pregame_weather'] and 'late' not in r['pregame_weather']
    assert r['context_status']=='ARCHIVED_PREGAME_REVIEW'


def test_no_pregame_context_is_explicitly_missing():
    p,a,b=sample();a['created_at_utc']='2026-11-14T12:00:00Z';r=join_context(p,a,b)[0]
    assert r['context_status']=='NO_ELIGIBLE_PREGAME_REVIEW_RECOVERED'
    assert r['pregame_risks'] is None and r['source_review'] is None
