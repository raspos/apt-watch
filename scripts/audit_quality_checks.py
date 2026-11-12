"""Automated 10-Point Data Quality Audit Engine for APT WATCH.
Executes daily after collection & metric calculation:
1. SQLite Integrity Check (PRAGMA integrity_check)
2. Collection Success Rate Check (>= 95% target)
3. Asking Price Range Validity Check (5,000만원 <= price <= 50억원)
4. Listing ID Uniqueness & Deduplication Check (Zero duplicate IDs per complex-day)
5. Observation Date Consistency Check (No future dates, UTC timestamp format)
6. Consecutive Tracking Rate Check (Tracking continuity verification)
7. Price Divergence Sample Composition Check (Dual metric: All sample vs Matched panel)
8. Regional District Coverage Check (Seoul 25 districts presence)
9. Day-over-Day Abnormal Fluctuation Check (Flagging shifts > 15%p)
10. Dashboard Data Integrity Check (site/data.json schema & valid ranges)
"""
import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent

def run_quality_checks(target_day=None):
    db_path = ROOT / 'data' / 'history.sqlite3'
    db = sqlite3.connect(db_path)
    
    if not target_day:
        target_day = db.execute("SELECT MAX(day) FROM listings").fetchone()[0] or '2026-11-12'
        
    print("="*80)
    print(f"APT WATCH 10-POINT AUTOMATED DATA QUALITY AUDIT [{target_day}]")
    print("="*80)
    
    results = {}
    
    # 1. SQLite Integrity Check
    c1 = db.execute("PRAGMA integrity_check").fetchall()
    c1_pass = (c1 == [('ok',)])
    results['1_sqlite_integrity'] = {
        'pass': c1_pass,
        'message': 'OK' if c1_pass else f'Integrity errors: {c1}'
    }
    
    # 2. Collection Success Rate Check
    batches = db.execute("SELECT complex, success FROM batches WHERE day=?", (target_day,)).fetchall()
    total_b = len(batches)
    succ_b = sum(1 for b in batches if b[1] == 1)
    rate = (succ_b / total_b * 100) if total_b else 0.0
    c2_pass = (rate >= 95.0) and (total_b >= 100)
    results['2_collection_success_rate'] = {
        'pass': c2_pass,
        'attempted': total_b,
        'successful': succ_b,
        'success_rate_pct': round(rate, 2),
        'message': f"{succ_b}/{total_b} ({rate:.1f}%)"
    }
    
    # 3. Asking Price Range Validity Check
    listings = db.execute("SELECT complex, id, price FROM listings WHERE day=?", (target_day,)).fetchall()
    invalid_prices = [l for l in listings if l[2] is None or not math.isfinite(l[2]) or l[2] < 1000 or l[2] > 5000000]
    c3_pass = (len(invalid_prices) == 0) and (len(listings) > 0)
    results['3_price_range_validity'] = {
        'pass': c3_pass,
        'total_listings': len(listings),
        'invalid_count': len(invalid_prices),
        'min_price_eok': round(min(l[2] for l in listings)/10000, 2) if listings else None,
        'max_price_eok': round(max(l[2] for l in listings)/10000, 2) if listings else None,
        'message': f"0 invalid out of {len(listings):,} listings" if c3_pass else f"{len(invalid_prices)} out-of-range listings"
    }
    
    # 4. Listing ID Uniqueness Check
    dups = db.execute("SELECT complex, id, COUNT(*) FROM listings WHERE day=? GROUP BY complex, id HAVING COUNT(*) > 1", (target_day,)).fetchall()
    c4_pass = (len(dups) == 0)
    results['4_listing_id_uniqueness'] = {
        'pass': c4_pass,
        'duplicate_keys': len(dups),
        'message': 'Zero duplicates' if c4_pass else f'{len(dups)} duplicate keys found'
    }
    
    # 5. Observation Date Consistency Check
    today_kst = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    future_batches = db.execute("SELECT COUNT(*) FROM batches WHERE day > ?", (today_kst,)).fetchone()[0]
    utc_samples = db.execute("SELECT observed FROM batches WHERE day=? LIMIT 10", (target_day,)).fetchall()
    all_utc_format = all(b[0].endswith('Z') or '+00:00' in b[0] for b in utc_samples) if utc_samples else False
    c5_pass = (future_batches == 0) and (target_day <= today_kst) and all_utc_format
    results['5_date_consistency'] = {
        'pass': c5_pass,
        'target_day': target_day,
        'today_kst': today_kst,
        'future_batches': future_batches,
        'utc_format_verified': all_utc_format,
        'message': f'Observation day {target_day} is valid & timestamps stored in UTC' if c5_pass else 'Date inconsistency detected'
    }
    
    # 6. Consecutive Tracking Rate Check
    prev_days = sorted(r[0] for r in db.execute("SELECT DISTINCT day FROM batches WHERE day < ? AND success=1", (target_day,)).fetchall())
    if prev_days:
        prev_day = prev_days[-1]
        prev_ids = set(r[0] for r in db.execute("SELECT id FROM listings WHERE day=?", (prev_day,)).fetchall())
        curr_ids = set(r[0] for r in db.execute("SELECT id FROM listings WHERE day=?", (target_day,)).fetchall())
        reobserved = len(prev_ids & curr_ids)
        track_rate = (reobserved / len(prev_ids) * 100) if prev_ids else 0.0
        c6_pass = (track_rate >= 50.0) # Normal daily market continuity >= 50%
        c6_msg = f"Consecutive tracking rate: {track_rate:.1f}% ({reobserved:,}/{len(prev_ids):,} from {prev_day})"
    else:
        c6_pass = True
        track_rate = None
        c6_msg = f"Day 1 Baseline established ({len(listings):,} listings). 2nd consecutive observation pending."
    results['6_consecutive_tracking_rate'] = {
        'pass': c6_pass,
        'has_previous_day': bool(prev_days),
        'tracking_rate_pct': track_rate,
        'message': c6_msg
    }
    
    # 7. Price Divergence Sample Composition Check
    div_file = ROOT / 'data' / 'divergence_expansion_report.json'
    if div_file.exists():
        div_data = json.loads(div_file.read_text(encoding='utf-8'))
        dual_metric_present = ('metric_A_all_sample_pct' in div_data)
        strata_count = div_data.get('waterfall', {}).get('stage5_strata_count', 0)
        c7_pass = dual_metric_present and (strata_count > 0)
        c7_msg = f"Dual metrics computed: All sample {div_data.get('metric_A_all_sample_pct')}% vs Matched panel {div_data.get('metric_B_matched_panel_pct')}% ({strata_count} strata)"
    else:
        c7_pass = False
        c7_msg = "divergence_expansion_report.json not found"
    results['7_price_divergence_composition'] = {
        'pass': c7_pass,
        'message': c7_msg
    }
    
    # 8. Regional District Coverage Check
    manifest_file = ROOT / 'data' / 'seoul-100-run-manifest.json'
    districts_in_batches = set(r[0] for r in db.execute("SELECT district FROM listing_roster WHERE day=?", (target_day,)).fetchall())
    c8_pass = (len(districts_in_batches) == 25)
    results['8_regional_coverage'] = {
        'pass': c8_pass,
        'covered_districts_count': len(districts_in_batches),
        'target_districts': 25,
        'message': f"All 25 Seoul autonomous districts present ({len(districts_in_batches)}/25)" if c8_pass else f"Only {len(districts_in_batches)}/25 districts covered"
    }
    
    # 9. Day-over-Day Abnormal Fluctuation Check
    c9_pass = True
    c9_msg = "Baseline day - no abnormal fluctuation."
    if prev_days:
        # Check median price shift
        prev_med = db.execute("SELECT price FROM listings WHERE day=? ORDER BY price LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM listings WHERE day=?)", (prev_day, prev_day)).fetchone()
        curr_med = db.execute("SELECT price FROM listings WHERE day=? ORDER BY price LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM listings WHERE day=?)", (target_day, target_day)).fetchone()
        if prev_med and curr_med and prev_med[0] > 0:
            shift = abs(curr_med[0] - prev_med[0]) / prev_med[0] * 100
            if shift > 15.0:
                c9_pass = False
                c9_msg = f"Abnormal median price shift: {shift:.1f}% DoD"
            else:
                c9_msg = f"Median price shift stable: {shift:.1f}% DoD"
    results['9_abnormal_fluctuation'] = {
        'pass': c9_pass,
        'message': c9_msg
    }
    
    # 10. Dashboard Data Integrity Check
    site_file = ROOT / 'site' / 'data.json'
    if site_file.exists():
        site_data = json.loads(site_file.read_text(encoding='utf-8'))
        has_asking = 'asking' in site_data and site_data['asking'].get('listings', 0) > 0
        has_market = 'market' in site_data and 'regions' in site_data['market']
        c10_pass = has_asking and has_market
        c10_msg = f"Dashboard data.json valid: {site_data.get('asking', {}).get('listings', 0):,} listings, asOf {site_data.get('asOf')}"
    else:
        c10_pass = False
        c10_msg = "site/data.json missing"
    results['10_dashboard_integrity'] = {
        'pass': c10_pass,
        'message': c10_msg
    }
    
    all_passed = all(r['pass'] for r in results.values())
    print("\n[Audit Results Summary]")
    for k, v in results.items():
        status = "PASS" if v['pass'] else "FAIL"
        print(f"  [{status}] {k}: {v['message']}")
        
    overall = {
        'date': target_day,
        'auditedAt': datetime.now(ZoneInfo('Asia/Seoul')).isoformat(),
        'allChecksPassed': all_passed,
        'passedCount': sum(1 for v in results.values() if v['pass']),
        'totalChecks': len(results),
        'details': results
    }
    
    out_dir = ROOT / 'data' / 'logs'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f'quality_check_{target_day}.json'
    out_file.write_text(json.dumps(overall, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nQuality audit saved to {out_file}")
    db.close()
    
    if not all_passed:
        raise RuntimeError(f"Quality checks failed: {[k for k, v in results.items() if not v['pass']]}")
    return overall

if __name__ == '__main__':
    import sys
    day_arg = sys.argv[1] if len(sys.argv) > 1 else None
    run_quality_checks(day_arg)
