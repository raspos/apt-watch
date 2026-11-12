"""Build the 100 Fixed Daily Sample Complexes across Seoul 25 Districts (4 per district).
Balanced across:
1. High-tier / Landmark (고가/대장)
2. Large-scale / Mid-high (대단지/중상위: >1,000 households)
3. Established / Older (>20 yrs) / Reconstruction (구축/재건축: buildYear <= 2005)
4. Affordable / Entry-level (중저가/실수요: low-mid price practical)
"""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SEOUL = '종로 중 용산 성동 광진 동대문 중랑 성북 강북 도봉 노원 은평 서대문 마포 양천 강서 구로 금천 영등포 동작 관악 서초 강남 송파 강동'.split()
DISTRICTS = dict(zip('11110 11140 11170 11200 11215 11230 11260 11290 11305 11320 11350 11380 11410 11440 11470 11500 11530 11545 11560 11590 11620 11650 11680 11710 11740'.split(), [n+'구' for n in SEOUL]))

def load_all_candidates():
    comps = json.loads((ROOT / 'data' / 'complexes.json').read_text(encoding='utf-8'))
    mapo_c = json.loads((ROOT / 'scratch' / 'mapo_candidates.json').read_text(encoding='utf-8'))
    sb_c = json.loads((ROOT / 'scratch' / 'seongbuk_candidates.json').read_text(encoding='utf-8'))
    trade_stats = json.loads((ROOT / 'scratch' / 'trade_stats_recent.json').read_text(encoding='utf-8'))
    roster = json.loads((ROOT / 'data' / 'seoul-mapped-roster.json').read_text(encoding='utf-8'))
    roster_hh = {str(c['complex']): c.get('total_households', 0) for c in roster}

    all_c = list(comps)
    for c in mapo_c:
        all_c.append({
            'complex': str(c['complexNo']),
            'district': '11440',
            'dong': c['dongName'],
            'jibun': c.get('jibunAddress', ''),
            'name': c['complexName'],
            'naver_name': c['complexName'],
            'total_households': c.get('totalHouseholdCount', 0),
            'deal_count': c.get('dealCount', 0),
            'tradeComplex': ['11440', c['dongName'], c.get('jibunAddress', ''), c['complexName']],
            'tradeCrosswalkVerified': True
        })
    for c in sb_c:
        all_c.append({
            'complex': str(c['complexNo']),
            'district': '11290',
            'dong': c['dongName'],
            'jibun': c.get('jibunAddress', ''),
            'name': c['complexName'],
            'naver_name': c['complexName'],
            'total_households': c.get('totalHouseholdCount', 0),
            'deal_count': c.get('dealCount', 0),
            'tradeComplex': ['11290', c['dongName'], c.get('jibunAddress', ''), c['complexName']],
            'tradeCrosswalkVerified': True
        })

    # Fill households from roster if missing
    for c in all_c:
        cid = str(c.get('complex', ''))
        if not c.get('total_households') or c['total_households'] == 0:
            c['total_households'] = roster_hh.get(cid, 0)

    # Match trade statistics
    by_dist = defaultdict(list)
    for c in all_c:
        dist = c['district']
        name = c['name']
        dong = c['dong']
        matched_stat = None
        for k, s in trade_stats.items():
            parts = k.split('::')
            if parts[0] == dist and (parts[3] == name or name in parts[3] or parts[3] in name):
                if parts[1] == dong or not matched_stat:
                    matched_stat = s
                    if not c.get('jibun') or len(c.get('jibun','')) == 0:
                        c['jibun'] = parts[2]
                    c['tradeComplex'] = [dist, parts[1], parts[2], parts[3]]
                    c['tradeCrosswalkVerified'] = True
        if matched_stat:
            c['trade_stat'] = matched_stat
            c['median_price'] = matched_stat['median_price']
            c['trade_count'] = matched_stat['count']
            build_years = [int(y) for y in matched_stat['build_years'] if str(y).isdigit()]
            c['build_year'] = min(build_years) if build_years else 2000
            c['median_area'] = matched_stat.get('median_area', 84)
            by_dist[dist].append(c)

    return by_dist

def select_4_balanced(candidates, dist_code, dist_name):
    """Pick 4 distinct complexes representing:
    1. High-tier / Landmark (highest price)
    2. Large-scale / Mid-high (highest households > 1000)
    3. Established / Older (>20 yrs or buildYear <= 2005)
    4. Affordable / Entry-level (lowest quartile price among active)
    """
    sorted_by_price = sorted(candidates, key=lambda x: x['median_price'], reverse=True)
    sorted_by_size = sorted(candidates, key=lambda x: x.get('total_households', 0), reverse=True)
    older_cands = [c for c in candidates if c['build_year'] <= 2005]
    if not older_cands:
        older_cands = sorted(candidates, key=lambda x: x['build_year'])

    chosen = []
    chosen_ids = set()

    # 1. Mega-complex / Mid-high: highest households first to capture district anchors
    mega = None
    for c in sorted_by_size:
        if c['complex'] not in chosen_ids:
            mega = c
            break
    mega['archetype'] = '대단지/중상위'
    chosen.append(mega)
    chosen_ids.add(mega['complex'])

    # 2. High-tier / Landmark: top price
    top_tier = None
    for c in sorted_by_price:
        if c['complex'] not in chosen_ids:
            top_tier = c
            break
    top_tier['archetype'] = '고가/대장'
    chosen.append(top_tier)
    chosen_ids.add(top_tier['complex'])

    # 3. Established / Older (>20 yrs): active older complex
    older = None
    older_sorted = sorted(older_cands, key=lambda x: x.get('trade_count', 0), reverse=True)
    for c in older_sorted:
        if c['complex'] not in chosen_ids:
            older = c
            break
    if not older:
        for c in sorted(candidates, key=lambda x: x['build_year']):
            if c['complex'] not in chosen_ids:
                older = c
                break
    older['archetype'] = '구축/재건축'
    chosen.append(older)
    chosen_ids.add(older['complex'])

    # 4. Affordable / Entry-level: lowest price with decent trading
    affordable = None
    low_price_sorted = sorted(candidates, key=lambda x: (x['median_price'], -x.get('trade_count', 0)))
    for c in low_price_sorted:
        if c['complex'] not in chosen_ids:
            affordable = c
            break
    affordable['archetype'] = '중저가/실수요'
    chosen.append(affordable)
    chosen_ids.add(affordable['complex'])

    return chosen

def main():
    by_dist = load_all_candidates()
    final_100 = []
    print("=== Selecting 100 Fixed Daily Sample Complexes (4 per district) ===")
    for code, name in DISTRICTS.items():
        cands = by_dist.get(code, [])
        picks = select_4_balanced(cands, code, name)
        for p in picks:
            entry = {
                'complex': str(p['complex']),
                'district': code,
                'district_name': name,
                'dong': p['dong'],
                'jibun': p.get('jibun', ''),
                'name': p['name'],
                'naver_name': p.get('naver_name', p['name']),
                'archetype': p['archetype'],
                'total_households': p.get('total_households', 0),
                'build_year': p['build_year'],
                'median_price_manwon': p['median_price'],
                'median_price_eok': round(p['median_price'] / 10000, 2),
                'median_area_m2': round(p['median_area'], 1),
                'recent_trade_count': p['trade_count'],
                'tradeComplex': p['tradeComplex'],
                'tradeCrosswalkVerified': True,
                'tracking_tier': 'fixed_daily'
            }
            final_100.append(entry)
        print(f"[{name}] 4 complexes: {', '.join(p['name'] + '(' + p['archetype'] + ', ' + str(p.get('total_households',0)) + '세대, ' + str(round(p['median_price']/10000,1)) + '억)' for p in picks)}")

    print(f"\nTotal Selected: {len(final_100)} complexes across {len(DISTRICTS)} districts.")
    
    out_file = ROOT / 'data' / 'seoul-fixed-sample.json'
    out_file.write_text(json.dumps(final_100, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Saved to {out_file}")

    prices = [c['median_price_eok'] for c in final_100]
    households = [c['total_households'] for c in final_100]
    years = [c['build_year'] for c in final_100]
    archetypes = defaultdict(int)
    for c in final_100:
        archetypes[c['archetype']] += 1

    summary = {
        'total_complexes': len(final_100),
        'districts_covered': len(DISTRICTS),
        'complexes_per_district': 4,
        'archetype_counts': dict(archetypes),
        'price_eok': {
            'min': min(prices),
            'p25': sorted(prices)[len(prices)//4],
            'median': sorted(prices)[len(prices)//2],
            'mean': round(sum(prices)/len(prices), 2),
            'p75': sorted(prices)[3*len(prices)//4],
            'max': max(prices)
        },
        'households': {
            'min': min(households),
            'p25': sorted(households)[len(households)//4],
            'median': sorted(households)[len(households)//2],
            'mean': round(sum(households)/len(households), 0),
            'p75': sorted(households)[3*len(households)//4],
            'max': max(households),
            'total_stock': sum(households)
        },
        'build_year': {
            'min': min(years),
            'p25': sorted(years)[len(years)//4],
            'median': sorted(years)[len(years)//2],
            'p75': sorted(years)[3*len(years)//4],
            'max': max(years)
        }
    }
    print("\n=== Fixed Sample Summary ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    (ROOT / 'data' / 'seoul-fixed-sample-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')

if __name__ == '__main__':
    main()
