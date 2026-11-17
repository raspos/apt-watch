"""Second collection pass for complexes the quality check did not accept (SUSPECT / INVALID).

A partially rendered page or an unconfirmed zero is re-collected once into a separate staging store.
The retry is merged only if observation_quality.validate_retry_store judges it VALID against the latest
valid earlier observation. Rows it replaces are first copied to `superseded_listings` (originals kept),
then the day is re-assessed by the caller.

usage (manual): python scripts/recheck_nonvalid.py --day 2026-11-17
"""
import argparse
import json
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import observation_quality as oq  # noqa: E402

SUPERSEDED_DDL = """
CREATE TABLE IF NOT EXISTS superseded_listings (
    day TEXT, complex TEXT, id TEXT, price REAL, payload TEXT, superseded_at TEXT, reason TEXT
)"""


def recheck(db_file, manifest, day, timeout_per_complex=45):
    db_file = Path(db_file)
    with sqlite3.connect(db_file) as db:
        bad = [str(r[0]) for r in db.execute(
            "SELECT complex FROM observation_quality WHERE day=? AND status IN ('SUSPECT','INVALID')", (day,))]
    targets = [c for c in manifest if str(c['complex']) in set(bad)]
    if not targets:
        return {'rechecked': 0, 'accepted': [], 'rejected': {}}
    stamp = datetime.now().strftime('%H%M%S')
    mf = ROOT / 'data' / 'staging' / f'recheck_{day}_{stamp}_manifest.json'
    store = ROOT / 'data' / 'staging' / f'recheck_{day}_{stamp}.sqlite3'
    mf.write_text(json.dumps(targets, ensure_ascii=False, indent=2), encoding='utf-8')
    cmd = [sys.executable, '-u', str(ROOT / 'collect_naver.py'), '--manifest', str(mf), '--store', str(store), '--day', day]
    try:
        subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       timeout=max(600, timeout_per_complex * len(targets)), cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        pass
    if not store.exists():
        return {'rechecked': len(targets), 'accepted': [], 'rejected': {c['complex']: 'no recheck store' for c in targets}}
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    with sqlite3.connect(store) as rdb, sqlite3.connect(db_file) as mdb:
        verdicts = oq.validate_retry_store(mdb, rdb, day, targets)
        accepted = [cx for cx, (ok, _) in verdicts.items() if ok]
        mdb.execute(SUPERSEDED_DDL)
        for cx in accepted:
            mdb.execute("INSERT INTO superseded_listings SELECT day, complex, id, price, payload, ?, ? FROM listings WHERE day=? AND complex=?",
                        (now, f'replaced by recheck {store.name}', day, cx))
            mdb.execute("DELETE FROM listings WHERE day=? AND complex=?", (day, cx))
            mdb.executemany("INSERT OR REPLACE INTO batches VALUES (?, ?, ?, ?)",
                            rdb.execute("SELECT day, complex, observed, success FROM batches WHERE complex=?", (cx,)).fetchall())
            mdb.executemany("INSERT OR REPLACE INTO listings VALUES (?, ?, ?, ?, ?)",
                            rdb.execute("SELECT day, complex, id, price, payload FROM listings WHERE complex=?", (cx,)).fetchall())
            try:
                mdb.executemany("INSERT OR REPLACE INTO collection_telemetry VALUES (?,?,?,?,?,?,?,?,?,?)",
                                rdb.execute("SELECT * FROM collection_telemetry WHERE complex=?", (cx,)).fetchall())
            except sqlite3.OperationalError:
                pass
        mdb.commit()
    return {'rechecked': len(targets), 'store': store.name, 'accepted': accepted,
            'rejected': {cx: why for cx, (ok, why) in verdicts.items() if not ok}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', required=True)
    a = ap.parse_args()
    manifest = json.loads((ROOT / 'data' / 'fixed-110-panel.json').read_text(encoding='utf-8-sig'))
    db_file = ROOT / 'data' / 'history.sqlite3'
    res = recheck(db_file, manifest, a.day)
    with sqlite3.connect(db_file) as db:
        q = oq.assess_day(db, a.day, manifest)
    print(json.dumps({'recheck': res, 'quality': q}, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main()
