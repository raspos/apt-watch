"""Full Universe Rolling Collector and Runner for APT WATCH.
Orchestrates collection across the entire Seoul apartment universe (5,821 complexes across all 25 districts).

Features:
- Collect by single district (--district 11110) or entire city (--all)
- Configurable per-district complex limit (--limit) or complete enumeration
- Full auto-resume: skips complexes already collected for today
- Automatic rate-limiting and browser anti-bot mitigation
- Incremental SQLite commits to ensure zero data loss on interruption
- Automatic post-collection pipeline execution and data.json update
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

def load_universe(manifest_path=None):
    path = Path(manifest_path) if manifest_path else (ROOT / 'data' / 'complexes.json')
    if not path.exists():
        raise FileNotFoundError(f"Universe manifest not found at {path}")
    data = json.loads(path.read_text(encoding='utf-8'))
    return data

def get_collected_today(db_path, day):
    if not db_path.exists():
        return set()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("SELECT complex FROM batches WHERE day=? AND success=1", (day,))
    done = {str(row[0]) for row in cur.fetchall()}
    conn.close()
    return done

def run_universe_collection(args):
    today = args.day or datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    db_path = ROOT / 'data' / 'history.sqlite3'
    all_complexes = load_universe(args.manifest)
    
    # Filter by district if requested
    if args.district:
        dist_code = str(args.district)
        targets = [c for c in all_complexes if c['district'] == dist_code]
    else:
        targets = all_complexes

    # Apply per-district limit if requested
    if args.limit:
        from collections import defaultdict
        by_d = defaultdict(list)
        for c in targets:
            if len(by_d[c['district']]) < args.limit:
                by_d[c['district']].append(c)
        targets = [c for group in by_d.values() for c in group]

    print("=" * 80)
    print(f"APT WATCH FULL UNIVERSE RUNNER [{today}]")
    print(f"Total Targets: {len(targets):,} complexes across {len(set(c['district'] for c in targets))} districts")
    print("=" * 80)

    already_done = get_collected_today(db_path, today) if args.resume else set()
    pending = [c for c in targets if str(c['complex']) not in already_done]
    print(f"Already completed today: {len(already_done):,} | Pending to collect: {len(pending):,}")

    if not pending:
        print("All targets for today are already collected! Proceeding to analytical pipeline.")
    else:
        # Create a temporary run manifest for pending targets
        run_manifest_path = ROOT / 'data' / f'universe_run_{today}_{os.getpid()}.json'
        run_manifest_path.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding='utf-8')
        try:
            cmd = [
                sys.executable,
                str(ROOT / 'supervise_naver.py'),
                '--timeout', str(args.timeout),
                '--',
                '--manifest', str(run_manifest_path),
                '--store', str(db_path),
                '--day', today
            ]
            if args.resume:
                cmd.append('--resume')
            
            print(f"\n>>> Starting collection for {len(pending):,} complexes...")
            col_t0 = time.time()
            subprocess.run(cmd, cwd=str(ROOT))
            print(f">>> Collection phase ended in {time.time() - col_t0:.2f}s")
        finally:
            if run_manifest_path.exists():
                run_manifest_path.unlink()

    # Post-collection pipeline
    if not args.skip_pipeline:
        print("\n>>> Launching post-collection analytics and site update...")
        pipe_cmd = [sys.executable, str(ROOT / 'scripts' / 'run_post_collection_pipeline.py')]
        subprocess.run(pipe_cmd, cwd=str(ROOT), check=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Full Universe APT WATCH Collector")
    parser.add_argument('--day', help="Target observation date (YYYY-MM-DD)")
    parser.add_argument('--district', help="Filter to specific 5-digit district code (e.g. 11680)")
    parser.add_argument('--limit', type=int, help="Limit number of complexes per district")
    parser.add_argument('--manifest', help="Path to universe manifest (default: data/complexes.json)")
    parser.add_argument('--timeout', type=int, default=7200, help="Supervised timeout in seconds (default: 7200s)")
    parser.add_argument('--resume', action='store_true', default=True, help="Auto-resume from existing batches")
    parser.add_argument('--skip-pipeline', action='store_true', help="Skip analytical post-processing")
    args = parser.parse_args()
    run_universe_collection(args)
