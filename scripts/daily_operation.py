"""Production Daily Operation Runner for APT WATCH.
Executes daily at 06:00 KST:
1. Pre-execution DB integrity check & snapshot directory setup.
2. Supervised collection of 100 fixed sample (+ Yangcheon baseline, 108 total) with auto-resume.
3. Post-collection analytical pipeline:
   - Consecutive observation (DoD) & Asking Adjustment Index
   - Price Divergence Index 6-stage matching waterfall
   - Representativeness audit & stratified weighting
   - 8-metric daily operational audit log
   - Atomic update of site/data.json
4. Full test suite verification & final health check.
"""
import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent

def check_db_integrity(db_path):
    print(f"[DB Check] Verifying integrity for {db_path.name}...")
    db = sqlite3.connect(db_path)
    res = db.execute("PRAGMA integrity_check").fetchall()
    db.close()
    if res != [('ok',)]:
        raise RuntimeError(f"Database integrity check failed: {res}")
    print("[DB Check] PRAGMA integrity_check: OK")

def run_step(name, script_path, args=None):
    cmd = [sys.executable, str(script_path)] + (args or [])
    print(f"\n>>> Running: {name} ({script_path.name})")
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    elapsed = time.time() - t0
    if res.returncode != 0:
        print(f"FAILED {name} in {elapsed:.2f}s:\n{res.stderr}\n{res.stdout}")
        raise RuntimeError(f"Step {name} failed: {res.stderr}")
    print(f"COMPLETED {name} in {elapsed:.2f}s")
    if res.stdout:
        print(res.stdout.strip())
    return res.stdout

def run_daily_operation(day=None, manifest_path=None, resume=True, timeout=3600, workers=8):
    start_time = datetime.now(ZoneInfo('Asia/Seoul'))
    target_day = day or start_time.date().isoformat()
    manifest_file = Path(manifest_path) if manifest_path else (ROOT / 'data' / 'seoul-expanded-manifest.json')
    db_file = ROOT / 'data' / 'history.sqlite3'
    
    print("="*80)
    print(f"APT WATCH DAILY OPERATION [{target_day}] START")
    print(f"Manifest: {manifest_file.name}, DB: {db_file.name}, Resume: {resume}, Workers: {workers}")
    print("="*80)
    
    # 1. Pre-execution DB integrity check
    if db_file.exists():
        check_db_integrity(db_file)
        
    # 2. Snapshot directory
    snapshot_dir = ROOT / 'data' / 'snapshots' / target_day
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    
    # 3. Supervised Multi-Worker Collection
    if workers > 1:
        collector_args = [
            sys.executable,
            str(ROOT / 'scripts' / 'parallel_collector.py'),
            '--manifest', str(manifest_file),
            '--store', str(db_file),
            '--workers', str(workers),
            '--timeout', str(timeout),
            '--day', target_day
        ]
        if not resume:
            collector_args.append('--no-resume')
    else:
        collector_args = [
            sys.executable,
            str(ROOT / 'supervise_naver.py'),
            '--timeout', str(timeout),
            '--',
            '--manifest', str(manifest_file),
            '--store', str(db_file),
            '--day', target_day
        ]
        if resume:
            collector_args.append('--resume')
        
    print(f"\n[Step 1] Starting supervised Naver collection (workers: {workers}, timeout: {timeout}s)...")
    col_t0 = time.time()
    col_res = subprocess.run(collector_args, capture_output=True, text=True, encoding='utf-8')
    col_elapsed = time.time() - col_t0
    print(f"Collector finished with return code {col_res.returncode} in {col_elapsed:.2f}s")
    if col_res.stdout:
        last_lines = col_res.stdout.strip().splitlines()[-10:]
        print("\n".join(last_lines))
    if col_res.returncode != 0:
        print(f"WARNING: Collector exited with code {col_res.returncode}. Proceeding with collected data.")
        
    # 4. Save raw listings snapshot to JSONL
    print(f"\n[Step 2] Dumping raw snapshot to {snapshot_dir}...")
    db = sqlite3.connect(db_file)
    cur = db.cursor()
    cur.execute("SELECT payload FROM listings WHERE day=?", (target_day,))
    raw_file = snapshot_dir / 'raw_listings.jsonl'
    with open(raw_file, 'w', encoding='utf-8') as f:
        count = 0
        for (payload_str,) in cur:
            f.write(payload_str + '\n')
            count += 1
    print(f"Saved {count:,} listings to {raw_file.name}")
    db.close()
    
    # 5. Post-collection analytics
    print("\n[Step 3] Running Analytical Pipeline...")
    run_step("1. Consecutive Observation Analysis", ROOT / 'scripts' / 'analyze_consecutive_observation.py')
    run_step("2. Price Divergence Waterfall", ROOT / 'scripts' / 'audit_price_divergence_expanded.py')
    run_step("3. Representativeness Audit", ROOT / 'scripts' / 'audit_representativeness.py')
    run_step("4. Daily Audit Log Generation", ROOT / 'scripts' / 'generate_daily_audit_log.py')
    
    # 6. Rebuild Dashboard Data & Market Metrics
    print("\n[Step 4] Rebuilding Site Data...")
    run_step("5. Rebuild apt_watch", ROOT / 'apt_watch.py', ['--day', target_day])
    run_step("6. Rebuild nego_pressure", ROOT / 'nego_pressure.py')
    
    # 7. Post-run Automated 10-Point Quality Audit & Backup
    print("\n[Step 5] Post-run Automated Quality Verification...")
    run_step("7. 10-Point Data Quality Audit", ROOT / 'scripts' / 'audit_quality_checks.py', [target_day])
    
    # 8. Create Online Database Backup
    print(f"\n[Step 6] Creating standalone SQLite Backup for {target_day}...")
    backup_dir = ROOT / 'data' / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_file = backup_dir / f'history_backup_{target_day}.sqlite3'
    src_db = sqlite3.connect(db_file)
    dst_db = sqlite3.connect(backup_file)
    src_db.backup(dst_db)
    dst_db.close()
    src_db.close()
    check_db_integrity(backup_file)
    print(f"Verified standalone backup saved to {backup_file.name}")
    
    # 9. Full Test Suite Verification
    print("\n[Step 7] Full Test Suite Verification...")
    test_res = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v'],
                              cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8')
    if test_res.returncode != 0:
        print(f"Unit test failure:\n{test_res.stderr}\n{test_res.stdout}")
        raise RuntimeError("Post-run unit tests failed")
    print("All unit tests passed successfully!")
    
    # 10. Automated Public Deployment via GitHub
    print("\n[Step 8] Pushing verified site payload to GitHub...")
    subprocess.run(['git', 'add', 'site/data.json'], cwd=str(ROOT), capture_output=True, text=True)
    git_diff = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=str(ROOT))
    if git_diff.returncode != 0:
        commit_msg = f"data: daily update {target_day}"
        subprocess.run(['git', 'commit', '-m', commit_msg], cwd=str(ROOT), capture_output=True, text=True)
        push_res = subprocess.run(['git', 'push', 'origin', 'main'], cwd=str(ROOT), capture_output=True, text=True)
        if push_res.returncode == 0:
            print(f"Successfully pushed daily update ({target_day}) to GitHub origin main.")
        else:
            print(f"Warning: git push returned code {push_res.returncode}: {push_res.stderr}")
    else:
        print("site/data.json is unchanged; no new git commit needed.")
    
    end_time = datetime.now(ZoneInfo('Asia/Seoul'))
    total_elapsed = (end_time - start_time).total_seconds()
    print("="*80)
    print(f"APT WATCH DAILY OPERATION [{target_day}] COMPLETED IN {total_elapsed:.2f}s")
    print("="*80)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--day', help='Observation day (YYYY-MM-DD)')
    parser.add_argument('--manifest', help='Path to manifest JSON')
    parser.add_argument('--no-resume', action='store_true', help='Force re-scrape all complexes')
    parser.add_argument('--timeout', type=int, default=3600, help='Collector timeout in seconds')
    parser.add_argument('--workers', type=int, default=8, help='Number of parallel browser workers (default: 8)')
    args = parser.parse_args()
    
    run_daily_operation(
        day=args.day,
        manifest_path=args.manifest,
        resume=not args.no_resume,
        timeout=args.timeout,
        workers=args.workers
    )
