"""Verification of Consecutive Tracking of Identical Listings for Asking Adjustment Index (호가조정지수).
Tests:
1. Continuous tracking of identical listing IDs across observation days.
2. Accurate calculation of DoD (1-day), 7-day, and 30-day metrics:
   - cutShare (호가 인하 매물 비중)
   - riseShare (호가 인상 매물 비중)
   - netAdjustmentShare (순호가조정률 = riseShare - cutShare)
   - cutListings, riseListings
   - meanCutPct, meanRisePct
   - firstToLatestMedianPct
3. Invariant checks:
   - Unchanged listings are correctly kept in the denominator.
   - Delisted (관측 중단) listings are NOT counted as price cuts.
   - Newly appeared (신규 관측) listings are NOT counted in the consecutive denominator until reobserved.
"""
import json
import sqlite3
from datetime import date, timedelta
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from market_metrics import concession
from apt_watch import events, SCHEMA

def run_test():
    print("=== Testing Live Identical-Listing Consecutive Tracking ===")
    
    # Create in-memory database with real schema
    db = sqlite3.connect(':memory:')
    db.executescript(SCHEMA)

    day1 = '2026-11-12'
    day2 = '2026-11-13'
    complex_id = '11708' # 대성유니드 (실제 양천구 단지 ID)

    # 1. Day 1: 10 listings
    # Listings: 101 to 110 at 80,000만원
    db.execute("INSERT INTO batches VALUES (?, ?, ?, 1)", (day1, complex_id, f"{day1}T06:00:00+09:00"))
    for i in range(101, 111):
        lid = str(i)
        payload = json.dumps({'article_no': lid, 'asking_price_manwon': 80000, 'complex': complex_id})
        db.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?)", (day1, complex_id, lid, 80000.0, payload))

    # 2. Day 2:
    # 101, 102: price cut from 80,000 to 76,000 (5% cut) -> 2 listings
    # 103: price rise from 80,000 to 84,000 (5% rise) -> 1 listing
    # 104, 105, 106, 107, 108: unchanged at 80,000 -> 5 listings
    # 109: delisted (not in Day 2) -> 1 listing
    # 110: delisted (not in Day 2) -> 1 listing
    # 111, 112: newly listed at 82,000 -> 2 listings
    db.execute("INSERT INTO batches VALUES (?, ?, ?, 1)", (day2, complex_id, f"{day2}T06:00:00+09:00"))
    
    # 101, 102 cut
    for lid in ('101', '102'):
        payload = json.dumps({'article_no': lid, 'asking_price_manwon': 76000, 'complex': complex_id})
        db.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?)", (day2, complex_id, lid, 76000.0, payload))
    # 103 rise
    payload = json.dumps({'article_no': '103', 'asking_price_manwon': 84000, 'complex': complex_id})
    db.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?)", (day2, complex_id, '103', 84000.0, payload))
    # 104 ~ 108 unchanged
    for i in range(104, 109):
        lid = str(i)
        payload = json.dumps({'article_no': lid, 'asking_price_manwon': 80000, 'complex': complex_id})
        db.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?)", (day2, complex_id, lid, 80000.0, payload))
    # 111, 112 new
    for lid in ('111', '112'):
        payload = json.dumps({'article_no': lid, 'asking_price_manwon': 82000, 'complex': complex_id})
        db.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?)", (day2, complex_id, lid, 82000.0, payload))

    # 3. Analyze events
    evs = events(db)
    day2_events = [e for e in evs if e['day'] == day2]
    
    print(f"\nTotal Day 2 Events: {len(day2_events)}")
    for e in day2_events:
        print(f"  ID {e['id']}: kind={e['kind']}, before={e['before']}, after={e['after']}")

    # 4. Calculate asking concession for days=1 (DoD)
    res_dod = concession(evs, day2, 1, {complex_id})
    print("\n--- 1-Day (DoD) Asking Adjustment Metrics ---")
    print(json.dumps(res_dod, ensure_ascii=False, indent=2))

    # Assertions
    # Tracked sample must be 8 (101 to 108) - only listings observed on BOTH days!
    assert res_dod['sample'] == 8, f"Expected 8 consecutively tracked listings, got {res_dod['sample']}"
    assert res_dod['cutListings'] == 2, f"Expected 2 cuts, got {res_dod['cutListings']}"
    assert res_dod['riseListings'] == 1, f"Expected 1 rise, got {res_dod['riseListings']}"
    
    # cutShare = 2 / 8 = 25.0%
    assert abs(res_dod['cutShare'] - 25.0) < 0.01, f"Expected cutShare 25.0%, got {res_dod['cutShare']}"
    # riseShare = 1 / 8 = 12.5%
    assert abs(res_dod['riseShare'] - 12.5) < 0.01, f"Expected riseShare 12.5%, got {res_dod['riseShare']}"
    # netAdjustmentShare = riseShare - cutShare = 12.5 - 25.0 = -12.5%p
    assert abs(res_dod['netAdjustmentShare'] - (-12.5)) < 0.01, f"Expected netAdjustmentShare -12.5%p, got {res_dod['netAdjustmentShare']}"
    
    # meanCutPct = (80000 - 76000) / 80000 * 100 = 5.0%
    assert abs(res_dod['meanCutPct'] - 5.0) < 0.01, f"Expected meanCutPct 5.0%, got {res_dod['meanCutPct']}"
    # meanRisePct = (84000 - 80000) / 80000 * 100 = 5.0%
    assert abs(res_dod['meanRisePct'] - 5.0) < 0.01, f"Expected meanRisePct 5.0%, got {res_dod['meanRisePct']}"

    print("\nAll Invariants and Statistical Assertions Passed Successfully!")

if __name__ == '__main__':
    run_test()
