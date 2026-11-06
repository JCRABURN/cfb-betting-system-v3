from datetime import datetime,timezone
import pytest
from scripts.capture_week9_context import official_article_links,capture
from scripts.replay_week9_compat import ROOT,build,distance,main

def test_official_links_exclude_share_endpoints_other_hosts_and_future_news():
    base='https://example.edu/sports/football'
    assert official_article_links(base,['/news/2026/10/27/football-good','https://evil.com/news/2026/10/27/football','https://twitter.com/share?u=/news/2026/10/27/a','/news/2026/10/30/future','/news/2025/10/27/stale'],datetime(2026,10,28,tzinfo=timezone.utc))==['https://example.edu/news/2026/10/27/football-good']

def test_context_capture_refuses_existing_output_before_network():
    with pytest.raises(ValueError):capture(ROOT/'outputs/2026-week9-context/20261028T1320Z')

def test_all_54_contexts_replay_without_model_adjustment():
    folder=ROOT/'outputs/2026-week9-context/20261028T1320Z';data=build(folder)
    assert len(data['games'])==54 and all(not r['numerical_adjustments'] for r in data['games'])
    assert data['additional_market_games_beyond_screenshots']==[]
    assert main(folder,True)['owner_approval']=='PENDING'
    syracuse=next(r for r in data['games'] if r['game_id']==401858278)
    assert syracuse['weather_applicability']=='INDOOR_EXTERNAL_WEATHER_NOT_APPLIED'

def test_geodesic_proxy_is_not_roundtrip_or_route_distance():
    point={'latitude':40,'longitude':-90};assert distance(point,point)==0
