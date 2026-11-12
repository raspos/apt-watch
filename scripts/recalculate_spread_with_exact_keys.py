import sys
import sqlite3, json
from collections import defaultdict
from datetime import date, datetime, timedelta
from statistics import mean, median
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from market_metrics import trade_key, estimated_spread
from apt_watch import read_trade_vintage

db = sqlite3.connect(ROOT / 'data' / 'history.sqlite3')
day = '2026-11-12'

# Accurate real trade keys for the 10 Yangcheon sample complexes:
CORRECT_TRADE_KEYS = {
    '11708': ('신월동', '1033', '대성유니드'),
    '661': ('목동', '929', '목동청구한신아파트'),
    '3771': ('목동', '200', '우성'),
    '10307': ('목동', '956', '롯데캐슬위너'),
    '8742': ('신정동', '337', '목동우성2'),
    '675': ('신정동', '1279', '목동현대3차'),
    '108438': ('신월동', '1063', '롯데캐슬'),
    '672': ('신정동', '1259', '신트리1'),
    '117329': ('신월동', '1075', '목동센트럴아이파크위브1단지'),
    '107728': ('신정동', '1323', '목동힐스테이트')
}

# 1. Read vintage
vintage, cov, trades = read_trade_vintage(db, '2026-11-12T11:00:00+09:00')
print(f"Loaded trade vintage: {vintage} ({len(trades)} trades)")

# 2. Build asks with correct trade keys
asks = []
for cid, (dong, jibun, name) in CORRECT_TRADE_KEYS.items():
    obs = db.execute("SELECT observed FROM batches WHERE complex=? AND success=1", (cid,)).fetchone()
    if not obs:
        continue
    obs_time = obs[0]
    for row in db.execute("SELECT payload FROM listings WHERE complex=?", (cid,)).fetchall():
        p = json.loads(row[0])
        asks.append({
            **p,
            'district': '11470',
            'dong': dong,
            'jibun': jibun,
            'name': name,
            'area': p.get('exclusive_area_m2'),
            'observed': obs_time,
            'crosswalkVerified': True
        })

print(f"Prepared {len(asks)} asks across {len(CORRECT_TRADE_KEYS)} complexes.")

# 3. Calculate spread using estimated_spread (90d window, >= 3 trades)
spread_90d = estimated_spread(asks, trades, day, vintage, maximum_age=90)
print(f"\n[Default 90d Window, Min 3 Trades]")
print(json.dumps(spread_90d, ensure_ascii=False, indent=2))

# Also inspect with min 1 trade or 180d window to see the full curve
for max_age in [90, 180]:
    for min_trades in [1, 2, 3]:
        # Custom check
        end = date.fromisoformat(day)
        start = end - timedelta(days=max_age - 1)
        trades_by_key = defaultdict(list)
        for r in trades:
            if r.get('cancelled') or not start.isoformat() <= r['day'] <= day:
                continue
            try:
                pr = float(r['price'])
                if pr > 0:
                    trades_by_key[trade_key(r)].append((pr, r['day']))
            except Exception:
                continue
                
        asking_by_key = defaultdict(list)
        for r in asks:
            try:
                k = trade_key(r)
                pr = float(r['asking_price_manwon'])
                if pr > 0:
                    asking_by_key[k].append(pr)
            except Exception:
                continue
                
        values, ages, matched_strata = [], [], []
        matched_comps = set()
        matched_asks_count = 0
        for k, plist in asking_by_key.items():
            bm = trades_by_key[k]
            if len(bm) >= min_trades:
                val = 100 * (median(plist) / median(p for p, _ in bm) - 1)
                values.append(val)
                ages.append((end - date.fromisoformat(max(d for _, d in bm))).days)
                matched_strata.append((k, len(plist), len(bm), val))
                matched_comps.add(k[3])
                matched_asks_count += len(plist)
                
        print(f"MaxAge={max_age}d, MinTrades={min_trades}: Matched Strata={len(values)}, Matched Asks={matched_asks_count}, Complexes={len(matched_comps)}, Divergence={median(values):.2f}%, MedianAge={median(ages) if ages else None}d")
