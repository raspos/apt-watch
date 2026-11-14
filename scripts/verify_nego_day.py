"""Read-only verification of a published NEGO INDEX day, using the production engine functions.

Rebuilds the comparison groups exactly as divergence_dynamics.run_spread_dynamics does (quality-verified
listings only, point-in-time trade ledger benchmark, >=3 trades per group), then reports:
  * group table (CSV) and the canonical aggregate (median of group NEGO values)
  * sensitivity: excluding groups with exclusive-area bucket < 15 m2 / < 30 m2 (analysis only)
  * district coverage and why a district has no 90-day value
Nothing is written to the databases or to site/data.json.

usage: python scripts/verify_nego_day.py --day 2026-11-14 [--out docs/phase2]
"""
import argparse
import csv
import json
import random
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import divergence_dynamics as dd  # noqa: E402

DISTRICT_NAMES = {
    '11110': '종로구', '11140': '중구', '11170': '용산구', '11200': '성동구', '11215': '광진구', '11230': '동대문구',
    '11260': '중랑구', '11290': '성북구', '11305': '강북구', '11320': '도봉구', '11350': '노원구', '11380': '은평구',
    '11410': '서대문구', '11440': '마포구', '11470': '양천구', '11500': '강서구', '11530': '구로구', '11545': '금천구',
    '11560': '영등포구', '11590': '동작구', '11620': '관악구', '11650': '서초구', '11680': '강남구', '11710': '송파구',
    '11740': '강동구'}
TIER = {0: '저층(1~3)', 1: '중층(4~9)', 2: '고층(10~)'}


def build(day):
    crosswalk = dd.load_crosswalk()
    hdb = sqlite3.connect(f"file:{ROOT / 'data' / 'history.sqlite3'}?mode=ro", uri=True)
    tdb = sqlite3.connect(f"file:{ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3'}?mode=ro", uri=True)
    l_id, l_strata, comps, failed = dd.extract_listings_for_day(hdb, day, crosswalk)
    t90, meta = dd.extract_trades_up_to_day(tdb, day, window_days=90, mode='CONTEMPORANEOUS_ONLY')
    if meta['contemporaneousTrades'] == 0:
        t90, meta = dd.extract_trades_up_to_day(tdb, day, window_days=90, mode='EX_POST_RECONSTRUCTED')
    t90, meta = dd.apply_trade_ledger(day, t90, meta)
    t180, meta180 = dd.extract_trades_up_to_day(tdb, day, window_days=180, mode='CONTEMPORANEOUS_ONLY')
    if meta['contemporaneousTrades'] == 0:
        t180, meta180 = dd.extract_trades_up_to_day(tdb, day, window_days=180, mode='EX_POST_RECONSTRUCTED')
    s90 = dd.calculate_strata_divergence(l_strata, t90, min_trades=3)
    s180 = dd.calculate_strata_divergence(l_strata, t180, min_trades=2)
    return l_id, l_strata, t90, meta, s90, s180, comps


def boot_median_ci(vals, n=5000, seed=7):
    rnd = random.Random(seed)
    meds = sorted(median(rnd.choices(vals, k=len(vals))) for _ in range(n))
    return round(meds[int(0.025 * n)], 2), round(meds[int(0.975 * n)], 2)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--day', required=True)
    ap.add_argument('--out', default=str(ROOT / 'docs' / 'phase2'))
    a = ap.parse_args()
    day, out = a.day, Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    l_id, l_strata, t90, meta, s90, s180, comps = build(day)

    # --- group table
    rows = []
    for k, s in sorted(s90.items(), key=lambda kv: kv[1]['spreadPct']):
        cxs = sorted({x.split('_')[1] for x in s['listingIdsList']})
        rows.append({'district': DISTRICT_NAMES.get(s['district'], s['district']), 'districtCode': s['district'],
                     'complex': s['name'], 'complexIds': ' '.join(cxs), 'areaBucketM2': s['intArea'],
                     'floorTier': TIER.get(s['tier'], s['tier']), 'listings': s['listingCount'], 'trades90d': s['tradeCount'],
                     'askMedianManwon': s['askMedian'], 'tradeMedianManwon': s['tradeMedian'],
                     'groupNegoPct': round(s['spreadPct'], 2), 'medianTradeAgeDays': s['medianTradeAgeDays']})
    with open(out / f'groups_{day}.csv', 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    vals = [s['spreadPct'] for s in s90.values()]
    agg = dd.calculate_aggregate_spread(s90, {}, [])
    site = json.loads((ROOT / 'site' / 'data.json').read_text(encoding='utf-8'))
    published = (site.get('negoIndex') or {}).get('currentNegoLevel')
    srt = sorted(vals)
    n = len(srt)

    def sens(min_area):
        v = [s['spreadPct'] for s in s90.values() if s['intArea'] >= min_area]
        return {'groups': len(v), 'listings': sum(s['listingCount'] for s in s90.values() if s['intArea'] >= min_area),
                'median': round(median(v), 2) if v else None}

    by_d = defaultdict(list)
    for s in s90.values():
        by_d[s['district']].append(s)
    by_c = Counter(s['name'] for s in s90.values())
    # all listing strata (any trades) to show how much of the observed sample the index covers
    strata_trade_n = Counter()
    for k in l_strata:
        strata_trade_n[min(len(t90.get(k, [])), 3)] += 1
    district_cov = {}
    for d, nm in DISTRICT_NAMES.items():
        d_listings = sum(len(v) for k, v in l_strata.items() if k[0] == d)
        d_strata = [k for k in l_strata if k[0] == d]
        best = max((len(t90.get(k, [])) for k in d_strata), default=0)
        g180 = [s for k, s in s180.items() if k[0] == d]
        district_cov[nm] = {'groups90d': len(by_d.get(d, [])), 'median90d': round(median([s['spreadPct'] for s in by_d[d]]), 2) if by_d.get(d) else None,
                            'listingsInGroups': sum(s['listingCount'] for s in by_d.get(d, [])), 'listingsObserved': d_listings,
                            'listingStrata': len(d_strata), 'maxLedgerTradesInAnyStratum': best,
                            'groups180dTracker': len(g180)}
    summary = {
        'day': day,
        'benchmark': {k: meta.get(k) for k in ('benchmarkSource', 'tradeLevelFirstSeenVerified')} | {
            'tradesInWindow': (meta.get('tradeLedger') or {}).get('tradesInWindow'),
            'cutoff': (meta.get('tradeLedger') or {}).get('cutoff')},
        'tradesUsedInGroups': sum(s['tradeCount'] for s in s90.values()),
        'groups': n, 'listingsInGroups': sum(s['listingCount'] for s in s90.values()),
        'listingsObservedVerified': len(l_id), 'complexesWithListings': len(comps),
        'complexesInGroups': len({c for r in rows for c in r['complexIds'].split()}),
        'aggregate': {'medianOfGroups': agg['equalWeight'], 'recomputedMedianUnrounded': round(median(vals), 4),
                      'middleValues': [round(x, 4) for x in (srt[n // 2 - 1:n // 2 + 1] if n % 2 == 0 else srt[n // 2:n // 2 + 1])],
                      'meanOfGroups': round(mean(vals), 2),
                      'listingWeightedMean': round(sum(s['spreadPct'] * s['listingCount'] for s in s90.values()) / sum(s['listingCount'] for s in s90.values()), 2),
                      'districtBalanced': agg['districtBalanced'], 'complexBalanced': agg['complexBalanced'],
                      'published': published, 'matchesPublished': published == agg['equalWeight'],
                      'bootstrap95CIofMedian': boot_median_ci(vals),
                      'p10': round(srt[int(0.1 * n)], 2), 'p25': round(srt[int(0.25 * n)], 2), 'p75': round(srt[int(0.75 * n)], 2),
                      'p90': round(srt[int(0.9 * n)], 2), 'min': round(srt[0], 2), 'max': round(srt[-1], 2)},
        'sensitivity': {'all': sens(0), 'excludeUnder15m2': sens(15), 'excludeUnder30m2': sens(30)},
        'concentration': {'groupsPerComplexTop': by_c.most_common(5), 'complexesInGroups': len(by_c),
                          'groupsWithTrades3to4': sum(1 for s in s90.values() if s['tradeCount'] <= 4),
                          'groupsWithListings1': sum(1 for s in s90.values() if s['listingCount'] == 1)},
        'coverage': {'listingStrataTotal': len(l_strata), 'strataBy90dTradeCount(0,1,2,3+)': [strata_trade_n[i] for i in range(4)]},
        'districts': district_cov,
    }
    (out / f'verify_{day}.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: summary[k] for k in ('benchmark', 'tradesUsedInGroups', 'groups', 'listingsInGroups', 'listingsObservedVerified', 'complexesInGroups', 'aggregate', 'sensitivity', 'concentration', 'coverage')}, ensure_ascii=False, indent=1))
    print('districts without 90d value:', {k: v for k, v in district_cov.items() if not v['groups90d']})
    print('districts with 1-2 groups:', {k: v['groups90d'] for k, v in district_cov.items() if 0 < v['groups90d'] < 3})


if __name__ == '__main__':
    main()
