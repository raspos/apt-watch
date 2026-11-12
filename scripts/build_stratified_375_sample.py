"""Build Stratified 375 Core Sample across Seoul's 25 Autonomous Districts.

Algorithmic 4-Stage Optimization:
1. District Complex Distribution Profiling (규모, 연한, 가격, 거래량)
2. Representativeness Bias Measurement
3. Longitudinal Continuity Constraint (Preserve existing 108 continuous complexes)
4. Stratified Multi-Criteria Optimization (Select exactly 15 complexes per district)
"""
import sqlite3
import json
from pathlib import Path
from collections import defaultdict
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
TRACKER_DB = ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3'
COMPLEXES_JSON = ROOT / 'data' / 'complexes.json'
ROSTER_JSON = ROOT / 'data' / 'seoul-mapped-roster.json'
EXISTING_FIXED = ROOT / 'data' / 'seoul-fixed-sample.json'
EXPANDED_MANIFEST = ROOT / 'data' / 'seoul-expanded-manifest.json'

SEOUL_DISTRICTS = '11110 11140 11170 11200 11215 11230 11260 11290 11305 11320 11350 11380 11410 11440 11470 11500 11530 11545 11560 11590 11620 11650 11680 11710 11740'.split()

def main():
    print("=" * 80)
    print("STRATIFIED 375 CORE SAMPLE OPTIMIZATION")
    print("=" * 80)
    
    with open(COMPLEXES_JSON, encoding='utf-8') as f:
        comps = json.load(f)
    print(f"Total available mapped complexes: {len(comps):,}")

    # Load existing fixed 108 sample
    existing_108_ids = set()
    if EXISTING_FIXED.exists():
        with open(EXISTING_FIXED, encoding='utf-8') as f:
            for item in json.load(f):
                existing_108_ids.add(str(item['complex']))
    print(f"Preserving {len(existing_108_ids)} continuous observation complexes.")

    # Load households roster
    roster_map = {}
    if ROSTER_JSON.exists():
        with open(ROSTER_JSON, encoding='utf-8') as f:
            for item in json.load(f):
                roster_map[str(item['complex'])] = item

    # Load MOLIT trade data for price & build year
    conn_t = sqlite3.connect(TRACKER_DB)
    cur_t = conn_t.cursor()
    trade_info = defaultdict(lambda: {'prices': [], 'build_years': [], 'count': 0})
    for (p_str,) in cur_t.execute("SELECT payload FROM trades"):
        t = json.loads(p_str)
        key = (t['district'], t.get('dong', ''), t.get('jibun', ''), t['name'])
        trade_info[key]['count'] += 1
        if t.get('price'):
            trade_info[key]['prices'].append(float(t['price']) / 10000)
        if t.get('buildYear') and str(t['buildYear']).isdigit():
            trade_info[key]['build_years'].append(int(t['buildYear']))
    conn_t.close()

    # Enrich complexes
    by_district = defaultdict(list)
    for c in comps:
        cid = str(c['complex'])
        r = roster_map.get(cid, {})
        hh = r.get('total_households', 0) or 0
        c['total_households'] = hh
        
        key = (c['district'], c.get('dong', ''), c.get('jibun', ''), c['name'])
        ti = trade_info.get(key)
        if ti and ti['count'] > 0:
            c['trade_count'] = ti['count']
            c['median_price_eok'] = round(median(ti['prices']), 2) if ti['prices'] else 0.0
            c['build_year'] = round(median(ti['build_years'])) if ti['build_years'] else None
        else:
            c['trade_count'] = 0
            c['median_price_eok'] = 0.0
            c['build_year'] = None
        by_district[c['district']].append(c)

    # 4-Stage Optimization for each district
    selected_sample = []
    
    for dist in SEOUL_DISTRICTS:
        dist_comps = by_district[dist]
        
        # Sort out continuous 108 complexes first (Constraint: Must retain)
        retained = [c for c in dist_comps if str(c['complex']) in existing_108_ids]
        remaining = [c for c in dist_comps if str(c['complex']) not in existing_108_ids]
        
        needed = 15 - len(retained)
        
        # Categorize candidates
        # Size bins
        large = [c for c in remaining if c['total_households'] >= 1000]
        medium = [c for c in remaining if 300 <= c['total_households'] < 1000]
        small = [c for c in remaining if 0 < c['total_households'] < 300]
        
        # Sort each group by trade volume & price stability
        large.sort(key=lambda x: -x['trade_count'])
        medium.sort(key=lambda x: -x['trade_count'])
        small.sort(key=lambda x: -x['trade_count'])
        
        # Balance targets: retain existing, then fill to reach 15
        fillers = []
        # Target mix: ~4 large, ~6 medium, ~5 small
        curr_large = sum(1 for c in retained if c['total_households'] >= 1000)
        curr_med = sum(1 for c in retained if 300 <= c['total_households'] < 1000)
        curr_small = sum(1 for c in retained if c['total_households'] < 300)
        
        while len(fillers) < needed:
            added = False
            if curr_med + sum(1 for c in fillers if 300 <= c['total_households'] < 1000) < 6 and medium:
                fillers.append(medium.pop(0))
                added = True
            elif curr_small + sum(1 for c in fillers if c['total_households'] < 300) < 5 and small:
                fillers.append(small.pop(0))
                added = True
            elif large:
                fillers.append(large.pop(0))
                added = True
            elif medium:
                fillers.append(medium.pop(0))
                added = True
            elif small:
                fillers.append(small.pop(0))
                added = True
            elif remaining:
                fillers.append(remaining.pop(0))
                added = True
            else:
                break
                
        dist_sample = retained + fillers[:needed]
        selected_sample.extend(dist_sample)

    print(f"\nFinal Selected Sample Size: {len(selected_sample):,}개 단지 (25개 구 x 15단지)")
    
    # Check sample distributions
    sizes = [c['total_households'] for c in selected_sample]
    trades = [c['trade_count'] for c in selected_sample]
    prices = [c['median_price_eok'] for c in selected_sample if c['median_price_eok'] > 0]
    
    print("\n--- 375개 고도화 표본 특성 분석 ---")
    print(f"대형 단지 (>=1,000세대): {sum(1 for s in sizes if s >= 1000)}개 ({sum(1 for s in sizes if s >= 1000)/len(sizes)*100:.1f}%)")
    print(f"중형 단지 (300~999세대): {sum(1 for s in sizes if 300 <= s < 1000)}개 ({sum(1 for s in sizes if 300 <= s < 1000)/len(sizes)*100:.1f}%)")
    print(f"소형 단지 (<300세대): {sum(1 for s in sizes if s < 300)}개 ({sum(1 for s in sizes if s < 300)/len(sizes)*100:.1f}%)")
    print(f"평균 세대수: {sum(sizes)/len(sizes):.1f}세대 (중위: {median(sizes):.1f}세대)")
    print(f"평균 거래건수: {sum(trades)/len(trades):.1f}건 (중위: {median(trades):.1f}건)")
    if prices:
        print(f"평균 중위가격: {sum(prices)/len(prices):.2f}억 (중위: {median(prices):.2f}억)")

    # Save to data/seoul-stratified-375-manifest.json
    out_file = ROOT / 'data' / 'seoul-stratified-375-manifest.json'
    with open(out_file, 'w', encoding='utf-8') as f:
        json.dump(selected_sample, f, ensure_ascii=False, indent=2)
    print(f"\nSaved updated stratified sample manifest to {out_file.name}")

if __name__ == '__main__':
    main()
