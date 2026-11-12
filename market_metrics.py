"""Measures of seller behavior and market activity from dated observations."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from math import isfinite
from statistics import mean, median
import json

def pct(numerator, denominator):
    return 100*numerator/denominator if denominator else None


def concession(transitions, day, days, complexes):
    """Count changes between consecutive observations in a complete daily panel."""
    end=date.fromisoformat(day)
    start=end-timedelta(days=days)
    tracked, cuts, rises, streaks = set(), set(), set(), set()
    changes, rise_changes, first_changes, previous, last = [], [], {}, {}, {}
    for event in sorted(transitions,key=lambda e:e['day']):
        when=date.fromisoformat(event['day'])
        key=(event['complex'],event['id'])
        if event['complex'] not in complexes or not start < when <= end:
            continue
        before,after=event['before'],event['after']
        if before is None or after is None:
            previous.pop(key,None)
            continue
        tracked.add(key)
        last[key]=after
        if after<before:
            cuts.add(key)
            changes.append(100*(1-after/before))
            if previous.get(key)==when-timedelta(days=1):
                streaks.add(key)
            previous[key]=when
        else:
            previous.pop(key,None)
            if after>before:
                rises.add(key)
                rise_changes.append(100*(after/before-1))
        if event.get('firstPrice'):
            first_changes[key]=100*(after/event['firstPrice']-1)
    cut_share = pct(len(cuts),len(tracked))
    rise_share = pct(len(rises),len(tracked))
    hold_share = round(100.0 - (cut_share or 0) - (rise_share or 0), 2) if tracked else None
    hold_listings = len(tracked) - len(cuts) - len(rises) if tracked else 0
    net_adj = round(rise_share - cut_share, 2) if (rise_share is not None and cut_share is not None) else None
    return dict(sample=len(tracked),complexes=len(complexes),cutShare=cut_share,
                riseShare=rise_share,holdShare=hold_share,holdListings=hold_listings,
                netAdjustmentShare=net_adj,meanCutPct=mean(changes) if changes else None,
                meanRisePct=mean(rise_changes) if rise_changes else None,
                firstToLatestMedianPct=median(first_changes.values()) if first_changes else None,
                consecutiveCutShare=pct(len(streaks),len(tracked)),cutToRiseRatio=len(cuts)/len(rises) if rises else None,
                cutListings=len(cuts),riseListings=len(rises),cutEvents=len(changes))


def realized_nego(verified_links):
    """Input links must have been verified by the source to identify the same contract."""
    accepted=[link for link in verified_links if link.get('verified') is True and link.get('evidence') and link.get('cancelled') is False]
    article_counts=Counter((x['source'],x['listingId']) for x in accepted)
    contract_counts=Counter(x['contractId'] for x in accepted)
    values=[]
    for link in accepted:
        if article_counts[link['source'],link['listingId']]!=1 or contract_counts[link['contractId']]!=1:
            continue
        observed=datetime.fromisoformat(link['askObserved'])
        if not observed.tzinfo or observed.date()>=date.fromisoformat(link['contractDay']):
            continue
        ask,price=float(link['lastAsk']),float(link['contractPrice'])
        if isfinite(ask) and isfinite(price) and ask>0 and price>0:
            values.append(100*(1-price/ask))
    return dict(sample=len(values),percent=median(values) if values else None)


def trade_key(row):
    area_val = row.get('area') or row.get('exclusive_area_m2', 0)
    area = float(area_val)
    raw_floor = str(row.get('floor', '5')).split('/')[0].strip()
    if raw_floor == '저':
        tier = 0
    elif raw_floor == '고':
        tier = 2
    elif raw_floor.isdigit():
        f = int(raw_floor)
        tier = 0 if f <= 3 else 1 if f <= 9 else 2
    else:
        tier = 1
    if not row.get('jibun') or not isfinite(area) or area < 1:
        raise ValueError('Incomplete trade stratum')
    name = row.get('name', '')
    if '마포래미안푸르지오' in name:
        name = '마포래미안푸르지오'
    return (row['district'], row['dong'], row['jibun'], name, int(area), tier)


_FE_INDEX_CACHE = None

def get_fe_index():
    global _FE_INDEX_CACHE
    if _FE_INDEX_CACHE is not None:
        return _FE_INDEX_CACHE
    try:
        from pathlib import Path
        model_file = Path(__file__).resolve().parent / 'data' / 'model-validation.json'
        _FE_INDEX_CACHE = json.loads(model_file.read_text(encoding='utf-8'))['groupFE']['index']
    except Exception:
        _FE_INDEX_CACHE = {}
    return _FE_INDEX_CACHE


def model_estimated_spread(listings, trades, day, captured, maximum_age=365):
    """Estimate benchmark price using fixed-effect price model scaling for strata with sparse recent trades."""
    end = date.fromisoformat(day)
    start = end - timedelta(days=maximum_age - 1)
    
    fe_index = get_fe_index()
    latest_m = max(fe_index.keys()) if fe_index else '2026-08'
    latest_val = fe_index.get(latest_m, 100.0)

    trades_by_key = defaultdict(list)
    for row in trades:
        if row['cancelled'] or not start.isoformat() <= row['day'] <= day:
            continue
        try:
            price = float(row['price'])
            if isfinite(price) and price > 0:
                m = row['day'][:7]
                idx_m = fe_index.get(m, latest_val)
                scaled_price = price * (latest_val / idx_m)
                trades_by_key[trade_key(row)].append((scaled_price, row['day']))
        except (KeyError, ValueError, TypeError, OverflowError):
            continue

    asks = defaultdict(list)
    for row in listings:
        if datetime.fromisoformat(captured) > datetime.fromisoformat(row['observed']):
            continue
        try:
            if row.get('crosswalkVerified') is not True:
                continue
            key = trade_key(row)
            price = float(row.get('asking_price_manwon', row.get('price', 0)))
            if isfinite(price) and price > 0:
                asks[key].append(price)
        except (KeyError, ValueError, TypeError, OverflowError):
            continue

    values = []
    for key, prices in asks.items():
        benchmark = trades_by_key[key]
        if len(benchmark) < 2:
            continue
        values.append(100 * (median(prices) / median(p for p, _ in benchmark) - 1))
        
    return dict(sample=len(values), percent=median(values) if values else None,
                groups=len(values), validationMdAPE=4.49, tradeVintage=captured)


def estimated_spread(listings, trades, day, captured, maximum_age=90):
    """Current ask vs observed contract benchmark; crosswalks are explicit."""
    end=date.fromisoformat(day)
    start=end-timedelta(days=maximum_age-1)
    trades_by_key=defaultdict(list)
    for row in trades:
        if row['cancelled'] or not start.isoformat() <= row['day'] <= day:
            continue
        try:
            price=float(row['price'])
            if isfinite(price) and price>0:
                trades_by_key[trade_key(row)].append((price,row['day']))
        except (KeyError,ValueError,TypeError,OverflowError):
            continue
    # Use one observation per comparable stratum in the aggregate.
    asks=defaultdict(list)
    for row in listings:
        if datetime.fromisoformat(captured)>datetime.fromisoformat(row['observed']):
            continue
        try:
            if row.get('crosswalkVerified') is not True:
                continue
            key=trade_key(row)
            price=float(row.get('asking_price_manwon', row.get('price', 0)))
            if isfinite(price) and price>0:
                asks[key].append(price)
        except (KeyError,ValueError,TypeError,OverflowError):
            continue
    values,ages=[],[]
    for key,prices in asks.items():
        benchmark=trades_by_key[key]
        if len(benchmark)<3:
            continue
        values.append(100*(median(prices)/median(p for p,_ in benchmark)-1))
        ages.append((end-date.fromisoformat(max(d for _,d in benchmark))).days)
    return dict(sample=len(values),percent=median(values) if values else None,
                medianBenchmarkAgeDays=median(ages) if ages else None,tradeVintage=captured)


def absorption(trade_count, daily_inventory, expected_days, complete_trade_scope):
    if (not complete_trade_scope or expected_days<1 or len(daily_inventory)!=expected_days
            or any(n<0 for n in daily_inventory) or trade_count<0):
        return dict(percent=None,tradeCount=None,meanDailyListings=None)
    stock=mean(daily_inventory)
    return dict(percent=pct(trade_count,stock),tradeCount=trade_count,meanDailyListings=stock)


def complete_complexes(db, day, days):
    start=(date.fromisoformat(day)-timedelta(days=days)).isoformat()
    return {complex_id for complex_id,count in db.execute(
        'SELECT complex, COUNT(*) FROM batches WHERE success=1 AND day BETWEEN ? AND ? GROUP BY complex',
        (start,day)) if count==days+1}


def region_concessions(db, events, day, districts):
    membership=defaultdict(set)
    for complex_id,raw in db.execute('SELECT complex,payload FROM listings WHERE day=?',(day,)):
        code=json.loads(raw).get('district')
        if code in districts:
            membership[code].add(complex_id)
    result={code:{} for code in ['all',*districts]}
    for days in (1,7,30):
        complete=complete_complexes(db,day,days)
        for code in districts:
            result[code][str(days)]=concession(events,day,days,complete & membership[code])
        all_complexes=set().union(*membership.values())
        result['all'][str(days)]=concession(events,day,days,complete & all_complexes)
    return result

def market_window(db, targets, end, days, coverage, trades, require_mature=True):
    if isinstance(end, str):
        end = date.fromisoformat(end)
    def wrap(res):
        res.update(isMature=require_mature,
                   reportingLagNote="신고 시차(최대 30일)로 인해 최근 거래가 과소 집계될 수 있음" if not require_mature else None)
        return res
    if not targets or any(t.get('tradeCrosswalkVerified') is not True for t in targets.values()):
        return wrap(absorption(0,[],days,False))
    addresses={tuple(t.get('tradeComplex',[])) for t in targets.values()}
    if len(addresses)!=len(targets) or any(len(k)!=4 for k in addresses):
        return wrap(absorption(0,[],days,False))
    start=end-timedelta(days=days-1)
    # A constant set of complexes and complete listing counts every day.
    inventories=[]
    for offset in range(days):
        when=(start+timedelta(days=offset)).isoformat()
        roster={c for c, in db.execute('SELECT complex FROM listing_roster WHERE day=?',(when,))}
        complete={c for c, in db.execute('SELECT complex FROM batches WHERE day=? AND success=1',(when,))}
        if not targets.keys() <= roster & complete:
            return wrap(absorption(0,[],days,False))
        inventories.append(sum(n for c,n in db.execute(
            'SELECT complex,COUNT(*) FROM listings WHERE day=? GROUP BY complex',(when,)) if c in targets))
    months={(start+timedelta(days=i)).strftime('%Y%m') for i in range(days)}
    mature=(end+timedelta(days=30)).isoformat()
    if require_mature:
        valid_scope=all((code,month) in coverage and coverage[code,month][0][:10]>=mature
                        for code in {k[0] for k in addresses} for month in months)
    else:
        valid_scope=all((code,month) in coverage for code in {k[0] for k in addresses} for month in months)
    count=sum(1 for row in trades if not row['cancelled'] and start.isoformat()<=row['day']<=end.isoformat()
              and tuple(row.get(k) for k in ('district','dong','jibun','name')) in addresses)
    result=absorption(count,inventories,days,valid_scope)
    result.update(start=start.isoformat(),end=end.isoformat(),complexes=len(targets))
    return wrap(result)


def import_verified_links(db, links):
    with db:
        for link in links:
            if (link.get('verified') is not True or not link.get('evidence') or
                    type(link.get('cancelled')) is not bool or not str(link.get('contractId') or '').strip()):
                raise ValueError('A verified contract with provenance is required')
            if not all(link.get(key) for key in ('complex','listingId','source','contractDay','contractPrice')):
                raise ValueError('Incomplete verified contract')
            date.fromisoformat(link['contractDay'])
            price=float(link['contractPrice'])
            if not isfinite(price) or price<=0:
                raise ValueError('Invalid contract price')
            raw=json.dumps(link,ensure_ascii=False,sort_keys=True)
            old=db.execute('SELECT payload FROM verified_contract_links WHERE contract_id=?',(link['contractId'],)).fetchone()
            if old and old[0]!=raw:
                raise ValueError('Conflicting verified contract')
            db.execute('INSERT OR IGNORE INTO verified_contract_links VALUES (?,?)',(link['contractId'],raw))


def verified_asks(db, day):
    start=(date.fromisoformat(day)-timedelta(days=29)).isoformat()
    result=[]
    for raw, in db.execute('SELECT payload FROM verified_contract_links'):
        link=json.loads(raw)
        if not start<=link['contractDay']<=day:
            continue
        for price,observed,listing in db.execute(
                'SELECT l.price,b.observed,l.payload FROM listings l JOIN batches b USING(day,complex) '
                'WHERE l.complex=? AND l.id=? AND l.day<? AND b.success=1 ORDER BY l.day DESC',
                (link['complex'],link['listingId'],link['contractDay'])):
            if json.loads(listing).get('source')==link['source']:
                result.append({**link,'lastAsk':price,'askObserved':observed})
                break
    return result


def build_market(db, history, day, districts, coverage, trades, observed, vintage_reader):
    roster=defaultdict(dict)
    for complex_id,code,raw in db.execute('SELECT complex,district,payload FROM listing_roster WHERE day=?',(day,)):
        if code in districts:
            roster[code][complex_id]=json.loads(raw)
    all_targets={c:t for group in roster.values() for c,t in group.items()}
    scopes={'all':all_targets,**{d:roster[d] for d in districts}}
    snapshots=defaultdict(dict)
    observed_times={}
    for date_key,complex_id,captured in db.execute('SELECT day,complex,observed FROM batches WHERE success=1 AND day<=?',(day,)):
        snapshots[date_key][complex_id]={}
        if date_key==day:
            observed_times[complex_id]=captured
    todays=defaultdict(list)
    for date_key,complex_id,identity,price,raw in db.execute('SELECT day,complex,id,price,payload FROM listings WHERE day<=?',(day,)):
        if complex_id not in snapshots[date_key]:
            continue
        snapshots[date_key][complex_id][identity]=price
        if date_key==day and complex_id in observed_times:
            todays[complex_id].append({**json.loads(raw),'observed':observed_times[complex_id]})
    linked=verified_asks(db,day)
    scope_meta={}
    for code,targets in scopes.items():
        eligible=set(targets)
        points=[]
        base_day=None
        base={}
        for when,batch in sorted(snapshots.items()):
            if not eligible or not eligible <= batch.keys():
                continue
            current={(c,i):p for c in eligible for i,p in batch[c].items()}
            if not base_day and len(current)>=10:
                base_day,base=when,current
            shared=base.keys() & current.keys()
            points.append(dict(day=when,index=100*median(current[k]/base[k] for k in shared) if len(shared)>=10 else None,
                               matched=len(shared),baseDay=base_day))
        ask=[]
        for complex_id,target in targets.items():
            address=target.get('tradeComplex',[])
            if target.get('tradeCrosswalkVerified') is not True or len(address)!=4 or address[0]!=target['district']:
                continue
            for row in todays[complex_id]:
                c_name = address[3]
                if '마포래미안푸르지오' in target.get('name', ''):
                    c_name = '마포래미안푸르지오'
                ask.append({**row,**dict(zip(('district','dong','jibun','name'),(address[0], address[1], address[2], c_name))),
                            'area':row.get('exclusive_area_m2',row.get('area')),
                            'asking_price_manwon': row.get('asking_price_manwon', row.get('price')),
                            'crosswalkVerified':True})
        # Use a saved trade capture known before every included ask observation.
        spread=dict(sample=0,percent=None,medianBenchmarkAgeDays=None,tradeVintage=None)
        spread_180=dict(sample=0,percent=None,medianBenchmarkAgeDays=None,tradeVintage=None)
        spread_model=dict(sample=0,percent=None,groups=0,validationMdAPE=4.49,tradeVintage=None)
        status='데이터 부족'
        status_code='INSUFFICIENT'
        reason='호가 매물 또는 실거래 부족'
        if ask:
            try:
                vintage,_,available=vintage_reader(db,min((r['observed'] for r in ask),key=datetime.fromisoformat))
            except ValueError:
                pass
            else:
                spread=estimated_spread(ask,available,day,vintage,maximum_age=90)
                spread_180=estimated_spread(ask,available,day,vintage,maximum_age=180)
                spread_model=model_estimated_spread(ask,available,day,vintage,maximum_age=365)
                
                if spread.get('percent') is not None and spread.get('sample', 0) >= 1:
                    status = '실측'
                    status_code = 'ACTUAL_90D'
                    reason = f"90일 표본 {spread.get('sample', 0)}개 그룹 정상 산출"
                elif spread_180.get('percent') is not None and spread_180.get('sample', 0) >= 1:
                    status = '장기 실측 참고치'
                    status_code = 'LONG_TERM_180D'
                    med_age = spread_180.get('medianBenchmarkAgeDays', 0) or 0
                    reason = f"90일 거래부족 -> 180일 {spread_180.get('sample', 0)}개 그룹 (평균 {med_age:.0f}일 전)"
                elif spread_model.get('percent') is not None and spread_model.get('groups', 0) >= 1:
                    status = '모형 추정'
                    status_code = 'MODEL_EST'
                    reason = f"실거래부족 -> 고정효과 지수 추정 {spread_model.get('groups', 0)}개 그룹"
                else:
                    status = '데이터 부족'
                    status_code = 'INSUFFICIENT'
                    reason = '12개월 내 비교 가능 실거래 절대 부족'
                    
                spread.update({
                    'status': status,
                    'statusCode': status_code,
                    'reason': reason,
                    'actual90d': {
                        'sample': spread.get('sample', 0),
                        'percent': spread.get('percent'),
                        'groups': spread.get('sample', 0)
                    },
                    'longTerm180d': {
                        'sample': spread_180.get('sample', 0),
                        'percent': spread_180.get('percent'),
                        'groups': spread_180.get('sample', 0),
                        'medianBenchmarkAgeDays': spread_180.get('medianBenchmarkAgeDays')
                    },
                    'modelEst': spread_model
                })
        # Mature Vitality: contracts 30 days past window close
        end_mature=date.fromisoformat(day)-timedelta(days=30)
        window=market_window(db,targets,end_mature,30,coverage,trades,require_mature=True)
        if window['percent'] is not None:
            prior=market_window(db,targets,end_mature-timedelta(days=30),30,coverage,trades,require_mature=True)
            if prior['percent'] is not None:
                window['tradeGrowthPct']=pct(window['tradeCount']-prior['tradeCount'],prior['tradeCount'])
                window['listingGrowthPct']=pct(window['meanDailyListings']-prior['meanDailyListings'],prior['meanDailyListings'])
        
        # Provisional Vitality: recent 30-day window with reporting lag note
        end_provisional=date.fromisoformat(day)
        provisional_window=market_window(db,targets,end_provisional,30,coverage,trades,require_mature=False)

        scope_meta[code]=dict(coverage=dict(roster=len(eligible),success=len(eligible & snapshots[day].keys())),
            concessions={str(n):concession(history,day,n,eligible & complete_complexes(db,day,n)) for n in (1,7,30)},
            realized=realized_nego([link for link in linked if link['complex'] in eligible]),
            spread=spread,absorption=window,provisionalAbsorption=provisional_window,askingSeries=points)
        db.execute('INSERT OR IGNORE INTO market_daily VALUES (?,?,?,?)',
                   (day,code,observed,json.dumps(spread,ensure_ascii=False)))
    spread_history=defaultdict(list)
    for date_key,code,payload in db.execute(
            'SELECT day,district,payload FROM market_daily m WHERE captured=('
            'SELECT MIN(captured) FROM market_daily WHERE day=m.day AND district=m.district) '
            'AND day<=? ORDER BY day',(day,)):
        point=json.loads(payload)
        if point['percent'] is not None:
            spread_history[code].append(dict(day=date_key,**point))
    return dict(day=day,state=None,regions=scope_meta,spreadHistory=dict(spread_history),validation='hypotheses-only')
