"""Observation quality assessment (additive; never modifies raw observations).

Creates/updates table `observation_quality` in history.sqlite3:
  day, complex, kind (COLLECTED|FAILED|ZERO_LISTINGS), status (VALID|SUSPECT|INVALID|UNKNOWN),
  reason, n_listings, ref_n, id_overlap, count_ratio, median_ratio, basis, assessed_at

Evidence sources
  * evidence stores (--evidence): independent later recollections written to scratch SQLite stores.
    They are used ONLY to judge existing rows; their rows are never inserted into history.sqlite3.
  * the adjacent observation day.

Rules
  with same-day evidence : VALID if id-overlap >= 0.7 and 0.8 <= count ratio <= 1.25 and median ratio within 10%
  with adjacent day only : VALID if id-overlap >= 0.3 and 0.5 <= count ratio <= 2 and median ratio within 20%
  zero rows              : same-day evidence also zero -> VALID (confirmed zero);
                           same-day evidence >0 on the same day -> INVALID;
                           later-day evidence >0 for an earlier day -> SUSPECT (cannot assert the past);
                           no evidence and reference >= 10 rows -> SUSPECT; else UNKNOWN.
"""
import argparse
import json
import sqlite3
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / 'data' / 'history.sqlite3'

DDL = """
CREATE TABLE IF NOT EXISTS observation_quality (
    day TEXT, complex TEXT, kind TEXT, status TEXT, reason TEXT,
    n_listings INTEGER, ref_n INTEGER, id_overlap REAL, count_ratio REAL, median_ratio REAL,
    basis TEXT, assessed_at TEXT,
    PRIMARY KEY(day, complex)
)
"""


def listings(db, day, cx):
    return {r[0]: r[1] for r in db.execute("SELECT id, price FROM listings WHERE day=? AND complex=?", (day, cx))}


def compare(own, ref):
    if not own or not ref:
        return None
    ov = len(set(own) & set(ref)) / min(len(own), len(ref))
    cr = len(own) / len(ref)
    mr = statistics.median(own.values()) / statistics.median(ref.values())
    return ov, cr, mr


def passes(cmp, same_day):
    ov, cr, mr = cmp
    if same_day:
        return ov >= 0.7 and 0.8 <= cr <= 1.25 and 0.9 <= mr <= 1.1
    return ov >= 0.3 and 0.5 <= cr <= 2.0 and 0.8 <= mr <= 1.2


def assess(db, evidence, day, other_day, other_status, retried):
    out = []
    batches = {r[0]: r[1] for r in db.execute("SELECT complex, success FROM batches WHERE day=?", (day,))}
    for cx, ok in batches.items():
        own = listings(db, day, cx)
        n = len(own)
        ev = evidence.get(cx)                   # {id: price} from a later independent recollection
        ev_same_day = ev is not None and evidence_day == day
        adj = listings(db, other_day, cx) if other_day else {}
        adj_ok = other_status.get(cx) in ('VALID',)
        kind = 'ZERO_LISTINGS' if n == 0 else 'COLLECTED'
        if not ok:
            out.append((day, cx, 'FAILED', 'INVALID', 'collector reported failure', n, None, None, None, None, 'batches.success=0'))
            continue
        status, reason, ref_n, cmpv, basis = 'UNKNOWN', 'no reference observation', None, None, 'none'
        if n == 0:
            if ev is not None:
                ref_n = len(ev)
                if ref_n == 0:
                    status, reason, basis = 'VALID', 'zero listings confirmed by independent recollection', 'evidence'
                elif ev_same_day:
                    status, reason, basis = 'INVALID', f'0 rows recorded but same-day recollection found {ref_n}', 'evidence_same_day'
                else:
                    status, reason, basis = 'SUSPECT', f'0 rows recorded; later recollection found {ref_n}; past state not asserted', 'evidence_later'
            elif len(adj) >= 10:
                ref_n = len(adj)
                status, reason, basis = 'SUSPECT', f'0 rows but adjacent day had {len(adj)}', 'adjacent_day'
            else:
                ref_n = len(adj)
                status, reason, basis = 'UNKNOWN', 'zero rows, no strong reference', 'adjacent_day'
        else:
            if ev is not None and ev:
                ref_n = len(ev)
                cmpv = compare(own, ev)
                if passes(cmpv, ev_same_day):
                    status, reason, basis = 'VALID', 'matches independent recollection', 'evidence'
                else:
                    status = 'INVALID' if (ev_same_day and cx in retried) else 'SUSPECT'
                    reason = 'differs from independent recollection (ids / count / price level)'
                    basis = 'evidence_same_day' if ev_same_day else 'evidence_later'
            elif adj and adj_ok:
                ref_n = len(adj)
                cmpv = compare(own, adj)
                if passes(cmpv, False):
                    status, reason, basis = 'VALID', 'consistent with adjacent valid observation', 'adjacent_day'
                else:
                    status, reason, basis = 'SUSPECT', 'inconsistent with adjacent valid observation', 'adjacent_day'
            elif adj:
                ref_n = len(adj)
                cmpv = compare(own, adj)
                if cmpv and passes(cmpv, False):
                    status, reason, basis = 'VALID', 'consistent with adjacent observation', 'adjacent_day'
                else:
                    status, reason, basis = 'UNKNOWN', 'adjacent observation not validated', 'adjacent_day'
            elif n < 10:
                status, reason, basis = 'UNKNOWN', 'small sample, no reference', 'none'
        ov, cr, mr = cmpv if cmpv else (None, None, None)
        out.append((day, cx, kind, status, reason, n, ref_n, ov, cr, mr, basis))
    return out


def main():
    global evidence_day
    ap = argparse.ArgumentParser()
    ap.add_argument('--evidence', nargs='*', default=[])
    ap.add_argument('--evidence-day', default='2026-11-13', help='the day on which evidence was recollected')
    ap.add_argument('--days', nargs=2, default=['2026-11-13', '2026-11-12'], help='assess in this order')
    ap.add_argument('--retried', default=str(ROOT / 'data' / 'retry_13_manifest.json'))
    args = ap.parse_args()
    evidence_day = args.evidence_day

    evidence = {}
    for p in args.evidence:
        e = sqlite3.connect(f'file:{p}?mode=ro', uri=True)
        for (cx,) in e.execute("SELECT complex FROM batches WHERE success=1"):
            evidence[cx] = {r[0]: r[1] for r in e.execute("SELECT id, price FROM listings WHERE complex=?", (cx,))}
    retried = set()
    if Path(args.retried).exists():
        retried = {str(x['complex']) for x in json.loads(Path(args.retried).read_text(encoding='utf-8-sig'))}

    db = sqlite3.connect(DB)
    db.execute(DDL)
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    status_by_day = {}
    for day, other in ((args.days[0], args.days[1]), (args.days[1], args.days[0])):
        rows = assess(db, evidence, day, other, status_by_day.get(other, {}), retried if day == args.evidence_day else set())
        status_by_day[day] = {r[1]: r[3] for r in rows}
        db.executemany("INSERT OR REPLACE INTO observation_quality VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       [r + (now,) for r in rows])
    db.commit()
    for day in args.days:
        print(day, db.execute("SELECT status, kind, COUNT(*), COALESCE(SUM(n_listings),0) FROM observation_quality WHERE day=? GROUP BY status, kind", (day,)).fetchall())


if __name__ == '__main__':
    main()
