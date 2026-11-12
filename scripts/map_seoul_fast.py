from playwright.sync_api import sync_playwright
import json
import time
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
roster_path = ROOT / 'data' / 'seoul-trade-roster.json'
roster = json.loads(roster_path.read_text(encoding='utf-8-sig'))

roster_by_district = defaultdict(list)
for r in roster:
    roster_by_district[r['district']].append(r)

print(f"Loaded {len(roster)} trade candidates across {len(roster_by_district)} districts.", flush=True)

DISTRICT_CODES = {
    '11110': ('종로구', '1111000000'),
    '11140': ('중구', '1114000000'),
    '11170': ('용산구', '1117000000'),
    '11200': ('성동구', '1120000000'),
    '11215': ('광진구', '1121500000'),
    '11230': ('동대문구', '1123000000'),
    '11260': ('중랑구', '1126000000'),
    '11290': ('성북구', '1129000000'),
    '11305': ('강북구', '1130500000'),
    '11320': ('도봉구', '1132000000'),
    '11350': ('노원구', '1135000000'),
    '11380': ('은평구', '1138000000'),
    '11410': ('서대문구', '1141000000'),
    '11440': ('마포구', '1144000000'),
    '11470': ('양천구', '1147000000'),
    '11500': ('강서구', '1150000000'),
    '11530': ('구로구', '1153000000'),
    '11545': ('금천구', '1154500000'),
    '11560': ('영등포구', '1156000000'),
    '11590': ('동작구', '1159000000'),
    '11620': ('관악구', '1162000000'),
    '11650': ('서초구', '1165000000'),
    '11680': ('강남구', '1168000000'),
    '11710': ('송파구', '1171000000'),
    '11740': ('강동구', '1174000000')
}

def clean_jibun(j):
    if not j:
        return ""
    j = str(j).strip()
    if '-' in j:
        main_j, sub_j = j.split('-', 1)
        try:
            return f"{int(main_j)}-{int(sub_j)}"
        except ValueError:
            return j
    try:
        return str(int(j))
    except ValueError:
        return j

def clean_name(n):
    return (n.replace(" ", "")
             .replace("아파트", "")
             .replace("차", "")
             .replace("단지", "")
             .replace("·", "")
             .replace(".", "")
             .replace("-", "")
             .lower())

def run():
    all_matched = []
    representative_samples = []
    summary_by_gu = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            channel='chrome',
            headless=True,
            args=['--disable-blink-features=AutomationControlled', '--no-sandbox']
        )
        context = browser.new_context(
            viewport={'width': 1440, 'height': 900},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36'
        )
        page = context.new_page()
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.navigator.chrome = { runtime: {} };
        """)
        page.goto('https://new.land.naver.com/', wait_until='domcontentloaded')
        page.wait_for_timeout(2000)

        for d_code, (d_name, d_cortar) in DISTRICT_CODES.items():
            t0 = time.time()
            # 1. Fetch dongs
            dongs = page.evaluate("""async (cortarNo) => {
                try {
                    const resp = await fetch('/api/regions/list?cortarNo=' + cortarNo);
                    const data = await resp.json();
                    return data.regionList || [];
                } catch(e) {
                    return [];
                }
            }""", d_cortar)

            # 2. Parallel fetch all complexes in all dongs
            district_complexes = page.evaluate("""async (dongs) => {
                const promises = dongs.map(async (d) => {
                    try {
                        const url = '/api/regions/complexes?cortarNo=' + d.cortarNo + '&realEstateType=APT&order=';
                        const resp = await fetch(url, { signal: AbortSignal.timeout(5000) });
                        if (resp.ok) {
                            const data = await resp.json();
                            return (data.complexList || []).map(c => {
                                c.dongName = d.cortarName;
                                c.dongNo = d.cortarNo;
                                return c;
                            });
                        }
                    } catch (e) {}
                    return [];
                });
                const results = await Promise.all(promises);
                return results.flat();
            }""", dongs)

            candidates = roster_by_district[d_code]
            by_dong_jibun = defaultdict(list)
            by_dong_name = defaultdict(list)
            by_dong = defaultdict(list)
            for c in district_complexes:
                c_dong = c.get('dongName', '').strip()
                c_jibun = clean_jibun(c.get('jibunAddress', ''))
                c_name = clean_name(c.get('complexName', ''))
                if c_dong:
                    by_dong[c_dong].append(c)
                if c_dong and c_jibun:
                    by_dong_jibun[(c_dong, c_jibun)].append(c)
                if c_dong and c_name:
                    by_dong_name[(c_dong, c_name)].append(c)

            matched_district = []
            for cand in candidates:
                c_dong = cand['dong'].strip()
                c_jibun = clean_jibun(cand['jibun'])
                c_name = clean_name(cand['name'])

                hit = None
                # Rule 1: exact dong + jibun
                if (c_dong, c_jibun) in by_dong_jibun:
                    pool = by_dong_jibun[(c_dong, c_jibun)]
                    for p in pool:
                        if c_name in clean_name(p['complexName']) or clean_name(p['complexName']) in c_name:
                            hit = p
                            break
                    if not hit and len(pool) == 1:
                        hit = pool[0]

                # Rule 2: exact dong + name
                if not hit and (c_dong, c_name) in by_dong_name:
                    hit = by_dong_name[(c_dong, c_name)][0]

                # Rule 3: fuzzy in same dong
                if not hit:
                    for p in by_dong.get(c_dong, []):
                        p_name = clean_name(p['complexName'])
                        if c_name in p_name or p_name in c_name:
                            hit = p
                            break

                if hit:
                    matched_district.append({
                        'complex': str(hit['complexNo']),
                        'district': d_code,
                        'dong': cand['dong'],
                        'jibun': cand['jibun'],
                        'name': cand['name'],
                        'naver_name': hit['complexName'],
                        'deal_count': hit.get('dealCount', 0),
                        'total_households': hit.get('totalHouseholdCount', 0)
                    })

            all_matched.extend(matched_district)
            pct = (len(matched_district) / max(1, len(candidates))) * 100
            summary_by_gu[d_code] = {
                'name': d_name,
                'candidates': len(candidates),
                'naver_complexes': len(district_complexes),
                'matched': len(matched_district),
                'match_rate': round(pct, 1),
                'elapsed_s': round(time.time() - t0, 2)
            }
            print(f"[{d_name}] Candidates: {len(candidates)}, Naver: {len(district_complexes)}, Matched: {len(matched_district)} ({pct:.1f}%) in {time.time()-t0:.2f}s", flush=True)

            # Pick 1 top representative complex (with largest active deal_count and households >= 300)
            valid_reps = [m for m in matched_district if m.get('deal_count', 0) >= 3 and m.get('total_households', 0) >= 300]
            if not valid_reps:
                valid_reps = [m for m in matched_district if m.get('deal_count', 0) > 0]
            if not valid_reps and matched_district:
                valid_reps = matched_district
            if valid_reps:
                valid_reps.sort(key=lambda x: (x.get('deal_count', 0), x.get('total_households', 0)), reverse=True)
                rep = valid_reps[0]
                representative_samples.append(rep)

        browser.close()

    total_candidates = len(roster)
    total_matched = len(all_matched)
    print("\n================ FINAL SEOUL MAPPING SUMMARY ================", flush=True)
    print(f"Total Candidates: {total_candidates}", flush=True)
    print(f"Total Matched: {total_matched} ({total_matched/total_candidates*100:.1f}%)", flush=True)
    print(f"Representative Complexes Selected: {len(representative_samples)}", flush=True)

    # Deduplicate by complex ID
    unique_matched = {}
    for m in all_matched:
        cid = str(m['complex'])
        if cid not in unique_matched:
            unique_matched[cid] = m

    deduped = list(unique_matched.values())
    print(f"Unique Naver Complexes Mapped: {len(deduped)}", flush=True)

    # 1. Save all mapped matches
    out_all = ROOT / 'data' / 'seoul-mapped-roster.json'
    out_all.write_text(json.dumps(all_matched, ensure_ascii=False, indent=2), encoding='utf-8')

    # 2. Save 25 representative sample complexes (1 per district)
    out_rep = ROOT / 'data' / 'seoul-25-representative.json'
    out_rep.write_text(json.dumps(representative_samples, ensure_ascii=False, indent=2), encoding='utf-8')

    # 3. Save standardized deduped complexes.json
    standard_list = [{
        'complex': str(c['complex']),
        'district': str(c['district']),
        'dong': str(c['dong']),
        'jibun': str(c['jibun']),
        'name': str(c['name']),
        'naver_name': str(c.get('naver_name', c['name']))
    } for c in deduped]
    out_comp = ROOT / 'data' / 'complexes.json'
    out_comp.write_text(json.dumps(standard_list, ensure_ascii=False, indent=2), encoding='utf-8')

    # 4. Save mapping summary by district
    out_sum = ROOT / 'data' / 'seoul-mapping-summary.json'
    out_sum.write_text(json.dumps(summary_by_gu, ensure_ascii=False, indent=2), encoding='utf-8')

    print("All mapping data written successfully!", flush=True)

if __name__ == '__main__':
    run()
