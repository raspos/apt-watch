import sqlite3
import json
from pathlib import Path
from collections import defaultdict
from statistics import median

ROOT = Path(__file__).resolve().parent.parent
TRACKER_DB = ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3'
COMPLEXES_JSON = ROOT / 'data' / 'complexes.json'
ROSTER_JSON = ROOT / 'data' / 'seoul-mapped-roster.json'

def main():
    print("Enriching Seoul complexes metadata...")
    with open(COMPLEXES_JSON, encoding='utf-8') as f:
        comps = json.load(f)
    print(f"Loaded {len(comps)} complexes.")

    # 1. Roster metadata (households)
    roster_map = {}
    if ROSTER_JSON.exists():
        with open(ROSTER_JSON, encoding='utf-8') as f:
            for item in json.load(f):
                roster_map[str(item['complex'])] = item

    # 2. Trade metadata (build_year, prices, trade_count)
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

    enriched_count = 0
    size_bins = {'소규모 (<300)': 0, '중규모 (300-999)': 0, '대규모 (>=1000)': 0, '미상': 0}
    year_bins = {'신축 (<5년)': 0, '중간 (5-19년)': 0, '구축 (20-29년)': 0, '재건축연한 (>=30년)': 0, '미상': 0}

    for c in comps:
        cid = str(c['complex'])
        r = roster_map.get(cid, {})
        hh = r.get('total_households')
        c['total_households'] = hh

        # Match trade info
        key = (c['district'], c.get('dong', ''), c.get('jibun', ''), c['name'])
        ti = trade_info.get(key)
        if ti and ti['count'] > 0:
            c['trade_count'] = ti['count']
            c['median_price_eok'] = round(median(ti['prices']), 2) if ti['prices'] else None
            c['build_year'] = round(median(ti['build_years'])) if ti['build_years'] else None
            c['crosswalk_status'] = 'VERIFIED_EXACT'
            enriched_count += 1
        else:
            c['trade_count'] = 0
            c['median_price_eok'] = None
            c['build_year'] = None
            c['crosswalk_status'] = 'UNVERIFIED_PENDING'

        # Binning
        if hh is None:
            size_bins['미상'] += 1
        elif hh < 300:
            size_bins['소규모 (<300)'] += 1
        elif hh < 1000:
            size_bins['중규모 (300-999)'] += 1
        else:
            size_bins['대규모 (>=1000)'] += 1

        by = c['build_year']
        if by is None:
            year_bins['미상'] += 1
        else:
            age = 2026 - by
            if age < 5:
                year_bins['신축 (<5년)'] += 1
            elif age < 20:
                year_bins['중간 (5-19년)'] += 1
            elif age < 30:
                year_bins['구축 (20-29년)'] += 1
            else:
                year_bins['재건축연한 (>=30년)'] += 1

    print(f"\nSuccessfully enriched {enriched_count:,} / {len(comps):,} complexes with MOLIT trades!")
    print("\n--- 서울 전체 단지 규모 분포 (5,821개) ---")
    for k, v in size_bins.items():
        print(f"  {k}: {v:,}개 ({v/len(comps)*100:.1f}%)")

    print("\n--- 서울 전체 단지 건축연한 분포 (5,821개) ---")
    for k, v in year_bins.items():
        print(f"  {k}: {v:,}개 ({v/len(comps)*100:.1f}%)")

if __name__ == '__main__':
    main()
