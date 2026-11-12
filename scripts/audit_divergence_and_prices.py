import json
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean, median
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
db_path = ROOT / 'data' / 'history.sqlite3'
db = sqlite3.connect(db_path)

day = '2026-11-12'

# 1. Total raw listings
raw_rows = db.execute("SELECT complex, id, price, payload FROM listings WHERE day=?", (day,)).fetchall()
print(f"=== STEP 1: RAW LISTINGS IN DB ===")
print(f"1. Total listings: {len(raw_rows)}")

# 2. Valid asking prices
valid_listings = []
for cid, lid, price, payload in raw_rows:
    p = json.loads(payload)
    if price and price > 0 and lid:
        valid_listings.append((cid, lid, price, p))
print(f"2. Valid asking listings: {len(valid_listings)}")

# 3. Deduplicated listings
unique_ids = {}
for cid, lid, price, p in valid_listings:
    unique_ids[(cid, lid)] = (price, p)
print(f"3. Unique (complex, id) sample: {len(unique_ids)}")

# 4. Complex Mapping
with open(ROOT / 'data' / 'complexes.json', encoding='utf-8') as f:
    complexes_manifest = {str(c['complex']): c for c in json.load(f)}

# Load trade vintage
from apt_watch import read_trade_vintage, store
from market_metrics import trade_key

# Check trade vintage
obs_times = [p.get('observed', '2026-11-12T11:00:00+09:00') for _, p in unique_ids.values()]
earliest_obs = min(obs_times) if obs_times else '2026-11-12T11:00:00+09:00'
vintage, coverage, trades = read_trade_vintage(db, earliest_obs)
print(f"Loaded vintage {vintage} with {len(trades)} trades across {len(coverage)} district-months")

# Index trades by trade_key
maximum_age = 90
end = date.fromisoformat(day)
start = end - timedelta(days=maximum_age - 1)
trades_by_key = defaultdict(list)
for row in trades:
    if row.get('cancelled') or not start.isoformat() <= row['day'] <= day:
        continue
    try:
        pr = float(row['price'])
        if pr > 0:
            trades_by_key[trade_key(row)].append((pr, row['day']))
    except Exception:
        continue

print(f"Trades in last 90 days ({start} ~ {day}): {sum(len(v) for v in trades_by_key.values())} across {len(trades_by_key)} strata")

# Now audit the listings against trades
step4_matched_complex = []
step5_matched_area = []
step6_matched_floor = []
step7_has_trades = []
step8_has_min3_trades = []

complex_strata_breakdown = defaultdict(lambda: {'listings': 0, 'matched_strata': set(), 'benchmarks': {}})

for (cid, lid), (price, p) in unique_ids.items():
    target = complexes_manifest.get(cid)
    if not target or not target.get('tradeComplex'):
        continue
    step4_matched_complex.append((cid, lid))
    
    address = target['tradeComplex']
    area = p.get('exclusive_area_m2', p.get('area'))
    floor = p.get('floor')
    
    if not area:
        continue
    
    # Try finding any trade for this complex and area
    comp_prefix = (address[0], address[1], address[2], address[3], int(float(area)))
    has_area_trade = any(k[:5] == comp_prefix for k in trades_by_key)
    if has_area_trade:
        step5_matched_area.append((cid, lid))
        
    try:
        tkey = (address[0], address[1], address[2], address[3], int(float(area)),
                0 if int(floor) <= 3 else 1 if int(floor) <= 9 else 2)
    except Exception:
        continue
        
    complex_strata_breakdown[cid]['listings'] += 1
    
    if tkey in trades_by_key:
        step7_has_trades.append((cid, lid, tkey))
        bm = trades_by_key[tkey]
        complex_strata_breakdown[cid]['benchmarks'][tkey] = len(bm)
        if len(bm) >= 3:
            step8_has_min3_trades.append((cid, lid, tkey, bm))
            complex_strata_breakdown[cid]['matched_strata'].add(tkey)

print(f"\n=== STEP-BY-STEP FILTERING AUDIT ===")
print(f"4. Matched complex crosswalk: {len(step4_matched_complex)}")
print(f"5. Same complex & area had trade in 90d: {len(step5_matched_area)}")
print(f"6. Exact strata (complex + area + floor band) with trades in 90d: {len(step7_has_trades)}")
print(f"7. Exact strata with >= 3 trades in 90d (CURRENT THRESHOLD): {len(step8_has_min3_trades)}")

print(f"\n=== STRATA WITH TRADES IN 90 DAYS ===")
strata_keys = set(x[2] for x in step7_has_trades)
print(f"Distinct strata with trades in 90d: {len(strata_keys)}")
for sk in strata_keys:
    count = len(trades_by_key[sk])
    asking_for_sk = [x for x in step7_has_trades if x[2] == sk]
    print(f"  Stratum: {sk[3]} (area {sk[4]}m2, floor_tier {sk[5]}) -> {count} trades in 90d, {len(asking_for_sk)} asks today")

print(f"\n=== PRICE VALUE AUDIT ===")
prices_raw = [r[2] for r in raw_rows]
prices_raw.sort()
n = len(prices_raw)
def percentile(vals, p):
    return vals[int(len(vals) * p)]

print(f"Count: {n}")
print(f"Min: {min(prices_raw):,} 만원 ({min(prices_raw)/10000:.2f} 억원)")
print(f"P10: {percentile(prices_raw, 0.10):,} 만원 ({percentile(prices_raw, 0.10)/10000:.2f} 억원)")
print(f"P25: {percentile(prices_raw, 0.25):,} 만원 ({percentile(prices_raw, 0.25)/10000:.2f} 억원)")
print(f"Median (P50): {median(prices_raw):,} 만원 ({median(prices_raw)/10000:.2f} 억원)")
print(f"Mean: {mean(prices_raw):,.1f} 만원 ({mean(prices_raw)/10000:.2f} 억원)")
print(f"P75: {percentile(prices_raw, 0.75):,} 만원 ({percentile(prices_raw, 0.75)/10000:.2f} 억원)")
print(f"P90: {percentile(prices_raw, 0.90):,} 만원 ({percentile(prices_raw, 0.90)/10000:.2f} 억원)")
print(f"Max: {max(prices_raw):,} 만원 ({max(prices_raw)/10000:.2f} 억원)")

print(f"\n=== PER COMPLEX DISTRIBUTION ===")
by_comp = defaultdict(list)
for cid, lid, pr, p in raw_rows:
    by_comp[cid].append(pr)
for cid, prs in sorted(by_comp.items()):
    cname = complexes_manifest.get(cid, {}).get('name', cid)
    print(f"Complex {cid} ({cname}): {len(prs)} asks | Median: {median(prs)/10000:.2f}억 | Mean: {mean(prs)/10000:.2f}억 | Min: {min(prs)/10000:.2f}억 | Max: {max(prs)/10000:.2f}억")
