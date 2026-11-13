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


def main():
    hold = load_holds()
    if not hold:
        print('[hold] no publication_holds.json; nothing to do')
        return 0
    site = json.loads(SITE_FILE.read_text(encoding='utf-8'))
    changed = apply_hold(site, hold)
    if changed:
        SITE_FILE.write_text(json.dumps(site, ensure_ascii=False, indent=2), encoding='utf-8')
        print('[hold] publication hold applied to site/data.json')
    else:
        print('[hold] site data does not reference a held day; no change')
    return 0


if __name__ == '__main__':
    sys.exit(main())
