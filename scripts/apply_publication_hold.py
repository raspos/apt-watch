"""Publication hold for NEGO INDEX values built on unverified observations.

Reads data/publication_holds.json. If the published site/data.json refers to a held day
(negoIndex.asOf, market.day, or any spread series day), every NEGO-derived number is withheld
and replaced with a visible "수집 데이터 검증 중" state. Raw observations in SQLite are never touched.

Idempotent. Run it on site/data.json before it is committed (daily_operation does this).
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HOLD_FILE = ROOT / 'config' / 'publication_holds.json'
SITE_FILE = ROOT / 'site' / 'data.json'

HELD_STATUS = '수집 데이터 검증 중'
HELD_CODE = 'HELD_VERIFICATION'


def load_holds():
    if not HOLD_FILE.exists():
        return None
    return json.loads(HOLD_FILE.read_text(encoding='utf-8'))


def _hold_spread_node(node):
    """Withhold a spread-like node (percent / sample / groups / listings) in place."""
    if not isinstance(node, dict):
        return
    for k in list(node.keys()):
        v = node[k]
        if k == 'percent':
            node[k] = None
        elif k in ('sample', 'groups', 'matchedListings', 'groups90d', 'groups180d'):
            node[k] = 0
        elif k in ('actual90d', 'longTerm180d', 'modelEst'):
            _hold_spread_node(v)
        elif k == 'changes' and isinstance(v, dict):
            for p in list(v.keys()):
                v[p] = {'status': HELD_CODE, 'deltaPctPoint': None, 'reason': HELD_STATUS}
    if 'status' in node:
        node['status'] = HELD_STATUS
    if 'statusCode' in node:
        node['statusCode'] = HELD_CODE
    if 'reason' in node:
        node['reason'] = HELD_STATUS
    if 'medianBenchmarkAgeDays' in node:
        node['medianBenchmarkAgeDays'] = None


def _held_days(site, hold):
    days = set(hold.get('holdDays', []))
    seen = set()
    n = site.get('negoIndex') or {}
    seen.add(n.get('asOf'))
    seen.add((site.get('market') or {}).get('day'))
    so = ((site.get('market') or {}).get('spreadDynamics') or {}).get('seoulOverall') or {}
    for s in ('seriesA_FullCrossSection', 'seriesB_FixedSamplePanel'):
        for p in so.get(s, []) or []:
            seen.add(p.get('day'))
    seen.add(((site.get('market') or {}).get('spreadDynamics') or {}).get('qualityCounts', {}).get('targetDay'))
    return days & {x for x in seen if x}


def apply_hold(site, hold):
    touched = _held_days(site, hold)
    if not touched:
        return False
    prov = hold.get('provisional')

    # 1) NEGO hero
    n = site.setdefault('negoIndex', {})
    n['status'] = HELD_CODE
    n['statusLabel'] = HELD_STATUS
    n['officialPublicationAllowed'] = False
    n['currentNegoPressurePct'] = None
    n['currentNegoLevel'] = None
    n['changes'] = {p: {'status': HELD_CODE, 'deltaPctPoint': None, 'reason': HELD_STATUS}
                    for p in ('1d', '7d', '28d')}
    n.pop('decomposition', None)
    n['seriesA_FullCrossSection'] = []
    n['seriesB_FixedSamplePanel'] = []
    n['heldReason'] = hold.get('reason')
    n['heldDays'] = sorted(hold.get('holdDays', []))
    n['provisionalNote'] = prov.get('note') if prov else None

    market = site.setdefault('market', {})
    # 2) legacy pressure + region/map spread
    if isinstance(market.get('pressure'), dict):
        market['pressure']['spreadPct'] = None
        psd = market['pressure'].get('spreadDynamics')
        if isinstance(psd, dict):
            psd['spreadPct'] = None
            psd['changes'] = {p: {'status': HELD_CODE, 'deltaPctPoint': None, 'reason': HELD_STATUS}
                              for p in ('1d', '7d', '28d')}
            psd['decomposition'] = {'status': HELD_CODE, 'reason': HELD_STATUS}
    for node in (market.get('regions') or {}).values():
        _hold_spread_node(node.get('spread') if isinstance(node, dict) else None)
    for pts in (market.get('spreadHistory') or {}).values():
        for p in pts:
            _hold_spread_node(p)
    for day_map in (market.get('dailySnapshots') or {}).values():
        for node in day_map.values():
            _hold_spread_node(node)

    # 3) spread dynamics (Seoul + districts + decomposition + series)
    sd = market.get('spreadDynamics') or {}
    so = sd.get('seoulOverall') or {}
    if so:
        so['currentSpreadPct'] = None
        so['currentSpreadStatus'] = HELD_STATUS
        so['sampleGroupsCount'] = 0
        so['matchedListingsCount'] = 0
        so['changes'] = {p: {'status': HELD_CODE, 'deltaPctPoint': None, 'reason': HELD_STATUS}
                         for p in ('1d', '7d', '28d')}
        so['decomposition'] = {'status': HELD_CODE, 'reason': HELD_STATUS}
        so['seriesA_FullCrossSection'] = []
        so['seriesB_FixedSamplePanel'] = []
        so.pop('allSample', None)
    for node in (sd.get('districts') or {}).values():
        _hold_spread_node(node)
        node['decomposition'] = {'status': HELD_CODE, 'reason': HELD_STATUS}
    qc = sd.get('qualityCounts') or {}
    if isinstance(qc.get('weightingComparisons'), dict):
        for k in list(qc['weightingComparisons'].keys()):
            if isinstance(qc['weightingComparisons'][k], (int, float)):
                qc['weightingComparisons'][k] = None
    sd['status'] = HELD_CODE

    # 4) append to data change log (kept, never rewritten)
    log = site.setdefault('dataChangeLog', [])
    entry = {
        'id': hold.get('id'),
        'appliedFor': sorted(touched),
        'at': hold.get('loggedAt'),
        'action': 'NEGO INDEX 수치 공표 유예 (수집 데이터 검증 중)',
        'reason': hold.get('reason'),
    }
    if not any(e.get('id') == entry['id'] for e in log):
        log.append(entry)
    return True


def _quality(day, planned):
    """Quality summary for a day from history.sqlite3 (None if the day was never assessed)."""
    import sqlite3
    sys.path.insert(0, str(ROOT / 'scripts'))
    import observation_quality as oq
    db_path = ROOT / 'data' / 'history.sqlite3'
    if not db_path.exists() or not day:
        return None
    with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True) as db:
        try:
            if db.execute("SELECT COUNT(*) FROM observation_quality WHERE day=?", (day,)).fetchone()[0] == 0:
                return None
        except sqlite3.OperationalError:
            return None
        rows = db.execute("SELECT status, COUNT(*) FROM observation_quality WHERE day=? GROUP BY status", (day,)).fetchall()
    valid = dict(rows).get('VALID', 0)
    return {'valid': valid, 'planned': planned, 'rate': valid / planned if planned else 0.0}


def evaluate_gate(site, hold, min_rate=0.95):
    """Return (level_reasons, {horizon: reason}) -- reasons are empty when publication is allowed."""
    n = site.get('negoIndex') or {}
    day = n.get('asOf') or (site.get('market') or {}).get('day')
    panel = ROOT / 'data' / 'fixed-110-panel.json'
    planned = len(json.loads(panel.read_text(encoding='utf-8-sig'))) if panel.exists() else 110
    level, changes = [], {}
    if day in set(hold.get('holdDays', [])):
        level.append(f'{day} is a held day')
    q = _quality(day, planned)
    if q is None:
        level.append(f'{day} observations have no quality assessment')
    elif q['rate'] < min_rate:
        level.append(f'{day} quality-verified complexes {q["valid"]}/{q["planned"]} < {min_rate:.0%}')
    vint = (((site.get('market') or {}).get('spreadDynamics') or {}).get('qualityCounts') or {}).get('pointInTimeVintageAudit') or {}
    # The official benchmark must be the point-in-time trade ledger, verified for this exact day
    # (per-trade first-seen times, raw evidence, all 25 districts x window months). The legacy
    # snapshot-level flag (isContemporaneousLiveVintage) describes the tracker benchmark only and is
    # neither required nor sufficient once the ledger is the benchmark.
    ledger = vint.get('tradeLedger') or {}
    ledger_ok = (vint.get('targetDay') == day
                 and vint.get('benchmarkSource') == 'APT_WATCH_TRADE_LEDGER'
                 and vint.get('tradeLevelFirstSeenVerified') is True
                 and ledger.get('tradeLevelFirstSeenVerified') is True
                 and ledger.get('cutoff', '')[:10] == day
                 and ledger.get('districts') == 25
                 and not ledger.get('districtMonthsMissing')
                 and not ledger.get('evidenceProblems'))
    if hold.get('requireTradeFirstSeenVerification', True) and not ledger_ok:
        level.append(f'{day} trade benchmark is not the verified point-in-time ledger '
                     f'(per-trade first-seen / evidence / 25-district completeness)')
    min_ref = hold.get('minReferenceDay')
    for h, ch in ((site.get('negoIndex') or {}).get('changes') or {}).items():
        ref = (ch or {}).get('referenceDay')
        if ch is None or ch.get('deltaPctPoint') is None:
            continue
        if not ref:
            changes[h] = 'no reference day recorded'
        elif not ch.get('referenceTradeLevelFirstSeenVerified'):
            changes[h] = f'reference day {ref} trade benchmark lacks per-trade first-seen verification'
        elif min_ref and ref < min_ref:
            changes[h] = f'reference day {ref} precedes first verified live baseline {min_ref}'
        else:
            rq = _quality(ref, planned)
            if rq is None or rq['rate'] < min_rate:
                changes[h] = f'reference day {ref} not quality-verified'
    return level, changes


def scrub_held_day_points(site, hold):
    """Drop per-day points (series / history / snapshots) for explicitly held days. Idempotent."""
    days = set(hold.get('holdDays', []))
    market = site.get('market') or {}
    for pts in (market.get('spreadHistory') or {}).values():
        for p in pts:
            if p.get('day') in days:
                _hold_spread_node(p)
    for d in list((market.get('dailySnapshots') or {}).keys()):
        if d in days:
            for node in market['dailySnapshots'][d].values():
                _hold_spread_node(node)
    so = (market.get('spreadDynamics') or {}).get('seoulOverall') or {}
    for k in ('seriesA_FullCrossSection', 'seriesB_FixedSamplePanel'):
        if so.get(k):
            so[k] = [p for p in so[k] if p.get('day') not in days]
    n = site.get('negoIndex') or {}
    for k in ('seriesA_FullCrossSection', 'seriesB_FixedSamplePanel'):
        if n.get(k):
            n[k] = [p for p in n[k] if p.get('day') not in days]


def hold_changes_only(site, horizons, reasons):
    held = {'status': HELD_CODE, 'deltaPctPoint': None, 'reason': HELD_STATUS}
    containers = [(site.get('negoIndex') or {}).get('changes'),
                  ((site.get('market') or {}).get('spreadDynamics') or {}).get('seoulOverall', {}).get('changes'),
                  ((site.get('market') or {}).get('pressure') or {}).get('spreadDynamics', {}).get('changes')]
    for c in containers:
        if isinstance(c, dict):
            for h in horizons:
                if h in c:
                    c[h] = dict(held)
    so = ((site.get('market') or {}).get('spreadDynamics') or {}).get('seoulOverall') or {}
    if '1d' in horizons:
        so['decomposition'] = {'status': HELD_CODE, 'reason': HELD_STATUS}
        so['seriesB_FixedSamplePanel'] = []
    log = site.setdefault('dataChangeLog', [])
    log.append({'id': f"CHANGE-HOLD-{(site.get('negoIndex') or {}).get('asOf')}-{','.join(sorted(horizons))}",
                'at': datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds'),
                'action': '변화폭 공표 유예', 'reason': '; '.join(reasons.values())})


def main():
    hold = load_holds()
    if not hold:
        print('[hold] no publication_holds.json; nothing to do')
        return 0
    site = json.loads(SITE_FILE.read_text(encoding='utf-8'))
    before = json.dumps(site, sort_keys=True)
    scrub_held_day_points(site, hold)
    level_reasons, change_reasons = evaluate_gate(site, hold)
    if level_reasons:
        # static hold days use the logged reason; dynamic failures log their own
        h2 = dict(hold)
        if not any('held day' in r for r in level_reasons):
            h2['id'] = f"GATE-{(site.get('negoIndex') or {}).get('asOf')}"
            h2['holdDays'] = sorted(set(hold.get('holdDays', [])) | {(site.get('negoIndex') or {}).get('asOf')})
            h2['reason'] = '자동 품질 게이트 미통과: ' + '; '.join(level_reasons)
            h2['loggedAt'] = datetime.now(timezone(timedelta(hours=9))).isoformat(timespec='seconds')
        apply_hold(site, h2)
        print('[hold] LEVEL held:', '; '.join(level_reasons))
    elif change_reasons:
        hold_changes_only(site, set(change_reasons), change_reasons)
        print('[hold] CHANGES held:', change_reasons)
    else:
        print('[hold] gate passed; nothing withheld')
    if json.dumps(site, sort_keys=True) != before:
        SITE_FILE.write_text(json.dumps(site, ensure_ascii=False, indent=2), encoding='utf-8')
        print('[hold] site/data.json updated')
    return 0


if __name__ == '__main__':
    sys.exit(main())
