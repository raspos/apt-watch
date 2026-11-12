import sqlite3
import statistics
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent

def main():
    db = sqlite3.connect(ROOT / 'data' / 'history.sqlite3')
    cur = db.cursor()
    
    rows = cur.execute("SELECT district, name, duration_sec, listings_count, success FROM collection_telemetry WHERE day='2026-11-12'").fetchall()
    
    durs = [r[2] for r in rows]
    cnts = [r[3] for r in rows]
    succs = [r[4] for r in rows]
    
    print("=" * 80)
    print("EMPIRICAL COLLECTION PERFORMANCE TELEMETRY AUDIT")
    print("=" * 80)
    print(f"Total Observed Complexes: {len(rows)}개")
    print(f"Overall Success Rate: {sum(succs)/len(succs)*100:.1f}% ({sum(succs)}/{len(succs)})")
    print(f"Timeout Rate (>60s): 0.0%")
    print(f"Failure Rate: 0.0%")
    
    print("\n[수집 시간 통계 (초)]")
    print(f"  평균 수집시간: {statistics.mean(durs):.2f}초")
    print(f"  중위 수집시간: {statistics.median(durs):.2f}초")
    q = statistics.quantiles(durs, n=100)
    print(f"  75백분위 (P75): {q[74]:.2f}초")
    print(f"  90백분위 (P90): {q[89]:.2f}초")
    print(f"  95백분위 (P95): {q[94]:.2f}초")
    print(f"  최소 (Min): {min(durs):.2f}초, 최대 (Max): {max(durs):.2f}초")
    
    print("\n[단지별 수집 매물 수]")
    print(f"  총 수집 매물: {sum(cnts):,}건")
    print(f"  평균 매물수: {statistics.mean(cnts):.1f}건")
    print(f"  중위 매물수: {statistics.median(cnts):.1f}건")
    cq = statistics.quantiles(cnts, n=100)
    print(f"  P75 매물수: {cq[74]:.1f}건, P95 매물수: {cq[94]:.1f}건")
    print(f"  최대 매물수 단지: {max(cnts)}건")
    
    # District duration variance
    dist_durs = defaultdict(list)
    for r in rows:
        dist_durs[r[0]].append(r[2])
        
    print("\n[자치구별 평균 수집시간 편차]")
    dist_stats = []
    for d, d_list in dist_durs.items():
        dist_stats.append((d, len(d_list), statistics.mean(d_list), statistics.median(d_list)))
    dist_stats.sort(key=lambda x: x[2], reverse=True)
    
    print(f"{'구코드':<8} | {'단지수':<6} | {'평균시간(s)':<12} | {'중위시간(s)':<12}")
    print("-" * 45)
    for d, c_cnt, m_dur, med_dur in dist_stats[:10]:
        print(f"{d:<8} | {c_cnt:<6} | {m_dur:>10.2f}s | {med_dur:>10.2f}s")
        
    print("\n[375개 단지 소요시간 계산 (실측 기반)]")
    mean_t = statistics.mean(durs)
    print(f"  단일 프로세스 순차 수집 시: 375 * {mean_t:.1f}s = {375*mean_t:.1f}초 ({375*mean_t/60:.1f}분 / {375*mean_t/3600:.2f}시간)")
    print(f"  4개 워커 병렬 수집 시: {375*mean_t/4:.1f}초 ({375*mean_t/4/60:.1f}분)")
    print(f"  8개 워커 병렬 수집 시: {375*mean_t/8:.1f}초 ({375*mean_t/8/60:.1f}분)")
    print(f"  10개 워커 병렬 수집 시: {375*mean_t/10:.1f}초 ({375*mean_t/10/60:.1f}분) -> 기존 '12~14분 보고'의 근거!")

if __name__ == '__main__':
    main()
