import sys
import sqlite3, json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
tracker_db = sqlite3.connect(ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3')

with open(ROOT / 'data' / 'yangcheon-10-sample.json', encoding='utf-8') as f:
    sample_10 = json.load(f)

# Load 2026 trades for Yangcheon (11470)
print("Loading 2026 Yangcheon trades from tracker.sqlite3...")
trades = []
for row in tracker_db.execute("SELECT payload FROM trades WHERE district='11470' AND month >= '202601'"):
    trades.append(json.loads(row[0]))

print(f"Loaded {len(trades)} trades in Yangcheon for 2026.")

for s in sample_10:
    cid = s['complex']
    dong = s['dong'].strip()
    jibun = s['jibun'].strip()
    name = s['name'].strip()
    
    # Matching trades
    matched_trades = [t for t in trades if t.get('dong') == dong and t.get('jibun') == jibun]
    trade_names = Counter(t.get('name') for t in matched_trades)
    
    # Check if exact name matched
    exact_matched = [t for t in matched_trades if t.get('name') == name]
    
    print(f"\nComplex {cid} (Naver: {s.get('naver_name')}):")
    print(f"  Roster: dong='{dong}', jibun='{jibun}', name='{name}'")
    print(f"  Trades in dong+jibun (2026): {len(matched_trades)}, exact name '{name}' matches: {len(exact_matched)}")
    print(f"  Actual names in trades: {dict(trade_names)}")
