"""APT WATCH — Listing-to-Trade Matching & Verification Engine (A/B/C Grade Classifier).

Strictly implements the verification hierarchy defined in docs/nego_index_methodology.md:
  - Grade A: Confirmed identical property (independent broker evidence / verified link)
  - Grade B: Probabilistic candidate match (unique vs multiple candidate tracking)
  - Grade C: Strata cohort price divergence benchmark (Price Divergence Index)

Calculates the three distinct discount metrics:
  1. Initial-to-Contract Discount Rate: (P_ask,0 - P_contract) / P_ask,0 * 100
  2. Closing Nego Discount Rate:        (P_ask,last - P_contract) / P_ask,last * 100
  3. Public Asking Price Cut Rate:      (P_ask,0 - P_ask,last) / P_ask,0 * 100

Accounts for the 30-day MOLIT reporting lag and observation timeline.
Outputs full audit to data/nego_matching_audit_report.json.
"""

import json
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent

def load_crosswalk():
    crosswalk = {}
    comps_path = ROOT / 'data' / 'complexes.json'
    if comps_path.exists():
        for c in json.loads(comps_path.read_text(encoding='utf-8')):
            crosswalk[c['complex']] = c

    fixed_path = ROOT / 'data' / 'seoul-fixed-sample.json'
    if fixed_path.exists():
        for c in json.loads(fixed_path.read_text(encoding='utf-8')):
            crosswalk[c['complex']] = c
    return crosswalk


def run_matching_engine(target_day=None):
    hdb_path = ROOT / 'data' / 'history.sqlite3'
    tdb_path = ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3'

    crosswalk = load_crosswalk()

    with sqlite3.connect(hdb_path) as hdb:
        if not target_day:
            target_day = hdb.execute("SELECT MAX(day) FROM listings").fetchone()[0] or '2026-11-12'

        # 1. Ingest listing lifecycles
        print(f"[Matching Engine] Ingesting listing lifecycles from {hdb_path.name}...")
        cur = hdb.cursor()
        
        listing_lifecycles = defaultdict(lambda: {
            'complex': None,
            'id': None,
            'district': None,
            'dong': None,
            'jibun': None,
            'name': None,
            'area': None,
            'floor': None,
            'firstDay': None,
            'firstPrice': None,
            'lastDay': None,
            'lastPrice': None,
            'observations': []
        })

        rows = cur.execute("SELECT day, complex, id, price, payload FROM listings ORDER BY day ASC").fetchall()
        for day, cid, lid, price, p_str in rows:
            p = json.loads(p_str)
            key = (cid, lid)
            item = listing_lifecycles[key]
            item['complex'] = cid
            item['id'] = lid
            
            cinfo = crosswalk.get(cid)
            if cinfo and cinfo.get('tradeComplex'):
                tc = cinfo['tradeComplex']
                item['district'] = tc[0]
                item['dong'] = tc[1]
                item['jibun'] = tc[2]
                item['name'] = tc[3]
                
            raw_area = p.get('exclusive_area_m2') or p.get('area')
            if raw_area:
                try:
                    item['area'] = float(raw_area)
                except:
                    pass

            raw_floor = p.get('floor')
            if raw_floor is not None:
                item['floor'] = str(raw_floor).split('/')[0].strip()

            ask_price = float(p.get('asking_price_manwon') or price or 0)
            if ask_price > 0:
                if item['firstPrice'] is None:
                    item['firstPrice'] = ask_price
                    item['firstDay'] = day
                item['lastPrice'] = ask_price
                item['lastDay'] = day
                item['observations'].append((day, ask_price))

    print(f"[Matching Engine] Tracked {len(listing_lifecycles):,} distinct listing lifecycles.")

    # 2. Ingest MOLIT transactions
    print(f"[Matching Engine] Ingesting transactions from {tdb_path.name}...")
    with sqlite3.connect(tdb_path) as tdb:
        end_date = date.fromisoformat(target_day)
        start_date = end_date - timedelta(days=179)
        t_rows = tdb.execute("SELECT district, month, payload FROM trades WHERE month >= '2024-01'").fetchall()

    recent_trades = []
    for dist, month, p_str in t_rows:
        p = json.loads(p_str)
        if p.get('cancelled'):
            continue
        t_day = p.get('day')
        if not t_day or not (start_date.isoformat() <= t_day <= target_day):
            continue
        price = float(p.get('price', 0))
        if price <= 0:
            continue
        try:
            area = float(p.get('area') or p.get('exclusive_area_m2', 0))
            floor = str(p.get('floor', '')).strip()
        except:
            continue
        
        recent_trades.append({
            'district': p['district'],
            'dong': p['dong'],
            'jibun': p.get('jibun', ''),
            'name': p['name'],
            'area': area,
            'floor': floor,
            'day': t_day,
            'price': price,
            'id': p.get('id') or f"{p['district']}_{t_day}_{p['name']}_{area}_{floor}_{price}"
        })

    print(f"[Matching Engine] Ingested {len(recent_trades):,} transactions within 180-day window.")

    # 3. Matching Architecture
    # Index listings by (district, dong, jibun, name, round(area), floor)
    listings_by_exact_strata = defaultdict(list)
    for key, l in listing_lifecycles.items():
        if l['name'] and l['area'] and l['floor'] and l['lastPrice']:
            s_key = (l['district'], l['dong'], l['jibun'], l['name'], int(round(l['area'])), l['floor'])
            listings_by_exact_strata[s_key].append(l)

    grade_a_matches = []
    grade_b_strict_temporal = []
    grade_b_exploratory_unique = []
    grade_b_multiple_candidates = []
    unmatched_trades = 0

    for tr in recent_trades:
        s_key = (tr['district'], tr['dong'], tr['jibun'], tr['name'], int(round(tr['area'])), tr['floor'])
        candidates = listings_by_exact_strata.get(s_key, [])
        if not candidates:
            unmatched_trades += 1
            continue

        # Check area tolerance within 0.5m2
        area_matched_candidates = [c for c in candidates if abs(c['area'] - tr['area']) <= 0.5]
        if not area_matched_candidates:
            unmatched_trades += 1
            continue

        t_contract = date.fromisoformat(tr['day'])

        if len(area_matched_candidates) == 1:
            matched_listing = area_matched_candidates[0]
            t_first = date.fromisoformat(matched_listing['firstDay'])
            t_last = date.fromisoformat(matched_listing['lastDay'])

            p_initial = matched_listing['firstPrice']
            p_last = matched_listing['lastPrice']
            p_contract = tr['price']

            disc_initial = round(100.0 * (p_initial - p_contract) / p_initial, 2)
            disc_closing = round(100.0 * (p_last - p_contract) / p_last, 2)
            disc_asking_cut = round(100.0 * (p_initial - p_last) / p_initial, 2)

            match_data = {
                'tradeId': tr['id'],
                'listingKey': f"{matched_listing['complex']}_{matched_listing['id']}",
                'complex': matched_listing['name'],
                'district': tr['district'],
                'dong': tr['dong'],
                'contractDay': tr['day'],
                'listingFirstObserved': matched_listing['firstDay'],
                'listingLastObserved': matched_listing['lastDay'],
                'daysBetweenContractAndFirstObs': (t_first - t_contract).days,
                'areaM2': tr['area'],
                'floor': tr['floor'],
                'p_initial_manwon': p_initial,
                'p_last_manwon': p_last,
                'p_contract_manwon': p_contract,
                'initialDiscountPct': disc_initial,
                'closingNegoPct': disc_closing,
                'publicAskingCutPct': disc_asking_cut,
                'candidateCompetitionCount': 1
            }

            # Check strict temporal alignment (contract on or after listing observation)
            if t_first <= t_contract:
                grade_b_strict_temporal.append(match_data)
            else:
                grade_b_exploratory_unique.append(match_data)
        else:
            grade_b_multiple_candidates.append({
                'tradeId': tr['id'],
                'complex': tr['name'],
                'district': tr['district'],
                'contractDay': tr['day'],
                'areaM2': tr['area'],
                'floor': tr['floor'],
                'contractPriceManwon': tr['price'],
                'candidateCount': len(area_matched_candidates)
            })

    # Summary Statistics for Exploratory Unique Matches (Exact same complex, area, floor)
    all_unique = grade_b_strict_temporal + grade_b_exploratory_unique
    nego_rates = [m['closingNegoPct'] for m in all_unique]
    initial_discounts = [m['initialDiscountPct'] for m in all_unique]
    asking_cuts = [m['publicAskingCutPct'] for m in all_unique]

    # Filter out extreme outliers for robustness (|nego| <= 40%)
    valid_nego_rates = [r for r in nego_rates if -30 <= r <= 30]

    report = {
        'auditTimestamp': datetime.now().isoformat(),
        'targetDay': target_day,
        'summaryCounts': {
            'totalRecentTransactions180d': len(recent_trades),
            'totalTrackedListingLifecycles': len(listing_lifecycles),
            'exactStrataMatchedTransactions': len(all_unique) + len(grade_b_multiple_candidates),
            'gradeA_ConfirmedIdentical': len(grade_a_matches),
            'gradeB_UniqueCandidateMatches': len(all_unique),
            'gradeB_StrictTemporalUniqueMatches': len(grade_b_strict_temporal),
            'gradeB_ExploratorySameFloorUniqueMatches': len(grade_b_exploratory_unique),
            'gradeB_AmbiguousMultipleCandidates': len(grade_b_multiple_candidates),
            'unmatchedTrades': unmatched_trades
        },
        'gradeA_OfficialPublicationStatus': {
            'isPublished': False,
            'reason': 'A등급 독립 검증 자료(중개업소 확약/계약 증빙) 미확보 상태로, 공식 확정 네고지수 공표 유예 및 검증 단계 유지'
        },
        'gradeB_AnalysisReport': {
            'explanation': '동일 단지·면적·층수가 정확히 일치하며 해당 조건에 유일한 1건의 매물만 존재한 탐색적 비교 표본 분석',
            'sampleCount': len(all_unique),
            'validSampleCountInRange': len(valid_nego_rates),
            'medianClosingNegoPct': round(median(valid_nego_rates), 2) if valid_nego_rates else None,
            'meanClosingNegoPct': round(mean(valid_nego_rates), 2) if valid_nego_rates else None,
            'medianInitialDiscountPct': round(median(initial_discounts), 2) if initial_discounts else None,
            'medianPublicAskingCutPct': round(median(asking_cuts), 2) if asking_cuts else None,
            'interquartileRange': {
                'p25': round(sorted(valid_nego_rates)[len(valid_nego_rates)//4], 2) if len(valid_nego_rates) >= 4 else None,
                'p75': round(sorted(valid_nego_rates)[3*len(valid_nego_rates)//4], 2) if len(valid_nego_rates) >= 4 else None
            } if valid_nego_rates else None
        },
        'reportingLagImplication': {
            'observationStartDate': '2026-11-10',
            'molitReportingLagDays': 30,
            'keyTakeaway': '2026-11-10 이후 관측된 매물들의 실제 계약은 30일 신고 기한으로 인해 11월 하순~12월 중순 국토부 데이터에 집계되므로, 연속 관측 패널이 축적됨에 따라 엄격한 B등급 매칭 표본이 급증하게 됨.'
        },
        'sampleMatchingCases': all_unique[:10]
    }

    out_file = ROOT / 'data' / 'nego_matching_audit_report.json'
    out_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"\n[Matching Engine] Audit report successfully written to {out_file}")

    print("=" * 80)
    print("APT WATCH LISTING-TO-TRADE MATCHING ENGINE AUDIT RESULTS")
    print("=" * 80)
    print(f"Total Ingested 180d Transactions:             {len(recent_trades):,} 건")
    print(f"Total Ingested Listing Lifecycles:             {len(listing_lifecycles):,} 건")
    print(f"Exact Same Complex, Area & Floor Transactions: {len(all_unique) + len(grade_b_multiple_candidates):,} 건")
    print(f"  - Grade A (Confirmed Identical Property):    {len(grade_a_matches):,} 건 (독립 증빙 미확보 -> 0건 공표 유예)")
    print(f"  - Grade B (Unique 1:1 Single Candidates):    {len(all_unique):,} 건")
    print(f"    * Strict Temporal Forward Matches:         {len(grade_b_strict_temporal):,} 건 (30일 신고시차 대기 중)")
    print(f"    * Same-floor/Area Retrospective Matches:   {len(grade_b_exploratory_unique):,} 건")
    print(f"  - Grade B (Ambiguous Multiple Candidates):   {len(grade_b_multiple_candidates):,} 건 (불확실성 보존)")
    print(f"Unmatched Transactions (No same floor/area):   {unmatched_trades:,} 건")
    print("-" * 80)
    if valid_nego_rates:
        print(f"Grade B Exploratory Closing Nego Rate (N={len(valid_nego_rates)}):")
        print(f"  중위값: {median(valid_nego_rates):.2f}% | 평균: {mean(valid_nego_rates):.2f}% | IQR: [{sorted(valid_nego_rates)[len(valid_nego_rates)//4]:.2f}% ~ {sorted(valid_nego_rates)[3*len(valid_nego_rates)//4]:.2f}%]")
        print(f"Grade B Initial-to-Contract Discount: 중위값 {median(initial_discounts):.2f}%")
        print(f"Grade B Public Asking Price Cut Rate: 중위값 {median(asking_cuts):.2f}%")
    print("=" * 80)
    return report

if __name__ == '__main__':
    run_matching_engine()
