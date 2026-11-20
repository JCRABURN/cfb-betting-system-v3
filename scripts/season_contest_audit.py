"""Read-only reconciliation of recovered contest exports, not prediction inputs.

Week 11 external-origin submissions are preserved without grading or comparison.
The confirmed v3 submitted-performance population is Weeks 1--10, 50 selections.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

from ingestion import CanonicalTeamResolver
from scripts.week10_audit_sources import read_csv, unique, load_response, nonnegative_score, instant
from scripts.week11_audit_inputs import ROOT, sha

SOURCE = ROOT / 'data/ingest/2026-season-splashsports-recovery'
CAPTURE = ROOT / 'outputs/2026-season-contest-evidence/20261116-v1'
EXPECTED = {1:43,2:49,3:57,4:58,5:56,6:58,7:59,8:56,9:56,10:62,11:67}


def number(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError('Nonfinite contest number')
    return result


def sources():
    raw_manifest = (SOURCE/'manifest.json').read_bytes().replace(b'\r\n',b'\n')
    if sha(raw_manifest) != '81eae1d8e529a1a394730f1fc3250dbf96d422f821673886ebf3d6a2d1b08354':
        raise ValueError('PR54 export manifest custody mismatch')
    manifest = json.loads(raw_manifest)
    for name, digest in manifest['outputs'].items():
        # PR54 text blobs use LF; Git's Windows checkout adds CRLF. Verify
        # exactly that documented text conversion, never strip other whitespace.
        if sha((SOURCE/name).read_bytes().replace(b'\r\n',b'\n')) != digest:
            raise ValueError('Export custody mismatch: '+name)
    lines = read_csv(SOURCE/'2026-splashsports-all-contest-lines.csv')
    picks = read_csv(SOURCE/'2026-splashsports-submitted-picks.csv')
    validate_sources(lines,picks)
    return manifest,lines,picks


def validate_sources(lines,picks):
    if Counter(int(r['week']) for r in lines) != EXPECTED:
        raise ValueError('Exact 621-game weekly coverage required')
    key=lambda r:(int(r['week']),int(r['source_order']))
    index={key(r):r for r in lines}
    if len(index)!=len(lines) or len({key(r) for r in picks})!=55 or len(picks)!=55:
        raise ValueError('Duplicate or missing source identity')
    if {key(r) for r in lines if r['selected_market']}!={key(r) for r in picks}:
        raise ValueError('Selection markers disagree')
    for r in lines:
        if number(r['away_spread'])!=-number(r['home_spread']) or number(r['total'])<=0:
            raise ValueError('Invalid line pair')
        if not r['pdf'] or int(r['page'])<1:
            raise ValueError('Missing PDF provenance')
    for week in range(1,12):
        if sorted(int(r['contest_weight']) for r in picks if int(r['week'])==week)!=list(range(1,6)):
            raise ValueError('Each week requires weights 1 through 5')
    for p in picks:
        if p!=index[key(p)]:
            raise ValueError('Pick differs from full PDF export row')
        if p['selected_market']=='ATS':
            side=p['selected_side'].lower()
            if side not in ('home','away') or p['selected_pick']!=p[side+'_team'] or number(p['selected_line'])!=number(p[side+'_spread']):
                raise ValueError('ATS selection/line mismatch')
        elif p['selected_market']=='TOTAL':
            if p['selected_side'] not in ('OVER','UNDER') or p['selected_pick']!=p['selected_side'] or number(p['selected_line'])!=number(p['total']):
                raise ValueError('Totals selection/line mismatch')
        else:
            raise ValueError('Unsupported market')


def capture():
    manifest=json.loads((CAPTURE/'capture-manifest.json').read_bytes())
    records=unique(manifest['records'],'name')
    if set(records)!={f'{p}-week{w}' for w in range(1,12) for p in ('cfbd','espn')} or manifest['failures']:
        raise ValueError('Provider capture coverage')
    return records,{k:load_response(CAPTURE,v) for k,v in records.items()}


def reconcile(lines,records,data):
    games=[g for w in range(1,12) for g in data[f'cfbd-week{w}']]
    resolver=CanonicalTeamResolver({g[s+'Team'] for g in games for s in ('home','away')})
    index=defaultdict(list)
    for week in range(1,12):
        unique(data[f'cfbd-week{week}'],'id')
        for g in data[f'cfbd-week{week}']:
            k=(week,g['awayTeam'],g['homeTeam'])
            index[k].append(g)
    events={w:unique(data[f'espn-week{w}']['events'],'id') for w in range(1,12)}
    result=[]
    for r in lines:
        week=int(r['week']); names={}
        for side in ('away','home'):
            resolution=resolver.resolve('SplashSports',r[side+'_team'])
            if resolution.status!='resolved':raise ValueError('Unresolved team: '+r[side+'_team'])
            names[side]=resolution.canonical_name
        matches=index.get((week,names['away'],names['home']),[])
        if len(matches)!=1:raise ValueError('No unique provider matchup: '+str(names))
        g=matches[0]
        if g['week']!=week or g['season']!=2026 or g['seasonType']!='regular' or g['completed'] is not True:
            raise ValueError('Provider final identity mismatch')
        gid=str(g['id']); e=events[week].get(gid)
        if not e or e['season']['year']!=2026 or e['week']['number']!=week or len(e['competitions'])!=1:
            raise ValueError('ESPN identity/coverage mismatch: '+gid)
        c=e['competitions'][0]
        if c['status']['type']['completed'] is not True:raise ValueError('ESPN not final')
        sides=unique(c['competitors'],'homeAway')
        if set(sides)!={'home','away'}:raise ValueError('Provider orientation mismatch')
        for side in ('home','away'):
            if str(sides[side]['team']['id'])!=str(g[side+'Id']):raise ValueError('Provider team ID mismatch')
            if nonnegative_score(sides[side]['score'])!=nonnegative_score(g[side+'Points']):raise ValueError('Provider score conflict')
        rec=records[f'cfbd-week{week}']; er=records[f'espn-week{week}']
        if min(instant(rec['requested_at_utc']),instant(er['requested_at_utc']))<=instant(g['startDate']):
            raise ValueError('Postgame retrieval must follow kickoff')
        result.append(dict(week=week,source_order=int(r['source_order']),game_id=gid,
            away=names['away'],home=names['home'],away_id=g['awayId'],home_id=g['homeId'],
            away_score=g['awayPoints'],home_score=g['homePoints'],neutral_site=g['neutralSite'],
            provider_kickoff_utc=g['startDate'],export_date=r['game_date'],export_kickoff_display=r['kickoff_display'],
            pdf=r['pdf'],page=int(r['page']),raw_away=r['away_team'],raw_home=r['home_team'],
            export_home_spread=float(number(r['home_spread'])),export_total=float(number(r['total'])),
            final_status='FINAL_BOTH_PROVIDERS',cfbd_game_id=g['id'],espn_game_id=e['id'],
            cfbd_source=rec['resolved_url'],espn_source=er['resolved_url'],
            cfbd_sha256=rec['raw_sha256'],espn_sha256=er['raw_sha256'],
            cfbd_retrieved_at=rec['received_at_utc'],espn_retrieved_at=er['received_at_utc']))
    if len({(r['week'],r['game_id']) for r in result})!=621:raise ValueError('Reconciled game duplication')
    return result,resolver


def grade(market,side,line,home,away):
    line=number(line); home=nonnegative_score(home); away=nonnegative_score(away)
    if market=='ATS' and side in ('HOME','AWAY'):
        margin=number(home-away)*(1 if side=='HOME' else -1)+line
    elif market=='TOTAL' and side in ('OVER','UNDER'):
        margin=(number(home+away)-line)*(1 if side=='OVER' else -1)
    else:raise ValueError('Invalid grading direction')
    result='WIN' if margin>0 else 'LOSS' if margin<0 else 'PUSH'
    units=Fraction(10,11) if result=='WIN' else Fraction(-1) if result=='LOSS' else Fraction(0)
    return dict(grading_margin=float(margin),result=result,units_minus110=float(units),units_exact=str(units))


def submitted(picks,finals,manifest):
    lookup={(r['week'],r['source_order']):r for r in finals}
    pdfs={r['week']:r for r in manifest['weeks']}
    ledger=[];excluded=[]
    for p in picks:
        week=int(p['week']); f=lookup[week,int(p['source_order'])]
        if week==11:
            excluded.append(dict(p,status='EXTERNAL_ORIGIN_EXCLUDED_FROM_V3_PERFORMANCE',
                                 grading_status='NOT_GRADED_OR_COMPARED_PER_OWNER_SCOPE',pdf_sha256=pdfs[week]['sha256']))
            continue
        selection=f[p['selected_side'].lower()] if p['selected_market']=='ATS' else p['selected_side']
        row=dict(f,market=p['selected_market'],selection=selection,selected_side=p['selected_side'],
                 contest_line=float(number(p['selected_line'])),contest_weight=int(p['contest_weight']),
                 origin='PROJECT_MODEL_OWNER_ATTESTED',pdf_sha256=pdfs[week]['sha256'],
                 export_print_date=manifest['print_date'],forecast_timestamp=None,model_confidence=None)
        row.update(grade(row['market'],row['selected_side'],row['contest_line'],f['home_score'],f['away_score']))
        row['weighted_points']=row['contest_weight'] if row['result']=='WIN' else 0
        row['push_scoring']='NO_PUSHES_IN_ACTUAL_SAMPLE; hypothetical push points not inferred'
        ledger.append(row)
    return sorted(ledger,key=lambda r:(r['week'],-r['contest_weight'])),excluded


def metrics(rows):
    c=Counter(r['result'] for r in rows); n=len(rows); decided=c['WIN']+c['LOSS']
    units=sum((Fraction(r['units_exact']) for r in rows),Fraction(0))
    return dict(n=n,wins=c['WIN'],losses=c['LOSS'],pushes=c['PUSH'],
                hit_rate=c['WIN']/decided if decided else None,units_minus110=float(units),units_exact=str(units),
                roi=float(units)/n if n else None,weighted_points=sum(r.get('weighted_points',0) for r in rows),
                possible_points=sum(r.get('contest_weight',0) for r in rows))


def recommendations(finals,resolver,modern,current_groups):
    """Original cohorts stay distinct; no cross-cohort sum is model performance."""
    final={(r['week'],r['game_id']):r for r in finals}; result=[]
    def add(week,cohort,market,gid,pick,line,path,rank=None,qualification='ORIGINAL_ARCHIVED_COHORT'):
        gid=str(gid); f=final.get((week,gid))
        if f is None:raise ValueError(f'Recommendation has no reconciled final: {week}/{gid}/{cohort}')
        if market=='TOTAL': selection=pick.upper(); side=selection
        else:
            res=resolver.resolve('SplashSports',pick)
            if res.status!='resolved':raise ValueError('Unresolved recommendation: '+pick)
            selection=res.canonical_name
            if selection not in (f['home'],f['away']):raise ValueError('Recommendation not in matchup')
            side='HOME' if selection==f['home'] else 'AWAY'
        row=dict(week=week,cohort=cohort,market=market,game_id=gid,selection=selection,
                 recommendation_line=float(number(line)),cohort_rank=rank,source_path=path,qualification=qualification)
        row.update(grade(market,side,line,f['home_score'],f['away_score']))
        result.append(row)
    from scripts.research_week7_acceptance import load_earlier
    for r in load_earlier():
        away,home=[resolver.resolve('SplashSports',s).canonical_name for s in r.game.split(' @ ')]
        mapped=[f for f in finals if (f['week'],f['away'],f['home'])==(r.week,away,home)]
        if len(mapped)!=1:raise ValueError('Early recommendation identity unresolved')
        gid=mapped[0]['game_id']
        add(r.week,'FROZEN_FULL_'+r.market,r.market,gid,r.selection,r.line,
            'outputs/2026-week7-acceptance-research/source-evidence',r.rank,r.provenance)
        if r.governed_top5:
            add(r.week,'GOVERNED_ATS_TOP5',r.market,gid,r.selection,r.line,
                'outputs/2026-week7-acceptance-research/source-evidence',qualification=r.provenance)
    for r in modern:
        w=int(r['week'])
        if w>10:continue
        add(w,'FROZEN_FULL_'+r['market'],r['market'],r['game_id'],r['selection'],r['locked_line'],
            f'outputs/2026-week{w}-postgame-audit',r['research_rank'])
        if w in (5,6):
            if str(r.get('governed_top5'))=='True':
                add(w,'GOVERNED_ATS_TOP5',r['market'],r['game_id'],r['selection'],r['locked_line'],f'outputs/2026-week{w}-postgame-audit')
            for n in (5,10):
                if int(r['research_rank'])<=n:
                    add(w,f'{r["market"]}_RESEARCH_TOP{n}',r['market'],r['game_id'],r['selection'],r['locked_line'],
                        f'outputs/2026-week{w}-postgame-audit',r['research_rank'],'PREGAME_FORECAST_RETROSPECTIVE_RANK')
    paths={7:'outputs/2026-week7-postgame-audit/week7_cohort_membership.csv',
           8:'outputs/2026-week8-postgame-audit/week8_cohort_membership.csv',
           9:'outputs/2026-week9-postgame-audit/v1/frozen_cohort_membership.csv',
           10:'outputs/2026-week10-postgame-audit/v2/frozen_cohort_membership.csv'}
    for w,path in paths.items():
        for r in read_csv(ROOT/path):
            if any(t in r['cohort'].lower() for t in ('remaining','11+','_full')):continue
            add(w,r['cohort'],r['market'],r['game_id'],r['selection'],r['locked_line'],path,r.get('cohort_rank'))
    for w,path in [(5,'outputs/2026-week5-review-20261001/week5_decision_shortlist.csv'),
                   (6,'outputs/2026-week6-execution-20261006T2133Z/week6_decision_shortlist.csv')]:
        for r in read_csv(ROOT/path):
            add(w,'AI_CONTEXTUAL_DECISION',r.get('market',r.get('market_type')),r['game_id'],r.get('pick',r.get('selection')),
                r.get('locked_splash_line',r.get('locked_line')),path,int(r.get('rank',r.get('decision_rank'))))
    path='outputs/2026-week6-execution-20261006T2133Z/week6_combined_top5.csv'
    for r in read_csv(ROOT/path):
        add(6,'ORIGINAL_COMBINED_RESEARCH_TOP5',r['market'],r['game_id'],r['pick'],r['locked_line'],path,int(r['rank']))
    path='outputs/2026-week7-acceptance-research/source-evidence/week2-pregame.json'
    pre=json.loads((ROOT/path).read_bytes())
    for r in pre['experimental_combined_top_five']['candidates']:
        detail=next(x for x in pre['totals_shadow']['full_ledger'] if x['game_id']==r['game_id'])
        away,home=[resolver.resolve('SplashSports',detail[s]).canonical_name for s in ('away','home')]
        f=next(f for f in finals if (f['week'],f['away'],f['home'])==(2,away,home))
        add(2,'ORIGINAL_COMBINED_RESEARCH_TOP5','TOTAL',f['game_id'],detail['selected_direction'],detail['locked_total'],path,r['rank'])
    for name,rows in current_groups.items():
        for i,r in enumerate(rows,1):
            add(11,name,r['market'],r['game_id'],r['selection'],r['locked_line'],
                'outputs/2026-week11-prospective and timestamped owner-review artifacts',i)
    keys=[(r['week'],r['cohort'],r['market'],r['game_id'],r['selection'],r['recommendation_line']) for r in result]
    if len(keys)!=len(set(keys)):raise ValueError('Duplicate recommendation within cohort')
    return result


def correspondence(ledger,recs):
    differences=[]; groups=defaultdict(list)
    for r in recs:
        if r['week']<=10:groups[r['week'],r['cohort']].append(r)
    same=lambda a,b:(a['game_id'],a['market'],a['selection'])==(b['game_id'],b['market'],b['selection'])
    for p in ledger:
        matches=[r for r in recs if r['week']==p['week'] and same(p,r)]
        p['exact_recommendation_cohorts']='; '.join(sorted(r['cohort'] for r in matches if r['recommendation_line']==p['contest_line']))
        p['line_different_cohorts']='; '.join(sorted(r['cohort'] for r in matches if r['recommendation_line']!=p['contest_line']))
        p['recommendation_custody']='NO_ORIGINAL_FULL_CARD_RECOVERED' if p['week']==4 else 'MATCHED' if matches else 'SUBMISSION_ONLY_NO_MATCHING_ARCHIVED_RECOMMENDATION'
    for (week,name),rows in sorted(groups.items()):
        actual=[p for p in ledger if p['week']==week]
        for r in rows:
            matches=[p for p in actual if same(p,r)]
            p=matches[0] if matches else None
            differences.append(dict(week=week,cohort=name,game_id=r['game_id'],market=r['market'],selection=r['selection'],
                recommendation_line=r['recommendation_line'],submitted_line=p['contest_line'] if p else None,
                status=('EXACT_MATCH' if p['contest_line']==r['recommendation_line'] else 'SAME_SELECTION_DIFFERENT_LINE') if p else 'RECOMMENDED_NOT_SUBMITTED',
                source_path=r['source_path']))
        for p in actual:
            if not any(same(p,r) for r in rows):
                differences.append(dict(week=week,cohort=name,game_id=p['game_id'],market=p['market'],selection=p['selection'],
                    recommendation_line=None,submitted_line=p['contest_line'],status='SUBMITTED_NOT_IN_COHORT',source_path=rows[0]['source_path']))
    return differences


def locks(finals,resolver,modern):
    index={(r['week'],r['away'],r['home']):r for r in finals}; rows=[]
    def add(week,away,home,spread,total,path,original_display=None):
        resolved=[]
        for name in (away,home):
            r=resolver.resolve('SplashSports',name)
            if r.status!='resolved':raise ValueError('Unresolved historical lock '+name)
            resolved.append(r.canonical_name)
        f=index.get((week,*resolved))
        if not f:
            rows.append(dict(week=week,away=resolved[0],home=resolved[1],source_path=path,status='HISTORICAL_MATCHUP_NOT_IN_EXPORT'))
            return
        hs=None if spread in ('',None) else float(number(spread)); t=None if total in ('',None) else float(number(total))
        rows.append(dict(week=week,game_id=f['game_id'],away=f['away'],home=f['home'],source_path=path,
                         frozen_home_spread=hs,export_home_spread=f['export_home_spread'],
                         frozen_total=t,export_total=f['export_total'],original_display=original_display,
                         export_display=f['export_date']+' '+f['export_kickoff_display'],
                         status='ORIGINAL_LINE_UNAVAILABLE' if hs is None or t is None else
                         'LINE_DIFFERENCE_PRESERVE_BOTH' if hs!=f['export_home_spread'] or t!=f['export_total'] else 'LINES_MATCH'))
    for p in sorted((ROOT/'production-weeks').glob('2026-week*-splashsports*.csv')):
        week=int(p.name.split('week')[1].split('-')[0])
        if week>11:continue
        for r in read_csv(p):
            add(week,r['Away Team'],r['Home Team'],r['Spread'],r.get('Total'),p.relative_to(ROOT).as_posix(),r.get('Game Date','')+' '+r.get('Game Time',''))
    # Original frozen prediction inputs, distinct from later contest exports.
    for r in modern:
        if r['market']=='ATS':
            totals=[t for t in modern if t['market']=='TOTAL' and t['week']==r['week'] and t['game_id']==r['game_id']]
            add(int(r['week']),r['away'],r['home'],r['locked_home_spread'],totals[0]['locked_line'] if totals else None,
                f'outputs/2026-week{r["week"]}-postgame-audit/frozen-prediction-inputs')
    from scripts.research_week7_acceptance import load_earlier
    earlier=load_earlier()
    for r in earlier:
        if r.market!='ATS':continue
        away,home=[resolver.resolve('SplashSports',s).canonical_name for s in r.game.split(' @ ')]
        f=next(f for f in finals if (f['week'],f['away'],f['home'])==(r.week,away,home))
        selected=resolver.resolve('SplashSports',r.selection).canonical_name
        total=next((t.line for t in earlier if t.week==r.week and t.game_id==r.game_id and t.market=='TOTAL'),None)
        add(r.week,f['away'],f['home'],r.line if selected==f['home'] else -r.line,total,
            'outputs/2026-week7-acceptance-research/source-evidence/early-frozen-inputs')
    return rows


def build(modern,current_groups):
    manifest,lines,picks=sources(); records,data=capture(); finals,resolver=reconcile(lines,records,data)
    ledger,excluded=submitted(picks,finals,manifest)
    recs=recommendations(finals,resolver,modern,current_groups)
    differences=correspondence(ledger,recs)
    lock_rows=locks(finals,resolver,modern)
    weekly=[]
    peak=0;max_drawdown=0
    for week in range(1,11):
        r=dict(week=week,**metrics([p for p in ledger if p['week']==week]))
        cumulative=metrics([p for p in ledger if p['week']<=week])
        peak=max(peak,cumulative['units_minus110']);max_drawdown=max(max_drawdown,peak-cumulative['units_minus110'])
        r.update({'cumulative_'+k:v for k,v in cumulative.items()})
        r['max_drawdown_units_week_end']=max_drawdown
        weekly.append(r)
    weights=[dict(contest_weight=w,**metrics([p for p in ledger if p['contest_weight']==w])) for w in range(1,6)]
    by_market=[dict(market=m,**metrics([p for p in ledger if p['market']==m])) for m in ('ATS','TOTAL')]
    cohorts=[dict(week=w,cohort=c,**metrics([r for r in recs if (r['week'],r['cohort'])==(w,c)])) for w,c in sorted({(r['week'],r['cohort']) for r in recs})]
    w4=metrics([r for r in ledger if r['week']==4])
    if (w4['wins'],w4['losses'],w4['weighted_points'])!=(3,2,8):raise ValueError('Week4 independent result disagrees')
    w7=[r for r in differences if r['week']==7 and r['cohort']=='owner_approved_five']
    if len(w7)!=5 or any(r['status']!='EXACT_MATCH' for r in w7):raise ValueError('Week7 corrected approval mismatch')
    w5=next(r for r in ledger if r['week']==5 and r['contest_weight']==1)
    if (w5['selection'],w5['contest_line'])!=('Texas Tech',-13.5):raise ValueError('Week5 fifth selection mismatch')
    if any(r['result']=='PUSH' for r in ledger):raise ValueError('Confirm actual contest push scoring before weighted report')
    schedule=[]
    from datetime import datetime
    source11=read_csv(ROOT/'production-weeks/2026-week11-splashsports.csv')
    for original in source11:
        a,h=[resolver.resolve('SplashSports',original[s+' Team']).canonical_name for s in ('Away','Home')]
        new=next(r for r in lines if r['week']=='11' and
                 resolver.resolve('SplashSports',r['away_team']).canonical_name==a and
                 resolver.resolve('SplashSports',r['home_team']).canonical_name==h)
        old=datetime.strptime(original['Game Date']+' '+original['Game Time'],'%Y-%m-%d %I:%M %p')
        fresh=datetime.strptime(new['game_date']+' '+new['kickoff_display'].split(' ',1)[1],'%Y-%m-%d %I:%M%p')
        if old!=fresh:schedule.append(dict(away=new['away_team'],home=new['home_team'],original_display=old.isoformat(),export_display=fresh.isoformat(),custody_effect='NONE_ORIGINAL_ELIGIBILITY_AND_SEAL_PRESERVED'))
    if len(schedule)!=9:raise ValueError('Week11 nine display differences required')
    return dict(finals=finals,ledger=ledger,excluded=excluded,weekly=weekly,weights=weights,by_market=by_market,
                total=metrics(ledger),recommendations=recs,cohorts=cohorts,differences=differences,locks=lock_rows,
                kickoff_differences=schedule,source_manifest=manifest,
                quality=dict(source_matchups=621,reconciled_matchups=621,export_selections=55,v3_graded_selections=50,
                             excluded_external_origin=5,score_conflicts=0,unresolved_matchups=0,duplicate_games=0,
                             week4_verified='3-2, 8/15; full-card forecasts missing',week7_verified='ALL_FIVE_EXACT_MATCHES',
                             original_pdf_binary_verification='NOT_AVAILABLE_LOCALLY; upstream manifest hashes preserved',
                             model_attribution='Owner confirmed later PR54 correction in this task; Weeks1-10 only',
                             source_print_date='2026-11-16; does not prove forecast timestamps'))
