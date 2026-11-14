"""Observation quality library used by the daily pipeline.

Status values: VALID | SUSPECT | INVALID | UNKNOWN. Raw `listings` / `batches` rows are never changed.
`assess_day` writes `observation_quality`. `validate_retry_store` gates retry data BEFORE it is merged.
"""
import json
import sqlite3
import statistics
from datetime import datetime, timezone

DDL = """
CREATE TABLE IF NOT EXISTS observation_quality (
    day TEXT, complex TEXT, kind TEXT, status TEXT, reason TEXT,
    n_listings INTEGER, ref_n INTEGER, id_overlap REAL, count_ratio REAL, median_ratio REAL,
    basis TEXT, assessed_at TEXT,
    PRIMARY KEY(day, complex)
)
"""
RETRY_DDL = """
CREATE TABLE IF NOT EXISTS retry_attempts (
    day TEXT, complex TEXT, attempted_at TEXT, n_listings INTEGER, accepted INTEGER, reasons TEXT
)
"""
PRICE_RANGE = (1000, 5_000_000)     # 만원
# m2 exclusive area. Lower bound 10: MOLIT Seoul apartment trades (2026-08..11, 11,343 versions) go down to
# 10.78 m2 and 1% are < 15 m2 (도시형/초소형 panel complexes, e.g. 12.21 / 13.83 / 14.22 m2 match MOLIT exactly).
# Values < 10 (e.g. a 평 figure read as m2 for a studio, 0, 1.0) are still rejected. Was 15 until 2026-11-14.
AREA_RANGE = (10, 600)
REFERENCE_MAX_AGE_DAYS = 7


def _now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def compare(own, ref):
    """own/ref: {id: price}. Returns (id_overlap, count_ratio, median_ratio) or None."""
    if not own or not ref:
        return None
    return (len(set(own) & set(ref)) / min(len(own), len(ref)),
            len(own) / len(ref),
            statistics.median(own.values()) / statistics.median(ref.values()))


def passes(cmp, same_day=False):
    ov, cr, mr = cmp
    if same_day:
        return ov >= 0.7 and 0.8 <= cr <= 1.25 and 0.9 <= mr <= 1.1
    return ov >= 0.3 and 0.5 <= cr <= 2.0 and 0.8 <= mr <= 1.2


def structural_check(rows, manifest_entry=None):
    """rows: list of (id, price, payload_dict). Returns list of failure reasons (empty = ok)."""
    problems = []
    ids = [str(r[0]) for r in rows]
    if len(set(ids)) != len(ids):
        problems.append('duplicate listing ids')
    if any(not i or i == 'None' for i in ids):
        problems.append('missing listing id')
    names = set()
    if manifest_entry:
        names = {manifest_entry.get('name'), manifest_entry.get('naver_name')} - {None}
    for _id, price, p in rows:
        if not (PRICE_RANGE[0] <= float(price) <= PRICE_RANGE[1]):
            problems.append(f'price out of range: {price}')
            break
    for _id, price, p in rows:
        a = p.get('exclusive_area_m2')
        if a is None or not (AREA_RANGE[0] <= float(a) <= AREA_RANGE[1]):
            problems.append(f'area out of range: {a}')
            break
    if names:
        for _id, price, p in rows:
            if p.get('complex_name') and p['complex_name'] not in names:
                problems.append('complex name mismatch')
                break
    return problems


def _rows(db, day, cx):
    out = []
    for lid, price, payload in db.execute("SELECT id, price, payload FROM listings WHERE day=? AND complex=?", (day, cx)):
        out.append((lid, price, json.loads(payload)))
    return out


def latest_valid_reference(db, day, cx):
    """Most recent earlier observation of this complex with quality VALID (within REFERENCE_MAX_AGE_DAYS)."""
    r = db.execute(
        "SELECT day FROM observation_quality WHERE complex=? AND day<? AND status='VALID' "
        "AND julianday(?) - julianday(day) <= ? ORDER BY day DESC LIMIT 1",
        (cx, day, day, REFERENCE_MAX_AGE_DAYS)).fetchone()
    if not r:
        return None, {}
    return r[0], {x[0]: x[1] for x in db.execute("SELECT id, price FROM listings WHERE day=? AND complex=?", (r[0], cx))}


def judge(rows, ref_day, ref, manifest_entry=None, min_ref_for_zero=10):
    """Return (kind, status, reason, ref_n, cmp, basis) for one complex-day observation."""
    own = {str(r[0]): r[1] for r in rows}
    n = len(rows)
    kind = 'ZERO_LISTINGS' if n == 0 else 'COLLECTED'
    if n == 0:
        if ref_day is None:
            return kind, 'UNKNOWN', 'zero rows and no valid earlier reference', None, None, 'none'
        if len(ref) >= min_ref_for_zero:
            return kind, 'SUSPECT', f'0 rows but valid reference {ref_day} had {len(ref)}', len(ref), None, 'reference'
        return kind, 'VALID', f'0 rows; reference {ref_day} had only {len(ref)} (below {min_ref_for_zero})', len(ref), None, 'reference'
    probs = structural_check(rows, manifest_entry)
    if probs:
        return kind, 'INVALID', '; '.join(probs), len(ref) if ref else None, None, 'structural'
    if ref_day is None:
        return kind, 'VALID', 'baseline: structural checks passed, no earlier valid reference', None, None, 'structural_only'
    if not ref:
        return kind, 'SUSPECT', f'valid reference {ref_day} had 0 rows but today {n}', 0, None, 'reference'
    cmpv = compare(own, ref)
    if passes(cmpv):
        return kind, 'VALID', f'consistent with valid reference {ref_day}', len(ref), cmpv, 'reference'
    return kind, 'SUSPECT', f'inconsistent with valid reference {ref_day} (ids/count/price level)', len(ref), cmpv, 'reference'


def assess_day(db, day, manifest=None):
    """Assess every batch of `day` against the latest valid earlier observation. Returns summary dict."""
    db.execute(DDL)
    man = {str(m['complex']): m for m in (manifest or [])}
    now = _now()
    out = []
    for cx, ok in db.execute("SELECT complex, success FROM batches WHERE day=?", (day,)).fetchall():
        cx = str(cx)
        if not ok:
            out.append((day, cx, 'FAILED', 'INVALID', 'collector reported failure', 0, None, None, None, None, 'batches.success=0', now))
            continue
        ref_day, ref = latest_valid_reference(db, day, cx)
        kind, status, reason, ref_n, cmpv, basis = judge(_rows(db, day, cx), ref_day, ref, man.get(cx))
        ov, cr, mr = cmpv if cmpv else (None, None, None)
        n = db.execute("SELECT COUNT(*) FROM listings WHERE day=? AND complex=?", (day, cx)).fetchone()[0]
        out.append((day, cx, kind, status, reason, n, ref_n, ov, cr, mr, basis, now))
    db.executemany("INSERT OR REPLACE INTO observation_quality VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", out)
    db.commit()
    return quality_summary(db, day)


def quality_summary(db, day, planned=None):
    db.execute(DDL)
    rows = db.execute("SELECT status, COUNT(*), COALESCE(SUM(n_listings),0) FROM observation_quality WHERE day=? GROUP BY status", (day,)).fetchall()
    by = {s: (c, l) for s, c, l in rows}
    valid = by.get('VALID', (0, 0))
    total = sum(c for c, _ in by.values())
    planned = planned or total
    return {'day': day, 'assessed': total, 'planned': planned,
            'valid': valid[0], 'validListings': valid[1],
            'suspect': by.get('SUSPECT', (0, 0))[0], 'invalid': by.get('INVALID', (0, 0))[0],
            'unknown': by.get('UNKNOWN', (0, 0))[0],
            'validRate': (valid[0] / planned) if planned else 0.0}


def valid_complexes(db, day):
    db.execute(DDL)
    return {r[0] for r in db.execute("SELECT complex FROM observation_quality WHERE day=? AND status='VALID'", (day,))}


def day_is_assessed(db, day):
    db.execute(DDL)
    return db.execute("SELECT COUNT(*) FROM observation_quality WHERE day=?", (day,)).fetchone()[0] > 0


def validate_retry_store(main_db, retry_db, target_day, manifest):
    """Decide which retried complexes may be merged into the main DB. Returns {complex: (accepted, reasons)}.

    Accepted only when the retry succeeded AND judge() says VALID against the latest valid earlier
    observation (or baseline structural checks). Everything else stays out of the official data.
    """
    main_db.execute(RETRY_DDL)
    man = {str(m['complex']): m for m in manifest}
    verdicts = {}
    now = _now()
    for cx, ok, observed in retry_db.execute("SELECT complex, success, observed FROM batches").fetchall():
        cx = str(cx)
        rows = [(r[0], r[1], json.loads(r[2])) for r in
                retry_db.execute("SELECT id, price, payload FROM listings WHERE day=? AND complex=?", (target_day, cx))]
        if not ok:
            verdicts[cx] = (False, 'retry collector reported failure')
        else:
            ref_day, ref = latest_valid_reference(main_db, target_day, cx)
            kind, status, reason, *_ = judge(rows, ref_day, ref, man.get(cx))
            verdicts[cx] = (status == 'VALID', f'{status}: {reason}')
        main_db.execute("INSERT INTO retry_attempts VALUES (?,?,?,?,?,?)",
                        (target_day, cx, observed or now, len(rows), int(verdicts[cx][0]), verdicts[cx][1]))
    main_db.commit()
    return verdicts
