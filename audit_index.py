"""Reproducible sensitivity audit. Optionally compare an official month,index CSV."""
import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from random import Random
from statistics import correlation, median, stdev
from apt_watch import ROOT, read_trades, price_indices

def panel(rows, exact=False):
    result = defaultdict(lambda: defaultdict(list))
    for r in rows:
        try:
            area, floor, price = float(r['area']), int(r['floor']), int(r['price'])
            if r['cancelled'] or not r['jibun'] or price <= 0 or area < 1:
                continue
            key = (r['district'],r['dong'],r['jibun'],r['name'],round(area,2) if exact else int(area),
                   floor if exact else 0 if floor<=3 else 1 if floor<=9 else 2)
            result[r['day'][:7]][key].append(price)
        except (ValueError, TypeError, OverflowError):
            continue
    return result

def audit(coverage, rows):
    production = price_indices(coverage,rows)['series']['all']
    source = panel(rows)
    months = [p['month'] for p in production]
    med = {m:{k:median(v) for k,v in source[m].items()} for m in months}
    base = med[months[0]]
    anchor = {}
    fixed, hedonic = {}, {}
    # Two-period log-price regression with stratum fixed effects. Within-stratum
    # time coefficients are weighted by n0*n1/(n0+n1), the exact OLS weights.
    for m in months:
        shared = base.keys() & med[m].keys()
        if len(shared)<10:
            continue
        fixed[m] = 100*math.exp(sum(math.log(med[m][k]/base[k]) for k in shared)/len(shared))
        weighted, weights = 0., 0.
        for k in shared:
            a,b = source[months[0]][k],source[m][k]
            weight=len(a)*len(b)/(len(a)+len(b))
            weighted += weight*(sum(map(math.log,b))/len(b)-sum(map(math.log,a))/len(a))
            weights += weight
        hedonic[m]=100*math.exp(weighted/weights)
        anchor[m]=len(shared)
    latest, prev = months[-1], months[-2]
    keys = med[latest].keys() & med[prev].keys()
    clusters=defaultdict(list)
    for key in sorted(keys):
        clusters[key[:4]].append(math.log(med[latest][key]/med[prev][key]))
    values=list(clusters.values())
    rng=Random(201901)
    returns=sorted(100*math.expm1(median([v for group in rng.choices(values,k=len(values)) for v in group])) for _ in range(2000)) if values else []
    strict=panel(rows, exact=True)
    common=strict[latest].keys() & strict[prev].keys()
    balanced=[math.log(med[latest][k]/med[prev][k]) for k in sorted(keys) if min(len(source[latest][k]),len(source[prev][k]))>=2]
    districts={k[0] for k in keys}
    district_links={d:sum(k[0]==d for k in keys) for d in sorted(districts)}
    price_cut=sorted(med[prev].values())[int(.9*len(med[prev]))]
    expensive=[k for k in keys if med[prev][k]>=price_cut]
    excluding=[math.log(med[latest][k]/med[prev][k]) for k in keys if med[prev][k]<price_cut]
    return dict(asOf=max(f for f,_ in coverage.values()),raw=len(rows), latest=production[-1],previous=production[-2],
                recentVolume={m:sum(map(len,source[m].values())) for m in months[-13:]},
                recentMatches={m:len(med[m].keys() & med[months[i-1]].keys()) for i,m in enumerate(months) if i>=len(months)-13},
                latestDistricts=district_links,complexClusters=len(values),
                matchedTradeCount=sum(len(source[latest][k]) for k in keys),
                recentGroups=len(med[latest]),priorGroups=len(med[prev]),
                upperDecileMatched=len(expensive), excludingUpperDecileReturn=100*math.expm1(median(excluding)) if excluding else None,
                clusterBootstrapMonthlyReturn=[returns[50],returns[1949]] if returns else None,
                strictPairs=len(common),strictMonthlyReturn=100*math.expm1(median([math.log(median(strict[latest][k])/median(strict[prev][k])) for k in common])) if common else None,
                twoTradesEachPairs=len(balanced),twoTradesEachReturn=100*math.expm1(median(balanced)) if balanced else None,
                fixedBase=fixed,hedonic=hedonic,fixedBasePairs=anchor,production={p['month']:p['index'] for p in production if p['index'] is not None})

def compare(data, official):
    common = sorted(data['production'].keys() & official.keys())
    if not common or common[0]!='2019-01':
        raise ValueError('Official Seoul apartment sales series must include January 2019')
    result={}
    for method in ('production','fixedBase','hedonic'):
        series=data[method]
        months=[m for m in common if m in series]
        def previous(m,n):
            y,mo=map(int,m.split('-'))
            y,mo=divmod(y*12+mo-1-n,12)
            return f'{y:04d}-{mo+1:02d}'
        def changes(n):
            return [(m,100*(series[m]/series[p]-1),100*(official[m]/official[p]-1))
                    for m in months if (p:=previous(m,n)) in series and p in official]
        monthly=changes(1)
        x,y=zip(*[(a,b) for _,a,b in monthly])
        end=months[-1]
        result[method]=dict(end=end,cumulative=[series[end]-100,100*(official[end]/official[months[0]]-1)],
            correlation=correlation(x,y) if len(x)>1 and stdev(x) and stdev(y) else None,
            volatility=[stdev(x),stdev(y)] if len(x)>1 else None,
            directionAgreement=sum((a>0)-(a<0)==(b>0)-(b<0) for a,b in zip(x,y))/len(x),
            monthly=monthly, annual=changes(12))
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--tracker',type=Path,default=ROOT.parent/'seoul-apartment-tracker/data/tracker.sqlite3')
    p.add_argument('--official',type=Path)
    p.add_argument('--output',type=Path,default=ROOT/'data/index-audit.json')
    args=p.parse_args()
    result=audit(*read_trades(args.tracker))
    if args.official:
        with args.official.open(encoding='utf-8-sig',newline='') as f:
            result['officialComparison']=compare(result,{r['month']:float(r['index']) for r in csv.DictReader(f)})
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
