"""Empirical Cadence Calculator for APT WATCH Universe.
Models the realistic rolling cadence for Seoul's 5,821 complexes based on:
  - 375 Core complexes (collected daily)
  - 5,446 Non-core complexes (rotated on rolling schedule)
  - Empirical per-complex latency: 20.42s
  - Worker configurations: 4, 8, 10 workers
  - Target daily operational time budget (30 min, 45 min, 60 min, 90 min)
"""
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPLEXES_JSON = ROOT / 'data' / 'complexes.json'
MANIFEST_375 = ROOT / 'data' / 'seoul-expanded-manifest.json'

ZONES = {
    '11110': '도심권', '11140': '도심권', '11170': '도심권',
    '11650': '동남권', '11680': '동남권', '11710': '동남권', '11740': '동남권',
    '11200': '동북권', '11215': '동북권', '11230': '동북권', '11260': '동북권',
    '11290': '동북권', '11305': '동북권', '11320': '동북권', '11350': '동북권',
    '11380': '서북권', '11410': '서북권', '11440': '서북권',
    '11470': '서남권', '11500': '서남권', '11530': '서남권', '11545': '서남권',
    '11560': '서남권', '11590': '서남권', '11620': '서남권'
}

def main():
    with open(COMPLEXES_JSON, encoding='utf-8') as f:
        comps = json.load(f)
    with open(MANIFEST_375, encoding='utf-8') as f:
        core_ids = {str(c['complex']) for c in json.load(f)}

    total_universe = len(comps)
    core_count = len(core_ids)
    non_core_count = total_universe - core_count

    # Group by Zone
    zone_total = Counter()
    zone_core = Counter()
    zone_non_core = Counter()

    for c in comps:
        cid = str(c['complex'])
        z = ZONES.get(c['district'], '기타')
        zone_total[z] += 1
        if cid in core_ids:
            zone_core[z] += 1
        else:
            zone_non_core[z] += 1

    print("=" * 80)
    print("SEOUL 5,821 UNIVERSE ZONE DISTRIBUTION AUDIT")
    print("=" * 80)
    print(f"{'Zone':8s} | {'Total Comps':11s} | {'Core (Daily)':12s} | {'Non-Core (Rolling)':18s} | {'Universe Share':14s}")
    print("-" * 75)
    for z, tot in zone_total.most_common():
        cr = zone_core[z]
        ncr = zone_non_core[z]
        pct = tot / total_universe * 100
        print(f"{z:8s} | {tot:11,d} | {cr:12,d} | {ncr:18,d} | {pct:13.2f}%")
    print("-" * 75)
    print(f"{'TOTAL':8s} | {total_universe:11,d} | {core_count:12,d} | {non_core_count:18,d} | 100.00%")
    print("=" * 80)

    # Latency model
    sec_per_comp = 20.42

    print("\n[수집 시간 및 가동 예산별 순환 주기 시뮬레이션]")
    print(f"기준: 단지당 실측 {sec_per_comp:.2f}초, 핵심 표본 {core_count}개 매일 고정 수집")
    
    for workers in [4, 8, 10]:
        core_time_min = (core_count * sec_per_comp / workers) / 60
        print(f"\n--- [워커 수: {workers}개] ---")
        print(f"  핵심 375개 일일 수집 소요시간: {core_time_min:.1f}분")
        
        for daily_rolling_quota in [500, 750, 1000, 1100]:
            rolling_time_min = (daily_rolling_quota * sec_per_comp / workers) / 60
            total_daily_time_min = core_time_min + rolling_time_min
            cycle_days = non_core_count / daily_rolling_quota
            print(f"  일일 순환 쿼터 {daily_rolling_quota:4d}개: 순환 수집 {rolling_time_min:4.1f}분 | 총 일일가동 {total_daily_time_min:5.1f}분 | 전체 완주 주기: {cycle_days:.1f}일")

if __name__ == '__main__':
    main()
