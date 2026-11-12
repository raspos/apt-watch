"""APT WATCH reads the tracker without modifying it."""
import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
from market_metrics import build_market, concession, complete_complexes
from statistics import median
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
SEOUL = '종로 중 용산 성동 광진 동대문 중랑 성북 강북 도봉 노원 은평 서대문 마포 양천 강서 구로 금천 영등포 동작 관악 서초 강남 송파 강동'.split()
DISTRICTS = dict(zip('11110 11140 11170 11200 11215 11230 11260 11290 11305 11320 11350 11380 11410 11440 11470 11500 11530 11545 11560 11590 11620 11650 11680 11710 11740'.split(), [n+'구' for n in SEOUL]))
SCHEMA = """
CREATE TABLE IF NOT EXISTS batches(day TEXT, complex TEXT, observed TEXT, success INTEGER,
  PRIMARY KEY(day, complex));
CREATE TABLE IF NOT EXISTS listings(day TEXT, complex TEXT, id TEXT, price REAL, payload TEXT,
  PRIMARY KEY(day, complex, id));
CREATE TABLE IF NOT EXISTS trade_vintage_payloads(hash TEXT PRIMARY KEY, payload BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS trade_vintages(
  observed TEXT, district TEXT, month TEXT, source_fetched TEXT, hash TEXT,
  PRIMARY KEY(observed,district,month));
CREATE TABLE IF NOT EXISTS listing_roster(day TEXT, complex TEXT, district TEXT, payload TEXT,
  PRIMARY KEY(day,complex));
CREATE TABLE IF NOT EXISTS verified_contract_links(
  contract_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS market_daily(
  day TEXT, district TEXT, captured TEXT, payload TEXT,
  PRIMARY KEY(day,district,captured));
CREATE TABLE IF NOT EXISTS publications(observed TEXT PRIMARY KEY, payload TEXT NOT NULL);
"""

def now():
    return datetime.now(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')

def store(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=60.0)
    db.execute('PRAGMA busy_timeout=60000')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=NORMAL')
    db.executescript(SCHEMA)
    return db

def ingest(db, batch):
    """Accept a permitted feed's normalized observations, one complete batch per day and complex."""
    observed_dt = datetime.fromisoformat(batch['observed'].replace('Z', '+00:00'))
    if not observed_dt.tzinfo:
        raise ValueError('Offset required')
    observed_kst = observed_dt.astimezone(ZoneInfo('Asia/Seoul'))
    today_kst = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    day, complex_id = observed_kst.date().isoformat(), str(batch['complex'])
    if day > today_kst:
        raise ValueError(f"Observation date {day} cannot be in the future (today is {today_kst})")
    success = batch['success']
    if type(success) is not bool or not complex_id:
        raise ValueError('Invalid batch')
    rows = {}
    for row in batch.get('rows', []):
        identity = str(row['article_no'] or '').strip()
        price = float(row['asking_price_manwon'])
        if not identity or not math.isfinite(price) or price <= 0:
            raise ValueError('Invalid listing')
        value = (day, complex_id, identity, price, json.dumps(row, ensure_ascii=False, sort_keys=True))
        if identity in rows and rows[identity] != value:
            raise ValueError('Conflicting listing IDs')
        rows[identity] = value
    observed_utc = observed_dt.astimezone(ZoneInfo('UTC')).strftime('%Y-%m-%dT%H:%M:%SZ')
    with db:
        old = db.execute('SELECT success FROM batches WHERE day=? AND complex=?', (day,complex_id)).fetchone()
        if old and old[0]:
            return
        db.execute('INSERT OR REPLACE INTO batches VALUES (?,?,?,?)', (day,complex_id,observed_utc,success))
        if success:
            db.executemany('INSERT INTO listings VALUES (?,?,?,?,?)', rows.values())

def events(db):
    previous, seen = {}, defaultdict(dict)
    result = []
    for day, complex_id in db.execute('SELECT day,complex FROM batches WHERE success=1 ORDER BY day,complex'):
        rows = {i:(p,raw) for i,p,raw in db.execute('SELECT id,price,payload FROM listings WHERE day=? AND complex=?',(day,complex_id))}
        old = previous.get(complex_id, {})
        for identity in sorted(set(old) | set(rows)):
            a, b = old.get(identity), rows.get(identity)
            if b is None:
                kind = '관측 중단'
            elif a is None:
                kind = '재등장' if identity in seen[complex_id] else '신규 관측'
            elif b[0] != a[0]:
                kind = '인하' if b[0] < a[0] else '인상'
            else:
                # Observation metadata can change even when the listing does not.
                fields = ('building_name','floor','exclusive_area_m2','realtor_name','article_feature')
                x, y = json.loads(a[1]), json.loads(b[1])
                kind = '정보 수정' if any(x.get(k)!=y.get(k) for k in fields) else '유지'
            result.append(dict(day=day,complex=complex_id,id=identity,kind=kind,
                               before=a[0] if a else None,after=b[0] if b else None,
                               firstObserved=seen[complex_id].get(identity, (day,None))[0],
                               firstPrice=seen[complex_id].get(identity, (day,b[0] if b else None))[1]))
        previous[complex_id] = rows
        for identity in rows:
            seen[complex_id].setdefault(identity, (day, rows[identity][0]))
    return result

def asking_metrics(db, day):
    history = events(db)
    return {str(days):concession(history,day,days,complete_complexes(db,day,days)) for days in (1,7,30)}

def read_trades(path):
    with sqlite3.connect(path.resolve().as_uri()+'?mode=ro', uri=True) as db:
        db.execute('BEGIN')
        coverage = {(d,m): (f,n) for d,m,f,n in db.execute('SELECT district,month,fetched,count FROM snapshots')
                    if d in DISTRICTS and m >= '201901'}
        if not coverage:
            raise ValueError('Tracker has no Seoul snapshots')
        trades = [json.loads(row[0]) for row in db.execute("SELECT payload FROM trades WHERE month >= '201901'")]
    return coverage, trades

def month_range(last):
    y,m = 2019,1
    while (key:=f'{y:04d}{m:02d}') <= last:
        yield key
        y,m = y+(m==12),m%12+1

def price_indices(coverage, trades):
    groups = defaultdict(lambda: defaultdict(list))
    valid = 0
    for row in trades:
        if row['cancelled'] or row['district'] not in DISTRICTS:
            continue
        try:
            floor = int(row['floor'])
            area = int(float(row['area']))
            price = int(row['price'])
        except (ValueError, TypeError, OverflowError):
            continue
        if area<=0 or price<=0 or not row.get('jibun'):
            continue
        valid += 1
        key = (row['district'],row['dong'],row['jibun'],row['name'],area,
               'low' if floor<=3 else 'middle' if floor<=9 else 'high')
        groups[row['day'][:7].replace('-','')][key].append(price)
    asof = max(f for f,_ in coverage.values())
    cutoff = date.fromisoformat(asof[:10])-timedelta(days=30)
    series = {code:[] for code in ['all',*DISTRICTS]}
    anchors = {}
    for month in month_range(max(m for _,m in coverage)):
        current = {k: median(v) for k,v in groups[month].items()}
        counts = defaultdict(int)
        for key in current:
            counts[key[0]] += len(groups[month][key])
        following = date(int(month[:4])+(month[4:]=='12'),int(month[4:])%12+1,1)
        provisional = following-timedelta(days=1)>cutoff
        for code in series:
            codes = DISTRICTS if code=='all' else [code]
            covered = sum((d,month) in coverage for d in codes)
            subset = {key: value for key, value in current.items() if key[0] in codes}
            value, links, comparison = None, [], None
            if covered == len(codes) and subset:
                if month == '201901':
                    value = 100.
                elif code in anchors:
                    comparison, previous, previous_level = anchors[code]
                    elapsed = (int(month[:4])-int(comparison[:4]))*12 + int(month[4:])-int(comparison[4:])
                    if elapsed <= 12:
                        links = [math.log(price/previous[key]) for key,price in subset.items() if key in previous]
                        if len(links) >= 10:
                            value = previous_level * math.exp(median(links))
            if value is not None:
                anchors[code] = (month, subset, value)
            series[code].append(dict(month=month[:4]+'-'+month[4:],index=round(value,2) if value is not None else None,
                                     comparison=comparison, samples=sum(counts[d] for d in codes),
                                     matched=len(links),covered=covered,provisional=provisional))
    return dict(asOf=asof, raw=len(trades), eligibleTrades=valid, series=series, districts=DISTRICTS,
                districtMonths=len(coverage), version='matched-median-v1')

def withhold_recent_seoul(data):
    # Interim publication floor, pending validation against mature vintages.
    for point in data['series']['all']:
        if point['provisional'] and point['index'] is not None and point['matched'] < 100:
            point['index'] = None
            point['withheld'] = '잠정 비교 표본 100개 미만'
    data['publicationRule'] = 'provisional-seoul-min-100-v1'

def save_trade_vintage(db, observed, coverage, trades):
    # The contract day lives in each source row. Identical district-month
    # payloads are stored once; the capture records when they were available.
    partitions = defaultdict(list)
    for row in trades:
        key = (row['district'], row['day'][:7].replace('-', ''))
        partitions[key].append(json.dumps(row, sort_keys=True, ensure_ascii=False))
    for (district, month), (fetched, count) in coverage.items():
        rows = partitions[district, month]
        if len(rows) != count:
            raise ValueError(f'Tracker count mismatch for {district}/{month}')
        raw = ('[' + ','.join(sorted(rows)) + ']').encode('utf-8')
        digest = hashlib.sha256(raw).hexdigest()
        if not db.execute('SELECT 1 FROM trade_vintage_payloads WHERE hash=?',(digest,)).fetchone():
            db.execute('INSERT INTO trade_vintage_payloads VALUES (?,?)',(digest,gzip.compress(raw,compresslevel=3)))
        db.execute('INSERT INTO trade_vintages VALUES (?,?,?,?,?)',
                   (observed,district,month,fetched,digest))

_VINTAGE_CACHE = {}

def read_trade_vintage(db, cutoff):
    requested = datetime.fromisoformat(cutoff)
    if not requested.tzinfo:
        raise ValueError('Offset required')
    normalized = requested.astimezone(ZoneInfo('Asia/Seoul')).isoformat(timespec='seconds')
    observed = db.execute('SELECT MAX(observed) FROM trade_vintages WHERE observed<=?',(normalized,)).fetchone()[0]
    if observed is None:
        raise ValueError('No recorded trade vintage at this cutoff')
    if observed in _VINTAGE_CACHE:
        cov, tr = _VINTAGE_CACHE[observed]
        return observed, cov.copy(), tr
    coverage, trades = {}, []
    for district,month,fetched,payload in db.execute(
            'SELECT district,month,source_fetched,payload FROM trade_vintages '
            'JOIN trade_vintage_payloads USING(hash) WHERE observed=?',(observed,)):
        rows = json.loads(gzip.decompress(payload))
        coverage[district,month] = (fetched,len(rows))
        trades.extend(rows)
    _VINTAGE_CACHE[observed] = (coverage, trades)
    return observed, coverage.copy(), trades

def build(args):
    coverage, trades = read_trades(args.tracker)
    observed = now()
    data = price_indices(coverage, trades)
    data['calculatedAt'] = now()
    from price_models import apply_validated_model
    apply_validated_model(data,trades)
    withhold_recent_seoul(data)

    with store(args.store) as db:
        last = db.execute('SELECT MAX(observed) FROM batches WHERE success=1').fetchone()[0]
        latest_day = db.execute('SELECT MAX(day) FROM batches WHERE success=1').fetchone()[0]
        day = getattr(args, 'day', None) or latest_day or now()[:10]
        ok, failed = db.execute('SELECT COUNT(CASE WHEN success=1 THEN 1 END), COUNT(CASE WHEN success=0 THEN 1 END) FROM batches WHERE day=?',(day,)).fetchone()
        count = db.execute('SELECT COUNT(*) FROM listings WHERE day=?',(day,)).fetchone()[0]
        data['asking'] = dict(lastSuccess=last, successes=ok, failures=failed, listings=count,
                              target=None, sentiment=None, premium=None, changes=asking_metrics(db, day))
        data['market'] = build_market(db, events(db), day, DISTRICTS, coverage, trades,
                                      observed, read_trade_vintage)
        payload=json.dumps(data,ensure_ascii=False,allow_nan=False)
        save_trade_vintage(db, observed, coverage, trades)
        db.execute('INSERT INTO publications VALUES (?,?)',(data['calculatedAt'],payload))
    output=args.output
    output.parent.mkdir(parents=True,exist_ok=True)
    temporary=output.with_suffix('.tmp')
    temporary.write_text(payload,encoding='utf-8')
    temporary.replace(output)
    print(f"{data['raw']:,} trades, {data['districtMonths']:,} district-months, {data['asOf']}")

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--tracker',type=Path,default=ROOT.parent/'seoul-apartment-tracker/data/tracker.sqlite3')
    parser.add_argument('--store',type=Path,default=Path(os.getenv('APT_WATCH_DB',ROOT/'data/history.sqlite3')))
    parser.add_argument('--day',type=str,help='Observation day override (YYYY-MM-DD)')
    parser.add_argument('--output',type=Path,default=ROOT/'site/data.json')
    parser.add_argument('--import-feed',type=Path,help='Authorized normalized JSONL observations')
    parser.add_argument('--events',action='store_true')
    parser.add_argument('--verified-links',type=Path,help='Source-verified listing-to-contract JSONL')
    args=parser.parse_args()
    if args.import_feed or args.events or args.verified_links:
        with store(args.store) as db:
            if args.import_feed:
                for line in args.import_feed.read_text(encoding='utf-8').splitlines():
                    if line.strip():
                        ingest(db,json.loads(line))
            if args.verified_links:
                from market_metrics import import_verified_links
                import_verified_links(db,[json.loads(line) for line in args.verified_links.read_text(encoding='utf-8-sig').splitlines() if line.strip()])
            if args.events:
                print(json.dumps(events(db),ensure_ascii=False))
    else:
        build(args)

if __name__=='__main__':
    main()
