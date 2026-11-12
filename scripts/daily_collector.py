"""Daily Unmanned Collection Supervisor and Audit Logger for APT WATCH.
Executes daily at 06:00 KST, records full audit logs, and preserves snapshots.
"""
import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent

def run_daily_pipeline(manifest_path, store_path=None):
    today = datetime.now(ZoneInfo('Asia/Seoul')).date().isoformat()
    store = store_path or (ROOT / 'data' / 'history.sqlite3')
    manifest = Path(manifest_path)
    
    if not manifest.exists():
        raise FileNotFoundError(f"Manifest not found: {manifest}")
        
    targets = json.loads(manifest.read_text(encoding='utf-8-sig'))
    print(f"[{today} 06:00 KST] Starting daily unmanned pipeline for {len(targets)} complexes...", flush=True)
    
    # 1. Prepare raw snapshot directory
    snapshot_dir = ROOT / 'data' / 'snapshots' / today
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    temp_db = snapshot_dir / 'day_collection.sqlite3'
    if temp_db.exists():
        temp_db.unlink()
        
    # 2. Run collector bounded by supervise_naver.py
    collector_script = ROOT / 'collect_naver.py'
    cmd = [
        sys.executable,
        str(ROOT / 'supervise_naver.py'),
        '--timeout', '3600',
        '--',
        '--manifest', str(manifest),
        '--store', str(temp_db)
    ]
    
    start_time = datetime.now(ZoneInfo('Asia/Seoul'))
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    end_time = datetime.now(ZoneInfo('Asia/Seoul'))
    
    exit_code = proc.returncode
    print(f"Collector finished with exit code {exit_code} in {(end_time - start_time).total_seconds():.1f}s", flush=True)
    
    # 3. Analyze collected data and merge into primary store
    main_db = sqlite3.connect(store)
    
    # Check existing baseline before merge
    prev_listings = set(r[0] for r in main_db.execute("SELECT id FROM listings WHERE day < ?", (today,)).fetchall())
    
    collected_complexes = 0
    successful_complexes = 0
    failed_complexes = 0
    new_listings_count = 0
    reobserved_listings_count = 0
    total_listings_today = 0
    
    if temp_db.exists():
        col_db = sqlite3.connect(temp_db)
        batches = col_db.execute("SELECT day, complex, observed, success FROM batches").fetchall()
        collected_complexes = len(batches)
        
        for b in batches:
            if b[3] == 1:
                successful_complexes += 1
            else:
                failed_complexes += 1
            main_db.execute("INSERT OR REPLACE INTO batches VALUES (?,?,?,?)", b)
            
        listings = col_db.execute("SELECT day, complex, id, price, payload FROM listings").fetchall()
        total_listings_today = len(listings)
        
        # Save raw snapshot jsonl
        raw_snapshot_file = snapshot_dir / 'raw_listings.jsonl'
        with open(raw_snapshot_file, 'w', encoding='utf-8') as f:
            for l in listings:
                f.write(l[4] + '\n')
                main_db.execute("INSERT OR REPLACE INTO listings VALUES (?,?,?,?,?)", l)
                if l[2] in prev_listings:
                    reobserved_listings_count += 1
                else:
                    new_listings_count += 1
                    
        main_db.commit()
        col_db.close()
        
    # 4. Check price events
    from apt_watch import events
    all_events = events(main_db)
    today_events = [e for e in all_events if e['day'] == today]
    cut_events = [e for e in today_events if e['kind'] == '인하']
    rise_events = [e for e in today_events if e['kind'] == '인상']
    
    # 5. Build daily audit summary
    audit_report = {
        'date': today,
        'startedAt': start_time.isoformat(),
        'finishedAt': end_time.isoformat(),
        'manifestPath': str(manifest),
        'targetComplexes': len(targets),
        'attemptedComplexes': collected_complexes,
        'successfulComplexes': successful_complexes,
        'failedComplexes': failed_complexes,
        'missingComplexes': len(targets) - collected_complexes,
        'totalListings': total_listings_today,
        'newListings': new_listings_count,
        'reobservedListings': reobserved_listings_count,
        'priceCuts': len(cut_events),
        'priceRises': len(rise_events),
        'dbPersistence': 'SUCCESS' if (temp_db.exists() and total_listings_today > 0) else 'PARTIAL_OR_EMPTY',
        'collectorExitCode': exit_code,
        'snapshotPath': str(snapshot_dir / 'raw_listings.jsonl')
    }
    
    # Save audit log
    log_dir = ROOT / 'data' / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f'daily_run_{today}.json'
    log_file.write_text(json.dumps(audit_report, ensure_ascii=False, indent=2), encoding='utf-8')
    
    print(f"Daily Audit Report saved to {log_file}")
    print(json.dumps(audit_report, ensure_ascii=False, indent=2), flush=True)
    
    # 6. Rebuild market metrics and site
    print("Rebuilding APT WATCH site data...", flush=True)
    subprocess.run([sys.executable, str(ROOT / 'apt_watch.py')], check=True)
    subprocess.run([sys.executable, str(ROOT / 'nego_pressure.py')], check=True)
    print("Daily pipeline completed successfully!", flush=True)
    return audit_report

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--manifest', default=str(ROOT / 'data' / 'yangcheon-10-sample.json'))
    args = parser.parse_args()
    run_daily_pipeline(args.manifest)
