from playwright.sync_api import sync_playwright
import json, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

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
    page.wait_for_timeout(3000)

    # 마포구 (1144000000)
    print("Fetching Mapo-gu dongs...")
    mapo_dongs = page.evaluate("""async () => {
        const resp = await fetch('/api/regions/list?cortarNo=1144000000');
        return await resp.json();
    }""")
    print("Mapo dongs count:", len(mapo_dongs.get('regionList', [])))
    
    # 성북구 (1129000000)
    print("Fetching Seongbuk-gu dongs...")
    sb_dongs = page.evaluate("""async () => {
        const resp = await fetch('/api/regions/list?cortarNo=1129000000');
        return await resp.json();
    }""")
    print("Seongbuk dongs count:", len(sb_dongs.get('regionList', [])))

    # Fetch top complexes in Mapo (아현동, 염리동, 대흥동 등)
    mapo_top_dongs = [d for d in mapo_dongs.get('regionList', []) if d['cortarName'] in ['아현동', '염리동', '대흥동', '공덕동', '상암동']]
    print(f"Querying {len(mapo_top_dongs)} key dongs in Mapo...")
    mapo_comps = page.evaluate("""async (dongs) => {
        const res = [];
        for (const d of dongs) {
            const resp = await fetch('/api/regions/complexes?cortarNo=' + d.cortarNo + '&realEstateType=APT&order=');
            const data = await resp.json();
            for (const c of (data.complexList || [])) {
                c.dongName = d.cortarName;
                res.push(c);
            }
        }
        return res;
    }""", mapo_top_dongs)
    print(f"Got {len(mapo_comps)} complexes in Mapo key dongs.")

    # Fetch top complexes in Seongbuk (길음동, 종암동, 하월곡동 등)
    sb_top_dongs = [d for d in sb_dongs.get('regionList', []) if d['cortarName'] in ['길음동', '종암동', '하월곡동', '돈암동']]
    print(f"Querying {len(sb_top_dongs)} key dongs in Seongbuk...")
    sb_comps = page.evaluate("""async (dongs) => {
        const res = [];
        for (const d of dongs) {
            const resp = await fetch('/api/regions/complexes?cortarNo=' + d.cortarNo + '&realEstateType=APT&order=');
            const data = await resp.json();
            for (const c of (data.complexList || [])) {
                c.dongName = d.cortarName;
                res.push(c);
            }
        }
        return res;
    }""", sb_top_dongs)
    print(f"Got {len(sb_comps)} complexes in Seongbuk key dongs.")

    browser.close()

# Pick representative for Mapo: 마포래미안푸르지오 or similar
mapo_valid = [c for c in mapo_comps if c.get('dealCount', 0) >= 10 and c.get('totalHouseholdCount', 0) >= 500]
mapo_valid.sort(key=lambda x: (x.get('dealCount', 0), x.get('totalHouseholdCount', 0)), reverse=True)
mapo_rep = mapo_valid[0] if mapo_valid else mapo_comps[0]
print(f"Mapo Representative: {mapo_rep['complexName']} (ID: {mapo_rep['complexNo']}, deals: {mapo_rep.get('dealCount')}, households: {mapo_rep.get('totalHouseholdCount')})")

# Pick representative for Seongbuk: 래미안길음센터피스 or 길음뉴타운
sb_valid = [c for c in sb_comps if c.get('dealCount', 0) >= 10 and c.get('totalHouseholdCount', 0) >= 500]
sb_valid.sort(key=lambda x: (x.get('dealCount', 0), x.get('totalHouseholdCount', 0)), reverse=True)
sb_rep = sb_valid[0] if sb_valid else sb_comps[0]
print(f"Seongbuk Representative: {sb_rep['complexName']} (ID: {sb_rep['complexNo']}, deals: {sb_rep.get('dealCount')}, households: {sb_rep.get('totalHouseholdCount')})")

# Add to seoul-25-representative.json
rep_file = ROOT / 'data' / 'seoul-25-representative.json'
reps = json.loads(rep_file.read_text(encoding='utf-8'))
rep_dict = {r['district']: r for r in reps}

rep_dict['11440'] = {
    'complex': str(mapo_rep['complexNo']),
    'district': '11440',
    'dong': mapo_rep['dongName'],
    'jibun': mapo_rep.get('jibunAddress', ''),
    'name': mapo_rep['complexName'],
    'naver_name': mapo_rep['complexName'],
    'deal_count': mapo_rep.get('dealCount', 0),
    'total_households': mapo_rep.get('totalHouseholdCount', 0)
}

rep_dict['11290'] = {
    'complex': str(sb_rep['complexNo']),
    'district': '11290',
    'dong': sb_rep['dongName'],
    'jibun': sb_rep.get('jibunAddress', ''),
    'name': sb_rep['complexName'],
    'naver_name': sb_rep['complexName'],
    'deal_count': sb_rep.get('dealCount', 0),
    'total_households': sb_rep.get('totalHouseholdCount', 0)
}

final_25_reps = sorted(rep_dict.values(), key=lambda x: x['district'])
print(f"\nFinal Representative List: {len(final_25_reps)} / 25 districts!")
rep_file.write_text(json.dumps(final_25_reps, ensure_ascii=False, indent=2), encoding='utf-8')
print("Saved 25 districts representative manifest!")
