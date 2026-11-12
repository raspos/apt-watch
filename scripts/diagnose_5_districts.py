import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3, json
from collections import defaultdict
from datetime import date, timedelta
from apt_watch import ROOT, read_trades, store
from market_metrics import trade_key

db = store(ROOT / 'data/history.sqlite3')
tracker = ROOT.parent / 'seoul-apartment-tracker/data/tracker.sqlite3'
_, trades = read_trades(tracker)

end = date.fromisoformat('2026-11-12')
start = end - timedelta(days=89)

# Group trades in 90 days
trades_90 = defaultdict(list)
for t in trades:
    if t.get('cancelled'): continue
    t_day = t.get('day')
    if t_day and start.isoformat() <= t_day <= '2026-11-12':
        k = trade_key(t)
        if k: trades_90[k].append(t)

missing_codes = {'11110': '종로구', '11215': '광진구', '11440': '마포구', '11650': '서초구', '11680': '강남구'}

for code, name in missing_codes.items():
    print(f"\n=== {name} ({code}) ===")
    cur = db.execute("SELECT payload FROM listing_roster WHERE day='2026-11-12' AND district=?", (code,))
    roster_targets = [json.loads(r[0]) for r in cur.fetchall()]
    total_dist_matched = 0
    for target in roster_targets:
        cid = target['complex']
        cname = target['name']
        tcomp = target.get('tradeComplex')
        
        listings_rows = db.execute("SELECT payload FROM listings WHERE day='2026-11-12' AND complex=?", (cid,)).fetchall()
        ask_keys = defaultdict(int)
        for (l_str,) in listings_rows:
            l = json.loads(l_str)
            row = {**l, **dict(zip(('district','dong','jibun','name'), tcomp)), 'area': l.get('exclusive_area_m2')}
            k = trade_key(row)
            if k: ask_keys[k] += 1
            
        print(f"  단지: {cname} ({cid}): 호가 매물 {len(listings_rows)}건, 유효 key {len(ask_keys)}개")
        matched_strata = 0
        for k, ask_count in ask_keys.items():
            tr_count = len(trades_90.get(k, []))
            if tr_count >= 3:
                matched_strata += 1
                total_dist_matched += 1
                print(f"    [MATCHED >=3] area={k[4]}㎡, tier={k[5]} -> asks={ask_count}건, trades={tr_count}건")
            elif tr_count > 0:
                print(f"    [PARTIAL <3] area={k[4]}㎡, tier={k[5]} -> asks={ask_count}건, trades={tr_count}건")
        if matched_strata == 0:
            print(f"    => 90일 내 3건 이상 실거래 매칭 그룹 0개")
    print(f"  => {name} 총 매칭 성립 그룹: {total_dist_matched}개")
