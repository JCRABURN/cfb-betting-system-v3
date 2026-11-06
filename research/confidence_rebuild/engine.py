"""Small deterministic estimators, fitted exclusively on earlier-week observations.

No imports of production modules, database access, provider calls, or policy writes.
"""
import math


def mean(values):return math.fsum(values)/len(values)
def dot(a,b):return math.fsum(x*y for x,y in zip(a,b))
def clip(x,lo,hi):return max(lo,min(hi,x))


def solve(matrix, target):
    a=[list(row)+[value] for row,value in zip(matrix,target)];n=len(a)
    for j in range(n):
        pivot=max(range(j,n),key=lambda i:abs(a[i][j]));a[j],a[pivot]=a[pivot],a[j]
        if abs(a[j][j])<1e-12:raise ValueError('singular research design')
        divisor=a[j][j];a[j]=[v/divisor for v in a[j]]
        for i in range(n):
            if i!=j:
                factor=a[i][j];a[i]=[x-factor*y for x,y in zip(a[i],a[j])]
    return [row[-1] for row in a]


class Design:
    def __init__(self, rows):
        columns=list(zip(*rows));self.means=[mean(c) for c in columns]
        self.scales=[math.sqrt(mean([(v-m)**2 for v in c])) for c,m in zip(columns,self.means)]
        self.constant=[s<1e-10 for s in self.scales]
        self.scales=[1 if c else s for c,s in zip(self.constant,self.scales)]
    def transform(self,row):return [1]+[(v-m)/s if not c else 0 for v,m,s,c in zip(row,self.means,self.scales,self.constant)]


class Ridge:
    def __init__(self, features, target, penalty):
        self.design=Design(features);x=[self.design.transform(r) for r in features];n=len(x[0])
        self.matrix=[[math.fsum(row[j]*row[k] for row in x)+(penalty if j==k and j else 0) for k in range(n)] for j in range(n)]
        self.coef=solve(self.matrix,[math.fsum(row[j]*y for row,y in zip(x,target)) for j in range(n)])
        fitted=[dot(self.coef,row) for row in x]
        self.loo=[y-(y-p)/max(1e-6,1-dot(row,solve(self.matrix,row))) for row,y,p in zip(x,target,fitted)]
    def predict(self,row):return dot(self.coef,self.design.transform(row))


def sigmoid(x):return 1/(1+math.exp(-clip(x,-30,30)))


class Logistic:
    def __init__(self, features, labels, penalty, iterations):
        self.design=Design(features);x=[self.design.transform(r) for r in features];n=len(x[0]);self.coef=[0.0]*n
        self.coef[0]=math.log((sum(labels)+1)/(len(labels)-sum(labels)+1))
        for _ in range(iterations):
            p=[sigmoid(dot(self.coef,row)) for row in x]
            gradient=[math.fsum(row[j]*(y-q) for row,y,q in zip(x,labels,p))-(penalty*self.coef[j] if j else 0) for j in range(n)]
            hessian=[[math.fsum(row[j]*row[k]*q*(1-q) for row,q in zip(x,p))+(penalty if j==k and j else 1e-7 if j==k else 0) for k in range(n)] for j in range(n)]
            step=solve(hessian,gradient)
            self.coef=[b+clip(s,-2,2) for b,s in zip(self.coef,step)]
    def predict(self,row):return sigmoid(dot(self.coef,self.design.transform(row)))


def uncertainty_features(r):
    f=r['features'];return [abs(r['market_forecast']),r['edge'],f['plays_per_drive'],f['off_success'],f['def_explosiveness']]


def residual_features(r):
    f=r['features'];return [r['forecast']-r['market_forecast'],r['market_forecast'],f['off_success'],f['def_success'],f['plays_per_drive'],f['rush_rate'],f['off_explosiveness'],f['def_explosiveness']]


def classifier_features(r,sigma,controlled):
    values=[r['edge']/sigma]
    if controlled:values += [math.log(sigma),abs(r['market_forecast']),r['sign']]
    return values


def quantile(values,coverage):
    ordered=sorted(values);index=min(len(ordered)-1,math.ceil((len(ordered)+1)*coverage)-1)
    return ordered[index]


class Fit:
    def __init__(self, train, target_week, protocol):
        if not train or any(r['week']>=target_week or r['actual'] is None or r['source_stats_through_week']>=r['week'] for r in train):
            raise ValueError('future, missing outcome, or contaminated training input')
        if len({r['market'] for r in train})!=1:raise ValueError('markets require separate fits')
        self.train=train;self.target_week=target_week;self.p=protocol
        penalty=protocol['ridge_penalty']
        self.uncertainty=Ridge([uncertainty_features(r) for r in train],[abs(r['actual']-r['forecast']) for r in train],penalty)
        self.sigma_loo=[self.sigma_from_mae(v) for v in self.uncertainty.loo]
        self.residual=Ridge([residual_features(r) for r in train],[r['actual']-r['market_forecast'] for r in train],penalty)
        self.logits={}
        for name,controlled,conditional in [('EDGE_LOGIT',False,False),('CONTROLLED_LOGIT',True,False),('CONDITIONAL_UNCERTAINTY_LOGIT',True,True)]:
            ix=[i for i,r in enumerate(train) if r['result']!='PUSH']
            features=[classifier_features(train[i],self.sigma_loo[i] if conditional else train[i]['sigma'],controlled) for i in ix]
            self.logits[name]=Logistic(features,[int(train[i]['result']=='WIN') for i in ix],protocol['logistic_penalty'],protocol['logistic_iterations'])
        self.radii={}
        for name in protocol['candidates']:
            residuals=[]
            for i,r in enumerate(train):
                if name=='LOCKED_LINE':point=r['market_forecast']
                elif name=='FIXED_25_PERCENT_MODEL':point=r['market_forecast']+protocol['fixed_model_weight']*(r['forecast']-r['market_forecast'])
                elif name=='MARKET_RESIDUAL_RIDGE':point=r['market_forecast']+self.residual.loo[i]
                else:point=r['forecast']
                sigma=self.sigma_loo[i] if name in ('CONDITIONAL_UNCERTAINTY_LOGIT','MARKET_RESIDUAL_RIDGE') else r['sigma']
                residuals.append(abs(r['actual']-point)/sigma)
            self.radii[name]={str(q):quantile(residuals,q) for q in protocol['interval_coverage']}
    def sigma_from_mae(self,value):return clip(value*math.sqrt(math.pi/2),self.p['sigma_floor'],self.p['sigma_ceiling'])
    def predict(self,row,name):
        if row['week']!=self.target_week or row['source_stats_through_week']>=row['week']:raise ValueError('test boundary')
        sigma=self.sigma_from_mae(self.uncertainty.predict(uncertainty_features(row))) if name in ('CONDITIONAL_UNCERTAINTY_LOGIT','MARKET_RESIDUAL_RIDGE') else row['sigma']
        forecast=row['forecast'];sign=row['sign'];probability=row['score'];score=probability
        if name=='LOCKED_LINE':forecast=row['market_forecast'];sign=0;probability=score=.5
        elif name=='FIXED_25_PERCENT_MODEL':forecast=row['market_forecast']+self.p['fixed_model_weight']*(forecast-row['market_forecast'])
        elif name=='MARKET_RESIDUAL_RIDGE':
            forecast=row['market_forecast']+self.residual.predict(residual_features(row));gap=forecast-row['market_forecast'];sign=1 if gap>=0 else -1
            probability=score=.5*(1+math.erf(abs(gap)/sigma/math.sqrt(2)))
        elif name in self.logits:
            probability=score=self.logits[name].predict(classifier_features(row,sigma,name!='EDGE_LOGIT'))
        lo,hi=self.p['probability_clip'];probability=clip(probability,lo,hi)
        result=None;cover=None
        if row['actual'] is not None and sign:
            cover=(row['actual']-row['market_forecast'])*sign;result='WIN' if cover>0 else 'LOSS' if cover<0 else 'PUSH'
        return dict(row,candidate=name,candidate_forecast=forecast,candidate_sign=sign,probability=probability,ranking_score=score,
                    candidate_sigma=sigma,candidate_result=result,candidate_cover=cover,
                    interval_radii={q:radius*sigma for q,radius in self.radii[name].items()},
                    training_weeks=sorted({r['week'] for r in self.train}),training_n=len(self.train),
                    status='RESEARCH_ONLY',authorized_confidence=1)


def select(rows, n=5, original=False):
    if not rows:return []
    if len({r['market'] for r in rows})==1 and original:
        ordered=sorted(rows,key=lambda r:r['rank'])
    else:ordered=sorted(rows,key=lambda r:(-r['ranking_score'],r['market'],r['locked_line_id'],r['game_id']))
    selected=[];seen=set()
    for row in ordered:
        if row['candidate_sign']==0 or row['game_id'] in seen:continue
        selected.append(row);seen.add(row['game_id'])
        if len(selected)==n:break
    return selected
