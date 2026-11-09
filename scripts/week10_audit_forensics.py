"""Observed process and pregame feature limitations; no causal injury fabrication."""
import gzip
import json
import math
import random
from fractions import Fraction
from scripts.week10_audit_sources import ROOT, BOARD, read_json, read_csv, sha, instant, unique
from scripts.week10_audit_diagnostics import metrics, mean, rounded, historical_rows


def clv(finals):
    eligible=unique(finals);observations=[]
    for path in sorted((ROOT/'outputs/2026-week10-context').glob('*/capture-manifest.json')):
        manifest=read_json(path)
        for record in manifest['records']:
            if record['name']!='cfbd-current-week10-lines':continue
            raw=gzip.decompress((path.parent/record['path']).read_bytes())
            if sha(raw)!=record['sha256']:raise ValueError('market raw hash')
            for game in json.loads(raw):
                gid=str(game['id'])
                if gid not in eligible:continue
                for price in game['lines']:
                    if any(k in price for k in ('lastUpdated','timestamp','closingTimestamp','quoteTimestamp')):raise ValueError('new quote timestamps require explicit adjudication')
                    observations.append(dict(game_id=gid,provider=price['provider'],spread=price.get('spread'),total=price.get('overUnder'),
                        received_at_utc=record['received_at_utc'],pregame_receipt=instant(record['received_at_utc'])<instant(eligible[gid]['frozen_kickoff_utc']),
                        provider_quote_timestamp=None,qualified_close=False,source=path.relative_to(ROOT).as_posix(),raw_sha256=record['sha256']))
    return dict(status='INCOMPLETE',qualified_closes=0,observations=observations,
                reason='Pregame receipt is not a qualified final pre-kickoff quote. Archived CFBD price objects lack quote timestamps; postgame market labels excluded. No close reconstructed.',
                blocks_unrelated_integrity_merge=False)


def source_reconciliation():
    from scripts import prepare_week10_source as source
    metadata=read_json(ROOT/'production-weeks/2026-week10-splashsports-lock-metadata.json')
    core=BOARD/'core-initial';games=read_json(core/'games.raw.json');teams=read_json(core/'teams.raw.json')
    original=source.read_csv(source.SOURCE)
    upcoming,excluded,rows=source.reconcile(original,source.read_csv(source.REVIEW),games,source.resolver_for([t['school'] for t in teams]),instant(metadata['prepared_at_utc']))
    if (len(upcoming),len(excluded),len(rows))!=(57,5,62) or excluded!=metadata['excluded_completed_games']:raise ValueError('original62 reconciliation')
    for item in excluded:
        raw=original[item['source_csv_row']-2];item.update(away=raw['away_team'],home=raw['home_team'])
    return dict(original_matchups=62,all_original_spreads_and_totals_match=True,eligible_games=57,excluded=excluded,records=rows,
                evidence_boundary='The original 62-game screenshot source matches FBS-vs-FBS entries. It is not proof of complete contest coverage for FBS-vs-FCS games; no retrospective line or prediction is added for Merrimack-Wake Forest.')


def human_comparison(grades,members):
    lookup={(r['market'],r['game_id']):r for r in grades}
    original={(r['market'],r['game_id']) for r in members if r['cohort']=='ORIGINAL_COMBINED_RESEARCH_TOP5'}
    result=[]
    for name in sorted({r['cohort'] for r in members if r['cohort'].startswith('HUMAN_') and r['cohort'].endswith('_1-5')}):
        selected={(r['market'],r['game_id']) for r in members if r['cohort']==name}
        describe=lambda keys:[{k:r[k] for k in ('game_id','market','away','home','selection','locked_line','result')} for key in sorted(keys) for r in [lookup[key]]]
        unit=lambda keys:sum(Fraction(10,11) if lookup[k]['result']=='WIN' else Fraction(-1) if lookup[k]['result']=='LOSS' else Fraction(0) for k in keys)
        result.append(dict(cohort=name,shared=describe(original&selected),added=describe(selected-original),removed=describe(original-selected),
                           unit_difference=float(unit(selected)-unit(original)),unit_difference_exact=str(unit(selected)-unit(original)),owner_approval='NO_APPROVAL_ARTIFACT_IDENTIFIED'))
    return result


def analyze(grades,members,process,diagnostics):
    game_process=unique(process['games']);teams={}
    for row in process['teams']:teams.setdefault(row['game_id'],[]).append(row)
    passers={}
    for row in process['observed_passers']:passers.setdefault(row['game_id'],[]).append(row)
    raw=read_json(BOARD/'week10_raw_model_components.json');components=unique(raw['games'])
    prior=unique(read_json(BOARD/'core-initial/week9-advanced.raw.json'),'team')
    extremes=sorted(grades,key=lambda r:(-abs(float(r['forecast_error_actual_minus_predicted'])),r['market'],r['game_id']))
    failures=[]
    for row in extremes:
        gid=row['game_id'];p=game_process[gid]
        failures.append(dict(selection=row,process=p,observed_teams=teams[gid],observed_passers=passers[gid],
                             frozen_model_components=components[gid],
                             documented_mechanism='ATS uses a single cumulative EPA differential; totals uses four cumulative offense/defense EPA levels. Neither directly models possession count, explosives, QB/OL availability or game-specific defensive personnel.',
                             observed_explanation='Observed play/drive volume, efficiency and scoring breakdown quantify the miss; they do not establish a causal injury effect or make postgame information pregame knowledge.'))
    compression=[]
    for market in ('ATS','TOTAL'):
        group=[r for r in grades if r['market']==market]
        fields={'model':[float(r['raw_projection']) for r in group],'actual':[float(r['actual_model_target']) for r in group],
                'locked_line':[float(r['locked_line']) if market=='TOTAL' else -float(r['locked_home_spread']) for r in group]}
        compression.append(dict(market=market,n=len(group),distributions={name:dict(min=min(v),max=max(v),mean=mean(v),sd=math.sqrt(mean([(x-mean(v))**2 for x in v]))) for name,v in fields.items()}))
    pace=[]
    for row in process['teams']:
        p=prior[row['team']]['offense'];g=next(g for g in grades if g['game_id']==row['game_id'])
        old=components[row['game_id']]['raw_point_in_time_package'][row['location']+'_stats']
        pace.append(dict(game_id=row['game_id'],team=row['team'],prior_cumulative_offense_ppa=p['ppa'],actual_offense_ppa=row['ppa'],prior_success=p['successRate'],actual_success=row['success_rate'],prior_explosiveness=p['explosiveness'],actual_explosiveness=row['explosiveness'],
                         postgame_drives=row['provider_advanced_drives'],postgame_plays=row['provider_advanced_plays'],feature_cutoff=[old['as_of_season'],old['as_of_week']],postgame_features_used_for_prediction=False))
    # Week-cluster uncertainty for paired forecast errors; this is descriptive and retrospective.
    allrows=historical_rows()+grades;rng=random.Random(20261109);uncertainty=[]
    for market in ('ATS','TOTAL'):
        weekly={w:[] for w in range(5,11)}
        for r in allrows:
            if r['market']!=market:continue
            actual=float(r['actual_model_target']);baseline=float(r['locked_line']) if market=='TOTAL' else -float(r['locked_home_spread'])
            weekly[r['week']].append(abs(actual-float(r['raw_projection']))-abs(actual-baseline))
        draws=[]
        for _ in range(2000):
            sampled=rng.choices(sorted(weekly),k=6);draws.append(mean([x for w in sampled for x in weekly[w]]))
        draws.sort();uncertainty.append(dict(market=market,n=sum(map(len,weekly.values())),weeks=6,mean_model_minus_line_mae=mean([x for v in weekly.values() for x in v]),week_block95=[draws[49],draws[1949]],resamples=2000,seed=20261109,limitation='Only six weeks, repeated teams and one season. Descriptive error comparison; no causal or betting-profit proof.'))
    return dict(status='RESEARCH_ONLY',largest_five=failures[:5],all_failures=failures,forecast_distributions=compression,prior_vs_observed_team_efficiency=pace,
                human_value=human_comparison(grades,members),paired_forecast_uncertainty=uncertainty,
                personnel_limit='Pregame review documents and observed QB statistics are retained. Missing verified OL snap counts, participation changes and causal counterfactuals prevent attributing an exact point loss to injury. No injury adjustment is invented.',
                numeric_candidates=[
                    dict(name='Locked-line anchor',parameters='Predeclare model weights 0, 0.25 and 0.50; fit no weights on the evaluation week.',evidence='Frozen PR50 25%-model candidate and exact market baseline are scored separately.',requirements='Nested prior-week selection, then untouched future weeks; improve both MAE/RMSE and prospective Top5 return against ATS research baseline.'),
                    dict(name='Possessions and points per drive',parameters='Recent 3-game and season-to-date drive rates with predeclared 0.25/0.50 recent weights; possessions times opponent-adjusted points/drive.',evidence='Actual high-scoring misses include ordinary-volume but extreme-efficiency games, so a tempo-only correction is insufficient.',requirements='Archive genuine pregame drive/play data, QB/OL status and missingness; never backfill from target-game plays.'),
                    dict(name='Tail uncertainty and abstention research',parameters='80% and 90% prior-only conformal intervals, separate market residual scales; compare global versus predeclared line/tempo strata.',evidence='Week10 57-game error and archived-sigma coverage tables.',requirements='At least 100 calibration residuals per stratum; missing-data tags and fallback; retain mandatory contest picks separately from betting abstention.'),
                    dict(name='Confidence and ranking governance',parameters='Keep PR50 gates: 100 prospective Top5 picks, 20 weeks, 2 seasons; ECE <=0.03, Jaccard >=0.60 and positive paired return lower95.',evidence='Controlled combined Top5 failed to improve Week10 over frozen ATS research.',requirements='Confidence3:500 decisions/8weeks/p>=.55/LB>.52381; Confidence4:500/12/p>=.60/LB>.55; Confidence5:800/16/p>=.65/LB>.60. Owner approval/new version still required.')])
