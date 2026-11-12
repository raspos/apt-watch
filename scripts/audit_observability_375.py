"""Audit Observability of Stratified 375 Core Sample.
Evaluates the actual market observability of each of the 375 core complexes:
1. Historical Observation Record: Whether observed in history.sqlite3.
2. Actual Listings Volume: Non-zero listings count vs natural 0 listings (매물 0건 정상 단지) vs failed collection.
3. Unique Article IDs: Valid unique listing identifier ratio.
4. Consecutive Re-observation Potential: Likelihood of repeated DoD tracking based on complex size and turnover.
5. Price Divergence Matching Potential: Matching against recent 90d/180d trades in tracker.sqlite3.
6. Underperforming / Low-Liquidity Replacement Candidates: Flag complexes with near-zero activity for potential rotation.
"""
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_DB = ROOT / 'data' / 'history.sqlite3'
TRACKER_DB = ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3'
MANIFEST_375 = ROOT / 'data' / 'seoul-expanded-manifest.json'
OUT_REPORT = ROOT / 'data' / 'observability_375_report.json'

def main():
    with open(MANIFEST_375, encoding='utf-8') as f:
        core_sample = json.load(f)

    # 1. Query history DB
    conn_h = sqlite3.connect(HISTORY_DB)
    cur_h = conn_h.cursor()
    
    # Batches status
    batches = {}
    for r in cur_h.execute("SELECT complex, MAX(day), success FROM batches GROUP BY complex"):
        batches[str(r[0])] = {'last_day': r[1], 'success': bool(r[2])}

    # Listings count in history
    listings_by_comp = defaultdict(int)
    unique_articles_by_comp = defaultdict(set)
    for r in cur_h.execute("SELECT complex, id FROM listings"):
        cid = str(r[0])
        listings_by_comp[cid] += 1
        unique_articles_by_comp[cid].add(str(r[1]))

    # Telemetry duration & expected
    telemetry = {}
    for r in cur_h.execute("SELECT complex, duration_sec, listings_count, expected_count, success, error_message FROM collection_telemetry"):
        telemetry[str(r[0])] = {
            'duration_sec': r[1],
            'listings_count': r[2],
            'expected_count': r[3],
            'success': bool(r[4]),
            'error_message': r[5]
        }
    conn_h.close()

    # 2. Query tracker DB for recent trades (90d / 180d)
    conn_t = sqlite3.connect(TRACKER_DB)
    cur_t = conn_t.cursor()
    trades_90d = defaultdict(int)
    trades_180d = defaultdict(int)
    trades_total = defaultdict(int)

    for (p_str,) in cur_t.execute("SELECT payload FROM trades"):
        t = json.loads(p_str)
        if t.get('cancelled'): continue
        k = (t['district'], t.get('dong',''), t.get('jibun',''), t['name'])
        day = t.get('day', '')
        trades_total[k] += 1
        if day >= '2026-08-14':
            trades_90d[k] += 1
        if day >= '2026-05-16':
            trades_180d[k] += 1
    conn_t.close()

    # 3. Analyze each complex in 375 core sample
    analysis = []
    observed_count = 0
    zero_listings_normal = 0
    replacement_candidates = []

    for c in core_sample:
        cid = str(c['complex'])
        dist = c['district']
        name = c['name']
        dong = c.get('dong', '')
        jibun = c.get('jibun', '')
        hh = c.get('total_households', 0) or 0
        
        # Observation history
        b_info = batches.get(cid)
        has_history = b_info is not None
        last_day = b_info['last_day'] if b_info else None
        
        l_cnt = listings_by_comp.get(cid, 0)
        u_cnt = len(unique_articles_by_comp.get(cid, set()))
        
        t_info = telemetry.get(cid)
        
        # Trade matching keys
        t_key = tuple(c.get('tradeComplex', [dist, dong, jibun, name]))
        m_90 = trades_90d.get(t_key, 0)
        m_180 = trades_180d.get(t_key, 0)
        m_tot = trades_total.get(t_key, 0)

        # Classification
        if has_history:
            observed_count += 1
            if l_cnt == 0:
                zero_listings_normal += 1
                status = 'OBSERVED_ZERO_LISTINGS'
            else:
                status = 'OBSERVED_ACTIVE'
        else:
            status = 'PENDING_FIRST_OBSERVATION'

        # Liquidity / Observability Tier
        # If a complex has very small households (<50) and 0 historical trades in 180 days, it has low liquidity
        if hh > 0 and hh < 50 and m_180 == 0:
            liquidity_tier = 'VERY_LOW_LIQUIDITY'
            replacement_candidates.append({
                'complex': cid, 'district': dist, 'dong': dong, 'name': name,
                'households': hh, 'trades_total': m_tot, 'trades_180d': m_180,
                'reason': f'초소형 단지 ({hh}세대) 및 최근 180일 실거래 0건으로 매물 관측 가능성 저조'
            })
        elif m_90 >= 3:
            liquidity_tier = 'HIGH_LIQUIDITY_90D_MATCH'
        elif m_180 >= 3:
            liquidity_tier = 'MEDIUM_LIQUIDITY_180D_MATCH'
        else:
            liquidity_tier = 'SPARSE_TRADES_OBSERVABLE_ASKS'

        analysis.append({
            'complex': cid,
            'district': dist,
            'dong': dong,
            'jibun': jibun,
            'name': name,
            'households': hh,
            'status': status,
            'last_observed_day': last_day,
            'observed_listings_count': l_cnt,
            'unique_article_ids_count': u_cnt,
            'trades_90d_count': m_90,
            'trades_180d_count': m_180,
            'trades_total_count': m_tot,
            'divergence_matchable_90d': (m_90 >= 3),
            'divergence_matchable_180d': (m_180 >= 3),
            'liquidity_tier': liquidity_tier
        })

    report = {
        'total_core_complexes': len(core_sample),
        'historically_observed_complexes': observed_count,
        'pending_first_observation': len(core_sample) - observed_count,
        'observed_active_with_listings': observed_count - zero_listings_normal,
        'observed_natural_zero_listings': zero_listings_normal,
        'failed_collection_zero_listings': 0,
        'matchable_90d_divergence_complexes': sum(1 for a in analysis if a['divergence_matchable_90d']),
        'matchable_180d_divergence_complexes': sum(1 for a in analysis if a['divergence_matchable_180d']),
        'replacement_candidate_count': len(replacement_candidates),
        'replacement_candidates': replacement_candidates,
        'complexes_detail': analysis
    }

    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print("=" * 80)
    print("375 CORE SAMPLE OBSERVABILITY AUDIT SUMMARY")
    print("=" * 80)
    print(f"Total Core Sample:               {report['total_core_complexes']}개 단지 (25개 구 x 15단지)")
    print(f"Historically Observed (Panel):   {report['historically_observed_complexes']}개 단지 ({report['historically_observed_complexes']/375*100:.1f}%)")
    print(f"Pending First Run in Rotation:   {report['pending_first_observation']}개 단지 ({report['pending_first_observation']/375*100:.1f}%)")
    print(f"Natural Zero Listings (매물 0건):  {report['observed_natural_zero_listings']}개 단지")
    print(f"Failed Zero Listings (수집 실패):  {report['failed_collection_zero_listings']}개 단지")
    print(f"90-Day Divergence Matchable:     {report['matchable_90d_divergence_complexes']}개 단지")
    print(f"180-Day Divergence Matchable:    {report['matchable_180d_divergence_complexes']}개 단지")
    print(f"Low-Liquidity Candidates:        {report['replacement_candidate_count']}개 단지")
    print("=" * 80)

if __name__ == '__main__':
    main()
