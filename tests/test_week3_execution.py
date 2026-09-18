from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from business_entities.common import BusinessEntityError
from business_entities.totals_weekly_model import run_component_totals_shadow_model
from business_entities.weekly_controller import run_epa_only_model
from contest_lines import create_contest, lock_contest_line
from ingestion import CanonicalTeamResolver
from scripts.run_week3_execution import reconcile, result_writer


def slate():
    rows, games, schools = [], [], []
    for index in range(57):
        date = "2026-09-17" if index == 0 else "2026-09-18" if index < 3 else "2026-09-19"
        home, away = f"Home {index}", f"Away {index}"
        schools.extend((home, away))
        rows.append(dict(week="3",game_date_local=date,kickoff_local="18:30",team_1=home,team_2=away,
                         team_1_spread="-3.5",team_2_spread="3.5",total="51.5",captured_at_local="2026-09-16T16:57:00-05:00"))
        games.append(dict(id=index+1,homeTeam=home,awayTeam=away,homeClassification="fbs",awayClassification="fbs",
                          startDate=date+"T23:30:00Z",startTimeTBD=False))
    return rows, games, CanonicalTeamResolver(schools)


def test_display_order_is_not_away_home_order():
    rows, games, resolver = slate()
    result = reconcile(rows,games,resolver)
    assert len(result) == 57
    assert result[0]["raw_home"] == "Home 0"
    assert result[0]["home_spread"] == -3.5
    rows[0].update(team_1="Away 0",team_2="Home 0",team_1_spread="3.5",team_2_spread="-3.5")
    assert reconcile(rows,games,resolver)[0]["home_spread"] == -3.5


@pytest.mark.parametrize("failure",["duplicate","missing_total","spread","unknown","kickoff","tbd","inventory"])
def test_reconciliation_fails_closed(failure):
    rows,games,resolver = slate()
    if failure=="duplicate": rows[4]=dict(rows[3])
    elif failure=="missing_total": rows[0]["total"]=""
    elif failure=="spread": rows[0]["team_2_spread"]="4.5"
    elif failure=="unknown": rows[0]["team_1"]="Unknown"
    elif failure=="kickoff": rows[0]["kickoff_local"]="17:30"
    elif failure=="tbd": games[0]["startTimeTBD"]=True
    elif failure=="inventory": rows.pop()
    with pytest.raises(ValueError): reconcile(rows,games,resolver)


def test_past_and_exact_kickoff_skipped_without_reading_features(temp_db,monkeypatch):
    from business_entities import totals_weekly_model
    from models import backtest_harness as harness
    now=datetime(2026,9,18,15,tzinfo=timezone.utc)
    conn=temp_db.get_connection()
    contest=create_contest(conn,contest_key="cutoff",name="Cutoff",season=2026,week=3,source="SplashSports",provenance="fixture",created_at=now)
    for game_id,offset in ((1,-1),(2,0),(3,1)):
        conn.execute("INSERT INTO games(game_id,season,week,home_team,away_team,start_date) VALUES(?,2026,3,?,?,?)",
                     (game_id,f"Home {game_id}",f"Away {game_id}",(now+timedelta(hours=offset)).isoformat()))
        lock_contest_line(conn,contest_id=contest.id,game_id=game_id,raw_home_team=f"Home {game_id}",raw_away_team=f"Away {game_id}",
            normalized_home_team=f"Home {game_id}",normalized_away_team=f"Away {game_id}",home_spread=-3.5,total=51.5,source="SplashSports",
            provenance="fixture",payload_sha256="a"*64,locked_at=now)
    reads=[]
    def package(connection,home,away,*args):
        reads.append(home)
        assert home=="Home 3"
        return {"home_stats":{"offense_epa_play":.3,"defense_epa_play":.1,"as_of_season":2026,"as_of_week":2},
                "away_stats":{"offense_epa_play":.2,"defense_epa_play":.15,"as_of_season":2026,"as_of_week":2}}
    monkeypatch.setattr(harness,"available_seasons_before",lambda *a:[2025])
    monkeypatch.setattr(harness,"build_training_set",lambda *a:([[.1],[.2]],[5.,6.]))
    monkeypatch.setattr(harness,"fit_multilinear",lambda *a:(3.,[20.]))
    monkeypatch.setattr(harness,"get_pregame_stats",package)
    run=run_epa_only_model(conn,contest_id=contest.id,model_run_key="cutoff:ats",code_commit_sha="b"*40,generated_at=now,provenance="fixture")
    assert conn.execute("SELECT game_id FROM model_predictions").fetchall()==[(3,)]
    assert "1:kickoff_not_in_future" in run.provenance and "2:kickoff_not_in_future" in run.provenance
    monkeypatch.setattr(totals_weekly_model,"build_totals_component_dataset",lambda *a,**k:(SimpleNamespace(dataset_sha256="c"*64),()))
    monkeypatch.setattr(totals_weekly_model,"fit_totals_component_model",lambda *a,**k:SimpleNamespace(uncertainty_points=12.))
    monkeypatch.setattr(totals_weekly_model,"predict_totals_component_score",lambda *a:(28.,24.))
    total=run_component_totals_shadow_model(conn,contest_id=contest.id,model_run_key="cutoff:total",code_commit_sha="b"*40,generated_at=now,provenance="fixture")
    assert conn.execute("SELECT game_id FROM total_model_predictions").fetchall()==[(3,)]
    assert "1:kickoff_not_in_future" in total.provenance and "2:kickoff_not_in_future" in total.provenance
    assert reads==["Home 3","Home 3"]
    assert conn.execute("SELECT COUNT(*) FROM contest_picks").fetchone()[0]==0


def test_result_import_preserves_schedule_and_rejects_conflicting_final(temp_db):
    conn=temp_db.get_connection()
    conn.execute("INSERT INTO games(game_id,season,week,home_team,away_team,start_date) VALUES(1,2026,2,'Home','Away','2026-09-13T04:00:00Z')")
    record=SimpleNamespace(season=2026,week=2,home_team="Home",away_team="Away",start_date="2026-09-13T03:59:00Z",completed=True,home_points=24,away_points=21)
    result_writer(conn,[record])
    result_writer(conn,[record])
    assert conn.execute("SELECT start_date,home_points,away_points FROM games").fetchone()==("2026-09-13T04:00:00Z",24,21)
    record.home_points=25
    with pytest.raises(ValueError,match="prior final"):result_writer(conn,[record])
