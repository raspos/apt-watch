"""Multi-Worker Parallel Collector for APT WATCH.
Distributes complex scraping across multiple concurrent Playwright headless browser workers.

Design Principles:
1. Sharded Concurrency: Splits pending complexes round-robin across N worker subprocesses (default: 8~10).
2. Throughput Target: With 20.4s/complex empirical baseline, 10 workers complete 375 complexes in ~12.8 minutes.
3. WAL Concurrency: Relies on SQLite WAL mode and 60s busy_timeout for atomic multi-writer database ingestion.
4. Auto-Resume & Deduplication: Queries SQLite batches table first and only schedules uncollected complexes.
5. Error Isolation & Rollover: A worker failure on one complex does not stall other workers.
6. Telemetry & Progress Monitoring: Real-time progress monitoring with per-worker status, ETA, and throughput.
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

def partition_manifest(pending, num_workers):
    """Round-robin partition of pending complexes into N worker shards."""
    shards = [[] for _ in range(num_workers)]
    for idx, item in enumerate(pending):
        shards[idx % num_workers].append(item)
    return [s for s in shards if s]

def run_worker_pool(targets, day, store_path, num_workers=8, timeout_per_worker=1800, resume=True):
    start_time = time.monotonic()
    print("=" * 80)
    print(f"APT WATCH MULTI-WORKER PARALLEL COLLECTOR [{day}]")
    print(f"Total Targets: {len(targets):,} complexes | Workers: {num_workers} | Timeout: {timeout_per_worker}s")
    print("=" * 80)

    # Filter out already collected if resume is enabled
    db = sqlite3.connect(store_path)
    done_ids = {str(r[0]) for r in db.execute("SELECT complex FROM batches WHERE day=? AND success=1", (day,)).fetchall()}
    db.close()

    if resume:
        pending = [c for c in targets if str(c['complex']) not in done_ids]
        print(f"Already completed today: {len(targets) - len(pending):,} | Pending to collect: {len(pending):,}")
    else:
        pending = targets

    if not pending:
        print("All targets are already collected successfully today. Nothing to do.")
        return 0, len(targets), 0

    actual_workers = min(num_workers, len(pending))
    shards = partition_manifest(pending, actual_workers)
    print(f"Partitioned {len(pending):,} complexes across {len(shards)} workers.")

    shard_files = []
    log_files = []
    processes = []
    pid = os.getpid()

    try:
        # Prepare shard files and spawn subprocesses
        for w_idx, shard in enumerate(shards):
            shard_path = ROOT / 'data' / f'temp_shard_{day}_w{w_idx}_{pid}.json'
            shard_path.write_text(json.dumps(shard, ensure_ascii=False, indent=2), encoding='utf-8')
            shard_files.append(shard_path)

            log_path = ROOT / 'data' / f'temp_log_{day}_w{w_idx}_{pid}.txt'
            log_files.append(log_path)
            log_fp = open(log_path, 'w', encoding='utf-8')

            cmd = [
                sys.executable,
                '-u',
                str(ROOT / 'collect_naver.py'),
                '--manifest', str(shard_path),
                '--store', str(store_path),
                '--day', day
            ]
            if resume:
                cmd.append('--resume')

            proc = subprocess.Popen(cmd, stdout=log_fp, stderr=subprocess.STDOUT, cwd=str(ROOT))
            processes.append((proc, log_fp, w_idx, len(shard)))
            print(f"  [Worker {w_idx+1:02d}] PID {proc.pid} assigned {len(shard)} complexes.")

        print("-" * 80)
        print("All workers running concurrently. Monitoring progress...")

        # Monitor loop
        completed_set = set()
        while True:
            alive = 0
            for proc, log_fp, w_idx, count in processes:
                if proc.poll() is None:
                    alive += 1

            # Count progress from DB
            db = sqlite3.connect(store_path)
            cur_done = {str(r[0]) for r in db.execute("SELECT complex FROM batches WHERE day=? AND success=1", (day,)).fetchall()}
            db.close()

            new_done = len(cur_done.intersection({str(c['complex']) for c in pending}))
            elapsed = time.monotonic() - start_time
            rate = (new_done / elapsed * 60) if elapsed > 0 else 0.0
            remaining = len(pending) - new_done
            eta_sec = (remaining / (rate / 60)) if rate > 0 else 0

            print(f"[{datetime.now().strftime('%H:%M:%S')}] Active Workers: {alive}/{len(processes)} | Done: {new_done}/{len(pending)} ({new_done/len(pending)*100:4.1f}%) | Speed: {rate:.1f} comp/min | ETA: {eta_sec/60:.1f}m", flush=True)

            if alive == 0:
                break

            if elapsed > timeout_per_worker:
                print(f"[WARNING] Worker pool exceeded timeout ({timeout_per_worker}s). Terminating remaining workers...")
                for proc, log_fp, w_idx, count in processes:
                    if proc.poll() is None:
                        proc.terminate()
                break

            time.sleep(15)

    finally:
        # Cleanup
        for proc, log_fp, w_idx, count in processes:
            try:
                log_fp.close()
            except Exception:
                pass
        for sf in shard_files:
            if sf.exists():
                try: sf.unlink()
                except Exception: pass
        for lf in log_files:
            if lf.exists():
                try: lf.unlink()
                except Exception: pass

    # Final tally
    db = sqlite3.connect(store_path)
    final_done = {str(r[0]) for r in db.execute("SELECT complex FROM batches WHERE day=? AND success=1", (day,)).fetchall()}
    db.close()

    total_elapsed = time.monotonic() - start_time
    total_successful = len(final_done.intersection({str(c['complex']) for c in targets}))
    failed_count = len(targets) - total_successful

    print("=" * 80)
    print(f"COLLECTION POOL COMPLETED IN {total_elapsed:.2f}s ({total_elapsed/60:.2f}m)")
    print(f"Successfully collected: {total_successful:,}/{len(targets):,} ({total_successful/len(targets)*100:.1f}%)")
    if failed_count > 0:
        print(f"Pending/Failed: {failed_count:,} complexes")
    print("=" * 80)

    return 0 if failed_count == 0 else 1, total_successful, failed_count

def main():
    parser = argparse.ArgumentParser(description="APT WATCH Parallel Collector")
    parser.add_argument('--manifest', type=Path, default=ROOT / 'data' / 'seoul-expanded-manifest.json',
                        help="Path to manifest JSON file")
    parser.add_argument('--store', type=Path, default=ROOT / 'data' / 'history.sqlite3',
                        help="Path to history SQLite database")
    parser.add_argument('--workers', type=int, default=8, help="Number of concurrent workers (default: 8)")
    parser.add_argument('--day', help="Target observation date (YYYY-MM-DD)")
    parser.add_argument('--timeout', type=int, default=1800, help="Pool timeout in seconds (default: 1800)")
    parser.add_argument('--no-resume', action='store_true', help="Do not skip already collected complexes")
    args = parser.parse_args()

    day = args.day or datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    if not args.manifest.exists():
        sys.exit(f"Manifest not found: {args.manifest}")

    with open(args.manifest, encoding='utf-8') as f:
        targets = json.load(f)

    code, succ, fail = run_worker_pool(
        targets=targets,
        day=day,
        store_path=args.store,
        num_workers=args.workers,
        timeout_per_worker=args.timeout,
        resume=not args.no_resume
    )
    sys.exit(code)

if __name__ == '__main__':
    main()
