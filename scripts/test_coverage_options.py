import json, sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

db = sqlite3.connect(ROOT / 'data' / 'history.sqlite3')
tdb = sqlite3.connect(ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3')
sample = json.load(open(ROOT / 'data' / 'seoul-fixed-sample.json', encoding='utf-8'))
crosswalk = {c['complex']: c for c in sample}

all_dist = {
    '11110': '종로구', '11140': '중구', '11170': '용산구', '11200': '성동구', '11215': '광진구',
    '11230': '동대문구', '11260': '중랑구', '11290': '성북구', '11305': '강북구', '11320': '도봉구',
    '11350': '노원구', '11380': '은평구', '11410': '서대문구', '11440': '마포구', '11470': '양천구',
    '11500': '강서구', '11530': '구로구', '11545': '금천구', '11560': '영등포구', '11590': '동작구',
    '11620': '관악구', '11650': '서초구', '11680': '강남구', '11710': '송파구', '11740': '강동구'
}

end_date = date.fromisoformat('2026-11-12')
for days in [90, 180]:
    start_date = end_date - timedelta(days=days-1)
    cur = tdb.cursor()
    cur.execute("SELECT district, month, payload FROM trades WHERE month >= '2023-01'")
    trades = defaultdict(list)
    trades_by_area = defaultdict(list)
    for dist, month, p_str in cur:
        p = json.loads(p_str)
        if p.get('cancelled'): continue
        t_day = p.get('day')
        if not t_day or not (start_date.isoformat() <= t_day <= '2026-11-12'): continue
        pr = float(p.get('price', 0))
        if pr <= 0: continue
        fl = int(p.get('floor', 5))
        tier = 0 if fl <= 3 else 1 if fl <= 9 else 2
        area = int(float(p.get('area', 0)))
        k = (p['district'], p['dong'], p.get('jibun', ''), p['name'], area, tier)
        k_area = (p['district'], p['dong'], p.get('jibun', ''), p['name'], area)
        trades[k].append(pr)
        trades_by_area[k_area].append(pr)
        
    listings = db.execute("SELECT complex, price, payload FROM listings WHERE day='2026-11-12'").fetchall()
    matched_strict = set()
    matched_fallback = set()
    for cid, pr, p_str in listings:
        cinfo = crosswalk.get(cid)
        if not cinfo or not cinfo.get('tradeComplex'): continue
        tc = cinfo['tradeComplex']
        p = json.loads(p_str)
        area = int(float(p.get('exclusive_area_m2', 0)))
        fl = p.get('floor')
        fl_int = int(fl) if str(fl).isdigit() else 5
        tier = 0 if fl_int <= 3 else 1 if fl_int <= 9 else 2
        k = (tc[0], tc[1], tc[2], tc[3], area, tier)
        k_area = (tc[0], tc[1], tc[2], tc[3], area)
        if len(trades.get(k, [])) >= 3:
            matched_strict.add(tc[0])
        if len(trades.get(k, [])) >= 3 or len(trades_by_area.get(k_area, [])) >= 3:
            matched_fallback.add(tc[0])
            
    print(f"\n--- 관측 윈도우: {days}일 ---")
    print(f"  Strict (평형+층구간 >=3건): {len(matched_strict)}/25개 구")
    missing_strict = [all_dist[k] for k in all_dist if k not in matched_strict]
    if missing_strict:
        print(f"    미달 자치구: {missing_strict}")
    print(f"  Fallback (층구간 부족시 동일 평형 >=3건 결합): {len(matched_fallback)}/25개 구")
    missing_fb = [all_dist[k] for k in all_dist if k not in matched_fallback]
    if missing_fb:
        print(f"    미달 자치구: {missing_fb}")
