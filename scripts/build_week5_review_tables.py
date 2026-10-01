"""Build auditable Week 5 context and large-edge checks from frozen v4 forecasts."""

from __future__ import annotations

import csv
import json
import unicodedata
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
V4 = ROOT / "outputs/2026-week5-execution-20260930-v4"
OUT = ROOT / "outputs/2026-week5-review-20261001"
EVIDENCE = OUT / "provider-evidence"

# These sources speak to recent participation, not guaranteed Week 5 starters.
QB_UPDATES = {
    "Western Kentucky": ("Rodney Tisdale Jr. / Brock Glenn", "UNCERTAIN", "WKU reports both played extensively in Week 4; no Week 5 starter designation.", "https://wkusports.com/news/2026/9/29/football-hilltoppers-face-first-conference-usa-matchup-against-new-mexico-state-on-thursday"),
    "New Mexico State": ("Trey Hedden / Adam Damante", "UNCERTAIN", "NM State reports Damante replaced Hedden late in Week 4; no Week 5 starter designation.", "https://nmstatesports.com/news/2026/9/28/football-aggies-open-conference-usa-action-on-thursday-against-wku.aspx"),
    "North Texas": ("Tayven Jackson", "PROBABLE", "North Texas identifies Jackson as its Week 4 starting quarterback; no Week 5 confirmation.", "https://meangreensports.com/news/2026/9/26/football-white-scores-four-tds-as-mean-green-rout-huskies"),
    "Tulsa": ("Dexter Williams II / Baylor Hayes", "UNCERTAIN", "Tulsa says Hayes played Weeks 1-2 and Williams the last two; independent injury reporting identifies a Hayes knee concern. Starter unconfirmed.", "https://tulsahurricane.com/news/2026/9/29/football-tulsa-opens-american-conference-play-thursday-against-north-texas"),
    "Liberty": ("Deshawn Purdie / Ethan Vasko", "UNCERTAIN", "Liberty's Week 4 recap describes both quarterbacks in scoring plays; Week 5 starter unconfirmed.", "https://libertyflames.com/news/2026/9/25/football-liberty-shines-in-second-half-to-secure-primetime-win-over-coastal-carolina"),
    "Delaware": ("Nick Minicucci", "PROBABLE", "Delaware's Week 5 preview identifies Minicucci as its leading quarterback; starter not formally confirmed.", "https://bluehens.com/news/2026/9/30/football-hosts-liberty-on-friday-for-sold-out-parents-family-weekend-game"),
    "Virginia Tech": ("Ethan Grunkemeyer", "PROBABLE", "Virginia Tech's current Pitt preview identifies Grunkemeyer as leading its offense.", "https://hokiesports.com/news/2026/09/29/virginia-tech-football-first-look-virginia-tech-vs-pitt-2026"),
    "Penn State": ("Rocco Becht", "PROBABLE", "Penn State coach discussed Becht's Week 4 play in its current Northwestern press conference.", "https://gopsusports.com/news/2026/09/29/weekly-press-conference-transcript-head-coach-matt-campbell-northwestern"),
    "Northwestern": ("Aidan Chiles", "PROBABLE", "Northwestern reports Chiles led its Week 4 offense against Indiana.", "https://nusports.com/news/2026/09/25/cats-comeback-falls-short-at-no-5-indiana-29-23"),
    "SMU": ("Kevin Jennings", "PROBABLE", "Boston College's current SMU personnel preview treats Jennings as the Mustang quarterback.", "https://bceagles.com/news/2026/9/30/-forboston-files-know-your-personnel-smu"),
    "UNLV": ("Jackson Arnold", "PROBABLE", "UNLV's 2026 recap identifies Arnold as its quarterback; no fresh Week 5 starter designation.", "https://unlvrebels.com/news/2026/8/30/football-memphis-rallies-past-rebels-in-season-opener.aspx"),
    "Pittsburgh": ("Mason Heintschel", "PROBABLE", "Pitt's September 29 quarterback interview and opponent preview identify Heintschel for Virginia Tech; not a confirmed starter.", "https://pittsburghpanthers.com/news/2026/9/29/football-talkin-pitt-taking-the-standard-on-the-road"),
    "Cincinnati": ("JC French IV", "PROBABLE", "Cincinnati's current Arizona preview includes French among the players speaking; not a confirmed starter.", "https://gobearcats.com/news/2026/09/29/watch-head-coach-scott-satterfield-players-preview-arizona-game-1"),
    "Arizona": ("Noah Fifita", "PROBABLE", "Arizona's Week 5 game preview identifies Fifita as the quarterback; not a confirmed starter.", "https://arizonawildcats.com/news/2026/9/28/football-wildcats-welcome-bearcats-for-big-12-home-opener"),
    "Alabama": ("Keelon Russell", "PROBABLE", "Alabama's current player bio and September 22 award item identify Russell's 2026 quarterback role; Week 5 designation unconfirmed.", "https://rolltide.com/sports/football/roster/russell-keelon/17477"),
    "Mississippi State": ("Kamario Taylor", "PROBABLE", "Mississippi State's September 26 Missouri recap identifies Taylor as its quarterback; Week 5 designation unconfirmed.", "https://hailstate.com/news/2026/9/26/football-ferries-record-setting-night-memorable-in-many-ways"),
    "Kent State": ("Dru DeShields", "PROBABLE", "Kent State's 2026 cumulative statistics show DeShields played all four games; Week 5 designation unconfirmed.", "https://kentstatesports.com/sports/football/stats/2026"),
    "Ohio": ("Matt Vezza / UNVERIFIED", "UNCERTAIN", "Ohio reported Vezza left a September game injured; no credible Week 5 availability confirmation found.", "https://ohiobobcats.com/news/2026/9/15/ohio-football-hits-the-road-to-take-on-south-alabama"),
}


def rows(name: str) -> list[dict[str, str]]:
    with (V4 / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(name: str, records: list[dict]) -> None:
    if not records:
        raise ValueError(f"empty review artifact: {name}")
    with (OUT / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)


def market_line(event: dict) -> tuple[float, float, str]:
    books = [book for book in event.get("bookmakers", []) if book.get("key") == "draftkings"]
    if len(books) != 1:
        raise ValueError(f"DraftKings offer missing for {event.get('id')}")
    book = books[0]
    markets = {market["key"]: market for market in book.get("markets", [])}
    home = [value for value in markets["spreads"]["outcomes"] if value["name"] == event["home_team"]]
    over = [value for value in markets["totals"]["outcomes"] if value["name"].casefold() == "over"]
    if len(home) != 1 or len(over) != 1:
        raise ValueError(f"DraftKings spread/total incomplete for {event.get('id')}")
    return float(home[0]["point"]), float(over[0]["point"]), book.get("last_update", "")


def main() -> None:
    capture = json.loads((EVIDENCE / "capture-manifest.json").read_text(encoding="utf-8"))
    if capture["status"] != "COMPLETE":
        raise ValueError("fresh evidence capture incomplete")
    ats = rows("week5_ats_full_card.csv")
    totals = {int(row["game_id"]): row for row in rows("week5_totals_full_card.csv")}
    schedule_all = json.loads((V4 / "provider-evidence/cfbd-2026-games.json").read_text(encoding="utf-8"))
    schedule = {game["id"]: game for game in schedule_all}
    previews = {row["game_id"]: row for row in json.loads((EVIDENCE / "espn-game-preview-qb-evidence.json").read_text(encoding="utf-8"))}
    weather = {row["game_id"]: row for row in json.loads((EVIDENCE / "weather-kickoff-review.json").read_text(encoding="utf-8"))}
    odds = json.loads((EVIDENCE / "odds-draftkings-current.json").read_text(encoding="utf-8"))
    odds_by_names = {(event["away_team"], event["home_team"]): event for event in odds}
    official_aliases = {
        "San Jos\ufffd State Spartans": "San Jose State Spartans",
        "Hawai'i Rainbow Warriors": "Hawaii Rainbow Warriors",
        "Massachusetts Minutemen": "UMass Minutemen",
        "Louisiana Ragin' Cajuns": "Louisiana Ragin Cajuns",
    }
    stats = {row["team"]: row for row in json.loads((V4 / "provider-evidence/cfbd-week4-advanced.json").read_text(encoding="utf-8"))}
    qb_rows: list[dict] = []
    context_rows: list[dict] = []
    large_rows: list[dict] = []
    observed_at = datetime.now(timezone.utc).isoformat()
    for pick in ats:
        game_id = int(pick["game_id"])
        game = schedule[game_id]
        leaders = {str(team["espn_team_id"]): team for team in previews[game_id]["teams"]}
        if len(leaders) != 2:
            raise ValueError(f"ESPN QB preview incomplete: {game_id}")
        qb_row: dict[str, object] = {"game_id": game_id, "away": pick["away"], "home": pick["home"]}
        odds_names: dict[str, str] = {}
        for side in ("away", "home"):
            team_name = pick[side]
            evidence = leaders.get(str(game[side + "Id"]))
            if evidence is None:
                raise ValueError(f"ESPN team identity mismatch: {game_id}:{side}")
            source_team = unicodedata.normalize("NFKD", evidence["team"]).encode("ascii", "ignore").decode("ascii")
            odds_names[side] = official_aliases.get(source_team, source_team)
            override = QB_UPDATES.get(team_name)
            candidate = evidence["season_passing_leader"] or "UNVERIFIED"
            expected, status, note, url = (override if override else (
                candidate, "UNCERTAIN" if candidate != "UNVERIFIED" else "UNAVAILABLE",
                "ESPN season passing leader only; this does not establish a Week 5 starter or availability.",
                previews[game_id]["source"],
            ))
            qb_row[f"expected_{side}_qb"] = expected
            qb_row[f"{side}_qb_status"] = status
            qb_row[f"{side}_qb_evidence"] = note
            qb_row[f"{side}_qb_source"] = url
            qb_row[f"{side}_qb_source_observed_at_utc"] = observed_at
            qb_row[f"{side}_qb_evidence_confidence"] = "MEDIUM" if override else "LOW"
            qb_row[f"material_{side}_injuries"] = (
                "Baylor Hayes knee concern; Week 5 availability unresolved" if team_name == "Tulsa" else
                "Matt Vezza left a September game injured; Week 5 availability unresolved; other injuries UNVERIFIED" if team_name == "Ohio" else
                "UNVERIFIED; ESPN injury feed records are from 2020/2022 and cannot establish 2026 health"
            )
        qb_row["injury_source"] = ("https://totalapexsports.com/north-texas-tulsa-preview-thursday/"
                                  if "Tulsa" in (pick["away"], pick["home"]) else
                                  "https://ohiobobcats.com/news/2026/9/15/ohio-football-hits-the-road-to-take-on-south-alabama"
                                  if "Ohio" in (pick["away"], pick["home"]) else
                                  "https://site.api.espn.com/apis/site/v2/sports/football/college-football/injuries")
        qb_row["injury_observed_at_utc"] = observed_at
        qb_row["injury_evidence_confidence"] = "LOW;UNVERIFIED_EXCEPT_TULSA_QB_CONCERN"
        qb_rows.append(qb_row)
        event = odds_by_names.get((odds_names["away"], odds_names["home"]))
        if event is None:
            raise ValueError(f"unmatched current market: {game_id} {odds_names}")
        current_spread, current_total, updated = market_line(event)
        locked_spread = float(pick["locked_home_spread"])
        locked_total = float(totals[game_id]["locked_total"])
        spread_move = current_spread - locked_spread
        total_move = current_total - locked_total
        current = weather[game_id]
        advantage = locked_spread - current_spread if pick["selected_side"] == "home" else current_spread - locked_spread
        total_advantage = current_total - locked_total if totals[game_id]["pick"] == "over" else locked_total - current_total
        context_rows.append({
            "game_id": game_id, "away": pick["away"], "home": pick["home"],
            "locked_home_spread": locked_spread, "current_dk_home_spread": current_spread,
            "current_minus_locked_home_spread": spread_move,
            "spread_move_flag_ge_1_5": abs(spread_move) >= 1.5,
            "ats_selected_locked_advantage": advantage,
            "locked_total": locked_total, "current_dk_total": current_total,
            "current_minus_locked_total": total_move,
            "total_move_flag_ge_2_5": abs(total_move) >= 2.5,
            "total_selected_locked_advantage": total_advantage,
            "draftkings_offer_updated_at": updated,
            "market_capture_at": capture["requests"][0]["requested_at"],
            "weather_status": current["status"], "wind_mph": current.get("wind_mph", ""),
            "precip_probability_pct": current.get("precip_probability_pct", ""),
            "temperature_f": current.get("temperature_f", ""),
            "forecast_hour_utc": current.get("forecast_hour_utc", ""),
            "weather_capture_at": current.get("requested_at", ""),
        })
        edge = float(pick["home_ats_edge"])
        if abs(edge) < 7:
            continue
        prior_review = {}
        for side in ("away", "home"):
            team_name = game[side + "Team"]
            previous = [item for item in schedule_all if item.get("completed") and item["week"] < 5 and team_name in (item["homeTeam"], item["awayTeam"])]
            fcs = [item for item in previous if item.get("homeClassification") != "fbs" or item.get("awayClassification") != "fbs"]
            biggest = max((abs(item["homePoints"] - item["awayPoints"]) for item in previous), default=0)
            team_stats = stats.get(team_name, {})
            prior_review[side] = {"completed_games": len(previous), "fbs_games": len(previous) - len(fcs),
                                  "fcs_games": len(fcs), "largest_final_margin": biggest,
                                  "offense_plays_in_week4_aggregate": team_stats.get("offense", {}).get("plays"),
                                  "defense_plays_in_week4_aggregate": team_stats.get("defense", {}).get("plays")}
        warnings = []
        if any(prior_review[side]["fcs_games"] for side in ("away", "home")):
            warnings.append("FCS_OPPONENT_IN_PRIOR_AGGREGATE")
        if any(prior_review[side]["largest_final_margin"] >= 35 for side in ("away", "home")):
            warnings.append("PRIOR_35_PLUS_BLOWOUT")
        if any((prior_review[side]["offense_plays_in_week4_aggregate"] or 0) < 100 for side in ("away", "home")):
            warnings.append("LOW_OFFENSE_PLAY_SAMPLE")
        if any(qb_row[f"{side}_qb_status"] != "PROBABLE" for side in ("away", "home")):
            warnings.append("QB_NOT_PROBABLE_BOTH_SIDES")
        if advantage <= -1.5:
            warnings.append("ADVERSE_MATERIAL_SPREAD_MOVE")
        large_rows.append({
            "game_id": game_id, "away": pick["away"], "home": pick["home"], "pick": pick["pick"],
            "locked_pick_spread": pick["pick_spread"], "home_ats_edge": edge,
            "away_completed_games": prior_review["away"]["completed_games"],
            "home_completed_games": prior_review["home"]["completed_games"],
            "away_fbs_games": prior_review["away"]["fbs_games"],
            "home_fbs_games": prior_review["home"]["fbs_games"],
            "away_fcs_games": prior_review["away"]["fcs_games"],
            "home_fcs_games": prior_review["home"]["fcs_games"],
            "away_max_prior_margin": prior_review["away"]["largest_final_margin"],
            "home_max_prior_margin": prior_review["home"]["largest_final_margin"],
            "away_offense_plays": prior_review["away"]["offense_plays_in_week4_aggregate"],
            "home_offense_plays": prior_review["home"]["offense_plays_in_week4_aggregate"],
            "home_away_model_adjustment": "BASELINE_HOME_MARGIN_ONLY;NO_CURRENT_LOCATION_SPLIT",
            "opponent_strength_adjustment": "NOT_IN_BASELINE;MIX_UNCONTROLLED",
            "garbage_time": "CFBD_QUERY_EXCLUDES_GARBAGE_TIME;NOT_INDEPENDENTLY_VERIFIED",
            "turnover_driven_performance": "UNVERIFIED;NO_TURNOVER_FEATURE",
            "qb_change_status": f"{qb_row['away_qb_status']}/{qb_row['home_qb_status']}",
            "structural_warnings": ";".join(warnings) or "NO_SPECIFIC_FLAG;CALIBRATION_STILL_WEAK",
            "review_classification": "CONDITIONAL_RAW_SIGNAL_NOT_VALIDATED_EDGE",
        })
    if len(qb_rows) != 56 or len(context_rows) != 56:
        raise ValueError("every locked game requires QB and market/weather rows")
    write_csv("week5_qb_injury_review.csv", qb_rows)
    write_csv("week5_market_weather_review.csv", context_rows)
    write_csv("week5_large_ats_edge_audit.csv", large_rows)
    print(json.dumps({"games": len(qb_rows), "matched_current_markets": len(context_rows),
                      "large_ats_edges_reviewed": len(large_rows),
                      "material_spread_moves": sum(row["spread_move_flag_ge_1_5"] for row in context_rows),
                      "material_total_moves": sum(row["total_move_flag_ge_2_5"] for row in context_rows)}))


if __name__ == "__main__":
    main()
