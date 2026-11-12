"""Audit the Representativeness of the 100 Seoul Fixed Sample Complexes
against the Full Seoul Apartment Population (8,788 complexes / 450,479 trades / total stock).

Compares:
1. District Household Share (자치구별 세대수 비중)
2. Price Tier Distribution (가격대별 비중)
3. Completion Year Distribution (준공연도별 비중)
4. Exclusive Area Distribution (전용면적별 비중)
5. Complex Size Distribution (단지 규모별 비중)
Proposes mathematical weighting calibration formulas (Equal vs Stock vs Stratified).
"""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent

SEOUL = '종로 중 용산 성동 광진 동대문 중랑 성북 강북 도봉 노원 은평 서대문 마포 양천 강서 구로 금천 영등포 동작 관악 서초 강남 송파 강동'.split()
DISTRICTS = dict(zip('11110 11140 11170 11200 11215 11230 11260 11290 11305 11320 11350 11380 11410 11440 11470 11500 11530 11545 11560 11590 11620 11650 11680 11710 11740'.split(), [n+'구' for n in SEOUL]))

def run_audit():
    # 1. Load Fixed 100 Sample
    fixed_sample = json.loads((ROOT / 'data' / 'seoul-fixed-sample.json').read_text(encoding='utf-8'))
    
    # 2. Load Population Trade Roster & Mapped Roster
    pop_roster = json.loads((ROOT / 'data' / 'seoul-mapped-roster.json').read_text(encoding='utf-8'))
    
    # 3. Load Tracker Trades for real area and price distributions
    tdb = sqlite3.connect(ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3')
    cur = tdb.cursor()
    cur.execute("SELECT district, month, payload FROM trades WHERE month >= '2023-01'")
    
    pop_prices = []
    pop_areas = []
    pop_years = []
    pop_district_counts = defaultdict(int)
    
    for dist, month, p_str in cur:
        p = json.loads(p_str)
        if p.get('cancelled'):
            continue
        pop_district_counts[dist] += 1
        if p.get('price'):
            pop_prices.append(float(p['price']) / 10000) # in 억
        if p.get('area'):
            try:
                pop_areas.append(float(p['area']))
            except:
                pass
        if p.get('buildYear') and str(p['buildYear']).isdigit():
            pop_years.append(int(p['buildYear']))
            
    # Population stock by district from mapped roster
    pop_stock_by_dist = defaultdict(int)
    for c in pop_roster:
        pop_stock_by_dist[c['district']] += c.get('total_households', 0)
    total_pop_stock = sum(pop_stock_by_dist.values()) or 1

    # Sample stock by district
    sample_stock_by_dist = defaultdict(int)
    for c in fixed_sample:
        sample_stock_by_dist[c['district']] += c.get('total_households', 0)
    total_sample_stock = sum(sample_stock_by_dist.values()) or 1
    
    sample_prices = [c['median_price_eok'] for c in fixed_sample]
    sample_areas = [c['median_area_m2'] for c in fixed_sample]
    sample_years = [c['build_year'] for c in fixed_sample]
    sample_households = [c['total_households'] for c in fixed_sample]

    print("="*80)
    print("SEOUL 100 FIXED SAMPLE REPRESENTATIVENESS AUDIT")
    print("="*80)
    
    # 1. District household share comparison
    print("\n[1. 자치구별 세대수 비중 비교 (Top/Bottom 편향 분석)]")
    dist_biases = []
    for code, name in DISTRICTS.items():
        pop_pct = pop_stock_by_dist[code] / total_pop_stock * 100
        sample_pct = sample_stock_by_dist[code] / total_sample_stock * 100
        bias = sample_pct - pop_pct
        dist_biases.append((name, code, pop_pct, sample_pct, bias))
    
    dist_biases.sort(key=lambda x: -abs(x[4]))
    print(f"{'자치구':<8} | {'모집단 비중(%)':<12} | {'표본 비중(%)':<12} | {'편향(%p)':<10}")
    print("-" * 50)
    for name, code, p_p, s_p, b in dist_biases[:8]:
        print(f"{name:<8} | {p_p:>10.2f}% | {s_p:>10.2f}% | {b:>+8.2f}%p")
    print("...")

    # 2. Price Distribution comparison
    print("\n[2. 가격대별 분포 비교 (실거래 기준 억 원)]")
    def quartiles(arr):
        s = sorted(arr)
        n = len(s)
        return {
            'min': round(s[0], 2),
            'p25': round(s[n//4], 2),
            'median': round(s[n//2], 2),
            'mean': round(mean(s), 2),
            'p75': round(s[3*n//4], 2),
            'max': round(s[-1], 2)
        }
    pop_p_stats = quartiles(pop_prices)
    s_p_stats = quartiles(sample_prices)
    print(f"  서울 전체 거래: P25 {pop_p_stats['p25']}억 | Median {pop_p_stats['median']}억 | Mean {pop_p_stats['mean']}억 | P75 {pop_p_stats['p75']}억")
    print(f"  고정 표본(100): P25 {s_p_stats['p25']}억 | Median {s_p_stats['median']}억 | Mean {s_p_stats['mean']}억 | P75 {s_p_stats['p75']}억")

    # 3. Build Year comparison
    print("\n[3. 준공연도 분포 비교]")
    pop_y_stats = quartiles(pop_years)
    s_y_stats = quartiles(sample_years)
    print(f"  서울 전체 거래: P25 {int(pop_y_stats['p25'])}년 | Median {int(pop_y_stats['median'])}년 | P75 {int(pop_y_stats['p75'])}년")
    print(f"  고정 표본(100): P25 {int(s_y_stats['p25'])}년 | Median {int(s_y_stats['median'])}년 | P75 {int(s_y_stats['p75'])}년")

    # 4. Exclusive Area comparison
    print("\n[4. 전용면적 분포 비교 (㎡)]")
    pop_a_stats = quartiles(pop_areas)
    s_a_stats = quartiles(sample_areas)
    print(f"  서울 전체 거래: P25 {pop_a_stats['p25']}㎡ | Median {pop_a_stats['median']}㎡ | P75 {pop_a_stats['p75']}㎡")
    print(f"  고정 표본(100): P25 {s_a_stats['p25']}㎡ | Median {s_a_stats['median']}㎡ | P75 {s_a_stats['p75']}㎡")

    # 5. Complex Size Distribution
    print("\n[5. 단지 규모별 분포 (세대수)]")
    mega_pop = sum(1 for c in pop_roster if c.get('total_households', 0) >= 1000) / len(pop_roster) * 100
    mega_sample = sum(1 for c in fixed_sample if c.get('total_households', 0) >= 1000) / len(fixed_sample) * 100
    print(f"  1,000세대 이상 대단지 비중: 모집단 {mega_pop:.1f}% vs 표본 {mega_sample:.1f}%")

    print("\n" + "="*80)
    print("WEIGHTING CALIBRATION PROPOSAL (가중치 보정안)")
    print("="*80)
    print("""
  1. 단순평균 (Equal Weight):
     W_i = 1 / N (자치구별 4개 단지 기여도 동일)
     - 문제점: 강동구(올림픽파크포레온 1.2만세대)와 종로구(수백세대)가 동일 비중으로 처리되어 소형 자치구 과대대표 편향 발생.
     
  2. 단지 세대수 가중치 (Stock Weight):
     W_i = TotalHouseholds_i / Sum(TotalHouseholds)
     - 대단지의 실제 시장 영향력을 정확히 반영하나, 초대형 단지 1곳(헬리오시티, 올림픽파크포레온 등)에 의해 지수가 급변할 수 있음.

  3. (권고) 2단계 자치구 재고 비례 층화가중치 (Stratified District Stock Weight):
     W_i = (DistrictStock_d / TotalSeoulStock) * (Households_i / DistrictSampleStock_d)
     - 1단계: 서울 25개 자치구의 실제 아파트 재고 비중을 그대로 유지.
     - 2단계: 자치구 내부에서는 4개 아키타입 단지의 규모에 비례해 배분.
     - 효과: 자치구별 동수 배정(4개)으로 인한 지역 편향을 완벽히 소거하면서도 시계열의 연속성 완벽 보존!
    """)
    
    report = {
        'total_sample_complexes': len(fixed_sample),
        'total_pop_complexes': len(pop_roster),
        'sample_stock_households': total_sample_stock,
        'pop_stock_households': total_pop_stock,
        'price_stats': {'pop': pop_p_stats, 'sample': s_p_stats},
        'year_stats': {'pop': pop_y_stats, 'sample': s_y_stats},
        'area_stats': {'pop': pop_a_stats, 'sample': s_a_stats},
        'district_biases': [{'name': r[0], 'code': r[1], 'pop_share': round(r[2], 2), 'sample_share': round(r[3], 2), 'bias_p': round(r[4], 2)} for r in dist_biases],
        'calibration_recommendation': '2-stage Stratified District Stock Weighting'
    }
    (ROOT / 'data' / 'representativeness_audit_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print("Saved representativeness report to data/representativeness_audit_report.json")

if __name__ == '__main__':
    run_audit()
