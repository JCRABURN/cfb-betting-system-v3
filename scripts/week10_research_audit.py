"""Score all seven sealed candidates. No fitting, tuning or new predictions."""
import gzip
import math
from fractions import Fraction
from scripts.week10_audit_sources import ROOT, BOARD, read_json, read_csv, sha, instant, unique
from scripts.week10_research_metrics import top5, summarize

FOLDER=ROOT/'outputs/2026-week10-postgame-evidence/research-pr50-original'
HOLDOUT_SHA='592b564798c434846ce169728aa3d0a4fd1b112d5397e587d40703ce2e58c23c'
PRIMARY=['FROZEN_V28:ATS','FROZEN_V28:COMBINED','CONTROLLED_LOGIT:COMBINED']


def read_original(suffix):
    custody=read_json(FOLDER/'custody.json')
    rows=[r for r in custody['records'] if r['source_path'].endswith(suffix)]
    if len(rows)!=1:raise ValueError('research source identity')
    record=rows[0];stored=(FOLDER/record['path']).read_bytes();raw=gzip.decompress(stored)
    if sha(raw)!=record['raw_sha256'] or sha(stored)!=record['stored_sha256']:raise ValueError('research original bytes')
    return raw


def frozen():
    import json
    raw=read_original('holdout/20261106-v1/prospective.json')
    if sha(raw)!=HOLDOUT_SHA:raise ValueError('original holdout seal identity')
    held=json.loads(raw);protocol=json.loads(read_original('protocol.json'))
    if sha(read_original('protocol.json'))!=held['protocol_sha256']:raise ValueError('original protocol identity')
    seal=json.loads(read_original('holdout/20261106-v1/seal.json'))
    if seal['sha256']!=HOLDOUT_SHA or seal['generated_at_utc']!=held['generated_at_utc']:raise ValueError('research seal contradiction')
    if held['owner_approval']!='PENDING' or held['policy_changed'] or held['status']!='PROSPECTIVE_RESEARCH_ONLY_NOT_CONTEST_REVISION':raise ValueError('research approval/policy contradiction')
    originals={}
    for market,name in [('ATS','ats'),('TOTAL','totals')]:
        originals.update({(r['game_id'],market):r for r in read_csv(BOARD/f'week10_{name}_full_card.csv')})
    expected={(gid,market,c) for gid,market in originals for c in protocol['candidates']}
    actual=[(r['game_id'],r['market'],r['candidate']) for r in held['selections']]
    if len(actual)!=798 or len(set(actual))!=len(actual) or set(actual)!=expected:raise ValueError('research exact coverage')
    for r in held['selections']:
        old=originals[r['game_id'],r['market']];ats=r['market']=='ATS'
        if r['actual'] is not None or instant(r['kickoff'])<=instant(held['generated_at_utc']):raise ValueError('research lookahead')
        if r['line']!=float(old['pick_spread' if ats else 'locked_total']) or r['forecast']!=float(old['projected_home_margin' if ats else 'projected_total']) or r['confidence']!=int(old['confidence']):raise ValueError('research original card changed')
        if r['market_forecast']!=(-float(old['locked_home_spread']) if ats else float(old['locked_total'])):raise ValueError('research line orientation')
        if not 0<r['probability']<1 or not math.isfinite(r['candidate_forecast']):raise ValueError('research numeric value')
    return held,protocol


def key(r):return r['game_id'],r['market'],r['candidate_sign']
def units(r):return Fraction(10,11) if r['candidate_result']=='WIN' else Fraction(-1) if r['candidate_result']=='LOSS' else Fraction(0)


def paired(left,right):
    a,b={key(r):r for r in left},{key(r):r for r in right};shared=set(a)&set(b)
    if len(a)!=len(left) or len(b)!=len(right):raise ValueError('duplicate selection')
    if any(a[k]['candidate_result']!=b[k]['candidate_result'] for k in shared):raise ValueError('shared selection grade conflict')
    describe=lambda r:{k:r[k] for k in ('game_id','market','candidate_sign','candidate_result','away','home','line')}
    gain=sum(map(units,left))-sum(map(units,right))
    game_contributions={gid:sum(units(r) for r in left if r['game_id']==gid)-sum(units(r) for r in right if r['game_id']==gid) for gid in {r['game_id'] for r in left+right}}
    return dict(shared=[describe(a[k]) for k in sorted(shared)],added=[describe(a[k]) for k in sorted(set(a)-shared)],removed=[describe(b[k]) for k in sorted(set(b)-shared)],
                unit_difference=float(gain),unit_difference_exact=str(gain),same_membership=not(set(a)^set(b)),
                exact_market_side_jaccard=len(shared)/len(set(a)|set(b)),
                leave_one_game_out_gain_range=[float(min(gain-v for v in game_contributions.values())),float(max(gain-v for v in game_contributions.values()))],
                inference='Descriptive one-week paired exposure accounting, not an independent-week confidence interval or validation. Shared picks cancel; no return benefit from reshuffling their ranks.')


def analyze(finals):
    import json
    held,protocol=frozen();lookup=unique(finals);rows=[]
    if set(lookup)!={r['game_id'] for r in held['selections']}:raise ValueError('research final coverage')
    label=lambda x:'WIN' if x>0 else 'LOSS' if x<0 else 'PUSH'
    for old in held['selections']:
        f=lookup[old['game_id']];actual=f['home_score']-f['away_score'] if old['market']=='ATS' else f['home_score']+f['away_score']
        error=actual-old['market_forecast'];cover=error*old['candidate_sign']
        rows.append(dict(old,actual=actual,result=label(error*old['sign']),candidate_cover=cover if old['candidate_sign'] else None,candidate_result=label(cover) if old['candidate_sign'] else None))
    groups={candidate+':'+scope:top5([r for r in rows if r['candidate']==candidate],scope) for candidate in protocol['candidates'] for scope in ('ATS','TOTAL','COMBINED')}
    selections=[dict(cohort=name,cohort_rank=i+1,**r) for name,group in groups.items() for i,r in enumerate(group)]
    full=[dict(market=market,candidate=candidate,**summarize([r for r in rows if r['market']==market and r['candidate']==candidate],protocol['probability_bins'])) for market in protocol['markets'] for candidate in protocol['candidates']]
    cohorts=[dict(cohort=name,**summarize(group,protocol['probability_bins'])) for name,group in groups.items()]
    previous=json.loads(read_original('results/v1/results.json'));weekly=[]
    for name in PRIMARY:
        candidate,scope=name.split(':');prior=next(r for r in previous['top5'] if r['candidate']==candidate and r['scope']==scope)
        for week in protocol['evaluation_weeks']:
            picks=[r for r in prior['selections'] if r['week']==week];w=sum(r['result']=='WIN' for r in picks);l=sum(r['result']=='LOSS' for r in picks)
            weekly.append(dict(cohort=name,week=week,n=len(picks),wins=w,losses=l,units=float(Fraction(w*10,11)-l),status='RETROSPECTIVE_CHRONOLOGICAL_RESEARCH'))
        m=next(r for r in cohorts if r['cohort']==name);weekly.append(dict(cohort=name,week=10,n=m['n'],wins=m['wins'],losses=m['losses'],units=m['units_minus110'],status='PREKICKOFF_SEALED_PROSPECTIVE_SHADOW'))
    return dict(status='RESEARCH_ONLY_NO_POLICY_PROMOTION',holdout_sha256=HOLDOUT_SHA,generated_at_utc=held['generated_at_utc'],source_commit=held['source_commit'],
                protocol=protocol,full_card=full,cohorts=cohorts,all_candidate_rows=rows,cohort_selections=selections,
                primary_paired=[dict(left=PRIMARY[i],right=PRIMARY[j],**paired(groups[PRIMARY[i]],groups[PRIMARY[j]])) for i,j in [(2,0),(2,1),(0,1)]],
                week_by_week_primary=weekly,historical_full_card_folds=previous['folds'],
                prior_only_stability=json.loads(read_original('UNCOMMITTED_NOV6_REPORTING_ADDENDUM/prior-only-stability.json')),
                reporting_addendum=json.loads(read_original('UNCOMMITTED_NOV6_REPORTING_ADDENDUM/evaluation-plan.json')),
                prospective_weeks=1,prospective_selections_per_top5=5,policy_gate_passed=False,
                reasons=['Only 1 prospective week versus minimum 20; 5 picks versus minimum 100; fewer than 2 seasons','No Confidence3/4/5 evidence thresholds satisfied','No independent model-policy approval'],
                caveat='All seven candidates retained, including failures. Late Nov6 reporting addendum follows Thursday kickoffs and is not claimed as original preregistration. Original protocol/798 predictions predate all kickoffs. Historical Weeks6–9 results remain retrospective research. Wilson intervals ignore within-week/team dependence; one week cannot support a reliable cluster interval.')
