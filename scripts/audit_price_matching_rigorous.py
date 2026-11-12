"""Rigorous Audit of Price Divergence Matching (가격괴리지수 정밀 매칭 검증).

Strictly implements the exact stratum matching algorithm from market_metrics.py:
  trade_key = (district, dong, jibun, name, int(area), tier)
  where tier = 0 (floor <= 3), 1 (floor 4..9), 2 (floor >= 10)

Calculates and distinguishes the 5 exact numbers across 90-day and 180-day windows:
  1. Complexes with >= 3 recent trades (90d and 180d)
  2. Observed asking complexes in history.sqlite3
  3. Complexes with exact matching strata (complexes having at least 1 valid matched stratum)
  4. Valid comparison groups with >= 3 benchmark trades
  5. Actual asking listings utilized in divergence index computation

Specifically verifies Gangnam (11680) and Seocho (11650) to ensure long-term 180d
benchmark groups and listings are accurately accounted for.
Outputs full report to data/price_matching_rigorous_report.json.
"""

import json
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from math import isfinite
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parent.parent

def trade_key(row):
    area_val = row.get('area') or row.get('exclusive_area_m2', 0)
    area = float(area_val)
    raw_floor = str(row.get('floor', '5')).split('/')[0].strip()
    if raw_floor == '저':
        tier = 0
    elif raw_floor == '고':
        tier = 2
    elif raw_floor.isdigit():
        f = int(raw_floor)
        tier = 0 if f <= 3 else 1 if f <= 9 else 2
    else:
        tier = 1
    if not row.get('jibun') or not isfinite(area) or area < 1:
        raise ValueError('Incomplete trade stratum')
    name = row.get('name', '')
    if '마포래미안푸르지오' in name:
        name = '마포래미안푸르지오'
    return (row['district'], row['dong'], row['jibun'], name, int(area), tier)


def run_rigorous_audit(target_day=None):
    hdb_path = ROOT / 'data' / 'history.sqlite3'
    tdb_path = ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3'

    with sqlite3.connect(hdb_path) as hdb:
        if not target_day:
            target_day = hdb.execute("SELECT MAX(day) FROM listings").fetchone()[0] or '2026-11-12'

        # 2. Observed asking complexes in history.sqlite3
        obs_comps_rows = hdb.execute(
            "SELECT DISTINCT complex FROM batches WHERE day=? AND success=1", (target_day,)
        ).fetchall()
        observed_complex_ids = {r[0] for r in obs_comps_rows}

        # Observed listings on target day
        listings_rows = hdb.execute(
            "SELECT day, complex, id, price, payload FROM listings WHERE day=?", (target_day,)
        ).fetchall()

    # Load complexes crosswalk mapping
    crosswalk = {}
    comps_path = ROOT / 'data' / 'complexes.json'
    if comps_path.exists():
        comps_data = json.loads(comps_path.read_text(encoding='utf-8'))
        for c in comps_data:
            crosswalk[c['complex']] = c

    fixed_path = ROOT / 'data' / 'seoul-fixed-sample.json'
    if fixed_path.exists():
        fixed_data = json.loads(fixed_path.read_text(encoding='utf-8'))
        for c in fixed_data:
            crosswalk[c['complex']] = c

    # District names
    district_names = {
        '11110': '종로구', '11140': '중구', '11170': '용산구', '11200': '성동구', '11215': '광진구',
        '11230': '동대문구', '11260': '중랑구', '11290': '성북구', '11305': '강북구', '11320': '도봉구',
        '11350': '노원구', '11380': '은평구', '11410': '서대문구', '11440': '마포구', '11470': '양천구',
        '11500': '강서구', '11530': '구로구', '11545': '금천구', '11560': '영등포구', '11590': '동작구',
        '11620': '관악구', '11650': '서초구', '11680': '강남구', '11710': '송파구', '11740': '강동구'
    }

    # Trade windows
    end_date = date.fromisoformat(target_day)
    start_date_90 = end_date - timedelta(days=89)
    start_date_180 = end_date - timedelta(days=179)

    # 1. Load trades from tracker
    with sqlite3.connect(tdb_path) as tdb:
        trades_raw = tdb.execute("SELECT district, month, payload FROM trades WHERE month >= '2024-01'").fetchall()

    trades_by_comp_90 = defaultdict(int)
    trades_by_comp_180 = defaultdict(int)
    trades_by_key_90 = defaultdict(list)
    trades_by_key_180 = defaultdict(list)

    total_valid_trades_90 = 0
    total_valid_trades_180 = 0

    for dist, month, p_str in trades_raw:
        p = json.loads(p_str)
        if p.get('cancelled'):
            continue
        t_day = p.get('day')
        if not t_day:
            continue
        price = float(p.get('price', 0))
        if price <= 0:
            continue

        comp_addr = (p['district'], p['dong'], p.get('jibun', ''), p['name'])

        if start_date_180.isoformat() <= t_day <= target_day:
            trades_by_comp_180[comp_addr] += 1
            total_valid_trades_180 += 1
            try:
                k = trade_key(p)
                trades_by_key_180[k].append((price, t_day))
            except Exception:
                pass

        if start_date_90.isoformat() <= t_day <= target_day:
            trades_by_comp_90[comp_addr] += 1
            total_valid_trades_90 += 1
            try:
                k = trade_key(p)
                trades_by_key_90[k].append((price, t_day))
            except Exception:
                pass

    # Total complexes with >= 3 trades in tracker universe
    universe_comps_ge3_90 = sum(1 for cnt in trades_by_comp_90.values() if cnt >= 3)
    universe_comps_ge3_180 = sum(1 for cnt in trades_by_comp_180.values() if cnt >= 3)

    # Breakdown by district for tracker trades
    district_trades_ge3_90 = defaultdict(int)
    district_trades_ge3_180 = defaultdict(int)
    for comp_addr, cnt in trades_by_comp_90.items():
        if cnt >= 3:
            district_trades_ge3_90[comp_addr[0]] += 1
    for comp_addr, cnt in trades_by_comp_180.items():
        if cnt >= 3:
            district_trades_ge3_180[comp_addr[0]] += 1

    # Map today's observed listings to strata
    # asks_by_key: key -> list of (listing_id, price, complex_id, district)
    asks_by_key = defaultdict(list)
    observed_comps_by_district = defaultdict(set)
    total_observed_listings_count = 0

    for day, cid, lid, price, payload_str in listings_rows:
        total_observed_listings_count += 1
        p = json.loads(payload_str)
        cinfo = crosswalk.get(cid)
        if not cinfo or not cinfo.get('tradeComplex'):
            continue
        tc = cinfo['tradeComplex']
        dist = tc[0]
        observed_comps_by_district[dist].add(cid)

        try:
            area = float(p.get('exclusive_area_m2') or p.get('area', 0))
            if area < 10:
                continue
            ask_price = float(p.get('asking_price_manwon') or price or 0)
            if ask_price <= 0:
                continue

            row = {
                'district': tc[0],
                'dong': tc[1],
                'jibun': tc[2],
                'name': tc[3],
                'exclusive_area_m2': area,
                'floor': p.get('floor', 5)
            }
            k = trade_key(row)
            asks_by_key[k].append({
                'id': lid,
                'complex': cid,
                'district': dist,
                'price': ask_price
            })
        except Exception:
            continue

    # Evaluate 90-day matching
    groups_90 = {}
    comps_matched_90 = set()
    listings_used_90 = []
    district_matching_90 = defaultdict(lambda: {'groups': 0, 'listings': 0, 'comps': set(), 'spreads': []})

    for k, ask_list in asks_by_key.items():
        dist = k[0]
        benchmark = trades_by_key_90.get(k, [])
        if len(benchmark) >= 3:
            med_ask = median(item['price'] for item in ask_list)
            med_trade = median(p for p, _ in benchmark)
            spread_pct = 100 * (med_ask / med_trade - 1)
            groups_90[k] = {
                'ask_count': len(ask_list),
                'trade_count': len(benchmark),
                'med_ask': med_ask,
                'med_trade': med_trade,
                'spread': spread_pct
            }
            district_matching_90[dist]['groups'] += 1
            district_matching_90[dist]['listings'] += len(ask_list)
            district_matching_90[dist]['spreads'].append(spread_pct)
            for item in ask_list:
                listings_used_90.append(item)
                comps_matched_90.add(item['complex'])
                district_matching_90[dist]['comps'].add(item['complex'])

    # Evaluate 180-day matching
    groups_180 = {}
    comps_matched_180 = set()
    listings_used_180 = []
    district_matching_180 = defaultdict(lambda: {'groups': 0, 'listings': 0, 'comps': set(), 'spreads': [], 'ages': []})

    for k, ask_list in asks_by_key.items():
        dist = k[0]
        benchmark = trades_by_key_180.get(k, [])
        if len(benchmark) >= 3:
            med_ask = median(item['price'] for item in ask_list)
            med_trade = median(p for p, _ in benchmark)
            spread_pct = 100 * (med_ask / med_trade - 1)
            latest_trade_day = max(d for _, d in benchmark)
            age_days = (end_date - date.fromisoformat(latest_trade_day)).days

            groups_180[k] = {
                'ask_count': len(ask_list),
                'trade_count': len(benchmark),
                'med_ask': med_ask,
                'med_trade': med_trade,
                'spread': spread_pct,
                'age_days': age_days
            }
            district_matching_180[dist]['groups'] += 1
            district_matching_180[dist]['listings'] += len(ask_list)
            district_matching_180[dist]['spreads'].append(spread_pct)
            district_matching_180[dist]['ages'].append(age_days)
            for item in ask_list:
                listings_used_180.append(item)
                comps_matched_180.add(item['complex'])
                district_matching_180[dist]['comps'].add(item['complex'])

    # Prepare 25-district detailed analysis
    district_details = {}
    for code, name in sorted(district_names.items()):
        obs_comps_cnt = len(observed_comps_by_district[code])
        tr_ge3_90 = district_trades_ge3_90[code]
        tr_ge3_180 = district_trades_ge3_180[code]

        # 90d
        d90 = district_matching_90[code]
        g90 = d90['groups']
        l90 = d90['listings']
        c90 = len(d90['comps'])
        med_sp_90 = round(median(d90['spreads']), 2) if d90['spreads'] else None

        # 180d
        d180 = district_matching_180[code]
        g180 = d180['groups']
        l180 = d180['listings']
        c180 = len(d180['comps'])
        med_sp_180 = round(median(d180['spreads']), 2) if d180['spreads'] else None
        med_age_180 = round(median(d180['ages']), 1) if d180['ages'] else None

        # Determine official status
        if g90 >= 1:
            tier_status = '실측 (90일)'
            tier_code = 'ACTUAL_90D'
            pub_groups = g90
            pub_listings = l90
            pub_spread = med_sp_90
        elif g180 >= 1:
            tier_status = '장기 실측 참고치 (180일)'
            tier_code = 'LONG_TERM_180D'
            pub_groups = g180
            pub_listings = l180
            pub_spread = med_sp_180
        else:
            tier_status = '비교자료 부족'
            tier_code = 'INSUFFICIENT'
            pub_groups = 0
            pub_listings = 0
            pub_spread = None

        district_details[code] = {
            'name': name,
            'observedComplexes': obs_comps_cnt,
            'universeComplexesWithTrades_ge3_90d': tr_ge3_90,
            'universeComplexesWithTrades_ge3_180d': tr_ge3_180,
            'match_90d': {
                'groups': g90,
                'matchedListings': l90,
                'matchedComplexes': c90,
                'spread': med_sp_90
            },
            'match_180d': {
                'groups': g180,
                'matchedListings': l180,
                'matchedComplexes': c180,
                'spread': med_sp_180,
                'medianBenchmarkAgeDays': med_age_180
            },
            'publication': {
                'status': tier_status,
                'statusCode': tier_code,
                'groups': pub_groups,
                'matchedListings': pub_listings,
                'spread': pub_spread
            }
        }

    report = {
        'targetDate': target_day,
        'summary5Metrics': {
            '1_complexesWithRecentTradesGe3': {
                '90days': universe_comps_ge3_90,
                '180days': universe_comps_ge3_180
            },
            '2_observedAskingComplexesInHistory': len(observed_complex_ids),
            '3_complexesWithExactStratumMatches': {
                '90days': len(comps_matched_90),
                '180days': len(comps_matched_180)
            },
            '4_validComparisonGroupsWithTradesGe3': {
                '90days': len(groups_90),
                '180days': len(groups_180)
            },
            '5_actualAskingListingsUtilizedInDivergenceIndex': {
                '90days': len(listings_used_90),
                '180days': len(listings_used_180)
            }
        },
        'gangnamSeochoVerification': {
            'gangnam_11680': district_details['11680'],
            'seocho_11650': district_details['11650']
        },
        'districts': district_details
    }

    out_file = ROOT / 'data' / 'price_matching_rigorous_report.json'
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Rigorous audit report saved to {out_file}")

    print("\n" + "="*80)
    print("5 RIGOROUS AUDIT METRICS (90d vs 180d):")
    print("="*80)
    print(f"1. 국토부 실거래 3건 이상 단지수: 90일={universe_comps_ge3_90:,}개 | 180일={universe_comps_ge3_180:,}개")
    print(f"2. history.sqlite3 실제 관측 호가 단지수: {len(observed_complex_ids):,}개")
    print(f"3. 정확한 스트라텀 매칭 성공 단지수: 90일={len(comps_matched_90)}개 | 180일={len(comps_matched_180)}개")
    print(f"4. 3건 이상 요건 충족 유효 비교 그룹수: 90일={len(groups_90)}개 | 180일={len(groups_180)}개")
    print(f"5. 가격괴리지수 산출에 실제 투입된 호가 매물수: 90일={len(listings_used_90):,}건 | 180일={len(listings_used_180):,}건")
    print("="*80)
    print("GANGNAM & SEOCHO STATUS:")
    print(f"  강남구(11680): 90일={district_details['11680']['match_90d']['groups']}그룹(0건) -> 180일={district_details['11680']['match_180d']['groups']}그룹({district_details['11680']['match_180d']['matchedListings']}건 매물), 괴리율={district_details['11680']['match_180d']['spread']}%")
    print(f"  서초구(11650): 90일={district_details['11650']['match_90d']['groups']}그룹(0건) -> 180일={district_details['11650']['match_180d']['groups']}그룹({district_details['11650']['match_180d']['matchedListings']}건 매물), 괴리율={district_details['11650']['match_180d']['spread']}%")
    print("="*80)
    return report

if __name__ == '__main__':
    run_rigorous_audit()
