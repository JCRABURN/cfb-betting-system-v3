"""Postgame process evidence, explicitly separated from pregame knowledge."""
from __future__ import annotations

from collections import defaultdict

from scripts.week9_audit_sources import ROOT, read_json, unique
from scripts.week9_audit_diagnostics import metrics, rounded
from scripts.week8_scoring_sequence_review import validate_sequence

PASS = {'Pass Reception', 'Passing Touchdown'}
RUSH = {'Rush', 'Rushing Touchdown'}
NON_OFFENSE_TD = {'Interception Return Touchdown', 'Fumble Return Touchdown',
                  'Kickoff Return Touchdown', 'Punt Return Touchdown', 'Blocked Field Goal Touchdown'}


def analyze_process(finals, grades, data):
    teams = unique(data['cfbd-team-stats'], 'id')
    players = unique(data['cfbd-player-stats'], 'id')
    advanced, drives, plays = defaultdict(list), defaultdict(list), defaultdict(list)
    for target, source in [(advanced, 'cfbd-advanced'), (drives, 'cfbd-drives'), (plays, 'cfbd-plays')]:
        for row in data[source]:
            target[str(row['gameId'])].append(row)
    rows, team_rows, quarterback_rows, scoring = [], [], [], []
    totals = {r['game_id']: r for r in grades if r['market'] == 'TOTAL'}
    for final in finals:
        gid = final['game_id']
        box = unique(teams[gid]['teams'], 'homeAway')
        qbs = unique(players[gid]['teams'], 'homeAway')
        adv = unique(advanced[gid], 'team')
        if len(adv) != 2 or set(box) != {'home', 'away'} or set(qbs) != {'home', 'away'}:
            raise ValueError('game process team coverage')
        all_plays = plays[gid]
        unique(all_plays, 'id')
        if not all_plays or not drives[gid]:
            raise ValueError('missing game process evidence')
        total_snaps = total_drives = total_yards = 0
        for side in ('away', 'home'):
            team = box[side]
            if team['teamId'] != final[side + '_id'] or team['points'] != final[side + '_score'] or qbs[side]['points'] != team['points'] or qbs[side]['team'] != team['team']:
                raise ValueError('box score orientation or final mismatch')
            a = adv[team['team']]
            opponent = box['home' if side == 'away' else 'away']['team']
            if a['opponent'] != opponent or a['season'] != 2026 or a['week'] != 9:
                raise ValueError('advanced identity mismatch')
            if a['defense'] != adv[opponent]['offense']:
                raise ValueError('advanced offense-defense mismatch')
            stats = unique(team['stats'], 'category')
            yards = int(stats['totalYards']['stat'])
            o = a['offense']
            total_snaps += o['plays']
            total_drives += o['drives']
            total_yards += yards
            team_rows.append(dict(game_id=gid, team=team['team'], location=side, points=team['points'],
                                  total_yards=yards, net_passing_yards=stats['netPassingYards']['stat'],
                                  rushing_yards=stats['rushingYards']['stat'], possession_time=stats['possessionTime']['stat'],
                                  provider_advanced_plays=o['plays'], provider_advanced_drives=o['drives'],
                                  ppa=o['ppa'], success_rate=o['successRate'], explosiveness=o['explosiveness'],
                                  defensive_ppa_allowed=a['defense']['ppa'], defensive_success_allowed=a['defense']['successRate'],
                                  passing_ppa=o['passingPlays']['ppa'], rushing_ppa=o['rushingPlays']['ppa'],
                                  evidence_time='POSTGAME;NOT_A_PREGAME_FEATURE_OR_CAUSAL_INJURY_ESTIMATE'))
            passing = next((c for c in qbs[side]['categories'] if c['name'] == 'passing'), None)
            if passing is None:
                quarterback_rows.append(dict(game_id=gid, team=team['team'], status='NO_PASSING_CATEGORY'))
            else:
                athletes = {}
                for kind in passing['types']:
                    for athlete in kind['athletes']:
                        entry = athletes.setdefault(athlete['id'], dict(game_id=gid, team=team['team'], athlete_id=athlete['id'],
                                                                      name=athlete['name'], status='OBSERVED_PASSER_NOT_ASSUMED_STARTER'))
                        entry[kind['name']] = athlete['stat']
                quarterback_rows.extend(athletes[k] for k in sorted(athletes))
        seq = data['espn-' + gid].get('scoringPlays', [])
        validate_sequence(seq, final['away_score'], final['home_score'])
        last = 0
        non_offense_events = non_offense_points = special_td = 0
        for p in seq:
            value = p['awayScore'] + p['homeScore']
            delta = value - last
            last = value
            kind = p['type']['text']
            special = kind in {'Kickoff Return Touchdown', 'Punt Return Touchdown', 'Blocked Field Goal Touchdown'}
            non_offense = kind in NON_OFFENSE_TD or kind in {'Safety', 'Defensive 2pt Conversion'} or (kind == 'Sack' and delta == 2)
            if non_offense:
                non_offense_events += 1
                non_offense_points += delta
                special_td += int(special)
                scoring.append(dict(game_id=gid, event_id=p['id'], type=kind, points_including_bundled_conversion=delta,
                                    period=p['period']['number'], clock=p['clock']['displayValue'], text=p['text'],
                                    source_sha256=final['espn_raw_sha256']))
        pass_plays = [p for p in all_plays if p['playType'] in PASS]
        rush_plays = [p for p in all_plays if p['playType'] in RUSH]
        explosive_pass = sum(p['yardsGained'] >= 20 for p in pass_plays)
        explosive_rush = sum(p['yardsGained'] >= 10 for p in rush_plays)
        t = totals[gid]
        rows.append(dict(game_id=gid, away=final['away'], home=final['home'], actual_total=t['actual_model_target'],
                         frozen_projection=t['raw_projection'], locked_total=t['locked_line'], result=t['result'],
                         forecast_error_actual_minus_predicted=t['forecast_error_actual_minus_predicted'],
                         provider_advanced_offensive_plays=total_snaps, provider_advanced_offensive_drives=total_drives,
                         raw_drives_with_positive_plays=sum(d['plays'] > 0 for d in drives[gid]),
                         raw_drive_records=len(drives[gid]), total_yards=total_yards,
                         explosive_pass_20_plus=explosive_pass, explosive_rush_10_plus=explosive_rush,
                         classified_explosives_per_100_advanced_plays=rounded(100*(explosive_pass+explosive_rush)/total_snaps),
                         non_offensive_scoring_events=non_offense_events, non_offensive_points_with_bundled_conversions=non_offense_points,
                         special_teams_touchdowns=special_td, overtime=any(p['period'] > 4 for p in all_plays),
                         points_per_provider_drive=rounded(t['actual_model_target']/total_drives)))
    lookup = {r['game_id']: r for r in rows}
    segments = []
    for name, predicate in [('plays_150_plus', lambda r: r['provider_advanced_offensive_plays'] >= 150),
                            ('plays_below150', lambda r: r['provider_advanced_offensive_plays'] < 150),
                            ('drives_26_plus', lambda r: r['provider_advanced_offensive_drives'] >= 26),
                            ('drives_below26', lambda r: r['provider_advanced_offensive_drives'] < 26),
                            ('nonoffensive_score', lambda r: r['non_offensive_scoring_events'] > 0),
                            ('no_nonoffensive_score', lambda r: r['non_offensive_scoring_events'] == 0)]:
        group = [t for gid, t in totals.items() if predicate(lookup[gid])]
        segments.append(dict(segment=name, status='POSTGAME_EXPLORATORY_SUBGROUP', **metrics(group)))
    # Preserve the actual words and evidence of the pregame decision; do not refit its rationale.
    decisions = []
    for path in sorted((ROOT/'outputs/2026-week9-owner-review').glob('*/owner_review_shortlist.json')):
        review = read_json(path)
        for r in review['selections']:
            if str(r['game_id']) in ('401862812', '401858278'):
                decisions.append(dict(source_review=path.relative_to(ROOT).as_posix(), revision_time=review['created_at_utc'],
                                      row_decision_time=r['created_at_utc'], game_id=r['game_id'], market=r['market'],
                                      rank=r['owner_review_rank'], recommended_five=r['recommended_five'],
                                      human_confidence=r['human_review_confidence_1_to_5'],
                                      supporting_evidence=r['supporting_evidence'], risk_and_exclusion_reason=r['risk_and_exclusion_reason'],
                                      sources=r['sources']))
    return dict(status='POSTGAME_PROCESS_DIAGNOSTICS_RESEARCH_ONLY', games=rows, teams=team_rows, observed_passers=quarterback_rows,
                nonoffensive_scoring_events=scoring, exploratory_process_segments=segments, fau_removal_pregame_record=decisions,
                definitions={'plays_and_drives': 'Provider advanced offensive counts; raw drives separately reported. Counts differ by provider inclusion of end-half/zero-play drives. Play volume is not clock-adjusted tempo.',
                             'explosives': 'Pass Reception/Passing Touchdown gains >=20; Rush/Rushing Touchdown gains >=10. Returns, penalties and ambiguous fumble types excluded. Denominator is provider advanced plays; not a universal explosive-rate definition.',
                             'non_offense': 'Validated ESPN scoring types for return touchdowns, safeties, defensive conversions; point deltas include conversions bundled with touchdown by ESPN. Not a counterfactual adjusted final.',
                             'personnel': 'Observed passer box scores do not establish medical clearance, causal injury effects, or what was known before kickoff. Pregame context remains in original timestamped versions.',
                             'availability': 'All 54 games have team/player, advanced, drives and play-by-play responses. Cross-provider agreement is corroboration; ESPN and CFBD may share upstream data.'})
