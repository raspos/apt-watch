import json, sqlite3

with open('C:/Users/kimwo/OneDrive/문서/New project/apt-watch/data/complexes.json', encoding='utf-8') as f:
    comps = json.load(f)

standardized = []
for c in comps:
    standardized.append({
        'complex': str(c['complex']),
        'district': str(c['district']),
        'dong': str(c.get('dong', '')),
        'jibun': str(c.get('jibun', '')),
        'name': str(c['name']),
        'naver_name': str(c.get('naver_name', c['name']))
    })

with open('C:/Users/kimwo/OneDrive/문서/New project/apt-watch/data/complexes.json', 'w', encoding='utf-8') as f:
    json.dump(standardized, f, ensure_ascii=False, indent=2)

db = sqlite3.connect('C:/Users/kimwo/OneDrive/문서/New project/apt-watch/data/history.sqlite3')
db.execute("DELETE FROM listing_roster WHERE day='2026-11-12'")
db.commit()
print('Standardized complexes.json and reset listing_roster for 2026-11-12')
