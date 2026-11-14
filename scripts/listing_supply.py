"""Listing supply (매물 수 증감) for the fixed 110-complex panel, and its pairing with the NEGO INDEX.

Rules (observation originals are only read, never modified):
  * Only complexes whose observation passed the quality check (observation_quality = VALID) count.
  * A day is publishable when >= ceil(minValidRate * panel) complexes are VALID (105/110, the NEGO gate),
    the day is not a held day and is on/after the first verified baseline (config/publication_holds.json).
  * A change between two days uses only complexes VALID on BOTH days (same-complex basis) and is
    published only when both days are publishable and the common set still meets the 105 threshold.
    A district change is published only when every panel complex of that district is common.
  * Listing ids are de-duplicated per day across complexes.
  * Disappeared ids are "관측 종료" (not "거래 완료"). A new id that matches an ended id on the same
    complex / area / floor / price is counted as a suspected re-registration, not a new listing.
  * The NEGO pairing (four quadrants) is descriptive only; no signal or forecast is derived from it.

Outputs: site/data.json -> market.listingSupply, and history.sqlite3 -> leading_indicator_panel
(day x scope x horizon rows for later lead-lag tests against transaction prices).

Run after apply_publication_hold.py so the NEGO changes it pairs with are the published ones.
"""
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HIST = ROOT / 'data' / 'history.sqlite3'
SITE = ROOT / 'site' / 'data.json'
PANEL = ROOT / 'data' / 'fixed-110-panel.json'
HOLDS = ROOT / 'config' / 'publication_holds.json'
KST = timezone(timedelta(hours=9))
HORIZONS = (('1d', 1), ('7d', 7), ('28d', 28))
QUADRANTS = {
    ('up', 'down'): ('Q1', '네고 압력 상승 · 매물 감소'),
    ('down', 'up'): ('Q2', '네고 압력 하락 · 매물 증가'),
    ('up', 'up'): ('Q3', '네고 압력 상승 · 매물 증가'),
    ('down', 'down'): ('Q4', '네고 압력 하락 · 매물 감소'),
}
PANEL_DDL = """
CREATE TABLE IF NOT EXISTS leading_indicator_panel (
    day TEXT, scope TEXT, horizon TEXT,
    nego_level REAL, nego_change REAL,
    listings INTEGER, common_complexes INTEGER, listings_ref INTEGER,
    supply_change INTEGER, supply_change_pct REAL,
    quadrant TEXT, published INTEGER, reason TEXT, computed_at TEXT,
    PRIMARY KEY(day, scope, horizon)
)"""


def _kst(ts):
    return datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone(KST)


def collection_kind(window, note):
    """SCHEDULED = regular 06:00 run (first observation 06:00-09:00 KST); RERUN = documented same-day
    re-observation; OFF_SCHEDULE = any other observation time."""
    if note:
        return 'RERUN'
    if window:
        h = datetime.fromisoformat(window['from']).hour
        if 6 <= h < 9:
            return 'SCHEDULED'
    return 'OFF_SCHEDULE'


class Supply:
    def __init__(self, db, panel, holds):
        self.db = db
        self.panel = {str(c['complex']): str(c['district']) for c in panel}
        self.holds = holds or {}
        rate = float(self.holds.get('minValidRate', 0.95))
        self.min_valid = math.ceil(rate * len(self.panel))
        self._cache = {}

    # ---- per day
    def valid(self, day):
        try:
            rows = self.db.execute("SELECT complex FROM observation_quality WHERE day=? AND status='VALID'", (day,)).fetchall()
        except sqlite3.OperationalError:
            return set()
        return {str(r[0]) for r in rows} & set(self.panel)

    def listings(self, day):
        """{complex: {id: (area, floor, price)}} for VALID complexes, ids unique across the day."""
        if day in self._cache:
            return self._cache[day]
        ok = self.valid(day)
        out, seen, dups = defaultdict(dict), set(), 0
        for cx, lid, price, payload in self.db.execute(
                "SELECT complex, id, price, payload FROM listings WHERE day=? ORDER BY complex, id", (day,)):
            cx, lid = str(cx), str(lid)
            if cx not in ok:
                continue
            if lid in seen:
                dups += 1
                continue
            seen.add(lid)
            try:
                p = json.loads(payload) if payload else {}
            except ValueError:
                p = {}
            out[cx][lid] = (p.get('exclusive_area_m2'), str(p.get('floor')), price)
        self._cache[day] = (out, dups)
        return out, dups

    def state(self, day):
        ok = self.valid(day)
        reasons = []
        if not ok:
            reasons.append('품질 판정 자료 없음')
        elif len(ok) < self.min_valid:
            reasons.append(f'품질 검증 통과 {len(ok)}/{len(self.panel)} < {self.min_valid}')
        if day in set(self.holds.get('holdDays', [])):
            reasons.append('공표 유예일(수집 오류 격리)')
        min_ref = self.holds.get('minReferenceDay')
        if min_ref and day < min_ref:
            reasons.append(f'첫 검증 기준선({min_ref}) 이전')
        return {'validComplexes': len(ok), 'publishable': not reasons, 'reasons': reasons}

    def window(self, day, complexes):
        rows = self.db.execute("SELECT complex, observed FROM batches WHERE day=? AND success=1", (day,)).fetchall()
        ts = sorted(_kst(o) for c, o in rows if str(c) in complexes and o)
        if not ts:
            return None
        return {'from': ts[0].isoformat(timespec='minutes'), 'to': ts[-1].isoformat(timespec='minutes'),
                'medianEpoch': ts[len(ts) // 2].timestamp()}

    def level(self, day):
        lst, dups = self.listings(day)
        by_d = Counter()
        for cx, ids in lst.items():
            by_d[self.panel[cx]] += len(ids)
        st = self.state(day)
        w = self.window(day, set(lst) | self.valid(day))
        note = (self.holds.get('observationNotes') or {}).get(day)
        return {'day': day, 'listings': sum(by_d.values()), 'validComplexes': st['validComplexes'],
                'plannedComplexes': len(self.panel), 'duplicateIdsSkipped': dups,
                'publishable': st['publishable'], 'reasons': st['reasons'],
                'observedFromKST': w and w['from'], 'observedToKST': w and w['to'],
                'collection': collection_kind(w, note), 'observationNote': note,
                'districts': dict(by_d)}

    # ---- between two days
    def change(self, day, ref, districts=None):
        s1, s0 = self.state(day), self.state(ref)
        l1, _ = self.listings(day)
        l0, _ = self.listings(ref)
        common = self.valid(day) & self.valid(ref)
        reasons = [f'{day}: {r}' for r in s1['reasons']] + [f'{ref}: {r}' for r in s0['reasons']]
        if len(common) < self.min_valid:
            reasons.append(f'공통 정상 관측 단지 {len(common)}개 < {self.min_valid}개')
        w1, w0 = self.window(day, common), self.window(ref, common)
        gap = round((w1['medianEpoch'] - w0['medianEpoch']) / 3600, 1) if w1 and w0 else None

        def stats(cxs):
            n0 = sum(len(l0.get(c, {})) for c in cxs)
            n1 = sum(len(l1.get(c, {})) for c in cxs)
            new = ended = relist = 0
            for c in cxs:
                a, b = l0.get(c, {}), l1.get(c, {})
                gone = [a[i] for i in a.keys() - b.keys()]
                came = [b[i] for i in b.keys() - a.keys()]
                ended += len(gone)
                new += len(came)
                pool = Counter(gone)
                for sig in came:   # same complex/area/floor/price under a new id -> re-registration suspected
                    if pool[sig] > 0:
                        pool[sig] -= 1
                        relist += 1
            return {'commonComplexes': len(cxs), 'listingsRef': n0, 'listings': n1, 'change': n1 - n0,
                    'changePct': round((n1 / n0 - 1) * 100, 2) if n0 else None,
                    'newListings': new - relist, 'endedListings': ended - relist,
                    'continuing': n1 - new}

        out = stats(common)
        out.update({'referenceDay': ref, 'observationGapHours': gap, 'published': not reasons, 'reasons': reasons})
        if districts:
            out['districts'] = {}
            for d in districts:
                panel_d = {c for c, dd_ in self.panel.items() if dd_ == d}
                cx_d = common & panel_d
                ds = stats(cx_d)
                complete = cx_d == panel_d and bool(panel_d)
                ds['published'] = out['published'] and complete
                if out['published'] and not complete:
                    ds['reason'] = f'자치구 표본 단지 {len(panel_d)}개 중 공통 정상 관측 {len(cx_d)}개'
                if not ds['published']:
                    ds['change'] = ds['changePct'] = None
                out['districts'][d] = ds
        if not out['published']:
            out['change'] = out['changePct'] = None
        return out


def direction(v, eps=0.0):
    if v is None:
        return None
    return 'up' if v > eps else 'down' if v < -eps else 'flat'


def quadrant(nego_change, supply_change):
    a, b = direction(nego_change), direction(supply_change)
    if a is None or b is None:
        return None, '두 지표의 비교 가능한 변화가 모두 있어야 표시'
    if 'flat' in (a, b):
        return 'FLAT', '변화 없음(보합) 포함'
    return QUADRANTS[(a, b)]


def build(site, db, panel, holds, day):
    s = Supply(db, panel, holds)
    days = [r[0] for r in db.execute("SELECT DISTINCT day FROM observation_quality ORDER BY day")]
    districts = sorted(set(s.panel.values()))
    lvl = s.level(day)
    n = site.get('negoIndex') or {}
    sd = ((site.get('market') or {}).get('spreadDynamics') or {})
    nego_dist = sd.get('districts') or {}
    changes, combo = {}, {}
    for h, k in HORIZONS:
        ref = (date.fromisoformat(day) - timedelta(days=k)).isoformat()
        if ref not in days:
            changes[h] = {'referenceDay': ref, 'published': False, 'change': None, 'changePct': None,
                          'reasons': [f'{ref} 관측 없음 ({k}일 전 자료 축적 대기)']}
        else:
            changes[h] = s.change(day, ref, districts)
        nego_ch = ((n.get('changes') or {}).get(h) or {}).get('deltaPctPoint')
        sup_ch = changes[h].get('changePct') if changes[h].get('published') else None
        q, label = quadrant(nego_ch, sup_ch)
        dq = {}
        for d in districts:
            dn = (((nego_dist.get(d) or {}).get('changes') or {}).get(h) or {}).get('deltaPctPoint')
            ds = ((changes[h].get('districts') or {}).get(d) or {})
            dq[d] = dict(zip(('quadrant', 'label'), quadrant(dn, ds.get('changePct') if ds.get('published') else None)))
        combo[h] = {'quadrant': q, 'label': label, 'negoChangePctPoint': nego_ch, 'supplyChangePct': sup_ch, 'districts': dq}

    # same-complex chain index over publishable days (first publishable day = 100)
    series, idx, prev = [], None, None
    for d in days:
        if d > day:
            break
        st = s.state(d)
        if not st['publishable']:
            continue
        lv = s.level(d)
        if prev is None:
            idx = 100.0
            link = None
        else:
            c = s.change(d, prev)
            link = c.get('changePct') if c['published'] else None
            idx = round(idx * (1 + link / 100), 2) if (link is not None and idx is not None) else None
        series.append({'day': d, 'listings': lv['listings'], 'validComplexes': lv['validComplexes'],
                       'sameComplexIndex': idx, 'linkFrom': prev, 'linkChangePct': link,
                       'collection': lv['collection']})
        prev = d

    return {
        'version': 'listing-supply-v1',
        'asOf': day,
        'definition': '고정 표본 110개 단지 중 품질 검증 통과 단지의 매도 매물 수(매물 ID 중복 제거). '
                      '증감은 비교하는 두 날짜에 모두 정상 관측된 단지만으로 계산.',
        'rules': {'minValidComplexes': s.min_valid, 'plannedComplexes': len(s.panel),
                  'districtRule': '자치구 표본 단지 전부가 두 날짜 모두 정상 관측일 때만 자치구 증감 공표',
                  'endedNote': '관측 종료는 거래 완료를 뜻하지 않음(철회·재등록·노출 종료 포함)',
                  'relistRule': '같은 단지·면적·층·가격으로 새 ID가 나타나면 ID만 바뀐 같은 매물로 보고 신규·관측 종료 모두에서 제외(순수치만 공표)',
                  'combinationNote': '네고 압력과 매물 증감의 조합은 관측 기록이며 가격 신호나 예측이 아님'},
        'level': lvl,
        'changes': changes,
        'combination': combo,
        'series': series,
    }


def write_panel(db, out, site):
    db.execute(PANEL_DDL)
    now = datetime.now(KST).isoformat(timespec='seconds')
    day = out['asOf']
    n = site.get('negoIndex') or {}
    nd = ((site.get('market') or {}).get('spreadDynamics') or {}).get('districts') or {}
    lvl = out['level']
    rows = [(day, 'all', 'level', n.get('currentNegoLevel'), None, lvl['listings'], lvl['validComplexes'], None, None, None,
             None, int(lvl['publishable']), '; '.join(lvl['reasons']) or None, now)]
    for d, cnt in lvl['districts'].items():
        rows.append((day, d, 'level', (nd.get(d) or {}).get('percent'), None, cnt, None, None, None, None, None,
                     int(lvl['publishable']), None, now))
    for h, ch in out['changes'].items():
        cb = out['combination'][h]
        rows.append((day, 'all', h, n.get('currentNegoLevel'), cb['negoChangePctPoint'], ch.get('listings'),
                     ch.get('commonComplexes'), ch.get('listingsRef'), ch.get('change'), ch.get('changePct'),
                     cb['quadrant'], int(bool(ch.get('published'))), '; '.join(ch.get('reasons') or []) or None, now))
        for d, ds in (ch.get('districts') or {}).items():
            dn = (((nd.get(d) or {}).get('changes') or {}).get(h) or {}).get('deltaPctPoint')
            rows.append((day, d, h, (nd.get(d) or {}).get('percent'), dn, ds.get('listings'), ds.get('commonComplexes'),
                         ds.get('listingsRef'), ds.get('change'), ds.get('changePct'), cb['districts'][d]['quadrant'],
                         int(bool(ds.get('published'))), ds.get('reason'), now))
    db.executemany("INSERT OR REPLACE INTO leading_indicator_panel VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    db.commit()


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--day')
    a = ap.parse_args(argv)
    site = json.loads(SITE.read_text(encoding='utf-8'))
    day = a.day or (site.get('negoIndex') or {}).get('asOf') or (site.get('market') or {}).get('day')
    panel = json.loads(PANEL.read_text(encoding='utf-8-sig'))
    holds = json.loads(HOLDS.read_text(encoding='utf-8')) if HOLDS.exists() else {}
    with sqlite3.connect(HIST) as db:
        out = build(site, db, panel, holds, day)
        write_panel(db, out, site)
    site.setdefault('market', {})['listingSupply'] = out
    SITE.write_text(json.dumps(site, ensure_ascii=False, indent=2), encoding='utf-8')
    lv = out['level']
    print(f"[supply] {day}: listings {lv['listings']} in {lv['validComplexes']}/{lv['plannedComplexes']} complexes, "
          f"publishable={lv['publishable']} {lv['reasons'] or ''}")
    for h, ch in out['changes'].items():
        print(f"[supply] {h} vs {ch.get('referenceDay')}: published={ch.get('published')} change={ch.get('change')} "
              f"pct={ch.get('changePct')} reasons={ch.get('reasons')}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
