"""Point-in-time ledger of MOLIT apartment trades (first_seen_at per trade version).

The tracker DB (seoul-apartment-tracker/data/tracker.sqlite3) keeps only the latest snapshot per
district-month, so it cannot prove WHEN an individual trade became visible. This ledger records
APT WATCH's own MOLIT queries:

  fetches          one row per district-month query: fetched_at, totalCount, raw evidence path + sha256
  trade_versions   one row per distinct trade content (sha256 of all raw API fields):
                   natural_key, contract day, first_seen_at / first_fetch_id, parsed + raw payload
  fetch_members    which versions each fetch returned (membership -> removals are detectable)
  trade_events     NEW / CORRECTED / CANCELLED / REMOVED / AMBIGUOUS per natural key

Rules
  * first_seen_at is only ever the timestamp of a real query made by this ledger. Nothing is
    back-filled from the tracker DB. The tracker DB is opened read-only and never written.
  * contract day (dealYear/Month/Day) and first_seen_at are separate fields.
  * trades_as_of(cutoff) uses, for every district-month, the LATEST ledger fetch with
    fetched_at <= cutoff. Trades reported, corrected or cancelled after the cutoff therefore cannot
    leak into an earlier index day.
  * tradeLevelFirstSeenVerified is True only if every district-month of the window has such a fetch
    AND every fetch's raw evidence file exists with a matching sha256.

Natural key: MOLIT publishes no deal id. key = (sggCd, umdCd, jibun, aptSeq, aptDong, excluUseAr,
floor, contract day). Several deals can share it; `occurrence` separates them and a change inside a
duplicated key is logged AMBIGUOUS instead of being guessed as a correction.
"""
import argparse
import gzip
import hashlib
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
TRACKER = ROOT.parent / 'seoul-apartment-tracker'
LEDGER_DB = ROOT / 'data' / 'trade_ledger.sqlite3'
EVIDENCE_DIR = ROOT / 'data' / 'trade_evidence'
KST = ZoneInfo('Asia/Seoul')
KEY_FIELDS = ('sggCd', 'umdCd', 'jibun', 'aptSeq', 'aptDong', 'excluUseAr', 'floor', 'dealYear', 'dealMonth', 'dealDay')
DAILY_CALL_LIMIT = 500

DDL = """
CREATE TABLE IF NOT EXISTS fetches(
    fetch_id INTEGER PRIMARY KEY AUTOINCREMENT, district TEXT, month TEXT, fetched_at TEXT,
    total_count INTEGER, row_count INTEGER, raw_sha256 TEXT, raw_path TEXT, status TEXT);
CREATE TABLE IF NOT EXISTS trade_versions(
    version_hash TEXT PRIMARY KEY, natural_key TEXT, district TEXT, month TEXT, contract_day TEXT,
    first_seen_at TEXT, first_fetch_id INTEGER, parsed_json TEXT, raw_json TEXT);
CREATE TABLE IF NOT EXISTS fetch_members(fetch_id INTEGER, version_hash TEXT, occurrence INTEGER,
    PRIMARY KEY(fetch_id, version_hash, occurrence));
CREATE TABLE IF NOT EXISTS trade_events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, fetch_id INTEGER, at TEXT, natural_key TEXT, event TEXT,
    before_hash TEXT, after_hash TEXT);
CREATE TABLE IF NOT EXISTS api_calls(day TEXT PRIMARY KEY, count INTEGER);
CREATE INDEX IF NOT EXISTS ix_fetch_dm ON fetches(district, month, fetched_at);
CREATE INDEX IF NOT EXISTS ix_tv_key ON trade_versions(natural_key);
"""


def connect(path=LEDGER_DB):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=60)
    db.executescript(DDL)
    return db


def now_kst():
    return datetime.now(KST).isoformat(timespec='seconds')


# ---------------------------------------------------------------- parsing / identity

def raw_items(xml_bytes):
    root = ET.fromstring(xml_bytes)
    for n in root.iter():
        n.tag = n.tag.split('}')[-1]
    return [{x.tag: (x.text or '').strip() for x in item} for item in root.findall('.//item')]


def natural_key(item):
    return '|'.join(item.get(f, '') for f in KEY_FIELDS)


def version_hash(item):
    return hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()


def parsed_row(item, district):
    """Same shape the tracker stores (so the NEGO engine's trade_key works unchanged)."""
    from decimal import Decimal
    day = date(int(item['dealYear']), int(item['dealMonth']), int(item['dealDay'])).isoformat()
    return dict(district=district, dong=item.get('umdNm', ''), name=item.get('aptNm', ''), jibun=item.get('jibun', ''),
                area=str(Decimal(item['excluUseAr']).normalize()), price=int(item['dealAmount'].replace(',', '')),
                floor=item.get('floor', ''), day=day,
                cancelled=bool(item.get('cdealDay')) or item.get('cdealType', '') not in ('', 'N'),
                cancelDay=item.get('cdealDay', ''), buildYear=item.get('buildYear', ''),
                aptSeq=item.get('aptSeq', ''), umdCd=item.get('umdCd', ''), tradeType=item.get('dealingGbn', ''))


# ---------------------------------------------------------------- recording

def record_snapshot(db, district, month, fetched_at, xml_pages, total_count, evidence_dir=EVIDENCE_DIR):
    """Store one complete district-month query. xml_pages: list of raw XML bytes (all pages)."""
    items = [it for page in xml_pages for it in raw_items(page)]
    if len(items) != total_count:
        raise ValueError(f'{district}-{month}: {len(items)} rows != totalCount {total_count}; not recorded')
    blob = b'\n<!--PAGE-->\n'.join(xml_pages)
    sha = hashlib.sha256(blob).hexdigest()
    evidence_dir = Path(evidence_dir) / fetched_at[:10]
    evidence_dir.mkdir(parents=True, exist_ok=True)
    raw_path = evidence_dir / f'{district}_{month}_{sha[:16]}.xml.gz'
    with gzip.open(raw_path, 'wb') as f:
        f.write(blob)

    prev = db.execute("SELECT fetch_id FROM fetches WHERE district=? AND month=? AND status='OK' "
                      "ORDER BY fetched_at DESC, fetch_id DESC LIMIT 1", (district, month)).fetchone()
    cur = db.execute("INSERT INTO fetches(district, month, fetched_at, total_count, row_count, raw_sha256, raw_path, status) "
                     "VALUES (?,?,?,?,?,?,?, 'OK')", (district, month, fetched_at, total_count, len(items), sha, str(raw_path)))
    fid = cur.lastrowid

    occ = Counter()
    now_by_key = defaultdict(list)
    for it in items:
        vh, nk = version_hash(it), natural_key(it)
        occ[vh] += 1
        now_by_key[nk].append(vh)
        db.execute("INSERT OR IGNORE INTO trade_versions VALUES (?,?,?,?,?,?,?,?,?)",
                   (vh, nk, district, month, parsed_row(it, district)['day'], fetched_at, fid,
                    json.dumps(parsed_row(it, district), ensure_ascii=False), json.dumps(it, ensure_ascii=False, sort_keys=True)))
        db.execute("INSERT OR IGNORE INTO fetch_members VALUES (?,?,?)", (fid, vh, occ[vh]))

    # change events versus the previous fetch of the same district-month
    before_by_key = defaultdict(list)
    if prev:
        for nk, vh in db.execute("SELECT tv.natural_key, fm.version_hash FROM fetch_members fm JOIN trade_versions tv "
                                 "ON tv.version_hash = fm.version_hash WHERE fm.fetch_id=?", (prev[0],)):
            before_by_key[nk].append(vh)
    def is_cancelled(vh):
        r = db.execute("SELECT parsed_json FROM trade_versions WHERE version_hash=?", (vh,)).fetchone()
        return bool(r and json.loads(r[0]).get('cancelled'))

    for nk in set(now_by_key) | set(before_by_key):
        b, a = sorted(before_by_key.get(nk, [])), sorted(now_by_key.get(nk, []))
        if b == a:
            continue
        if not b:
            if prev is None:
                continue  # first fetch of this district-month: baseline observation, no events
            ev, bh, ah = 'NEW', None, a[0]
        elif not a:
            ev, bh, ah = 'REMOVED', b[0], None
        elif len(a) == 1 and len(b) == 1:
            ev = 'CANCELLED' if (is_cancelled(a[0]) and not is_cancelled(b[0])) else 'CORRECTED'
            bh, ah = b[0], a[0]
        else:
            ev, bh, ah = 'AMBIGUOUS', ','.join(b), ','.join(a)
        db.execute("INSERT INTO trade_events(fetch_id, at, natural_key, event, before_hash, after_hash) VALUES (?,?,?,?,?,?)",
                   (fid, fetched_at, nk, ev, bh, ah))
    db.commit()
    return fid


# ---------------------------------------------------------------- point-in-time reads

def window_months(day, window_days=90):
    end = date.fromisoformat(day)
    start = end - timedelta(days=window_days - 1)
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append(f'{y:04d}{m:02d}')
        y, m = (y + (m == 12), m % 12 + 1)
    return out, start, end


def cutoff_for(day):
    """End of the index day in KST: only queries made on or before that day count."""
    return f'{day}T23:59:59+09:00'


def trades_as_of(db, day, window_days=90, districts=None, verify_files=True):
    """Return (rows, audit). rows: parsed trade dicts with first_seen_at, contract day within window."""
    months, start, end = window_months(day, window_days)
    districts = districts or sorted({r[0] for r in db.execute("SELECT DISTINCT district FROM fetches")})
    cutoff = cutoff_for(day)
    rows, missing, bad_evidence, fetch_ids = [], [], [], []
    for d in districts:
        for m in months:
            f = db.execute("SELECT fetch_id, raw_path, raw_sha256, fetched_at FROM fetches WHERE district=? AND month=? "
                           "AND status='OK' AND fetched_at <= ? ORDER BY fetched_at DESC, fetch_id DESC LIMIT 1",
                           (d, m, cutoff)).fetchone()
            if not f:
                missing.append(f'{d}-{m}')
                continue
            fid, path, sha, fat = f
            fetch_ids.append(fid)
            if verify_files:
                p = Path(path)
                if not p.exists() or hashlib.sha256(gzip.open(p, 'rb').read()).hexdigest() != sha:
                    bad_evidence.append(f'{d}-{m}')
            for pj, fs, occ in db.execute("SELECT tv.parsed_json, tv.first_seen_at, fm.occurrence FROM fetch_members fm "
                                          "JOIN trade_versions tv ON tv.version_hash = fm.version_hash WHERE fm.fetch_id=?", (fid,)):
                r = json.loads(pj)
                if not (start.isoformat() <= r['day'] <= end.isoformat()):
                    continue
                if fs > cutoff:  # defensive: a version can never be first seen after the fetch that returned it
                    bad_evidence.append(f'{d}-{m}:first_seen_after_cutoff')
                    continue
                r['firstSeenAt'] = fs
                rows.append(r)
    verified = bool(districts) and not missing and not bad_evidence and bool(rows)
    audit = {'source': 'APT_WATCH_TRADE_LEDGER', 'cutoff': cutoff, 'windowMonths': months,
             'districts': len(districts), 'districtMonthsRequired': len(districts) * len(months),
             'districtMonthsMissing': missing[:50], 'evidenceProblems': bad_evidence[:50],
             'fetchesUsed': len(fetch_ids), 'tradesInWindow': len(rows),
             'tradeLevelFirstSeenVerified': verified}
    return rows, audit


def key_collision_report(db):
    """How often the composite natural key is shared by more than one deal in the latest fetches."""
    latest = db.execute("SELECT MAX(fetch_id) FROM fetches WHERE status='OK' GROUP BY district, month").fetchall()
    keys = Counter()
    for (fid,) in latest:
        for (nk,) in db.execute("SELECT tv.natural_key FROM fetch_members fm JOIN trade_versions tv "
                                "ON tv.version_hash = fm.version_hash WHERE fm.fetch_id=?", (fid,)):
            keys[nk] += 1
    shared = sum(1 for v in keys.values() if v > 1)
    return {'keys': len(keys), 'keysWithMultipleDeals': shared,
            'collisionRatePct': round(shared / len(keys) * 100, 3) if keys else None}


# ---------------------------------------------------------------- fetching (own MOLIT queries)

def _api():
    sys.path.insert(0, str(TRACKER))
    import app  # tracker module: endpoint, district list, API key loader (key is never printed)
    return app


def fetch_month(db, district, month, app):
    key = app.api_key()
    if not key:
        raise RuntimeError('MOLIT_API_KEY not configured')
    pages, total, page = [], None, 1
    while True:
        today = now_kst()[:10]
        db.execute("INSERT OR IGNORE INTO api_calls VALUES (?, 0)", (today,))
        if db.execute("SELECT count FROM api_calls WHERE day=?", (today,)).fetchone()[0] >= DAILY_CALL_LIMIT:
            raise RuntimeError('ledger daily API call limit reached')
        db.execute("UPDATE api_calls SET count = count + 1 WHERE day=?", (today,))
        db.commit()
        url = app.ENDPOINT + '?' + urllib.parse.urlencode(dict(serviceKey=urllib.parse.unquote(key), LAWD_CD=district,
                                                               DEAL_YMD=month, pageNo=page, numOfRows=1000))
        body = None
        for attempt in range(3):
            try:
                with urllib.request.urlopen(url, timeout=30) as r:
                    body = r.read(20_000_000)
                break
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(2 ** attempt)
        if body is None:
            raise RuntimeError(f'{district}-{month}: API unreachable')
        root = ET.fromstring(body)
        for n in root.iter():
            n.tag = n.tag.split('}')[-1]
        code = root.findtext('.//resultCode')
        if code not in ('000', '00', '0'):
            raise RuntimeError(f'{district}-{month}: API result code {code}')
        t = int(root.findtext('.//totalCount') or 0)
        if total is not None and t != total:
            raise RuntimeError(f'{district}-{month}: totalCount changed between pages')
        total = t
        pages.append(body)
        if sum(len(raw_items(p)) for p in pages) >= total or page >= 50:
            break
        page += 1
    fetched_at = now_kst()
    return record_snapshot(db, district, month, fetched_at, pages, total)


def run_fetch(day=None, window_days=90):
    day = day or datetime.now(KST).date().isoformat()
    app = _api()
    months, _, _ = window_months(day, window_days)
    db = connect()
    ok, failed = 0, []
    for d in app.DISTRICTS:
        for m in months:
            try:
                fetch_month(db, d, m, app)
                ok += 1
            except Exception as e:
                failed.append(f'{d}-{m}: {e}')
    rows, audit = trades_as_of(db, day, window_days, districts=list(app.DISTRICTS))
    result = {'day': day, 'fetchedDistrictMonths': ok, 'failed': failed[:20], 'audit': audit,
              'keyCollision': key_collision_report(db)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--day')
    ap.add_argument('--window-days', type=int, default=90)
    a = ap.parse_args()
    sys.exit(run_fetch(a.day, a.window_days))
