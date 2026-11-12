"""Monthly price models and complex-level holdout checks."""
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev


def collect(rows):
    panels = [defaultdict(lambda: defaultdict(list)) for _ in range(2)]
    for row in rows:
        if row['cancelled'] or not row.get('jibun'):
            continue
        try:
            area, floor, price = float(row['area']), int(row['floor']), int(row['price'])
            if not math.isfinite(area) or area < 1 or price <= 0:
                continue
            month = row['day'][:7]
            key = (row['district'], row['dong'], row['jibun'], row['name'])
            log_price = math.log(price)
            panels[0][key+(int(area),0 if floor<=3 else 1 if floor<=9 else 2)][month].append(log_price)
            panels[1][key+(round(area,2),floor)][month].append(log_price)
        except (ValueError,TypeError,OverflowError):
            continue
    return panels


def solve(matrix, rhs):
    """Solve the small time-effect system by Gaussian elimination with pivoting."""
    n = len(rhs)
    for col in range(n):
        pivot = max(range(col,n), key=lambda i:abs(matrix[i][col]))
        if abs(matrix[pivot][col])<1e-10:
            raise ValueError('Unidentified month effects')
        matrix[col], matrix[pivot] = matrix[pivot], matrix[col]
        rhs[col],rhs[pivot]=rhs[pivot],rhs[col]
        for i in range(col+1,n):
            factor=matrix[i][col]/matrix[col][col]
            for j in range(col+1,n):
                matrix[i][j]-=factor*matrix[col][j]
            rhs[i]-=factor*rhs[col]
    out=[0.]*n
    for i in range(n-1,-1,-1):
        out[i]=(rhs[i]-sum(matrix[i][j]*out[j] for j in range(i+1,n)))/matrix[i][i]
    return out


def fixed_effects(panel, months):
    """OLS log prices with stratum and month effects, absorbing the stratum intercept."""
    months = sorted(months)
    index={m:i for i,m in enumerate(months)}
    n=len(months)
    matrix=[[0.]*n for _ in months]
    rhs=[0.]*n
    support=defaultdict(int)
    adjacency=defaultdict(set)
    for by_month in panel.values():
        obs=[(index[m],len(v),sum(v)) for m,v in by_month.items() if m in index]
        if len(obs)<2:
            continue
        count=sum(k for _,k,_ in obs)
        avg=sum(s for _,_,s in obs)/count
        linked={i for i,_,_ in obs}
        for i,ni,si in obs:
            support[months[i]]+=1
            adjacency[i].update(linked)
            rhs[i]+=si-ni*avg
            matrix[i][i]+=ni
            for j,nj,_ in obs:
                matrix[i][j]-=ni*nj/count
    connected={0}
    frontier=[0]
    while frontier:
        unseen=adjacency[frontier.pop()]-connected
        connected.update(unseen)
        frontier.extend(unseen)
    ids=sorted(connected-{0})
    values=solve([[matrix[i][j] for j in ids] for i in ids],[rhs[i] for i in ids])
    return ({months[0]:100., **{months[i]:100*math.exp(v) for i,v in zip(ids,values)}}, dict(support))


def direct(panel, months):
    ratios=defaultdict(list)
    for values in panel.values():
        if months[0] not in values:
            continue
        base=median(values[months[0]])
        for month,prices in values.items():
            ratios[month].append(median(prices)-base)
    return ({m:100*math.exp(mean(ratios[m])) for m in months if len(ratios[m])>=10},
            {m:len(ratios[m]) for m in months})


def heldout_returns(panel, months):
    ratios=defaultdict(list)
    for values in panel.values():
        for previous,month in zip(months,months[1:]):
            if previous in values and month in values:
                ratios[month].append(median(values[month])-median(values[previous]))
    return {m:100*median(v) for m,v in ratios.items() if len(v)>=20}


def returns(series, months):
    return {m:100*math.log(series[m]/series[p]) for p,m in zip(months,months[1:]) if p in series and m in series}


def validate(rows, official):
    panels=collect(rows)
    months=sorted(official)
    if months[0]!='2019-01':
        raise ValueError('January 2019 base required')
    models=[('direct',direct,panels[0]),('groupFE',fixed_effects,panels[0]),('strictFE',fixed_effects,panels[1])]
    output={}
    evaluations=defaultdict(dict)
    for fold in range(5):
        def held(key):
            digest=hashlib.sha256(repr(key[:4]).encode()).digest()
            return int.from_bytes(digest[:4],'big')%5==fold
        benchmark=heldout_returns({k:v for k,v in panels[0].items() if held(k)},months)
        for name,model,panel in models:
            series,_=model({k:v for k,v in panel.items() if not held(k)},months)
            prediction=returns(series,months)
            evaluations[name][fold]={m:abs(benchmark[m]-prediction[m]) for m in benchmark.keys() & prediction.keys()}
    for name,model,panel in models:
        series,support=model(panel,months)
        evaluation=[]
        for fold in range(5):
            shared=set.intersection(*(set(evaluations[key][fold]) for key,_,_ in models))
            evaluation.extend(evaluations[name][fold][m] for m in sorted(shared))
        monthly=returns(series,months)
        output[name]=dict(index=series,support=support,monthlyLogPct=monthly,
                          cumulative=series[months[-1]]-100,volatility=stdev(monthly.values()),
                          holdoutMAE=mean(evaluation),holdoutN=len(evaluation))
    return output


def apply_validated_model(data, rows):
    # Keep the original chained observations and their methodology available.
    data['researchSeries'] = data['series']
    coarse,_ = collect(rows)
    revised={}
    for district,old in data['researchSeries'].items():
        panel=coarse if district=='all' else {k:v for k,v in coarse.items() if k[0]==district}
        months=[p['month'] for p in old if p['covered']==(len(data['districts']) if district=='all' else 1)]
        levels,support=fixed_effects(panel,months) if months and months[0]=='2019-01' else ({},{})
        month_groups=defaultdict(set)
        for key,observations in panel.items():
            for month in observations:
                month_groups[month].add(key)
        series=[]
        prior=set()
        for point in old:
            month=point['month']
            value=levels.get(month)
            matched=len(prior & month_groups[month])
            prior=month_groups[month]
            if support.get(month,0)<10 or (point['provisional'] and matched<(100 if district=='all' else 10)):
                value=None
            series.append({**point,'index':round(value,2) if value is not None else None,
                           'modelGroups':support.get(month,0),'matched':matched,
                           'withheld':'잠정 비교 표본 부족' if value is None and point['provisional'] else None})
        revised[district]=series
    data['series']=revised
    data['version']='stratum-month-fixed-effects-v1'

if __name__=='__main__':
    import csv
    from apt_watch import ROOT,read_trades
    with (ROOT/'data/reb-seoul-2019-2026.csv').open(encoding='utf-8-sig') as f:
        official={r['month']:float(r['index']) for r in csv.DictReader(f)}
    coverage,rows=read_trades(ROOT.parent/'seoul-apartment-tracker/data/tracker.sqlite3')
    result=validate(rows,official)
    out=ROOT/'data/model-validation.json'
    out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    for name,value in result.items():
        print(name,{k:v for k,v in value.items() if k not in ('index','support','monthlyLogPct')})
