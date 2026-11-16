"""Separate contextual judgment and complete candidate evidence matrix; no card writes."""
import argparse
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path
from scripts import week11_context as context
from scripts import capture_week11_availability as availability
from scripts.seal_week11_board import ROOT, OUT as BOARD, csv_rows, instant, read, sha
from research.week11_validation.forward_shadow import CAPTURE

CONTEXT=ROOT/'outputs/2026-week11-context/20261112T1220Z-initial'
AVAILABILITY=ROOT/'outputs/2026-week11-context/20261112-availability-v1'
OUT=ROOT/'outputs/2026-week11-owner-review/20261112-v1'
# Deliberately separate, low-confidence contextual judgments. No fabricated margin adjustments.
CHOICES=[('401858296','ATS',2),('401860917','TOTAL',2),('401858294','ATS',1),('401856860','ATS',1),('401858523','ATS',1)]
NOTES={
 '401858296':('Duke OL has allowed four sacks through nine games; Sheppard has 1,189 rushing yards at6.23/carry. Those are specific ways to sustain drives while receiving13.5. Miami lists Toney and Joshua Moore out.','Duke also lists four OL out; roster designations do not identify their snap shares. Secondary absences, road environment and Miami efficiency remain serious risks. No injury points added.',['article-duke-3','article-duke-4']),
 '401860917':('CSU official preview reports Washington State scoring19.0/game, with Eshelman starting its last three games. That supports scrutiny of a67.5 total; model55.17 remains unchanged.','CSU has scored over35/game and produced12 explosives against Boise State. Four different OL starting combinations, backup running backs and QB scrambling make a simple slow-game assumption unsafe. Moderate forecast wind is not an Under adjustment.',['article-colorado-state-5','article-colorado-state-4','article-colorado-state-2']),
 '401858294':('Receiving28.5 against an unchanged17.59 home-margin forecast supplies cushion across four touchdowns. BC weekly preview reports165.9 rushing yards/game and QB rushing production.','This is a low-confidence cushion argument, not validated value. Notre Dame quality, BC recent large losses and unconfirmed final OL/defensive availability make a blowout plausible. No independent full-health claim.',['article-boston-college-0','article-boston-college-3']),
 '401856860':('Colorado receives10.5 at home against a2.33-point Houston margin. Lampron had18 tackles and CU held ASU to2.6 rushing yards/carry; specific defensive evidence supports the possibility of staying close.','Houston OL is a Joe Moore semifinalist. Colorado scored10 last game and has multiple receiver/secondary absences; Houston Wolford is out and Buhake questionable. Friday game needs final report; no assumed return from Coach Prime comments.',['article-colorado-7','article-colorado-0','article-houston-1']),
 '401858523':('Michigan receives11.5 against a1.91-point Oregon margin. Oregon lists Moore, Davison, Tuioti and two OL out.','Michigan scored6 last game and lists Sprague out, Frazier doubtful, Norton and Daley questionable. Oregon scored34 and41 in its last two games and allowed zero sacks in both. Moore absence already enters cumulative inputs; no second injury adjustment. QB Available does not confirm a starter.',['primary-supplement-3','article-michigan-2']),
 '401858522':('Northwestern remains an original ATS research candidate at+12.5; forecastOhio State3.99.','Excluded from contextualfive: both Chiles and Sayin are out. Northwestern backup/OL risk offsets an automatic fade of Ohio State. No causal injury valuation or starter inference.',['official-northwestern','official-ohio-state']),
 '401856863':('Original Under73.5 / forecast52.05 remains frozen researchrank1.','Excluded: OSU43.9PPG,5.5% three-and-outs,7.89 first-down yards/play and Mestemaker production conflict with trusting a21.45-point gap. Texas Tech QB change to Castellanos and a53-48 prior game amplify regime/efficiency risk. Initial OL/RB/WR limitations do not quantify an offset.',['primary-supplement-0','article-texas-tech-5']),
 '401862826':('Original Under74.5 / forecast55.54 remains frozen researchrank2.','Excluded: FAU40.8PPG and Veltkamp five consecutive games with3+ passTDs; Tulsa just scored60 with Baylor Hayes. Defensive takeaways can create short fields. A low model total is not evidence of low possession volume.',['article-florida-atlantic-1','article-florida-atlantic-3','article-tulsa-4']),
 '401862827':('Original Under76.5 / forecast57.57 remains frozen researchrank3.','Excluded: UNT recently scored48 and52; official preview emphasizes two scores after Rice turnovers and McCown efficiency. Indoor Alamodome supplies no wind suppression. Final QB/OL/D clearance is incomplete; turnover/short-field variance remains.',['primary-supplement-2']),
 '401856861':('Original Under67.5 / forecast53.10 remains frozen researchrank4.','Excluded: WVU reports70 plays of20+ allowed and35 of30+, both national highs; Kansas has54 plays of20+. Hawkins dual-threat production and explosive defense failures dominate raw-gap comfort. WVU Grayson/Dillard out; no invented offset.',['article-west-virginia-2','article-west-virginia-6']),
 '401864540':('Over39.5 / forecast48.94 is retained as a researchalternative.','Not selected: Wyoming officially calls Hughes doubtful with forearm fracture; Sims is next up. Backup workload changes and UTEP efficiency uncertainty challenge an Over built on old inputs.',['article-wyoming-6']),
 '401860914':('Under65.5 / forecast57.08 remains a researchalternative.','Boise initial report has Madsen questionable, Rasmussen out. Boise39.0PPG and elite OL/possession efficiency plus Oregon State Atkinson352.1 passing yards/game oppose a simple low-possession Under narrative.',['article-boise-state-4','article-boise-state-1','article-oregon-state-0']),
 '401860916':('Under60.5 / forecast52.20 remains a researchalternative.','Texas State Week10 advanced evidence shows84 offensive plays,13 drives,.3647PPA and58.33% success. Fresno has seven OL combinations in nine games and a second straight road trip through a third time zone. Pace and efficiency must be separated; no assumption that rain erases them.',['article-fresno-state-2','official-texas-state']),
 '401871099':('Under55.5 / forecast47.79 remains a researchalternative.','Southern Miss QB transition/tempo comments and Louisiana Tech Baker efficiency remain unresolved personnel/regime risks. Prior defensive performance is not current clearance.',['article-southern-miss-1','article-louisiana-tech-2','article-louisiana-tech-3']),
 '401864537':('Over38.5 / forecast45.86 remains a researchalternative.','NWS forecast23mph sustained wind throughout kickoff window is material to passing and kicking; gust data unavailable. Long travel to Hawaii and Alejado passing volume add uncertainty. No numeric wind adjustment.',['article-north-dakota-state-0']),
 '401869952':('Georgia State+5.5 / projectedhome margin+2.79 remains a researchalternative.','Georgia Southern Max Johnson accounted for fiveTDs against Marshall. Final personnel evidence for Georgia State is incomplete; no confidence promotion based only on an8.29-point edge.',['article-georgia-southern-3','official-georgia-state']),
 '401856889':('Vanderbilt+15.5 / Alabama margin8.37 remains a researchalternative.','Alabama Russell production and unresolved final SEC OL/D availability keep this outside thefive. No verified numeric personnel adjustment.',['article-alabama-1','official-vanderbilt']),
 '401870769':('Sam Houston+7.5 / Kennesaw margin0.37 remains a researchalternative.','Sam Houston lost47-14; Locke returned from an injury last week, which does not establish clearance. Final QB/OL/D confirmation and protection against explosive rushing remain incomplete.',['article-sam-houston-2','official-kennesaw-state']),
 '401866462':('Original SacramentoState+17.5 / CMU margin7.44 remains frozen ATSresearchrank2.','Already-started Wednesday game: no new recommendation, personnel retrieval or retrospective reassessment. Late external-seal limitation remains explicit.',[]),
}

def build(as_of):
    context.verify(CONTEXT);availability.verify(AVAILABILITY)
    m=read(CONTEXT/'manifest.json'); evidence={r['name']:r for r in m['records']}
    schedule={g['game_id']:g for g in m['candidates']};weather={r['game_id']:r for r in m['weather']}
    ats={r['game_id']:r for r in csv_rows('week11_ats_full_card.csv')};totals={r['game_id']:r for r in csv_rows('week11_totals_full_card.csv')}
    ranks={market:{r['game_id']:i+1 for i,r in enumerate(csv_rows(f'week11_{name}_research_top10.csv'))} for market,name in [('ATS','ats'),('TOTAL','totals')]}
    people={}
    for conf in availability.OFFICIAL:
        for report in json.loads(gzip.decompress((AVAILABILITY/(conf+'.json.gz')).read_bytes())).values():
            for team in report['games']:
                people[team['teamDisplayName']]=dict(conference=conf,published_date=report['publishDate'],published_time=report['postedTime'],timezone_label=report['conferenceTimeZone'],report_type=report['ReportType'],
                    entries=[r for r in team['rows'] if r['name'].startswith('QB ') or r['status'] not in ('Available','Exempt')])
    advanced=[]
    for week in (8,9,10):advanced.extend(json.loads(gzip.decompress((CAPTURE/f'cfbd-prior-week{week}-advanced.json.gz').read_bytes())))
    market={str(g['id']):g for g in json.loads(gzip.decompress((CONTEXT/'separate-current-market.gz').read_bytes()))}
    rows=[]
    for gid,g in sorted(schedule.items()):
        support,risk,names=NOTES[gid]
        source_refs=[dict(name=n,url=evidence[n]['url'],raw_sha256=evidence[n].get('raw_sha256')) for n in names]
        started=instant(g['kickoff_utc'])<=instant(as_of)
        teams=[]
        if not started:
            for side in ('away','home'):
                team=g[side];prior=[r for r in advanced if r['team']==team]
                teams.append(dict(team=team,side=side,availability=people.get(team,{'status':'OFFICIAL_FINAL_CLEARANCE_NOT_OBTAINED'}),
                    recent_games=[dict(week=r['week'],opponent=r['opponent'],offensive_plays=r['offense']['plays'],offensive_drives=r['offense']['drives'],offensive_ppa=r['offense']['ppa'],offensive_success_rate=r['offense']['successRate'],offensive_explosiveness=r['offense']['explosiveness'],defensive_ppa=r['defense']['ppa']) for r in prior],
                    rest_days=g[side+'_kickoff_to_kickoff_rest_days'],travel='Away team travels to '+g['venue'] if side=='away' else 'Home venue; no travel adjustment'))
        rows.append(dict(game_id=gid,game=g['away']+' @ '+g['home'],kickoff_utc=g['kickoff_utc'],ats_research_rank=ranks['ATS'].get(gid),totals_research_rank=ranks['TOTAL'].get(gid),
            frozen_ats=ats[gid],frozen_total=totals[gid],context_status='FROZEN_STARTED_NO_NEW_RECOMMENDATION' if started else 'PROVISIONAL_PREGAME_REVIEW',
            evidence_support=support,risks=risk,sources=source_refs,team_context=teams,weather=weather.get(gid),
            separate_market_observation=None if started else market.get(gid),market_status='RETRIEVAL_OBSERVATION_NOT_CLOSE_OR_CONTEST_REPLACEMENT',final_clearance='INCOMPLETE',numeric_adjustments=[]))
    by_id={r['game_id']:r for r in rows};choices=[]
    for rank,(gid,kind,confidence) in enumerate(CHOICES,1):
        row=by_id[gid]
        if instant(as_of)>=instant(row['kickoff_utc']):raise ValueError('cannot issue new recommendation after kickoff')
        original=ats[gid] if kind=='ATS' else totals[gid]
        choices.append(dict(rank=rank,game_id=gid,game=row['game'],market=kind,pick=original['pick'],contest_line=float(original['pick_spread'] if kind=='ATS' else original['locked_total']),
            frozen_projection=float(original['projected_home_margin'] if kind=='ATS' else original['projected_total']),projection_orientation='HOME_MARGIN' if kind=='ATS' else 'GAME_TOTAL',
            original_confidence=int(original['confidence']),human_confidence=confidence,reason=row['evidence_support'],unresolved_risks=row['risks']))
    input_paths=[CONTEXT/'manifest.json',AVAILABILITY/'manifest.json',BOARD/'week11_initial_seal_manifest.json']+[CAPTURE/f'cfbd-prior-week{w}-advanced.json.gz' for w in (8,9,10)]
    return dict(created_at_utc=as_of,status='PROVISIONAL_OWNER_REVIEW_NOT_SUBMITTED_CONTEST_PICKS',owner_approval='PENDING',choices=choices,candidates=rows,
        original_combined_research_top5=csv_rows('week11_legacy_mixed_research_top5.csv'),input_sha256={p.relative_to(ROOT).as_posix():sha(p) for p in input_paths},
        changes='Initial separate human review; replaces none of the frozen research rankings. Four original combined Unders excluded on offense/explosive evidence; CSU-WSU Under retained. No diversification quota. Sacramento State original ATS research row remains frozen after kickoff.',
        confidence_definition='Human1=very tentative;2=tentative with some matchup support. Ordinal judgments only, not calibrated win probabilities, no governed confidence change.',
        outstanding=['Final Saturday availability and confirmed QB assignments','Complete depth/snap-share context for every OL/defensive absence','Weather/gust refresh before kickoff; no numerical weather adjustment','Provider market observations have retrieval times but no book quote timestamps; CLV INCOMPLETE','All original forecasts unchanged; Wednesday pregame external sealing unproven','No proven profitable Top5 selection method or owner approval'])

def markdown(value):
    lines=['# Week 11 separate owner review — PROVISIONAL', '', f"Created {value['created_at_utc']}. Owner approval PENDING. v2.8 unchanged. Human confidence is ordinal, not a probability.",'','| Rank | Selection | Frozen projection | Human C | Reason and unresolved risks |','|---:|---|---:|---:|---|']
    for r in value['choices']:
        lines.append(f"| {r['rank']} | {r['game']}: {r['pick']} {r['contest_line']:+g} | {r['frozen_projection']:.2f} ({r['projection_orientation']}) | {r['human_confidence']}/5 | {r['reason']} {r['unresolved_risks']} |")
    lines+=['','## All Top10 candidate games','','| Matchup | ATS rank | Total rank | Evidence / exclusion |','|---|---:|---:|---|']
    for r in value['candidates']:
        refs='; '.join(f"[{s['name']}]({s['url']})" for s in r['sources'])
        lines.append(f"| {r['game']} | {r['ats_research_rank'] or '-'} | {r['totals_research_rank'] or '-'} | {r['evidence_support']} {r['risks']} Sources: {refs} |")
    lines+=['','The JSON companion contains all recorded QB/OL/defensive designations, prior-week efficiency and possession samples, venue weather, rest, and separate market observations. Absence of a report is explicitly incomplete. Depth charts and prior participation do not establish medical clearance.','',value['changes'],'']
    return '\n'.join(lines)

def main(verify=False):
    if verify:
        saved=read(OUT/'review.json');value=build(saved['created_at_utc'])
        if saved!=value or (OUT/'REVIEW.md').read_text(encoding='utf-8')!=markdown(value):raise ValueError('owner review replay mismatch')
    else:
        if OUT.exists():raise FileExistsError('never overwrite owner review')
        value=build(datetime.now(timezone.utc).isoformat());OUT.mkdir(parents=True)
        with (OUT/'review.json').open('x',encoding='utf-8',newline='\n') as stream:stream.write(json.dumps(value,indent=2,sort_keys=True)+'\n')
        with (OUT/'REVIEW.md').open('x',encoding='utf-8',newline='\n') as stream:stream.write(markdown(value))
    return dict(status=value['status'],candidate_games=len(value['candidates']),recommendations=len(value['choices']),owner_approval=value['owner_approval'])

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--verify',action='store_true');print(json.dumps(main(p.parse_args().verify)))
