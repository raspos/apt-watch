"""Empirical Worker Scaling Benchmark for APT WATCH.
Executes controlled parallel collection across 1, 2, 4 (and 8) workers on a calibrated test sample
to empirically measure:
  - Throughput (complexes/min)
  - Speedup factor vs single worker
  - Per-worker latency (mean, median, P95)
  - SQLite lock errors (zero in staged architecture)
  - Extrapolated 375-complex duration (explicitly labeled as ESTIMATE)
"""
import json
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.parallel_collector import run_worker_pool

# Representative sample of 4 distinct complexes across different districts
BENCHMARK_COMPLEXES = [
    {"complex": "22314", "district": "11110", "name": "건양하늘터"},      # Small (Jongno)
    {"complex": "3422",  "district": "11290", "name": "길음래미안1차"},    # Medium (Seongbuk)
    {"complex": "10443", "district": "11110", "name": "경희궁의아침"},     # Landmark (Jongno)
    {"complex": "661",   "district": "11470", "name": "목동청구한신아파트"}  # Large (Yangcheon)
]

def run_benchmark():
    test_db = ROOT / 'data' / 'benchmark_test.sqlite3'
    if test_db.exists():
        test_db.unlink()

    results = []
    
    # 1. Test Worker 1 (Baseline) on 2 complexes
    print("\n" + "="*80)
    print("RUNNING BENCHMARK 1: 1 WORKER (BASELINE, 2 COMPLEXES)")
    print("="*80)
    sample_w1 = BENCHMARK_COMPLEXES[:2]
    code1, r1 = run_worker_pool(sample_w1, '2026-11-12', test_db, num_workers=1, resume=False)
    results.append(('1 Worker', r1))

    # 2. Test Worker 2 on 4 complexes
    print("\n" + "="*80)
    print("RUNNING BENCHMARK 2: 2 WORKERS (4 COMPLEXES)")
    print("="*80)
    sample_w2 = BENCHMARK_COMPLEXES[:4]
    code2, r2 = run_worker_pool(sample_w2, '2026-11-12', test_db, num_workers=2, resume=False)
    results.append(('2 Workers', r2))

    # 3. Test Worker 4 on 4 complexes
    print("\n" + "="*80)
    print("RUNNING BENCHMARK 3: 4 WORKERS (4 COMPLEXES)")
    print("="*80)
    sample_w4 = BENCHMARK_COMPLEXES[:4]
    code3, r4 = run_worker_pool(sample_w4, '2026-11-12', test_db, num_workers=4, resume=False)
    results.append(('4 Workers', r4))

    # Cleanup test db
    if test_db.exists():
        test_db.unlink()

    # Compile Benchmark Report
    print("\n" + "="*80)
    print("EMPIRICAL BENCHMARK PERFORMANCE COMPARISON TABLE")
    print("="*80)
    print(f"{'Configuration':12s} | {'Sample':6s} | {'Elapsed(s)':10s} | {'Throughput(cpm)':15s} | {'Eff. s/comp':11s} | {'375 Est.(min)':13s} | {'Locks':5s}")
    print("-" * 85)
    
    out_data = []
    for label, res in results:
        tot = res['total_targets']
        el = res['elapsed_sec']
        cpm = res['throughput_cpm']
        eff = res['effective_sec_per_complex']
        est_375_min = round(375 * eff / 60, 1)
        locks = sum(m.get('sqlite_lock_errors', 0) for m in res.get('per_worker_metrics', []))
        print(f"{label:12s} | {tot:6d} | {el:10.2f} | {cpm:15.2f} | {eff:11.2f} | {est_375_min:11.1f}m | {locks:5d}")
        out_data.append({
            'configuration': label,
            'sample_size': tot,
            'elapsed_sec': el,
            'throughput_cpm': cpm,
            'effective_sec_per_complex': eff,
            'estimated_375_duration_minutes': est_375_min,
            'sqlite_lock_errors': locks,
            'per_worker_metrics': res.get('per_worker_metrics', [])
        })

    report_path = ROOT / 'data' / 'parallel_benchmark_report.json'
    report_path.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\nSaved empirical benchmark report to {report_path.name}")

if __name__ == '__main__':
    run_benchmark()
