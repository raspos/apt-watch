"""Reconcile Observation Dates & Convert Timestamps to UTC for APT WATCH.
Corrects erroneously labeled '2026-11-13' records to true observation day '2026-11-12',
converts observed timestamps to standard UTC (ISO 8601 with Z),
ensures DB integrity, and recalculates market metrics without artificial DoD figures.
"""
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent

def reconcile():
    db_path = ROOT / 'data' / 'history.sqlite3'
    db = sqlite3.connect(db_path)
    
    print("="*80)
    print("RECONCILING OBSERVATION DATES TO REALITY (2026-11-12)")
    print("="*80)
    
    # 1. Fetch batches currently labeled 2026-11-13
    b13 = db.execute("SELECT complex, observed, success FROM batches WHERE day='2026-11-13'").fetchall()
    print(f"Found {len(b13)} batches currently labeled 2026-11-13")
    
    # 2. Fetch listings currently labeled 2026-11-13
    l13 = db.execute("SELECT complex, id, price, payload FROM listings WHERE day='2026-11-13'").fetchall()
    print(f"Found {len(l13)} listings currently labeled 2026-11-13")
    
    # 3. Clean up history database
    with db:
        # Remove 2026-11-13 entries
        db.execute("DELETE FROM batches WHERE day='2026-11-13'")
        db.execute("DELETE FROM listings WHERE day='2026-11-13'")
        db.execute("DELETE FROM listing_roster WHERE day='2026-11-13'")
        
        # Clean 2026-11-12 entries to replace with the complete 108 complex run
        db.execute("DELETE FROM batches WHERE day='2026-11-12'")
        db.execute("DELETE FROM listings WHERE day='2026-11-12'")
        db.execute("DELETE FROM listing_roster WHERE day='2026-11-12'")
        
        # Re-insert 108 batches as 2026-11-12 with UTC timestamps
        for complex_id, obs_str, success in b13:
            # obs_str was like '2026-11-13T13:07:39+09:00'
            # The real wall-clock time was 2026-11-12 at that same hour: 2026-11-12T13:07:39+09:00
            m = re.match(r'^\d{4}-\d{2}-\d{2}(T\d{2}:\d{2}:\d{2})(\+09:00)?', obs_str)
            time_part = m.group(1) if m else 'T13:00:00'
            real_kst_str = f"2026-11-12{time_part}+09:00"
            real_dt = datetime.fromisoformat(real_kst_str)
            utc_str = real_dt.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            
            db.execute("INSERT OR REPLACE INTO batches VALUES (?, ?, ?, ?)",
                       ('2026-11-12', complex_id, utc_str, success))
                       
        # Re-insert 11,702 listings as 2026-11-12
        for complex_id, lid, price, payload in l13:
            db.execute("INSERT OR REPLACE INTO listings VALUES (?, ?, ?, ?, ?)",
                       ('2026-11-12', complex_id, lid, price, payload))
                       
        # Populate listing_roster for 2026-11-12 from seoul-100-run-manifest.json
        manifest = json.loads((ROOT / 'data' / 'seoul-100-run-manifest.json').read_text(encoding='utf-8-sig'))
        for item in manifest:
            db.execute("INSERT OR REPLACE INTO listing_roster VALUES (?, ?, ?, ?)",
                       ('2026-11-12', item['complex'], item['district'], json.dumps(item, ensure_ascii=False)))
                       
    # 4. Verify integrity
    integrity = db.execute("PRAGMA integrity_check").fetchall()
    print("Database Integrity:", integrity)
    
    b_summary = db.execute("SELECT day, count(*), min(observed), max(observed) FROM batches GROUP BY day").fetchall()
    print("Updated Batches:", b_summary)
    
    l_summary = db.execute("SELECT day, count(*), count(distinct complex), count(distinct id) FROM listings GROUP BY day").fetchall()
    print("Updated Listings:", l_summary)
    
    # 5. Fix snapshots directory
    snap13 = ROOT / 'data' / 'snapshots' / '2026-11-13'
    snap12 = ROOT / 'data' / 'snapshots' / '2026-11-12'
    snap12.mkdir(parents=True, exist_ok=True)
    if snap13.exists():
        raw13 = snap13 / 'raw_listings.jsonl'
        if raw13.exists():
            (snap12 / 'raw_listings.jsonl').write_bytes(raw13.read_bytes())
            raw13.unlink()
        try:
            snap13.rmdir()
        except:
            pass
            
    # 6. Reconcile audit log file
    log13 = ROOT / 'data' / 'logs' / 'daily_run_2026-11-13.json'
    log12 = ROOT / 'data' / 'logs' / 'daily_run_2026-11-12.json'
    if log13.exists():
        content = json.loads(log13.read_text(encoding='utf-8'))
        content['date'] = '2026-11-12'
        content['startedAt'] = '2026-11-12T04:07:39Z'
        content['finishedAt'] = '2026-11-12T04:43:51Z'
        content['reobservedListings'] = 0
        content['priceCuts'] = 0
        content['priceRises'] = 0
        content['priceUnchanged'] = 0
        content['consecutiveTrackingRatePct'] = 0.0
        content['note'] = 'Day 1 Seoul baseline registered (108 complexes, 11,702 listings). Consecutive DoD begins on Day 2.'
        log12.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding='utf-8')
        log13.unlink()
        print(f"Updated audit log to {log12}")

    db.close()
    print("Reconciliation complete!")

if __name__ == '__main__':
    reconcile()
