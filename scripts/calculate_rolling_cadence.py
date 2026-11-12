"""Empirical Cadence Calculator for APT WATCH Universe.

Models the realistic rolling cadence for Seoul's 5,821 complexes based on:
  - 375 Core complexes (collected daily)
  - 5,446 Non-core complexes (rotated on rolling schedule)
  - Empirical per-complex latency: 17.3s (3.4~3.5 complexes/min with 2~4 workers)
  - Empirical atomic staging merge overhead: ~1.0s
  - Daily operational time budget scenarios: 45 min, 60 min, 90 min, 120 min
  - Zone-based rotation modeling across Seoul's 5 major planning zones

Replaces unrealistic 1,000 complexes/day assumptions with empirically grounded
throughput and sustainable Task Scheduler / GitHub Actions budgets.
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

def calculate_cadence():
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

    # Empirical benchmarks (from benchmark_worker_scaling.py)
    # 4 workers sustained: ~17.3s per complex (effective throughput ~3.47 cpm)
    sec_per_comp = 17.3
    workers = 4
    effective_cpm = (60.0 / sec_per_comp) # ~3.47 complexes/min across 4 workers
    core_time_min = (core_count * sec_per_comp / workers) / 60.0 # ~27.0 min

    # Daily operational budget scenarios
    scenarios = []
    for total_budget_min in [45, 60, 90, 120]:
        avail_rolling_min = max(0, total_budget_min - core_time_min)
        daily_rolling_capacity = int(avail_rolling_min * (60.0 / (sec_per_comp / workers)) / 60.0)
        # More precisely: capacity = avail_rolling_min * (workers * 60 / sec_per_comp)
        daily_rolling_capacity = int((avail_rolling_min * 60.0) / (sec_per_comp / workers))
        
        cycle_days = round(non_core_count / max(1, daily_rolling_capacity), 1)
        cycle_weeks = round(cycle_days / 7.0, 1)

        scenarios.append({
            'totalDailyBudgetMin': total_budget_min,
            'coreCollectionMin': round(core_time_min, 1),
            'rollingCollectionMin': round(avail_rolling_min, 1),
            'dailyRollingComplexes': daily_rolling_capacity,
            'fullUniverseCycleDays': cycle_days,
            'fullUniverseCycleWeeks': cycle_weeks,
            'feasibility': '매우 안정적 (권장)' if 60 <= total_budget_min <= 90 else ('최소 가동' if total_budget_min == 45 else '여유 가동')
        })

    # Zone-based cycle rotation
    zone_breakdown = {}
    for z, tot in zone_total.most_common():
        cr = zone_core[z]
        ncr = zone_non_core[z]
        pct = round(tot / total_universe * 100, 2)
        zone_breakdown[z] = {
            'total': tot,
            'coreDaily': cr,
            'nonCoreRolling': ncr,
            'universeSharePct': pct
        }

    report = {
        'empiricalParameters': {
            'workerCount': workers,
            'secPerComplex': sec_per_comp,
            'effectiveThroughputCPM': round(effective_cpm * workers, 2),
            'coreSampleCount': core_count,
            'nonCoreUniverseCount': non_core_count,
            'totalUniverseCount': total_universe,
            'dailyCoreTimeMin': round(core_time_min, 1)
        },
        'zoneBreakdown': zone_breakdown,
        'operationalBudgetScenarios': scenarios
    }

    out_path = ROOT / 'data' / 'rolling_cadence_report.json'
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Rolling cadence report saved to {out_path}")

    print("=" * 80)
    print("EMPIRICAL ROLLING CADENCE VERIFICATION (4 Workers, 17.3s/complex)")
    print("=" * 80)
    print(f"Total Universe: {total_universe:,} complexes | Core Sample: {core_count} complexes (Daily)")
    print(f"Non-Core Rolling Pool: {non_core_count:,} complexes")
    print(f"Core Collection Time: {core_time_min:.1f} minutes")
    print("-" * 80)
    for sc in scenarios:
        print(f"Budget {sc['totalDailyBudgetMin']:3d} min/day | Rolling {sc['rollingCollectionMin']:4.1f} min | Capacity {sc['dailyRollingComplexes']:4d} comps/day | Cycle: {sc['fullUniverseCycleDays']:4.1f} days ({sc['fullUniverseCycleWeeks']:3.1f} weeks) [{sc['feasibility']}]")
    print("=" * 80)
    return report

if __name__ == '__main__':
    calculate_cadence()
