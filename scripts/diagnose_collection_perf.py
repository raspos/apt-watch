import sqlite3
import statistics
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def main():
    db = sqlite3.connect(ROOT / 'data' / 'history.sqlite3')
    cur = db.cursor()
    
    rows = cur.execute("SELECT complex, observed, success FROM batches WHERE day='2026-11-12' ORDER BY observed").fetchall()
    print(f"Total batches for 2026-11-12: {len(rows)}")
    
    times = [datetime.fromisoformat(r[1].replace('Z', '+00:00')) for r in rows]
    intervals = [(times[i] - times[i-1]).total_seconds() for i in range(1, len(times))]
    
    total_span_sec = (times[-1] - times[0]).total_seconds()
    print(f"First observation: {times[0]}")
    print(f"Last observation: {times[-1]}")
    print(f"Total span: {total_span_sec:.1f}s ({total_span_sec/60:.1f} minutes, {total_span_sec/3600:.2f} hours)")
    
    # Filter out pauses (e.g. gaps > 60s when batches were run in separate sessions)
    active_intervals = [x for x in intervals if x < 60]
    paused_intervals = [x for x in intervals if x >= 60]
    
    print("\n--- Interval Statistics (All) ---")
    print(f"Average interval: {statistics.mean(intervals):.2f}s")
    print(f"Median interval: {statistics.median(intervals):.2f}s")
    
    print("\n--- Active In-Flight Intervals (gap < 60s, continuous runs) ---")
    print(f"Count of continuous steps: {len(active_intervals)}")
    if active_intervals:
        print(f"Mean continuous step time: {statistics.mean(active_intervals):.2f}s")
        print(f"Median continuous step time: {statistics.median(active_intervals):.2f}s")
        quantiles = statistics.quantiles(active_intervals, n=100)
        print(f"P75: {quantiles[74]:.2f}s, P90: {quantiles[89]:.2f}s, P95: {quantiles[94]:.2f}s")
        print(f"Min: {min(active_intervals):.2f}s, Max: {max(active_intervals):.2f}s")
    
    print(f"\nDiscontinuous Gaps / Batch Pauses (gap >= 60s): {len(paused_intervals)} pauses, total paused: {sum(paused_intervals):.1f}s")
    for p in paused_intervals:
        print(f"  Gap: {p:.1f}s ({p/60:.1f}m)")

    # Analyze listings per complex
    listing_counts = cur.execute("""
        SELECT complex, COUNT(*) as cnt 
        FROM listings 
        WHERE day='2026-11-12' 
        GROUP BY complex
    """).fetchall()
    cnts = [r[1] for r in listing_counts]
    print("\n--- Listings per Complex ---")
    print(f"Total complexes with listings: {len(cnts)}")
    print(f"Total listings: {sum(cnts):,}건")
    print(f"Average listings per complex: {statistics.mean(cnts):.1f}건")
    print(f"Median listings per complex: {statistics.median(cnts):.1f}건")
    print(f"Min: {min(cnts)}건, Max: {max(cnts)}건")
    cnt_q = statistics.quantiles(cnts, n=100)
    print(f"P75: {cnt_q[74]:.1f}건, P90: {cnt_q[89]:.1f}건, P95: {cnt_q[94]:.1f}건")

    # Check collector implementation
    print("\n--- Collector Analysis (collect_naver.py & supervise_naver.py) ---")
    with open(ROOT / 'collect_naver.py', encoding='utf-8') as f:
        c_code = f.read()
    with open(ROOT / 'supervise_naver.py', encoding='utf-8') as f:
        s_code = f.read()
    
    print("collect_naver concurrency / threading:", "ThreadPoolExecutor" in c_code or "asyncio" in c_code)
    print("supervise_naver concurrency:", "ThreadPoolExecutor" in s_code or "asyncio" in s_code)
    
    # Check rate limiting / sleeps in collect_naver
    import re
    sleeps = re.findall(r'sleep\((.*?)\)', c_code)
    print(f"sleep calls in collect_naver.py: {sleeps}")

if __name__ == '__main__':
    main()
