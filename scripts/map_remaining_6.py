from playwright.sync_api import sync_playwright
import json, time
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent.parent
roster_path = ROOT / 'data' / 'seoul-trade-roster.json'
roster = json.loads(roster_path.read_text(encoding='utf-8-sig'))
roster_by_district = defaultdict(list)
dongs_by_district = defaultdict(set)
for r in roster:
    roster_by_district[r['district']].append(r)
    dongs_by_district[r['district']].add(r['dong'].strip())

targets = [
    ('11140', '중구', '1114000000'),
    ('11200', '성동구', '1120000000'),
    ('11290', '성북구', '1129000000'),
    ('11440', '마포구', '1144000000'),
    ('11560', '영등포구', '1156000000'),
    ('11740', '강동구', '1174000000')
]

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

    additional_matched = []
    additional_reps = []

    for d_code, d_name, d_cortar in targets:
        t0 = time.time()
        # Fetch all dongs
        all_dongs = page.evaluate("""async (cortarNo) => {
            try {
                const resp = await fetch('/api/regions/list?cortarNo=' + cortarNo);
                const data = await resp.json();
                return data.regionList || [];
            } catch(e) {
                return [];
            }
        }""", d_cortar)

        # Filter dongs to only those in the roster!
        valid_dong_names = list(dongs_by_district[d_code])
        filtered_dongs = [d for d in all_dongs if d.get('cortarName') in valid_dong_names]
        if not filtered_dongs:
            filtered_dongs = all_dongs

        # Fetch complexes for these filtered dongs in parallel with 3s timeout
        complexes = page.evaluate("""async (dongs) => {
            const promises = dongs.map(async (d) => {
                try {
                    const url = '/api/regions/complexes?cortarNo=' + d.cortarNo + '&realEstateType=APT&order=';
                    const resp = await fetch(url, { signal: AbortSignal.timeout(3000) });
                    if (resp.ok) {
                        const data = await resp.json();
                        return (data.complexList || []).map(c => {
                            c.dongName = d.cortarName;
                            c.dongNo = d.cortarNo;
                            return c;
                        });
                    }
                } catch(e) {}
                return [];
            });
            const results = await Promise.all(promises);
            return results.flat();
        }""", filtered_dongs)

        candidates = roster_by_district[d_code]
        by_dong_jibun = defaultdict(list)
        by_dong_name = defaultdict(list)
        by_dong = defaultdict(list)
        for c in complexes:
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
            if (c_dong, c_jibun) in by_dong_jibun:
                pool = by_dong_jibun[(c_dong, c_jibun)]
                for p in pool:
                    if c_name in clean_name(p['complexName']) or clean_name(p['complexName']) in c_name:
                        hit = p
                        break
                if not hit and len(pool) == 1:
                    hit = pool[0]

            if not hit and (c_dong, c_name) in by_dong_name:
                hit = by_dong_name[(c_dong, c_name)][0]

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

        additional_matched.extend(matched_district)
        pct = len(matched_district)/max(1, len(candidates))*100
        print(f"[{d_name}] Candidates: {len(candidates)}, Filtered Dongs: {len(filtered_dongs)}, Naver: {len(complexes)}, Matched: {len(matched_district)} ({pct:.1f}%) in {time.time()-t0:.2f}s", flush=True)

        valid_reps = [m for m in matched_district if m.get('deal_count', 0) >= 3 and m.get('total_households', 0) >= 300]
        if not valid_reps:
            valid_reps = [m for m in matched_district if m.get('deal_count', 0) > 0]
        if not valid_reps and matched_district:
            valid_reps = matched_district
        if valid_reps:
            valid_reps.sort(key=lambda x: (x.get('deal_count', 0), x.get('total_households', 0)), reverse=True)
            rep = valid_reps[0]
            additional_reps.append(rep)
            print(f"  Representative for {d_name}: {rep['name']} (ID {rep['complex']}, deals {rep['deal_count']})", flush=True)

    browser.close()

# Merge with existing
existing_matched = json.loads((ROOT / 'data' / 'seoul-mapped-roster.json').read_text(encoding='utf-8'))
all_matched = existing_matched + additional_matched

existing_reps = json.loads((ROOT / 'data' / 'seoul-25-representative.json').read_text(encoding='utf-8'))
# Filter out any duplicate district in reps
rep_by_gu = {r['district']: r for r in existing_reps}
for r in additional_reps:
    rep_by_gu[r['district']] = r

all_reps = sorted(rep_by_gu.values(), key=lambda x: x['district'])

unique_matched = {}
for m in all_matched:
    cid = str(m['complex'])
    if cid not in unique_matched:
        unique_matched[cid] = m
deduped = list(unique_matched.values())

print("\n================ FINAL COMPLETE 25 DISTRICTS SUMMARY ================", flush=True)
print(f"Total Candidates: {len(roster)}", flush=True)
print(f"Total Matched: {len(all_matched)} ({len(all_matched)/len(roster)*100:.1f}%)", flush=True)
print(f"Unique Naver Complexes Mapped: {len(deduped)}", flush=True)
print(f"Total Representative Complexes: {len(all_reps)} / 25 districts", flush=True)

(ROOT / 'data' / 'seoul-mapped-roster.json').write_text(json.dumps(all_matched, ensure_ascii=False, indent=2), encoding='utf-8')
(ROOT / 'data' / 'seoul-25-representative.json').write_text(json.dumps(all_reps, ensure_ascii=False, indent=2), encoding='utf-8')

standard_list = [{
    'complex': str(c['complex']),
    'district': str(c['district']),
    'dong': str(c['dong']),
    'jibun': str(c['jibun']),
    'name': str(c['name']),
    'naver_name': str(c.get('naver_name', c['name']))
} for c in deduped]
(ROOT / 'data' / 'complexes.json').write_text(json.dumps(standard_list, ensure_ascii=False, indent=2), encoding='utf-8')
print("Successfully merged and updated all files!", flush=True)
