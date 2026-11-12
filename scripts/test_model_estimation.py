import json
import sqlite3
import math
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean, median
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 1. Load data
db = sqlite3.connect(ROOT / 'data' / 'history.sqlite3')
tdb = sqlite3.connect(ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3')
sample = json.load(open(ROOT / 'data' / 'seoul-fixed-sample.json', encoding='utf-8'))
crosswalk = {c['complex']: c for c in sample}

all_districts = {
    '11110': '종로구', '11140': '중구', '11170': '용산구', '11200': '성동구', '11215': '광진구',
    '11230': '동대문구', '11260': '중랑구', '11290': '성북구', '11305': '강북구', '11320': '도봉구',
    '11350': '노원구', '11380': '은평구', '11410': '서대문구', '11440': '마포구', '11470': '양천구',
    '11500': '강서구', '11530': '구로구', '11545': '금천구', '11560': '영등포구', '11590': '동작구',
    '11620': '관악구', '11650': '서초구', '11680': '강남구', '11710': '송파구', '11740': '강동구'
}

# Load District FE series
site_data = json.load(open(ROOT / 'site' / 'data.json', encoding='utf-8'))
dist_fe = {}
for d, pts in site_data.get('series', {}).items():
    dist_fe[d] = {p['month']: p['index'] for p in pts if p.get('index')}

cur = tdb.cursor()
cur.execute("SELECT district, month, payload FROM trades WHERE month >= '2023-01'")
all_trades = []
for dist, month, p_str in cur:
    p = json.loads(p_str)
    if p.get('cancelled'): continue
    pr = float(p.get('price', 0))
    if pr <= 0: continue
    all_trades.append(p)

def get_trade_key(row):
    try:
        area = int(float(row.get('area') or row.get('exclusive_area_m2', 0)))
        raw_floor = str(row.get('floor', '5')).split('/')[0].strip()
        if raw_floor == '저':
            floor_tier = 0
        elif raw_floor == '고':
            floor_tier = 2
        elif raw_floor.isdigit():
            f = int(raw_floor)
            floor_tier = 0 if f <= 3 else 1 if f <= 9 else 2
        else:
            floor_tier = 1
        name = row['name']
        if '마포래미안푸르지오' in name:
            name = '마포래미안푸르지오'
        return (row['district'], row['dong'], row.get('jibun', ''), name, area, floor_tier)
    except Exception:
        return None

end_date = date.fromisoformat('2026-11-12')
start_90 = end_date - timedelta(days=89)
start_180 = end_date - timedelta(days=179)
start_365 = end_date - timedelta(days=364)

# 1. Out-of-sample validation of District FE scaling
oos_errors = []
trades_prior = defaultdict(list)
trades_recent = defaultdict(list)

for t in all_trades:
    k = get_trade_key(t)
    if not k: continue
    t_day = t.get('day')
    if not t_day: continue
    pr = float(t['price'])
    m = t_day[:7]
    dist = t['district']
    
    fe_map = dist_fe.get(dist) or dist_fe.get('all', {})
    latest_m = max(fe_map.keys()) if fe_map else '2026-08'
    latest_val = fe_map.get(latest_m, 100.0)
    cur_val = fe_map.get(m, latest_val)
    
    if start_365.isoformat() <= t_day < start_90.isoformat():
        adj_pr = pr * (latest_val / cur_val)
        trades_prior[k].append(adj_pr)
    elif start_90.isoformat() <= t_day <= '2026-11-12':
        trades_recent[k].append(pr)

for k, recents in trades_recent.items():
    if k in trades_prior and len(trades_prior[k]) >= 1:
        pred = median(trades_prior[k])
        actual = median(recents)
        ape = abs(pred - actual) / actual
        oos_errors.append(ape)

mape = mean(oos_errors) * 100 if oos_errors else 0
mdape = median(oos_errors) * 100 if oos_errors else 0
print(f"================================================================================")
print(f"OUT-OF-SAMPLE VALIDATION: DISTRICT FIXED EFFECTS SCALING MODEL")
print(f"================================================================================")
print(f"Holdout Stratum count: {len(oos_errors):,}개 검증 표본")
print(f"MAPE: {mape:.2f}% | MdAPE: {mdape:.2f}%")
print(f"Validation threshold (MdAPE <= 5.0%): {'PASS' if mdape <= 5.0 else 'FAIL'}")

# 2. Build Trade Pools for A (90d), B (180d), C (Model)
trades_90 = defaultdict(list)
trades_180 = defaultdict(list)
trades_model = defaultdict(list)

for t in all_trades:
    k = get_trade_key(t)
    if not k: continue
    t_day = t.get('day')
    if not t_day: continue
    pr = float(t['price'])
    m = t_day[:7]
    dist = t['district']
    
    fe_map = dist_fe.get(dist) or dist_fe.get('all', {})
    latest_m = max(fe_map.keys()) if fe_map else '2026-08'
    latest_val = fe_map.get(latest_m, 100.0)
    cur_val = fe_map.get(m, latest_val)
    
    if start_90.isoformat() <= t_day <= '2026-11-12':
        trades_90[k].append((pr, t_day))
    if start_180.isoformat() <= t_day <= '2026-11-12':
        trades_180[k].append((pr, t_day))
    if start_365.isoformat() <= t_day <= '2026-11-12':
        adj_pr = pr * (latest_val / cur_val)
        trades_model[k].append((adj_pr, t_day))

# 3. Load Current Day Listings (2026-11-12)
listings_raw = db.execute("SELECT complex, id, price, payload FROM listings WHERE day='2026-11-12'").fetchall()
asks_by_district = defaultdict(lambda: defaultdict(list))
raw_listings_by_dist = defaultdict(list)
complexes_by_dist = defaultdict(set)

for cid, lid, price, payload_str in listings_raw:
    p = json.loads(payload_str)
    cinfo = crosswalk.get(cid)
    if not cinfo: continue
    dist = cinfo['district']
    complexes_by_dist[dist].add(cid)
    raw_listings_by_dist[dist].append(price)
    
    tc = cinfo.get('tradeComplex')
    if not tc: continue
    
    name = tc[3]
    if '마포래미안푸르지오' in cinfo['name']:
        name = '마포래미안푸르지오'
        
    row = {
        'district': tc[0],
        'dong': tc[1],
        'jibun': tc[2],
        'name': name,
        'exclusive_area_m2': p.get('exclusive_area_m2'),
        'floor': p.get('floor')
    }
    k = get_trade_key(row)
    if k:
        asks_by_district[dist][k].append(price)

# 4. Compute Metrics for each of the 25 Districts
print(f"\n================================================================================")
print(f"25 DISTRICT MULTI-TIER DIVERGENCE EVALUATION (2026-11-12)")
print(f"================================================================================")
print(f"{'구명':<6} | {'단지':<3} | {'호가':<5} | {'A: 90일 실측':<12} | {'B: 180일 장기':<12} | {'C: 모형 추정':<12} | {'최종 상태':<14} | {'원인/비고'}")
print("-" * 105)

results_25 = {}

for dist_code in sorted(all_districts.keys()):
    dist_name = all_districts[dist_code]
    num_comps = len(complexes_by_dist[dist_code])
    num_asks = len(raw_listings_by_dist[dist_code])
    asks = asks_by_district[dist_code]
    
    # A. 90-day strict
    diffs_90 = []
    groups_90 = 0
    matched_asks_90 = 0
    for k, ask_list in asks.items():
        trs = [p for p, _ in trades_90.get(k, [])]
        if len(trs) >= 3:
            diffs_90.append(100 * (median(ask_list) / median(trs) - 1))
            groups_90 += 1
            matched_asks_90 += len(ask_list)
    val_90 = round(median(diffs_90), 2) if diffs_90 else None
    
    # B. 180-day long-term
    diffs_180 = []
    groups_180 = 0
    matched_asks_180 = 0
    benchmark_ages = []
    for k, ask_list in asks.items():
        trs_with_dates = trades_180.get(k, [])
        if len(trs_with_dates) >= 3:
            prs = [p for p, _ in trs_with_dates]
            diffs_180.append(100 * (median(ask_list) / median(prs) - 1))
            groups_180 += 1
            matched_asks_180 += len(ask_list)
            latest_trade_day = max(d for _, d in trs_with_dates)
            age = (end_date - date.fromisoformat(latest_trade_day)).days
            benchmark_ages.append(age)
    val_180 = round(median(diffs_180), 2) if diffs_180 else None
    med_age_180 = round(median(benchmark_ages), 0) if benchmark_ages else None
    
    # C. Model estimation
    diffs_model = []
    groups_model = 0
    for k, ask_list in asks.items():
        trs_m = [p for p, _ in trades_model.get(k, [])]
        if len(trs_m) >= 2: # At least 2 indexed trades in last 12 months
            diffs_model.append(100 * (median(ask_list) / median(trs_m) - 1))
            groups_model += 1
    val_model = round(median(diffs_model), 2) if diffs_model else None

    # Determine status
    if val_90 is not None:
        status = '실측'
        status_code = 'ACTUAL_90D'
        reason = f"90일 표본 {groups_90}개 그룹 정상"
    elif val_180 is not None:
        status = '장기 실측 참고치'
        status_code = 'LONG_TERM_180D'
        reason = f"90일 거래부족 -> 180일 {groups_180}개 그룹(평균 {med_age_180:.0f}일전)"
    elif val_model is not None and mdape <= 5.0:
        status = '모형 추정'
        status_code = 'MODEL_EST'
        reason = f"실거래부족 -> 고정효과 지수 추정 {groups_model}개 그룹"
    else:
        status = '데이터 부족'
        status_code = 'INSUFFICIENT'
        if num_asks == 0:
            reason = "호가 매물 0건"
        elif not asks:
            reason = "단지 매핑 실패 또는 유효 호가 결측"
        else:
            reason = "12개월 내 비교 가능 실거래 절대 부족"
            
    str_90 = f"{val_90:+5.2f}% ({groups_90}G)" if val_90 is not None else "-"
    str_180 = f"{val_180:+5.2f}% ({groups_180}G)" if val_180 is not None else "-"
    str_model = f"{val_model:+5.2f}% ({groups_model}G)" if val_model is not None else "-"
    
    print(f"{dist_name:<6} | {num_comps:<4} | {num_asks:<5} | {str_90:<14} | {str_180:<14} | {str_model:<14} | {status:<16} | {reason}")
    
    results_25[dist_code] = {
        'district': dist_code,
        'district_name': dist_name,
        'complex_count': num_comps,
        'listing_count': num_asks,
        'matched_rate_pct': round(100 * len(asks) / num_asks, 1) if num_asks else 0,
        'actual_90d': {
            'value_pct': val_90,
            'groups': groups_90,
            'matched_listings': matched_asks_90
        },
        'long_term_180d': {
            'value_pct': val_180,
            'groups': groups_180,
            'matched_listings': matched_asks_180,
            'median_benchmark_age_days': med_age_180
        },
        'model_est': {
            'value_pct': val_model,
            'groups': groups_model,
            'validation_mdape': round(mdape, 2)
        },
        'status': status,
        'status_code': status_code,
        'reason': reason
    }

(ROOT / 'data' / 'seoul_25_divergence_audit.json').write_text(json.dumps(results_25, ensure_ascii=False, indent=2), encoding='utf-8')
print("\nSaved comprehensive audit report to data/seoul_25_divergence_audit.json")
