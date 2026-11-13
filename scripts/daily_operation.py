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
from datetime import datetime, timezone
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

def find_suspect_collections(cur, target_day, success_ids, min_prev=10, collapse_ratio=0.30):
    """Complexes flagged success=1 whose listing count collapsed vs. the previous observed day.

    A browser collector can return an empty or truncated page without raising an error. Treating
    those as successes would make a scrape failure look like a market change. A complex is
    SUSPECT when the previous day had >= min_prev listings and today has 0 listings or less
    than collapse_ratio of the previous count. Observations are never modified; only the gate
    numerator is affected.
    """
    prev_day = cur.execute("SELECT MAX(day) FROM listings WHERE day < ?", (target_day,)).fetchone()[0]
    if not prev_day:
        return set()
    prev = dict(cur.execute("SELECT complex, COUNT(*) FROM listings WHERE day=? GROUP BY complex", (prev_day,)).fetchall())
    curr = dict(cur.execute("SELECT complex, COUNT(*) FROM listings WHERE day=? GROUP BY complex", (target_day,)).fetchall())
    suspects = set()
    for cid in success_ids:
        p, c = prev.get(cid, 0), curr.get(cid, 0)
        if p >= min_prev and c < p * collapse_ratio:
            suspects.add(str(cid))
    return suspects


def evaluate_quality_gate(planned_count, successful_count):
    """Evaluate quality gate based on planned denominator vs successful numerator.
    Returns (status, success_rate, error_message or None).
    Status policies:
      - FULL_SUCCESS (>= 95.0%): Normal analytics & official index publication allowed.
      - PARTIAL_SUCCESS (80.0% <= rate < 95.0%): Internal data & logs preserved, official public release deferred.
      - CORE_QUALITY_BREACH (< 80.0%): Analytics & release aborted, error logged.
    """
    if planned_count <= 0:
        return 'CORE_QUALITY_BREACH', 0.0, "당일 수집 예정 단지 수가 0 이하입니다."
    
    rate = successful_count / planned_count
    rate_pct = round(rate * 100, 2)
    
    if rate < 0.80:
        msg = f"핵심 표본 수집 성공률({rate_pct}%)이 최소 품질 기준(80.0%)에 미달했습니다."
        return 'CORE_QUALITY_BREACH', rate, msg
    elif rate < 0.95:
        msg = f"부분 수집 완료 ({rate_pct}%). 품질 기준(95.0%) 미달로 공식 확정지수 공표가 유예됩니다."
        return 'PARTIAL_SUCCESS', rate, msg
    else:
        return 'FULL_SUCCESS', rate, None

def run_daily_operation(day=None, manifest_path=None, resume=True, timeout=3600, workers=8):
    start_time = datetime.now(ZoneInfo('Asia/Seoul'))
    target_day = day or start_time.date().isoformat()
    manifest_file = Path(manifest_path) if manifest_path else (ROOT / 'data' / 'fixed-110-panel.json')
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

    # 3-1. Automatic Sequential Retry for Failed Complexes before Quality Gate
    db = sqlite3.connect(db_file)
    cur = db.cursor()
    failed_complex_ids = [str(r[0]) for r in cur.execute("SELECT complex FROM batches WHERE day=? AND success=0", (target_day,)).fetchall()]
    db.close()
    if failed_complex_ids:
        print(f"\n[Step 1-1] Auto-retrying {len(failed_complex_ids)} failed complexes...")
        retry_manifest = [c for c in json.loads(manifest_file.read_text(encoding='utf-8-sig')) if str(c['complex']) in set(failed_complex_ids)]
        if retry_manifest:
            retry_mf_path = ROOT / 'data' / 'staging' / f'retry_{target_day}_manifest.json'
            retry_mf_path.parent.mkdir(parents=True, exist_ok=True)
            retry_mf_path.write_text(json.dumps(retry_manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            retry_store = ROOT / 'data' / 'staging' / f'retry_{target_day}_temp.sqlite3'
            if retry_store.exists():
                retry_store.unlink()
            cmd_retry = [
                sys.executable, '-u', str(ROOT / 'collect_naver.py'),
                '--manifest', str(retry_mf_path),
                '--store', str(retry_store),
                '--day', target_day
            ]
            try:
                rr = subprocess.run(cmd_retry, capture_output=True, text=True, encoding='utf-8', timeout=1800)
                if rr.returncode != 0:
                    print(f"[Step 1-1] WARNING: retry collector exited with code {rr.returncode}; merging only what was stored.")
            except subprocess.TimeoutExpired:
                print("[Step 1-1] WARNING: retry collector timed out after 1800s; merging only what was stored.")
            if retry_store.exists():
                with sqlite3.connect(retry_store) as rdb, sqlite3.connect(db_file) as mdb:
                    r_batches = rdb.execute("SELECT day, complex, observed, success FROM batches").fetchall()
                    r_listings = rdb.execute("SELECT day, complex, id, price, payload FROM listings").fetchall()
                    mdb.executemany("INSERT OR REPLACE INTO batches VALUES (?, ?, ?, ?)", r_batches)
                    mdb.executemany("INSERT OR REPLACE INTO listings VALUES (?, ?, ?, ?, ?)", r_listings)
                print(f"[Step 1-1] Auto-retry merged {len(r_batches)} batches and {len(r_listings)} listings.")
        
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
    
    # 4-1. Strict Quality Gate Check (Denominator: Total Planned Manifest Targets)
    with open(manifest_file, encoding='utf-8') as f:
        planned_targets = json.load(f)
    planned_count = len(planned_targets)

    db = sqlite3.connect(db_file)
    cur = db.cursor()
    success_ids = {str(r[0]) for r in cur.execute("SELECT complex FROM batches WHERE day=? AND success=1", (target_day,)).fetchall()}
    suspect_ids = find_suspect_collections(cur, target_day, success_ids)
    db.close()
    if suspect_ids:
        print(f"  [SUSPECT] 직전 관측일 대비 매물이 급감/소멸한 단지 {len(suspect_ids)}개는 정상 수집으로 인정하지 않습니다: {sorted(suspect_ids)[:20]}")
    success_ids -= suspect_ids

    planned_ids = {str(c['complex']) for c in planned_targets}
    successful_planned = len(planned_ids.intersection(success_ids))
    
    operational_status, success_rate, gate_msg = evaluate_quality_gate(planned_count, successful_planned)

    print(f"\n[Quality Gate Audit]")
    print(f"  당일 수집 예정 단지(분모): {planned_count}개")
    print(f"  실제 정상 수집 단지(분자): {successful_planned}개")
    print(f"  핵심 표본 수집 성공률:     {success_rate*100:.1f}%")
    print(f"  판정 상태:                 {operational_status}")

    if operational_status == 'CORE_QUALITY_BREACH':
        print(f"\n[CRITICAL QUALITY FAILURE] {gate_msg}")
        print("새로운 확정값 공표 및 배포를 중단하고 기존 확정값을 보존합니다.")
        incident_file = ROOT / 'data' / 'logs' / f'incident_{target_day}.json'
        incident_file.parent.mkdir(parents=True, exist_ok=True)
        incident_file.write_text(json.dumps({
            'day': target_day,
            'status': operational_status,
            'planned_count': planned_count,
            'successful_count': successful_planned,
            'success_rate_pct': round(success_rate * 100, 2),
            'message': gate_msg,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }, ensure_ascii=False, indent=2), encoding='utf-8')
        return 1

    elif operational_status == 'PARTIAL_SUCCESS':
        print(f"\n[NOTICE] {gate_msg}")
        print("내부 관측 데이터 및 스냅샷은 안전하게 보존하며, 확정지수 공식 공표는 유예합니다.")
    else:
        print(f"\n[PASS] 정상 수집 완료 ({success_rate*100:.1f}%). 정규 분석 및 공표 파이프라인을 진행합니다.")

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
    run_step("6-1. Divergence Dynamics & 3-Way Decomposition", ROOT / 'scripts' / 'divergence_dynamics.py', ['--day', target_day])
    
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
    
    # 10. Automated Public Deployment via GitHub (FULL_SUCCESS Only)
    if operational_status == 'FULL_SUCCESS':
        print("\n[Step 8] Pushing verified site payload to GitHub (FULL_SUCCESS Mode)...")
        hold_res = subprocess.run([sys.executable, str(ROOT / 'scripts' / 'apply_publication_hold.py')], cwd=str(ROOT), capture_output=True, text=True, encoding='utf-8')
        print(hold_res.stdout.strip())
        subprocess.run(['git', 'add', 'site/data.json'], cwd=str(ROOT), capture_output=True, text=True)
        git_diff = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=str(ROOT))
        if git_diff.returncode != 0:
            commit_msg = f"data: daily update {target_day}"
            subprocess.run(['git', 'commit', '-m', commit_msg], cwd=str(ROOT), capture_output=True, text=True)
            push_res = subprocess.run(['git', 'push', 'origin', 'main'], cwd=str(ROOT), capture_output=True, text=True)
            if push_res.returncode == 0:
                print(f"Successfully pushed daily update ({target_day}) to GitHub origin main.")
            else:
                err_msg = f"git push failed with code {push_res.returncode}: {push_res.stderr.strip()}"
                print(f"[CRITICAL DEPLOYMENT FAILURE] {err_msg}")
                incident_file = ROOT / 'data' / 'logs' / f'incident_{target_day}.json'
                incident_file.parent.mkdir(parents=True, exist_ok=True)
                incident_file.write_text(json.dumps({
                    'day': target_day,
                    'status': 'DEPLOY_FAILED',
                    'message': err_msg,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }, ensure_ascii=False, indent=2), encoding='utf-8')
                return 2  # Return code 2 indicates Deployment Failure
        else:
            print("site/data.json is unchanged; no new git commit needed.")
    else:
        print(f"\n[Step 8] Skipping public GitHub deployment (Status: {operational_status}).")
        print("Internal data, snapshots, and audit metrics are safely preserved locally; public benchmark publication is deferred.")
    
    end_time = datetime.now(ZoneInfo('Asia/Seoul'))
    total_elapsed = (end_time - start_time).total_seconds()
    print("="*80)
    print(f"APT WATCH DAILY OPERATION [{target_day}] COMPLETED ({operational_status}) IN {total_elapsed:.2f}s")
    print("="*80)
    return 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--day', help='Observation day (YYYY-MM-DD)')
    parser.add_argument('--manifest', help='Path to manifest JSON')
    parser.add_argument('--no-resume', action='store_true', help='Force re-scrape all complexes')
    parser.add_argument('--timeout', type=int, default=3600, help='Collector timeout in seconds')
    parser.add_argument('--workers', type=int, default=8, help='Number of parallel browser workers (default: 8)')
    args = parser.parse_args()
    
    exit_code = run_daily_operation(
        day=args.day,
        manifest_path=args.manifest,
        resume=not args.no_resume,
        timeout=args.timeout,
        workers=args.workers
    )
    sys.exit(exit_code)
