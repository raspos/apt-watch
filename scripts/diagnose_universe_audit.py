import sqlite3
import json
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
TRACKER_DB = ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3'
HISTORY_DB = ROOT / 'data' / 'history.sqlite3'
COMPLEXES_JSON = ROOT / 'data' / 'complexes.json'

def main():
    conn_t = sqlite3.connect(TRACKER_DB)
    cur_t = conn_t.cursor()
    
    unique_trade_keys = set()
    trade_counts = defaultdict(int)
    for (payload_str,) in cur_t.execute("SELECT payload FROM trades"):
        t = json.loads(payload_str)
        key = (t['district'], t.get('dong', ''), t.get('jibun', ''), t['name'])
        unique_trade_keys.add(key)
        trade_counts[key] += 1
        
    print(f"[Set A: MOLIT Real Transaction Candidates]")
    print(f"Total distinct address keys (district, dong, jibun, name): {len(unique_trade_keys):,}개")
    
    # 2. Set B: Naver ID Mapped Universe (complexes.json)
    with open(COMPLEXES_JSON, encoding='utf-8') as f:
        comps = json.load(f)
    print(f"\n[Set B: Naver Complex ID Mapped Universe (complexes.json)]")
    print(f"Total mapped complexes in complexes.json: {len(comps):,}개")
    
    mapped_keys = {(c['district'], c.get('dong', ''), c.get('jibun', ''), c['name']) for c in comps}
    mapped_in_trades = mapped_keys & unique_trade_keys
    unmapped_trade_keys = unique_trade_keys - mapped_keys
    mapped_not_in_trades = mapped_keys - unique_trade_keys
    
    print(f"Mapped keys present in MOLIT trades: {len(mapped_in_trades):,}개 ({len(mapped_in_trades)/len(unique_trade_keys)*100:.1f}% of trades)")
    print(f"MOLIT trade candidates not yet in complexes.json: {len(unmapped_trade_keys):,}개")
    print(f"complexes.json keys not found in MOLIT trades (new builds / zero historical trades): {len(mapped_not_in_trades):,}개")

    # Analyze trade count distribution of unmapped trade keys
    unmapped_trade_volumes = [trade_counts[k] for k in unmapped_trade_keys]
    import statistics
    print(f"Unmapped trade candidates volume distribution:")
    print(f"  Total trades in unmapped: {sum(unmapped_trade_volumes):,}건")
    print(f"  Mean trades per unmapped: {statistics.mean(unmapped_trade_volumes):.1f}건")
    print(f"  Median trades: {statistics.median(unmapped_trade_volumes)}건")
    print(f"  <= 3 trades: {sum(1 for v in unmapped_trade_volumes if v <= 3):,}개 ({sum(1 for v in unmapped_trade_volumes if v <= 3)/len(unmapped_trade_volumes)*100:.1f}%)")
    print(f"  >= 50 trades: {sum(1 for v in unmapped_trade_volumes if v >= 50):,}개")

    # 3. Set C: History DB Actual Observations
    conn_h = sqlite3.connect(HISTORY_DB)
    cur_h = conn_h.cursor()
    observed_comps = cur_h.execute("""
        SELECT complex, COUNT(*) as batch_cnt, 
               MAX(CASE WHEN success=1 THEN 1 ELSE 0 END) as any_succ,
               MAX(day) as latest_day
        FROM batches
        GROUP BY complex
    """).fetchall()
    succ_comps = [r for r in observed_comps if r[2] == 1]
    
    print(f"\n[Set C: Actually Observed Complexes in history.sqlite3]")
    print(f"Total complexes ever attempted: {len(observed_comps):,}개")
    print(f"Total complexes successfully observed (success=1): {len(succ_comps):,}개")

    # 4. Check Duplicate Naver IDs
    id_to_comps = defaultdict(list)
    for c in comps:
        id_to_comps[str(c['complex'])].append(c)
    dupe_ids = {k: v for k, v in id_to_comps.items() if len(v) > 1}
    print(f"\n[Quality Audit 1: Duplicate Naver Complex IDs in complexes.json]: {len(dupe_ids)}건")
    for k, v in list(dupe_ids.items())[:5]:
        print(f"   ID {k}: {[x['name'] + ' (' + x.get('dong','') + ')' for x in v]}")

    # 5. Check Landmark Complexes
    landmarks = [
        ('마포래미안푸르지오', '11440'),
        ('목동', '11470'),
        ('반포자이', '11650'),
        ('디에이치퍼스티어아이파크', '11680'),
        ('올림픽파크포레온', '11740'),
        ('헬리오시티', '11710'),
        ('구의현대', '11215'),
        ('현대프라임', '11215'),
        ('경희궁의아침', '11110')
    ]
    print("\n[Quality Audit 2: Landmark Complex Inspection in complexes.json]:")
    for name_query, dist in landmarks:
        matches = [c for c in comps if dist == c['district'] and name_query in c['name']]
        print(f"   [{name_query} (구코드 {dist})]: {len(matches)}개 매핑")
        for m in matches[:4]:
            print(f"     -> ID: {m['complex']}, Name: {m['name']}, Dong: {m.get('dong','')}, TradeCount: {m.get('trade_count',0)}")

if __name__ == '__main__':
    main()
