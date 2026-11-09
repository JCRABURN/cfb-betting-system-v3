"""Transparent descriptive metrics and week-block uncertainty; no fitted thresholds."""
import itertools
import math
from collections import Counter
from scripts.week10_audit_diagnostics import mean

def select(rows, n=5, original=False):
    if not rows:return []
    ordered=sorted(rows,key=lambda r:r["rank"]) if len({r["market"] for r in rows})==1 and original else sorted(rows,key=lambda r:(-r["ranking_score"],r["market"],r["locked_line_id"],r["game_id"]))
    selected=[];seen=set()
    for row in ordered:
        if row["candidate_sign"]==0 or row["game_id"] in seen:continue
        selected.append(row);seen.add(row["game_id"])
        if len(selected)==n:break
    return selected


def wilson(w,n):
    if not n:return [None,None]
    z=1.959963984540054;p=w/n;den=1+z*z/n;center=(p+z*z/(2*n))/den
    radius=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [center-radius,center+radius]


def auc(scores,labels):
    wins=[s for s,y in zip(scores,labels) if y];losses=[s for s,y in zip(scores,labels) if not y]
    if not wins or not losses:return None
    # Ties count half; no dependence on library sorting or iteration order.
    counts=Counter(losses);values=sorted(counts);below={};running=0
    for value in values:below[value]=running;running+=counts[value]
    import bisect
    cumulative=[0]
    for value in values:cumulative.append(cumulative[-1]+counts[value])
    return math.fsum(cumulative[bisect.bisect_left(values,s)]+.5*counts.get(s,0) for s in wins)/(len(wins)*len(losses))


def percentile(values,q):
    ordered=sorted(values);position=(len(ordered)-1)*q;lower=math.floor(position);upper=math.ceil(position)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)


def summarize(rows,bins):
    counts=Counter(r['candidate_result'] for r in rows);w,l,p=(counts[s] for s in ('WIN','LOSS','PUSH'))
    units=w*10/11-l
    errors=[r['actual']-r['candidate_forecast'] for r in rows if r['actual'] is not None]
    # A neutral line forecast has no bet; its .5 probability is evaluated only on
    # the existing frozen selections and explicitly kept separate from bet return.
    decided=[r for r in rows if (r['candidate_result'] or r['result']) in ('WIN','LOSS')]
    labels=[int((r['candidate_result'] or r['result'])=='WIN') for r in decided];probs=[r['probability'] for r in decided]
    reliability=[]
    for lower,upper in zip(bins,bins[1:]):
        indices=[i for i,p in enumerate(probs) if lower<=p<upper or upper==1 and p==1]
        if not indices:continue
        observed=mean([labels[i] for i in indices]);predicted=mean([probs[i] for i in indices])
        reliability.append(dict(lower=lower,upper=upper,n=len(indices),mean_probability=predicted,hit_rate=observed,wilson95=wilson(sum(labels[i] for i in indices),len(indices))))
    mixed=len({r['market'] for r in rows})>1
    return dict(n=len(rows),bets=w+l+p,wins=w,losses=l,pushes=p,hit_rate=w/(w+l) if w+l else None,wilson95=wilson(w,w+l),
                units_minus110=units,roi=units/(w+l+p) if w+l+p else None,
                mae=mean([abs(e) for e in errors]) if errors and not mixed else None,
                rmse=math.sqrt(mean([e*e for e in errors])) if errors and not mixed else None,
                bias_actual_minus_forecast=mean(errors) if errors and not mixed else None,
                auc=auc(probs,labels),brier=mean([(p-y)**2 for p,y in zip(probs,labels)]) if labels else None,
                log_loss=mean([-math.log(p if y else 1-p) for p,y in zip(probs,labels)]) if labels else None,
                ece=math.fsum(x['n']*abs(x['mean_probability']-x['hit_rate']) for x in reliability)/len(labels) if labels else None,
                reliability=reliability,
                interval_coverage={q:mean([int(abs(r['actual']-r['candidate_forecast'])<=r['interval_radii'][q]) for r in rows]) for q in ('0.8','0.9')} if rows and not mixed else None,
                mean_interval_width={q:mean([2*r['interval_radii'][q] for r in rows]) for q in ('0.8','0.9')} if rows and not mixed else None)


def top5(rows,scope):
    group=rows if scope=='COMBINED' else [r for r in rows if r['market']==scope]
    return select(group,original=bool(group and group[0]['candidate'] in ('FROZEN_V28','FIXED_25_PERCENT_MODEL')))


def week_block_ci(rows,field):
    """Exact resampling of the four evaluation-week clusters, not iid games."""
    weeks=sorted({r['week'] for r in rows}); groups={w:[r for r in rows if r['week']==w] for w in weeks}; values=[]
    for chosen in itertools.product(weeks,repeat=len(weeks)):
        sample=[r for w in chosen for r in groups[w]]
        if field=='auc':
            decided=[r for r in sample if (r['candidate_result'] or r['result'])!='PUSH']
            value=auc([r['probability'] for r in decided],[int((r['candidate_result'] or r['result'])=='WIN') for r in decided])
        else:value=mean([r[field] for r in sample])
        if value is not None:values.append(value)
    return [percentile(values,.025),percentile(values,.975)]


def paired_week_gain(candidate,baseline):
    weeks=sorted(candidate); differences={w:candidate[w]-baseline[w] for w in weeks}
    distribution=[math.fsum(differences[w] for w in draw) for draw in itertools.product(weeks,repeat=len(weeks))]
    return dict(weekly_unit_differences=differences,total_unit_difference=math.fsum(differences.values()),
                paired_week_block95=[percentile(distribution,.025),percentile(distribution,.975)],clusters=len(weeks),
                warning='Four observed weeks; repeated teams and season effects remain. This is not confirmation of prospective profitability.')
