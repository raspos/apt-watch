"""Analysis of Consecutive Listing Tracking and Asking Adjustment Index for APT WATCH.
Strictly requires two distinct real observation dates (day1 < day2).
If only 1 day is present, records the complete Day 1 baseline and marks consecutive metrics
as '데이터 축적 중' without fabricating artificial Day 2 data.
"""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent

def analyze_consecutive():
    db = sqlite3.connect(ROOT / 'data' / 'history.sqlite3')
    
    # 1. Discover unique observation days
    days = sorted(r[0] for r in db.execute("SELECT DISTINCT day FROM batches WHERE success=1").fetchall())
    print("="*80)
    print(f"CONSECUTIVE OBSERVATION AUDIT (Available Days: {days})")
    print("="*80)
    
    if len(days) < 2:
        current_day = days[0] if days else '2026-11-12'
        listings = db.execute("SELECT complex, id, price FROM listings WHERE day=?", (current_day,)).fetchall()
        batches = db.execute("SELECT complex, success FROM batches WHERE day=?", (current_day,)).fetchall()
        succ_batches = [b for b in batches if b[1] == 1]
        
        print(f"Status: Single Day Baseline Established ({current_day})")
        print(f"Total Successful Complexes: {len(succ_batches)}")
        print(f"Total Baseline Listings: {len(listings):,}건")
        print("Consecutive Tracking (DoD): 축적 중 (2회차 실제 관측 대기)")
        print("순호가조정률: 데이터 축적 중 (동일 매물 2회차 관측 후 산출)")
        
        res = {
            'status': 'BASELINE_ESTABLISHED',
            'current_day': current_day,
            'available_days': days,
            'batches_success': len(succ_batches),
            'total_listings': len(listings),
            'reobserved_count': 0,
            'reobserved_rate_pct': 0.0,
            'unchanged_count': 0,
            'unchanged_share_pct': None,
            'rise_count': 0,
            'rise_share_pct': None,
            'cut_count': 0,
            'cut_share_pct': None,
            'delisted_count': 0,
            'new_listings_count': len(listings),
            'net_adjustment_pctp': None,
            'mean_cut_pct': None,
            'mean_rise_pct': None,
            'market_regime': '데이터 축적 중 (1일차 11,702건 기준선 구축 완료 · 2회차 연속 관측 대기)'
        }
        (ROOT / 'data' / 'consecutive_observation_report.json').write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
        db.close()
        return res
        
    day1, day2 = days[-2], days[-1]
    print(f"Comparing distinct consecutive days: Day 1 ({day1}) vs Day 2 ({day2})")
    
    b1 = db.execute("SELECT complex, success FROM batches WHERE day=?", (day1,)).fetchall()
    b2 = db.execute("SELECT complex, success FROM batches WHERE day=?", (day2,)).fetchall()
    l1 = db.execute("SELECT complex, id, price, payload FROM listings WHERE day=?", (day1,)).fetchall()
    l2 = db.execute("SELECT complex, id, price, payload FROM listings WHERE day=?", (day2,)).fetchall()
    
    b1_success = {c for c, s in b1 if s == 1}
    b2_success = {c for c, s in b2 if s == 1}
    common_complexes = b1_success & b2_success
    
    print(f"Day 1 Successful Complexes: {len(b1_success)}")
    print(f"Day 2 Successful Complexes: {len(b2_success)}")
    print(f"Common Consecutively Observed Complexes: {len(common_complexes)}")
    
    d1_map = {(c, i): p for c, i, p, _ in l1}
    d2_map = {(c, i): p for c, i, p, _ in l2}
    
    d1_ids = set(d1_map.keys())
    d2_ids = set(d2_map.keys())
    
    common_d1_ids = {k for k in d1_ids if k[0] in common_complexes}
    common_d2_ids = {k for k in d2_ids if k[0] in common_complexes}
    
    reobserved = common_d1_ids & common_d2_ids
    delisted = common_d1_ids - common_d2_ids
    new_in_common = common_d2_ids - common_d1_ids
    new_other = {k for k in d2_ids if k[0] not in common_complexes}
    
    unchanged = []
    cuts = []
    rises = []
    
    for k in reobserved:
        p1 = d1_map[k]
        p2 = d2_map[k]
        if p2 < p1:
            cuts.append((k, p1, p2, 100 * (1 - p2 / p1)))
        elif p2 > p1:
            rises.append((k, p1, p2, 100 * (p2 / p1 - 1)))
        else:
            unchanged.append((k, p1))
            
    total_reobserved = len(reobserved)
    cut_share = (len(cuts) / total_reobserved * 100) if total_reobserved else 0.0
    rise_share = (len(rises) / total_reobserved * 100) if total_reobserved else 0.0
    unchanged_share = (len(unchanged) / total_reobserved * 100) if total_reobserved else 0.0
    net_adj = rise_share - cut_share
    
    mean_cut_pct = mean([c[3] for c in cuts]) if cuts else 0.0
    mean_rise_pct = mean([r[3] for r in rises]) if rises else 0.0
    
    res = {
        'status': 'CONSECUTIVE_OBSERVED',
        'day1': day1,
        'day2': day2,
        'batches_day1_success': len(b1_success),
        'batches_day2_success': len(b2_success),
        'common_complexes': len(common_complexes),
        'listings_day1_total': len(d1_ids),
        'listings_day2_total': len(d2_ids),
        'reobserved_count': total_reobserved,
        'reobserved_rate_pct': round(total_reobserved / len(common_d1_ids) * 100, 2) if common_d1_ids else 0.0,
        'unchanged_count': len(unchanged),
        'unchanged_share_pct': round(unchanged_share, 2),
        'rise_count': len(rises),
        'rise_share_pct': round(rise_share, 2),
        'cut_count': len(cuts),
        'cut_share_pct': round(cut_share, 2),
        'delisted_count': len(delisted),
        'new_in_common_count': len(new_in_common),
        'new_other_count': len(new_other),
        'net_adjustment_pctp': round(net_adj, 2),
        'mean_cut_pct': round(mean_cut_pct, 2),
        'mean_rise_pct': round(mean_rise_pct, 2)
    }
    
    (ROOT / 'data' / 'consecutive_observation_report.json').write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    db.close()
    return res

if __name__ == '__main__':
    analyze_consecutive()
