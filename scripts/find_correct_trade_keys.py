import sqlite3, json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tracker_db = sqlite3.connect(ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3')

trades = []
for row in tracker_db.execute("SELECT payload FROM trades WHERE district='11470' AND month >= '202401'"):
    trades.append(json.loads(row[0]))

print(f"Loaded {len(trades)} trades in Yangcheon since 2024.")

complex_searches = [
    ('11708', '신월대성유니드', ['대성유니드']),
    ('661', '목동한신청구', ['한신', '목동청구', '청구']),
    ('3771', '목동우성', ['목동우성', '우성']),
    ('10307', '목동롯데캐슬위너', ['롯데캐슬위너', '위너']),
    ('8742', '목동우성2차', ['목동우성2', '우성2']),
    ('675', '목동현대3차', ['현대3', '목동현대3']),
    ('108438', '신정뉴타운롯데캐슬', ['신정뉴타운', '롯데캐슬']),
    ('672', '신트리1단지', ['신트리1', '신트리']),
    ('117329', '목동센트럴아이파크위브', ['센트럴아이파크', '아이파크위브']),
    ('107728', '목동힐스테이트', ['힐스테이트', '목동힐스테이트'])
]

for cid, naver_name, keywords in complex_searches:
    print(f"\n=== Searching for {naver_name} (ID {cid}) ===")
    matches = []
    for t in trades:
        tname = t.get('name', '')
        if any(k in tname for k in keywords):
            matches.append((t.get('dong'), t.get('jibun'), tname))
    c = Counter(matches)
    for (dong, jibun, name), cnt in c.most_common(5):
        print(f"  -> dong='{dong}', jibun='{jibun}', name='{name}' ({cnt} trades since 2024)")
