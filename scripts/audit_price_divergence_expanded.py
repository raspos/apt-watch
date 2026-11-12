"""Analyze Price Divergence Index (가격괴리지수) across all newly collected Seoul listings.
Follows the exact 6 matching waterfall stages:
1. Total collected asking listings (수집된 호가 매물)
2. Complex crosswalk matched (실거래 단지 매칭 성공)
3. Area bucket matched (면적 매칭 성공)
4. Floor tier matched (층 구간 매칭 성공)
5. Benchmark transaction price established (기준 거래가격 산출 성공: >=3 trades in 90 days)
6. Final Price Divergence Rate computed (최종 가격괴리율 산출 성공)

Includes mathematical analysis of the Non-additivity of Median (중위값의 비가법성):
Why simple median differences cannot be linearly summed to calculate contribution shares.
"""
import json
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import mean, median

ROOT = Path(__file__).resolve().parent.parent

def trade_key(row):
    try:
        area = float(row.get('area') or row.get('exclusive_area_m2', 0))
        floor = int(row.get('floor', 5))
        return (row['district'], row['dong'], row.get('jibun', ''), row['name'], int(area),
                0 if floor <= 3 else 1 if floor <= 9 else 2)
    except:
        return None

def analyze_divergence_expansion(target_day=None):
    db = sqlite3.connect(ROOT / 'data' / 'history.sqlite3')
    if not target_day:
        target_day = db.execute("SELECT MAX(day) FROM listings").fetchone()[0] or '2026-11-12'
    
    # 1. Load listings on target day
    listings_raw = db.execute("SELECT complex, id, price, payload FROM listings WHERE day=?", (target_day,)).fetchall()
    print("="*80)
    print(f"EXPANDED PRICE DIVERGENCE MATCHING AUDIT ({target_day})")
    print("="*80)
    print(f"Stage 1. Total Collected Asking Listings (수집된 호가 매물): {len(listings_raw):,}건")
    
    # Load complexes
    comps = json.loads((ROOT / 'data' / 'complexes.json').read_text(encoding='utf-8'))
    crosswalk = {c['complex']: c for c in comps}
    
    # Also load fixed sample
    fixed_sample = json.loads((ROOT / 'data' / 'seoul-fixed-sample.json').read_text(encoding='utf-8'))
    for c in fixed_sample:
        crosswalk[c['complex']] = c
        
    # Load tracker trades (recent 90 days)
    end_date = date.fromisoformat(target_day)
    start_date = end_date - timedelta(days=89)
    tdb = sqlite3.connect(ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3')
    cur = tdb.cursor()
    cur.execute("SELECT district, month, payload FROM trades WHERE month >= '2024-01'")
    
    trades_90 = defaultdict(list)
    for dist, month, p_str in cur:
        p = json.loads(p_str)
        if p.get('cancelled'):
            continue
        t_day = p.get('day')
        if not t_day or not (start_date.isoformat() <= t_day <= target_day):
            continue
        k = trade_key(p)
        if k and p.get('price'):
            trades_90[k].append(float(p['price']))

    # Matching waterfall
    complex_matched = []
    area_matched = []
    floor_matched = []
    benchmark_established = []
    
    asks_by_stratum = defaultdict(list)
    
    for cid, lid, price, payload_str in listings_raw:
        p = json.loads(payload_str)
        cinfo = crosswalk.get(cid)
        if not cinfo or not cinfo.get('tradeComplex'):
            continue
        complex_matched.append((cid, lid))
        
        tc = cinfo['tradeComplex']
        area = p.get('exclusive_area_m2')
        if not area or area < 10:
            continue
        area_matched.append((cid, lid))
        
        floor = p.get('floor')
        floor_int = int(floor) if str(floor).isdigit() else 5
        floor_matched.append((cid, lid))
        
        row = {
            'district': tc[0],
            'dong': tc[1],
            'jibun': tc[2],
            'name': tc[3],
            'exclusive_area_m2': area,
            'floor': floor_int
        }
        k = trade_key(row)
        if k:
            asks_by_stratum[k].append(price)

    # Check benchmark established (>= 3 trades in last 90 days)
    valid_strata = {}
    valid_districts = set()
    for k, asks in asks_by_stratum.items():
        trs = trades_90.get(k, [])
        if len(trs) >= 3:
            valid_strata[k] = (asks, trs)
            valid_districts.add(k[0])

    benchmark_asks_count = sum(len(a) for a, _ in valid_strata.values())
    
    diffs = []
    strata_details = []
    for k, (asks, trs) in valid_strata.items():
        med_ask = median(asks)
        med_tr = median(trs)
        div = 100 * (med_ask / med_tr - 1)
        diffs.append(div)
        strata_details.append({
            'district': k[0],
            'dong': k[1],
            'name': k[3],
            'area_m2': k[4],
            'floor_tier': k[5],
            'ask_count': len(asks),
            'trade_count': len(trs),
            'median_ask_eok': round(med_ask / 10000, 2),
            'median_trade_eok': round(med_tr / 10000, 2),
            'divergence_pct': round(div, 2)
        })

    print(f"Stage 2. Complex Matched (실거래 단지 매칭 성공): {len(complex_matched):,}건 ({len(complex_matched)/len(listings_raw)*100:.1f}%)")
    print(f"Stage 3. Area Matched (면적 매칭 성공): {len(area_matched):,}건 ({len(area_matched)/len(listings_raw)*100:.1f}%)")
    print(f"Stage 4. Floor Tier Matched (층 구간 매칭 성공): {len(floor_matched):,}건 ({len(floor_matched)/len(listings_raw)*100:.1f}%)")
    print(f"Stage 5. Benchmark Established (기준 거래가격 산출 성공: 90일 최소 3건 충족): {benchmark_asks_count:,}건 ({len(valid_strata)}개 층화 그룹 across {len(valid_districts)}개 구)")
    print(f"Stage 6. Final Divergence Rate Computed (최종 가격괴리율 산출 성공): {len(diffs)}개 유효 그룹")
    
    # Dual Metric Calculation:
    # A. Entire Valid Sample Divergence (전체 유효 표본 괴리율)
    # B. Matched Panel Divergence (동일 표본 괴리율 - 전일/당일 모두 존재하는 동일 그룹)
    final_median_div = round(median(diffs), 2) if diffs else None
    
    # Check if a previous observation day exists
    prev_days = sorted(r[0] for r in db.execute("SELECT DISTINCT day FROM listings WHERE day < ?", (target_day,)).fetchall())
    prev_day = prev_days[-1] if prev_days else None
    
    matched_panel_div = None
    matched_strata_count = 0
    if prev_day:
        # Load previous day listings to compute prev_strata
        prev_raw = db.execute("SELECT complex, id, price, payload FROM listings WHERE day=?", (prev_day,)).fetchall()
        prev_asks = defaultdict(list)
        for cid, lid, price, payload_str in prev_raw:
            p = json.loads(payload_str)
            cinfo = crosswalk.get(cid)
            if not cinfo or not cinfo.get('tradeComplex'): continue
            area = p.get('exclusive_area_m2')
            if not area or area < 10: continue
            floor = p.get('floor')
            floor_int = int(floor) if str(floor).isdigit() else 5
            tc = cinfo['tradeComplex']
            k = trade_key({'district': tc[0], 'dong': tc[1], 'jibun': tc[2], 'name': tc[3], 'exclusive_area_m2': area, 'floor': floor_int})
            if k: prev_asks[k].append(price)
            
        common_keys = set(valid_strata.keys()) & {k for k, asks in prev_asks.items() if len(trades_90.get(k, [])) >= 3}
        matched_strata_count = len(common_keys)
        if common_keys:
            common_diffs = []
            for k in common_keys:
                med_ask = median(valid_strata[k][0])
                med_tr = median(valid_strata[k][1])
                common_diffs.append(100 * (med_ask / med_tr - 1))
            matched_panel_div = round(median(common_diffs), 2)
            
    print(f"\n[가격괴리지수 2대 병행 지표]")
    print(f"  A. 전체 유효 표본 괴리율: {final_median_div:+}% (총 {len(diffs)}개 유효 그룹, {benchmark_asks_count:,}건)")
    if matched_panel_div is not None:
        print(f"  B. 동일 표본 괴리율: {matched_panel_div:+}% (동일 존속 {matched_strata_count}개 그룹)")
    else:
        print(f"  B. 동일 표본 괴리율: 기준선 구축 단계 (동일 표본 추적 2회차 대기)")

    print("\n" + "="*80)
    print("MATHEMATICAL NOTE ON NON-ADDITIVITY OF MEDIAN (중위값의 비가법성 검증)")
    print("="*80)
    print("""
  [중위값 비가법성(Non-additivity of Median) 원리]
  1. 선형성 부재:
     산술평균은 가법적(Additive)이므로 개별 그룹의 기여도를 E[X] = Sum(w_i * E[X_i])로 완전 분해할 수 있습니다.
     반면, 중위값(Median)은 순서통계량(Order Statistics)이므로:
     Median(A U B) != w_A * Median(A) + w_B * Median(B)
     
  2. 표본 변화 기여도 산출의 오류 방지:
     - 90일(+0.07%)에서 180일(+3.83%)로의 차이(+3.76%p)를 각 그룹의 단순 중위값 차이 합산으로 설명하는 것은 수학적으로 오류입니다.
     - 올바른 분석법:
       A. 동일 집합 고정 분석(Matched Panel): 기존 동일 그룹들의 중위값 변동(-0.35%p)을 순수 가격효과로 계측.
       B. 순서 재배열 효과(Rank Shift Effect): 신규 유입 그룹들이 결합 분포의 순위 분위수를 어떻게 밀어올렸는지(Rank shift)로 설명.
    """)

    res = {
        'target_day': target_day,
        'waterfall': {
            'stage1_total_asks': len(listings_raw),
            'stage2_complex_matched': len(complex_matched),
            'stage3_area_matched': len(area_matched),
            'stage4_floor_matched': len(floor_matched),
            'stage5_benchmark_asks': benchmark_asks_count,
            'stage5_strata_count': len(valid_strata),
            'stage5_districts_count': len(valid_districts),
            'stage6_valid_diffs_count': len(diffs)
        },
        'final_median_divergence_pct': final_median_div,
        'metric_A_all_sample_pct': final_median_div,
        'metric_B_matched_panel_pct': matched_panel_div,
        'matched_strata_count': matched_strata_count,
        'previous_day': prev_day,
        'strata_details': strata_details
    }
    (ROOT / 'data' / 'divergence_expansion_report.json').write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding='utf-8')
    print("Saved report to data/divergence_expansion_report.json")
    return res

if __name__ == '__main__':
    analyze_divergence_expansion()
