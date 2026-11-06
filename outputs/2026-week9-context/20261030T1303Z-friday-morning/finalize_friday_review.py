"""Build only the new Friday context/review evidence; preserve prior versions."""
import copy
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CAP = Path(__file__).resolve().parent
PREV = ROOT/'outputs/2026-week9-owner-review/20261029-morning-decision/owner_review_shortlist.json'
OUT = ROOT/'outputs/2026-week9-owner-review/20261030-friday-morning'
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):
    with p.open('x',encoding='utf-8',newline='\n') as f: f.write(json.dumps(v,indent=2,ensure_ascii=False)+'\n')

def main():
    OUT.mkdir(exist_ok=False)
    prior=read(PREV);review=copy.deepcopy(prior);stamp=datetime.now(timezone.utc).isoformat()
    manifest=read(CAP/'capture-manifest.json');board=read(CAP/'derived_context_board.json')
    games={g['game_id']:g for g in board['games']}
    records=manifest['records']
    supplement=read(CAP/'supplement/manifest.json')['records']+read(CAP/'supplement/canonical-manifest.json')['records']
    records=records+supplement
    def source(name):
        r=next(x for x in records if x['name']==name)
        assert r['status']=='CAPTURED'
        return {'url':r['url'],'captured_at_utc':r['received_at_utc'],'sha256':r['sha256']}
    notes={
      1:('Friday: official previews retain Moore absence and coordinator change; three prior full games without Moore already enter the frozen cumulative inputs. Northwestern OL improvement and Pate replacing injured defenders are prior-game evidence. No second injury deduction or 6.973-point sensitivity adjustment.',
         'Oregon replacement QB and play-calling response remain uncertain; complete final OL/defensive clearance unavailable. Autzen travel/venue risk persists. Forecast wind 1-2 mph gives no material mitigation.', ['article-northwestern-2','article-northwestern-3','article-oregon-1','article-oregon-3']),
      2:('Friday: canonical official Navy preview is now successfully archived, resolving the earlier .aspx 404 custody gap. It confirms recent Gutierrez production and the adverse Notre Dame defensive matchup. Retain +30.5 at neutral Gillette without changing the frozen margin.',
         'Notre Dame permits 67.3 rushing yards and 13.4 points per game in the official preview. Navy starter/backup and complete OL/D medical clearance still unconfirmed; performance listings are not clearance. Notre Dame has fourteen versus Navy seven days between kickoffs.', ['navy-preview-canonical']),
      3:('Friday: official Sun Belt initial report lists Southern Miss QB Ethan Hampton probable, OL Greg Nunnery out, Luke Rogers questionable and Jahmir Davis out for season. These constrain offense but are not numerical adjustments. Both market observations total 55.5; locked total remains 56.5.',
         'Initial report is not final clearance. Southern Miss has DB/ILB/DL absences; ULM DB Korian Wilson and RJ Hall and OLB Le\u0027kell McGowan out, DL Zyan Tremont and Tyrell Brown questionable. Defensive weakness can offset offensive constraints. Rain probability 16-33%, wind 5 mph; no weather deduction.', ['sunbelt-report','sunbelt-official-page-canonical','article-southern-miss-3']),
      4:('Friday: retain qualitative rank 4, confidence 1. New official Syracuse preview reiterates Angeli\u0027s Week 8 return (256 passing yards, two TDs) and Ahmad Miller\u0027s consecutive 120-plus rushing games. This is already-played information, not a new injury adjustment. Improved Syracuse defense is counterevidence to the offensive risk.',
         'Angeli return, SMU Jennings and productive SMU OL remain substantial Under risks. No final OL/D clearance; dome weather not applied. Neither the 8.669-point raw gap nor selected prior FAU/UNT errors calibrates this selection.', ['article-syracuse-7','article-smu-1','article-smu-2']),
      7:('Friday: retain alternative rank 7 and all frozen values. CSU official sources continue to describe quarterback/secondary and roster continuity concerns; Robinson health feature does not resolve defense. Logan rain probability 33-52%, sustained wind 3 mph.',
         'No verified final Hejny/backup, OL or secondary clearance; rain alone is insufficient to promote this Under. Separate market totals 63/63.5 do not replace locked 63.5.', ['article-colorado-state-1','article-colorado-state-4','article-colorado-state-6']),
      8:('Friday: retain alternative rank 8. Earlier three-QB usage, 204-yard, 1-for-14 third-down and eleven-punt evidence remains adverse. Official SJSU preview refreshed; forecast and +14.5 preserved.',
         'Definitive starter/backup and complete OL/defensive availability still not confirmed. Separate observations New Mexico -14.5/-15 are not contest-line corrections. Clear low-wind forecast does not repair offensive uncertainty.', ['article-san-jose-state-1']),
      9:('Friday: retain alternative rank 9. Official Iowa transcript still plans Hank Brown with Hecklinski possible, and confirms Moulton out for season. No newly verified reversal of those facts.',
         'QB rotation, RB loss and strong defenses keep the Over at confidence 1. Forecast rain 18-30%, wind 5 mph; no invented points adjustment or total replacement.', ['article-iowa-1','article-wisconsin-4']),
      10:('Friday: retain alternative rank 10. Mississippi State official statement confirms Kamario Taylor season-ending foot surgery. The frozen aggregate forecast is preserved for comparison.',
          'Backup effectiveness, starting plan and OL/defensive availability remain unresolved; the raw margin is not a healthy-current-QB assessment. No numeric correction is invented.', ['article-mississippi-state-5'])}
    for row in review['selections']:
        rank=row['owner_review_rank'];g=games[row['game_id']]
        if not g['pregame_context']:
            assert rank in (5,6)
            continue # Exact whole-row preservation, including rank, membership, timestamps and sources.
        support,risk,names=notes[rank]
        row.update(supporting_evidence=support,risk_and_exclusion_reason=risk,
          created_at_utc=stamp,supersedes=PREV.relative_to(ROOT).as_posix(),
          previous_review_rank=rank,previous_human_confidence=row['human_review_confidence_1_to_5'],confidence_adjustment=0)
        row['sources']+= [source(n) for n in names]
        row['weather']={'status':g['weather']['status'],'applicability':g['weather_applicability'],
          'hours':g['weather'].get('game_hours',[]),'gust_status':g['weather'].get('gust_status'),
          'field_condition':g['weather'].get('field_condition')}
        row['current_market_context_only']=g['current_quotes_context_only']
    review.update(version='week9-owner-review-20261030-friday-v4',created_at_utc=stamp,
       previous_review_path=PREV.relative_to(ROOT).as_posix(),context_capture=CAP.relative_to(ROOT).as_posix(),
       changes=['No rank, membership, frozen forecast, locked line or human confidence change.',
                'Troy rank 5 and FAU/UNT rank 6 are exact prior-row copies because kickoff has passed.',
                'New future-game personnel, weather and market evidence is separate from sealed outputs.'],
       decision_status='OWNER_APPROVAL_PENDING;THURSDAY_ROWS_FROZEN',status='SEPARATE_OWNER_REVIEW_NOT_MODEL_OUTPUT')
    write(OUT/'owner_review_shortlist.json',review)
    market=next(x for x in manifest['records'] if x['name']=='cfbd-current-week9-lines')
    obs=[]
    for g in board['games']:
        if not g['pregame_context']: continue
        for q in g['current_quotes_context_only']:
            obs.append({'game_id':g['game_id'],'away':g['away'],'home':g['home'],'provider':q['provider'],
              'requested_at_utc':market['requested_at_utc'],'received_at_utc':market['received_at_utc'],
              'kickoff_utc':g['kickoff_utc'],'observed_home_spread':q['spread'],'observed_total':q['overUnder'],
              'locked_home_spread':g['locked_home_spread'],'locked_total':g['locked_total'],
              'provider_quote_timestamp':None,'quote_freshness':'UNKNOWN_PROVIDER_TIMESTAMP_NOT_SUPPLIED',
              'pregame_receipt_qualified':True,'closing_line_qualified':False,'raw_sha256':market['sha256'],'source_url':market['url']})
    write(CAP/'market-observations.json',{'status':'TIMESTAMPED_PREGAME_OBSERVATIONS_NOT_CLOSING_LINES',
      'received_at_utc':market['received_at_utc'],'games':len({x['game_id'] for x in obs}),
      'excluded_started_game_ids':[g['game_id'] for g in board['games'] if not g['pregame_context']], 'observations':obs})
    sb=json.loads(gzip.decompress((CAP/'supplement/sunbelt-report.gz').read_bytes()))
    write(CAP/'supplement/southern-miss-ulm-qualified-report.json',{'source':source('sunbelt-report'),
      'game':next(g for g in sb['games'] if g['gameId']=='2026-10-31-ULM-Southern Miss'),
      'usage':'Initial availability only; future game; no numeric adjustment; Thursday reports not consulted'})
    lines=['# Friday owner review — approval PENDING','',f'Created {stamp}.',
      'All ten ranks and human confidence values remain unchanged. Human confidence is ordinal judgment, not a validated probability.',
      'Troy and FAU/UNT rows are exact copies of the October 29 morning decision; no later recommendation is backdated.',
      'The October 29 21:33 UTC capture exists, but no completed final Thursday owner-review revision was saved before kickoff. Preserve it as captured evidence, not an invented decision.',
      '', '| Rank | Selection / locked line | Frozen home margin or total | Human C | Status |', '|---|---|---:|---:|---|']
    for r in review['selections']:
        label=(r['selection']+' '+str(r['locked_line'])) if r['market']=='ATS' else r['away']+'–'+r['home']+' '+r['selection']+' '+str(r['locked_line'])
        lines.append(f"| {r['owner_review_rank']} | {label} | {r['frozen_projection_home_margin_or_total']:.6f} | {r['human_review_confidence_1_to_5']} | {'FROZEN_STARTED' if r['owner_review_rank'] in (5,6) else 'UPCOMING'} |")
    for r in review['selections']:
        lines.extend(['',f"## Rank {r['owner_review_rank']}",'',r['supporting_evidence'],'',r['risk_and_exclusion_reason']])
    lines.extend(['','## Additional monitoring','',
      'Texas State official October 29 preview confirms the prior 20-17 Utah State win included a 100-yard kick-return TD. The low score alone is not proof of slower pace or improved offensive efficiency. No new verified possession-rate statistic was recovered; prior Week 7 forecasting concerns remain. Boise official initial report lists OL Carson Rasmussen out; WR Ben Ford, RB Sire Gaines and TE Austin Terry questionable. No invented point adjustment.',
      'Travel/rest proxies retain the sealed schedule. American availability page was archived through its canonical URL, but the dynamic report was not verified. Final backup/OL/D availability remains incomplete. Four .aspx HTTP 404 attempts are retained; extensionless official pages succeeded. A local text inspection first failed under CP1252 and was rerun successfully with UTF-8; no evidence was altered.',
      '50 upcoming games have weather coverage; four elapsed games are skipped. Separate observed prices have receipt timestamps but no provider quote timestamp; they are not closing lines. Historical CLV stays INCOMPLETE.',
      'No schema, application code, model or policy changes. No new tests or changed expectations; existing seal/context/owner-review checks are run separately. Rollback is to ignore this additive review, retaining it for custody; never rewrite earlier versions.',
      'CI on the unchanged delivery heads failed on GitHub. This new local evidence is not claimed to have passed independent CI. No push is performed after the CI stop condition, because it would trigger another run.'])
    with (OUT/'OWNER_REVIEW.md').open('x',encoding='utf-8',newline='\n') as f:f.write('\n'.join(lines)+'\n')
    write(OUT/'review-custody.json',{'created_at_utc':stamp,'owner_approval':'PENDING',
      'previous_review_path':PREV.relative_to(ROOT).as_posix(),'previous_review_sha256':sha(PREV),
      'output_sha256':{n:sha(OUT/n) for n in ['OWNER_REVIEW.md','owner_review_shortlist.json']},
      'context_manifest_sha256':sha(CAP/'capture-manifest.json'),
      'started_rows_exactly_preserved':[5,6], 'model_adjustments':0})
    print(json.dumps({'review':str(OUT),'market_games':len({x['game_id'] for x in obs}),'observations':len(obs)}))

if __name__=='__main__':main()
