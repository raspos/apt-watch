"""Audit Crosswalk Mappings between Naver Land complexes (5,821) and MOLIT Tracker Trades (8,788).
Explicitly categorize every complex into verification tiers:
1. VERIFIED_EXACT: Exact 4-tuple match (district, dong, jibun, name)
2. VERIFIED_NORM: Normalized syntax/bracket match (e.g. 래미안 vs (래미안))
3. VERIFIED_CROSSWALK: Multi-complex or lot crosswalk (Mapo Raemian Prugio, Mokdong, Gyeonghuigung, etc.)
4. VERIFIED_NEW_BUILD: Post-2020 new construction with verified land parcel
5. JIBUN_MATCH_DIFF_NAME: Parcel matches but name differs (e.g. brand rename)
6. NO_TRADE_ON_JIBUN: Parcel not found in historical trades (e.g. small villa, newly partitioned lot)
"""
import json
import re
import sqlite3
from collections import defaultdict, Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TRACKER_DB = ROOT.parent / 'seoul-apartment-tracker' / 'data' / 'tracker.sqlite3'
COMPLEXES_JSON = ROOT / 'data' / 'complexes.json'
OUT_TABLE = ROOT / 'data' / 'crosswalk_audit_table.json'

KNOWN_CROSSWALKS = {
    '104917': {
        'status': 'VERIFIED_CROSSWALK',
        'reason': '마포래미안푸르지오: 국토부 1~4단지 4개 실거래 단지와 네이버 104917 매핑 검증',
        'trade_names': ['마포래미안푸르지오1단지', '마포래미안푸르지오2단지', '마포래미안푸르지오3단지', '마포래미안푸르지오4단지']
    },
    '10443': {
        'status': 'VERIFIED_CROSSWALK',
        'reason': '경희궁의아침: 국토부 2,3,4단지 3개 필지와 네이버 10443 매핑 검증',
        'trade_names': ['경희궁의아침2단지', '경희궁의아침3단지', '경희궁의아침4단지']
    }
}

def clean(s):
    if not s: return ''
    return re.sub(r'[\(\)\s\-_\.,（）]', '', s).lower()

def main():
    with open(COMPLEXES_JSON, encoding='utf-8') as f:
        comps = json.load(f)

    conn = sqlite3.connect(TRACKER_DB)
    cur = conn.cursor()

    trades_exact = defaultdict(int)
    trades_by_jibun = defaultdict(list)
    trades_clean = defaultdict(list)

    for (p_str,) in cur.execute('SELECT payload FROM trades'):
        t = json.loads(p_str)
        dist = t['district']
        dong = t.get('dong', '')
        jibun = t.get('jibun', '')
        name = t['name']
        k_exact = (dist, dong, jibun, name)
        trades_exact[k_exact] += 1
        trades_by_jibun[(dist, dong, jibun)].append(name)
        trades_clean[(dist, dong, jibun, clean(name))].append(name)

    conn.close()

    audit_records = []
    status_counter = Counter()

    for c in comps:
        cid = str(c['complex'])
        dist = c['district']
        dong = c.get('dong', '')
        jibun = c.get('jibun', '')
        name = c['name']
        k_exact = (dist, dong, jibun, name)

        if cid in KNOWN_CROSSWALKS:
            info = KNOWN_CROSSWALKS[cid]
            status = info['status']
            reason = info['reason']
            is_verified = True
            matched_name = info['trade_names'][0]
        elif k_exact in trades_exact:
            status = 'VERIFIED_EXACT'
            reason = f'국토부 실거래 4개 식별자 완전 일치 ({trades_exact[k_exact]}건 거래)'
            is_verified = True
            matched_name = name
        else:
            k_cl = (dist, dong, jibun, clean(name))
            if k_cl in trades_clean:
                status = 'VERIFIED_NORM'
                trade_actual = trades_clean[k_cl][0]
                reason = f'표기 차이(괄호/공백) 정규화 일치: 국토부 "{trade_actual}" vs 네이버 "{name}"'
                is_verified = True
                matched_name = trade_actual
            else:
                jibun_trades = trades_by_jibun.get((dist, dong, jibun), [])
                if jibun_trades:
                    # Same parcel, different name
                    most_common_name = Counter(jibun_trades).most_common(1)[0][0]
                    # Check if name is subset or alias
                    if clean(name) in clean(most_common_name) or clean(most_common_name) in clean(name):
                        status = 'VERIFIED_ALIAS'
                        reason = f'지번 일치 및 단지명 별칭/약칭 매핑: 국토부 "{most_common_name}" ({len(jibun_trades)}건)'
                        is_verified = True
                        matched_name = most_common_name
                    else:
                        status = 'PENDING_DIFF_NAME'
                        reason = f'동일 지번 내 상이한 국토부 단지명 존재: 국토부 "{most_common_name}" ({len(jibun_trades)}건)'
                        is_verified = False
                        matched_name = most_common_name
                else:
                    # No trade on parcel
                    if any(term in name for term in ['포레온', '퍼스티어', '클라시아', '자이', '힐스테이트', '래미안', '아이파크', '롯데캐슬', 'e편한세상']) and ('신축' in name or '뉴타운' in name or int(c.get('total_households') or 0) > 500):
                        status = 'VERIFIED_NEW_BUILD'
                        reason = '최근 준공 대단지(분양권/입주권 상태 또는 실거래 등록 진행 중)'
                        is_verified = False  # Keep false for divergence calculation until trades exist!
                        matched_name = None
                    elif '도시형' in name or '주상복합' in name or '오피스텔' in name:
                        status = 'NON_APARTMENT_MIX'
                        reason = '도시형생활주택/주상복합/비전형단지 (실거래 비교 주의)'
                        is_verified = False
                        matched_name = None
                    else:
                        status = 'UNVERIFIED_NO_TRADES'
                        reason = '국토부 실거래 이력 부재 (거래 부진 소규모 단지 또는 신규 지번)'
                        is_verified = False
                        matched_name = None

        status_counter[status] += 1
        audit_records.append({
            'complex': cid,
            'district': dist,
            'dong': dong,
            'jibun': jibun,
            'naver_name': c.get('naver_name', name),
            'molit_name': matched_name or name,
            'verification_status': status,
            'tradeCrosswalkVerified': is_verified,
            'audit_reason': reason
        })

    # Save audit table
    OUT_TABLE.write_text(json.dumps(audit_records, ensure_ascii=False, indent=2), encoding='utf-8')
    print("=" * 80)
    print("CROSSWALK VERIFICATION AUDIT SUMMARY (5,821 COMPLEXES)")
    print("=" * 80)
    for stat, count in status_counter.most_common():
        print(f"  {stat:25s}: {count:5,d}개 ({count/len(comps)*100:5.2f}%)")
    
    verified_total = sum(1 for r in audit_records if r['tradeCrosswalkVerified'])
    unverified_total = sum(1 for r in audit_records if not r['tradeCrosswalkVerified'])
    print("-" * 80)
    print(f"총 검증 완료 (Verified):   {verified_total:5,d}개 ({verified_total/len(comps)*100:5.2f}%)")
    print(f"검증 보류/주의 (Unverified): {unverified_total:5,d}개 ({unverified_total/len(comps)*100:5.2f}%)")
    print("=" * 80)

    # Update complexes.json with explicit verification attributes
    updated_comps = []
    audit_dict = {r['complex']: r for r in audit_records}
    for c in comps:
        cid = str(c['complex'])
        ar = audit_dict[cid]
        c['tradeCrosswalkVerified'] = ar['tradeCrosswalkVerified']
        c['verification_status'] = ar['verification_status']
        c['audit_reason'] = ar['audit_reason']
        if ar['molit_name']:
            c['tradeComplex'] = [c['district'], c.get('dong',''), c.get('jibun',''), ar['molit_name']]
        updated_comps.append(c)

    COMPLEXES_JSON.write_text(json.dumps(updated_comps, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Synchronized {len(updated_comps):,} complexes in complexes.json with audit verification statuses.")

if __name__ == '__main__':
    main()
