import json, sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

db = sqlite3.connect(ROOT / 'data' / 'history.sqlite3')
tdb = sqlite3.connect(ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3')
sample = json.load(open(ROOT / 'data' / 'seoul-fixed-sample.json', encoding='utf-8'))

missing = {'11110': '종로구', '11215': '광진구', '11440': '마포구', '11650': '서초구', '11680': '강남구'}

end_date = date.fromisoformat('2026-11-12')
start_date = end_date - timedelta(days=89)

# Load trades in 90 days
cur = tdb.cursor()
cur.execute("SELECT district, month, payload FROM trades WHERE month >= '2024-01'")
trades_raw = []
for dist, month, p_str in cur:
    p = json.loads(p_str)
    if p.get('cancelled'): continue
    t_day = p.get('day')
    if not t_day or not (start_date.isoformat() <= t_day <= '2026-11-12'): continue
    trades_raw.append(p)

print(f"Loaded {len(trades_raw)} trades in last 90 days.")

for code, name in missing.items():
    comps = [c for c in sample if c['district'] == code]
    print(f"\n========================================================")
    print(f"[{name}] (코드 {code}) : 총 {len(comps)}개 단지 표본")
    print(f"========================================================")
    for c in comps:
        cid = c['complex']
        cname = c['name']
        tc = c.get('tradeComplex')
        
        listings = db.execute("SELECT price, payload FROM listings WHERE day='2026-11-12' AND complex=?", (cid,)).fetchall()
        print(f"\n* 단지: {cname} (ID: {cid})")
        print(f"  - tradeComplex 매핑: {tc}")
        print(f"  - 수집된 호가 수: {len(listings)}건")
        
        if not tc:
            print("  -> 사유: tradeComplex 매핑이 없음 (실거래 연결 불가)")
            continue
            
        # Check actual trades for this complex
        c_trades = [t for t in trades_raw if t.get('name') == tc[3] and t.get('dong') == tc[1]]
        print(f"  - 최근 90일 내 실거래 건수: {len(c_trades)}건 (단지명: {tc[3]})")
        
        # Breakdown by area & floor
        tr_by_stratum = defaultdict(int)
        for t in c_trades:
            area = int(float(t.get('area', 0)))
            floor = int(t.get('floor', 5))
            tier = 0 if floor <= 3 else 1 if floor <= 9 else 2
            tr_by_stratum[(area, tier)] += 1
            
        ask_by_stratum = defaultdict(list)
        ask_floor_types = defaultdict(int)
        for pr, p_str in listings:
            p = json.loads(p_str)
            area = int(float(p.get('exclusive_area_m2', 0)))
            fl = p.get('floor')
            ask_floor_types[str(fl)] += 1
            fl_int = int(fl) if str(fl).isdigit() else 5
            tier = 0 if fl_int <= 3 else 1 if fl_int <= 9 else 2
            ask_by_stratum[(area, tier)].append(pr)
            
        print(f"  - 실거래 평형/층 분포 (건수 >= 3 기준):")
        matched_strata = 0
        for st, count in tr_by_stratum.items():
            if count >= 3:
                asks = ask_by_stratum.get(st, [])
                print(f"    - 면적 {st[0]}㎡ (tier {st[1]}): 실거래 {count}건, 매칭 호가 {len(asks)}건")
                if len(asks) > 0:
                    matched_strata += 1
            else:
                pass
        if matched_strata == 0:
            print(f"    -> 90일 내 3건 이상 실거래가 성립한 동일 평형/층 매칭 그룹: 0개!")
            # Show why
            all_strata_tr = sum(tr_by_stratum.values())
            if all_strata_tr == 0:
                print(f"       (원인: 최근 90일간 실거래 자체가 0건임)")
            else:
                max_tr = max(tr_by_stratum.values()) if tr_by_stratum else 0
                print(f"       (원인: 최근 90일간 특정 평형/층의 실거래 건수가 최대 {max_tr}건으로 3건 기준 미달)")
