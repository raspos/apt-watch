"""Full Universe Rolling Collector and Runner for APT WATCH.
Orchestrates collection across the entire Seoul apartment universe (5,821 complexes across all 25 districts).

Features & Operational Principles:
1. Core Fixed Sample (375 complexes): Collected daily for uninterrupted high-frequency index continuity.
2. Rolling Universe (5,446 complexes): Rotated across 5 zones or prioritized by oldest observation.
3. Explicit Prioritization: When limited (--limit), sorts deterministically by (last_observed ASC, failure_count ASC, trade_count DESC).
4. Failure Handling & Rollover: Failed complexes are logged, failure_count incremented, and automatically prioritized in the next cycle.
5. Deduplication & Snapshot Preservation: Skips complexes already collected for the current date and preserves raw JSONL snapshots.
6. Deployment Safeguard: Inspects subprocess return codes; never deploys or reports success on broken or partial runs.
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

ZONES = {
    '11110': '도심권', '11140': '도심권', '11170': '도심권',
    '11650': '동남권', '11680': '동남권', '11710': '동남권', '11740': '동남권',
    '11200': '동북권', '11215': '동북권', '11230': '동북권', '11260': '동북권',
    '11290': '동북권', '11305': '동북권', '11320': '동북권', '11350': '동북권',
    '11380': '서북권', '11410': '서북권', '11440': '서북권',
    '11470': '서남권', '11500': '서남권', '11530': '서남권', '11545': '서남권',
    '11560': '서남권', '11590': '서남권', '11620': '서남권'
}

def sync_universe_tracking(db_path):
    """Synchronize SQLite complex_universe_tracking table with complexes.json and history batches."""
    comps_path = ROOT / 'data' / 'complexes.json'
    expanded_path = ROOT / 'data' / 'seoul-expanded-manifest.json'
    if not comps_path.exists():
        raise FileNotFoundError(f"Missing {comps_path}")

    comps = json.loads(comps_path.read_text(encoding='utf-8'))
    core_ids = set()
    if expanded_path.exists():
        core_ids = {str(c['complex']) for c in json.loads(expanded_path.read_text(encoding='utf-8'))}

    conn = sqlite3.connect(db_path)
    conn.execute('''
    CREATE TABLE IF NOT EXISTS complex_universe_tracking (
        complex TEXT PRIMARY KEY,
        district TEXT,
        name TEXT,
        dong TEXT,
        jibun TEXT,
        naver_name TEXT,
        is_core INTEGER DEFAULT 0,
        trade_count INTEGER DEFAULT 0,
        last_observed_day TEXT,
        last_success_day TEXT,
        failure_count INTEGER DEFAULT 0,
        consecutive_success INTEGER DEFAULT 0,
        zone TEXT,
        verification_status TEXT,
        trade_crosswalk_verified INTEGER DEFAULT 0,
        audit_reason TEXT,
        molit_name TEXT
    )
    ''')
    # Check if columns exist (for existing tables)
    existing_cols = {c[1] for c in conn.execute("PRAGMA table_info(complex_universe_tracking)").fetchall()}
    for col_name, col_def in [
        ('verification_status', 'TEXT'),
        ('trade_crosswalk_verified', 'INTEGER DEFAULT 0'),
        ('audit_reason', 'TEXT'),
        ('molit_name', 'TEXT')
    ]:
        if col_name not in existing_cols:
            conn.execute(f"ALTER TABLE complex_universe_tracking ADD COLUMN {col_name} {col_def}")

    history = {}
    for row in conn.execute('''
        SELECT complex, 
               MAX(day), 
               MAX(CASE WHEN success=1 THEN day ELSE NULL END), 
               SUM(CASE WHEN success=0 THEN 1 ELSE 0 END), 
               SUM(CASE WHEN success=1 THEN 1 ELSE 0 END) 
        FROM batches GROUP BY complex
    '''):
        history[str(row[0])] = row

    for c in comps:
        cid = str(c['complex'])
        dist = c['district']
        name = c['name']
        dong = c.get('dong', '')
        jibun = c.get('jibun', '')
        naver_name = c.get('naver_name', name)
        is_c = 1 if cid in core_ids else 0
        zone = ZONES.get(dist, '기타')
        h = history.get(cid)
        last_obs = h[1] if h else None
        last_succ = h[2] if h else None
        fail_cnt = h[3] if h else 0
        succ_cnt = h[4] if h else 0
        tc = c.get('trade_count', 0)
        v_stat = c.get('verification_status', 'UNVERIFIED_PENDING')
        v_flag = 1 if c.get('tradeCrosswalkVerified') else 0
        v_reason = c.get('audit_reason', '')
        t_complex = c.get('tradeComplex')
        m_name = t_complex[3] if t_complex and len(t_complex) >= 4 else name

        conn.execute('''
        INSERT OR REPLACE INTO complex_universe_tracking
        (complex, district, name, dong, jibun, naver_name, is_core, trade_count, 
         last_observed_day, last_success_day, failure_count, consecutive_success, zone,
         verification_status, trade_crosswalk_verified, audit_reason, molit_name)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (cid, dist, name, dong, jibun, naver_name, is_c, tc, last_obs, last_succ, fail_cnt, succ_cnt, zone,
              v_stat, v_flag, v_reason, m_name))

    conn.commit()
    conn.close()

def select_targets(db_path, mode='core', zone=None, district=None, limit=None, day=None):
    """Deterministically select targets from complex_universe_tracking based on mode and ordering rules."""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    query = """
    SELECT complex, district, name, dong, jibun, naver_name, is_core, trade_count,
           last_observed_day, last_success_day, failure_count, zone,
           verification_status, trade_crosswalk_verified, audit_reason, molit_name
    FROM complex_universe_tracking
    WHERE 1=1
    """
    params = []

    if mode == 'core':
        query += " AND is_core = 1"
    elif mode == 'rolling':
        query += " AND is_core = 0"

    if zone:
        query += " AND zone = ?"
        params.append(zone)

    if district:
        query += " AND district = ?"
        params.append(str(district))

    # Deterministic prioritization:
    # 1. Uncollected complexes or oldest observation first (COALESCE)
    # 2. Failed complexes with lower failure count retried first
    # 3. Higher historical trade volume first
    # 4. Complex name alphabetical as tie-breaker
    if mode == 'core':
        query += " ORDER BY trade_count DESC, name ASC"
    else:
        query += " ORDER BY COALESCE(last_success_day, '1970-01-01') ASC, failure_count ASC, trade_count DESC, name ASC"

    if limit and limit > 0:
        query += " LIMIT ?"
        params.append(limit)

    rows = cur.execute(query, params).fetchall()
    conn.close()

    targets = []
    for r in rows:
        targets.append({
            'complex': r[0],
            'district': r[1],
            'name': r[2],
            'dong': r[3],
            'jibun': r[4],
            'naver_name': r[5],
            'is_core': r[6],
            'trade_count': r[7],
            'last_observed_day': r[8],
            'last_success_day': r[9],
            'failure_count': r[10],
            'zone': r[11],
            'verification_status': r[12] or 'UNVERIFIED_PENDING',
            'tradeCrosswalkVerified': bool(r[13]),
            'audit_reason': r[14] or '',
            'tradeComplex': [r[1], r[3], r[4], r[15] or r[2]]
        })
    return targets

def run_universe_collector(mode='core', zone=None, district=None, limit=None, day=None, 
                           timeout=3600, workers=8, resume=True, skip_pipeline=False):
    start_time = datetime.now(ZoneInfo('Asia/Seoul'))
    target_day = day or start_time.date().isoformat()
    db_path = ROOT / 'data' / 'history.sqlite3'

    print("=" * 80)
    print(f"APT WATCH UNIVERSE COLLECTOR [{target_day}]")
    print(f"Mode: {mode} | Zone: {zone or 'ALL'} | District: {district or 'ALL'} | Limit: {limit or 'NONE'} | Workers: {workers}")
    print("=" * 80)

    # 1. Synchronize tracking table
    sync_universe_tracking(db_path)

    # 2. Select prioritized targets
    targets = select_targets(db_path, mode=mode, zone=zone, district=district, limit=limit, day=target_day)
    print(f"Selected {len(targets):,} targets for collection.")

    if not targets:
        print("No targets matched criteria.")
        return 0

    # 3. Filter already collected today if resume
    if resume and db_path.exists():
        conn = sqlite3.connect(db_path)
        done_set = {str(r[0]) for r in conn.execute("SELECT complex FROM batches WHERE day=? AND success=1", (target_day,)).fetchall()}
        conn.close()
        pending = [c for c in targets if str(c['complex']) not in done_set]
        print(f"Already completed today: {len(targets) - len(pending):,} | Pending to collect: {len(pending):,}")
    else:
        pending = targets

    if not pending:
        print("All targets for today are already collected successfully.")
        return 0

    # 4. Prepare temporary batch manifest
    batch_manifest = ROOT / 'data' / f'temp_batch_{target_day}_{os.getpid()}.json'
    batch_manifest.write_text(json.dumps(pending, ensure_ascii=False, indent=2), encoding='utf-8')

    col_success = False
    try:
        if workers > 1:
            col_cmd = [
                sys.executable,
                str(ROOT / 'scripts' / 'parallel_collector.py'),
                '--manifest', str(batch_manifest),
                '--store', str(db_path),
                '--workers', str(workers),
                '--timeout', str(timeout),
                '--day', target_day
            ]
            if not resume:
                col_cmd.append('--no-resume')
        else:
            col_cmd = [
                sys.executable,
                str(ROOT / 'supervise_naver.py'),
                '--timeout', str(timeout),
                '--',
                '--manifest', str(batch_manifest),
                '--store', str(db_path),
                '--day', target_day
            ]
            if resume:
                col_cmd.append('--resume')

        print(f"\n[Step 1] Running supervised collection ({len(pending):,} complexes, workers: {workers}, timeout: {timeout}s)...")
        col_t0 = time.time()
        col_proc = subprocess.run(col_cmd, cwd=str(ROOT))
        col_elapsed = time.time() - col_t0

        if col_proc.returncode != 0:
            print(f"\n[ERROR] Collector exited with failure code {col_proc.returncode} after {col_elapsed:.2f}s!")
            print("Aborting post-processing and deployment to prevent corrupted/partial data deployment.")
            return col_proc.returncode
        
        col_success = True
        print(f"\n[Step 1] Collection completed successfully in {col_elapsed:.2f}s.")
    finally:
        if batch_manifest.exists():
            batch_manifest.unlink()

    # 5. Resync tracking table with results
    sync_universe_tracking(db_path)

    # 6. Save raw snapshot
    snapshot_dir = ROOT / 'data' / 'snapshots' / target_day
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    raw_file = snapshot_dir / 'raw_listings.jsonl'
    db = sqlite3.connect(db_path)
    cur = db.cursor()
    cur.execute("SELECT payload FROM listings WHERE day=?", (target_day,))
    with open(raw_file, 'w', encoding='utf-8') as f:
        count = 0
        for (payload_str,) in cur:
            f.write(payload_str + '\n')
            count += 1
    db.close()
    print(f"[Step 2] Preserved raw snapshot ({count:,} listings) in {raw_file.name}")

    # 7. Post-collection analytics & deployment
    if not skip_pipeline and col_success:
        print("\n[Step 3] Executing post-collection analytical pipeline...")
        pipe_cmd = [sys.executable, str(ROOT / 'scripts' / 'run_post_collection_pipeline.py')]
        pipe_proc = subprocess.run(pipe_cmd, cwd=str(ROOT))
        if pipe_proc.returncode != 0:
            print(f"[ERROR] Post-collection pipeline failed with code {pipe_proc.returncode}!")
            return pipe_proc.returncode

    total_time = (datetime.now(ZoneInfo('Asia/Seoul')) - start_time).total_seconds()
    print("=" * 80)
    print(f"APT WATCH UNIVERSE COLLECTOR FINISHED IN {total_time:.2f}s")
    print("=" * 80)
    return 0

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="APT WATCH Universe Collector")
    parser.add_argument('--mode', choices=['core', 'rolling', 'all'], default='core',
                        help="Collection mode: core (375 fixed), rolling (non-core rotation), all (5,821)")
    parser.add_argument('--zone', choices=['도심권', '동남권', '동북권', '서북권', '서남권'], help="Filter by Seoul zone")
    parser.add_argument('--district', help="Filter by 5-digit district code")
    parser.add_argument('--limit', type=int, help="Limit number of complexes")
    parser.add_argument('--day', help="Target observation day (YYYY-MM-DD)")
    parser.add_argument('--workers', type=int, default=8, help="Number of concurrent browser workers (default: 8)")
    parser.add_argument('--timeout', type=int, default=3600, help="Supervised collector timeout in seconds")
    parser.add_argument('--no-resume', action='store_true', help="Do not skip already collected complexes")
    parser.add_argument('--skip-pipeline', action='store_true', help="Skip analytical post-processing")
    args = parser.parse_args()

    code = run_universe_collector(
        mode=args.mode,
        zone=args.zone,
        district=args.district,
        limit=args.limit,
        day=args.day,
        timeout=args.timeout,
        workers=args.workers,
        resume=not args.no_resume,
        skip_pipeline=args.skip_pipeline
    )
    sys.exit(code)
