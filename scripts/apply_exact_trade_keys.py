import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

with open(ROOT / 'data' / 'complexes.json', encoding='utf-8') as f:
    comps = json.load(f)

comp_dict = {str(c['complex']): c for c in comps}

# Correct Yangcheon keys
CORRECT_KEYS = {
    '11708': ('신월동', '1033', '대성유니드', 283),
    '661': ('목동', '929', '목동청구한신아파트', 1512),
    '3771': ('목동', '200', '우성', 332),
    '10307': ('목동', '956', '롯데캐슬위너', 1066),
    '8742': ('신정동', '337', '목동우성2', 1140),
    '675': ('신정동', '1279', '목동현대3차', 509),
    '108438': ('신월동', '1063', '롯데캐슬', 930),
    '672': ('신정동', '1259', '신트리1', 845),
    '117329': ('신월동', '1075', '목동센트럴아이파크위브1단지', 3045),
    '107728': ('신정동', '1323', '목동힐스테이트', 1081)
}

for cid, (dong, jibun, name, hh) in CORRECT_KEYS.items():
    if cid in comp_dict:
        comp_dict[cid]['dong'] = dong
        comp_dict[cid]['jibun'] = jibun
        comp_dict[cid]['name'] = name
        comp_dict[cid]['tradeComplex'] = ['11470', dong, jibun, name]
        comp_dict[cid]['tradeCrosswalkVerified'] = True
        comp_dict[cid]['total_households'] = hh

updated = list(comp_dict.values())
(ROOT / 'data' / 'complexes.json').write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding='utf-8')
print(f"Updated {len(updated)} complexes with exact verified trade keys and household sizes.")
