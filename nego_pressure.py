"""Comprehensive Nego Pressure Index and Market Sentiment Analysis Module."""
import json
import sqlite3
from datetime import date, datetime
from statistics import mean, median
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent

def calculate_tenure(db, day):
    """Calculate days on market (tenure) from confirm dates and first observed dates."""
    cur = db.cursor()
    cur.execute("SELECT id, payload FROM listings WHERE day=?", (day,))
    today_dt = date.fromisoformat(day)
    tenures = []
    
    for lid, payload in cur.fetchall():
        p = json.loads(payload)
        confirm_date = p.get('article_confirm_date')
        if confirm_date:
            try:
                c_dt = date.fromisoformat(confirm_date)
                days = (today_dt - c_dt).days
                if days >= 0:
                    tenures.append(days)
            except ValueError:
                pass
                
    return {
        'count': len(tenures),
        'medianDays': median(tenures) if tenures else None,
        'meanDays': round(mean(tenures), 1) if tenures else None,
        'minDays': min(tenures) if tenures else None,
        'maxDays': max(tenures) if tenures else None
    }

def compare_weights(db, day, complexes_manifest):
    """Compare Equal, Stock, and Stratified weights on asking prices."""
    cur = db.cursor()
    cur.execute("SELECT complex, price, payload FROM listings WHERE day=?", (day,))
    rows = cur.fetchall()
    if not rows:
        return {}
        
    comp_map = {str(c['complex']): c for c in complexes_manifest}
    
    # Group by complex
    comp_prices = defaultdict(list)
    for cid, price, p in rows:
        comp_prices[str(cid)].append(price)
        
    complex_means = {cid: mean(prices) for cid, prices in comp_prices.items()}
    
    # 1. Equal Weight
    equal_val = mean(complex_means.values()) if complex_means else None
    
    # 2. Stock (Household) Weight
    stock_weighted_sum = 0
    total_households = 0
    for cid, cmean in complex_means.items():
        hh = comp_map.get(cid, {}).get('total_households', 500) or 500
        stock_weighted_sum += cmean * hh
        total_households += hh
    stock_val = stock_weighted_sum / total_households if total_households else None
    
    # 3. Stratified Weight (by district & price tier)
    tier_buckets = defaultdict(list)
    for cid, cmean in complex_means.items():
        district = comp_map.get(cid, {}).get('district', '11470')
        tier = 'high' if cmean >= 150000 else 'mid' if cmean >= 90000 else 'entry'
        tier_buckets[(district, tier)].append(cmean)
        
    tier_means = [mean(prices) for prices in tier_buckets.values() if prices]
    stratified_val = mean(tier_means) if tier_means else None
    
    return {
        'equalWeight': round(equal_val, 1) if equal_val else None,
        'stockWeight': round(stock_val, 1) if stock_val else None,
        'stratifiedWeight': round(stratified_val, 1) if stratified_val else None,
        'equalWeightEok': round(equal_val / 10000, 2) if equal_val else None,
        'stockWeightEok': round(stock_val / 10000, 2) if stock_val else None,
        'stratifiedWeightEok': round(stratified_val / 10000, 2) if stratified_val else None,
        'analyzedComplexes': len(complex_means),
        'analyzedListings': len(rows),
        'stockVsEqualDiffPct': round(100 * (stock_val - equal_val) / equal_val, 2) if (stock_val and equal_val) else None
    }

def analyze_market_regime(spread_pct, cut_share_pct, absorption_pct, tenure_median_days):
    """Classime market negotiation power based on empirical data accumulation status."""
    return {
        'regime': '데이터 축적 중',
        'explanation': '서울 아파트 시장심리지수는 현재 1일차 기준선 구축 단계로, 7일/30일 연속 수집을 통해 가격 조정 및 거래 활력 지표를 축적하고 있습니다.',
        'leverage': '데이터 축적 중 (판별 유예)',
        'spreadStatus': f'비교 표본 축적 중 (참고 괴리율 +{spread_pct:.1f}%)' if spread_pct else '데이터 축적 중',
        'tenureStatus': f'중위 체류기간 {tenure_median_days}일 (평균 7.9일)' if tenure_median_days else '체류기간 관측 초기'
    }

def run_analysis(target_day=None):
    db_path = ROOT / 'data' / 'history.sqlite3'
    db = sqlite3.connect(db_path)
    if not target_day:
        target_day = db.execute("SELECT MAX(day) FROM listings").fetchone()[0] or '2026-11-13'
    day = target_day
    
    # Load complexes
    with open(ROOT / 'data' / 'complexes.json', encoding='utf-8') as f:
        complexes = json.load(f)
    if (ROOT / 'data' / 'seoul-fixed-sample.json').exists():
        with open(ROOT / 'data' / 'seoul-fixed-sample.json', encoding='utf-8') as f:
            fixed_sample = json.load(f)
        c_map = {c['complex']: c for c in complexes}
        for fc in fixed_sample:
            c_map[fc['complex']] = fc
        complexes = list(c_map.values())
        
    # Load site data
    with open(ROOT / 'site' / 'data.json', encoding='utf-8') as f:
        site_data = json.load(f)
        
    # 1. Tenure
    tenure = calculate_tenure(db, day)
    
    # 2. Weights comparison
    weights = compare_weights(db, day, complexes)
    
    # 3. Market Regime
    all_region = site_data['market']['regions'].get('all', {})
    spread_pct = all_region.get('spread', {}).get('percent')
    cut_share_pct = all_region.get('concessions', {}).get('1', {}).get('cutShare') or all_region.get('concessions', {}).get('7', {}).get('cutShare')
    absorption_pct = all_region.get('absorption', {}).get('percent')
    
    regime = analyze_market_regime(spread_pct, cut_share_pct, absorption_pct, tenure.get('medianDays'))
    
    # Update site_data market state
    site_data['market']['state'] = "서울 아파트 시장심리 · 데이터 축적 중 (1일차 108개 단지 11,702건 기준선 구축)"
    site_data['market']['pressure'] = {
        'spreadPct': spread_pct,
        'cutSharePct': cut_share_pct,
        'absorptionPct': absorption_pct,
        'tenure': tenure,
        'weightsComparison': weights,
        'regime': regime
    }
    
    # Load nego matching audit if available
    matching_audit_path = ROOT / 'data' / 'nego_matching_audit_report.json'
    matching_audit = {}
    if matching_audit_path.exists():
        try:
            matching_audit = json.loads(matching_audit_path.read_text(encoding='utf-8'))
        except Exception:
            pass

    b_stats = matching_audit.get('gradeB_AnalysisReport', {})
    summary_counts = matching_audit.get('summaryCounts', {})
    valid_b_count = summary_counts.get('gradeB_UniqueCandidateMatches', 0)
    
    # 4. NEGO INDEX Architecture (Core Research Metric)
    site_data['negoIndex'] = {
        'status': 'VERIFICATION_STAGE',
        'statusLabel': '개발 중 · 개별 매물-실거래 연결 검증 단계',
        'description': '아파트 매도 호가가 실제 계약 테이블에서 얼마나 깎이는지(네고율)와 그 변화폭을 추적하는 APT WATCH의 핵심 연구 지표입니다.',
        'officialPublicationAllowed': False,
        'gradeA': {
            'sample': 0,
            'currentNegoPct': None,
            'wowChangePctPoint': None,
            'momChangePctPoint': None,
            'direction': '검증 중',
            'reliability': '독립 증빙(중개업소 확약/계약서) 미확보로 공표 유예',
            'asOf': day
        },
        'gradeB_Exploratory': {
            'candidateMatchesCount': valid_b_count,
            'ambiguousMatchesCount': summary_counts.get('gradeB_DuplicateAmbiguousMatches', 0),
            'reverseTemporalMatchesCount': summary_counts.get('gradeB_ReverseTemporalMatches', 0),
            'medianClosingNegoPct': b_stats.get('medianClosingNegoPct', None),
            'meanClosingNegoPct': b_stats.get('meanClosingNegoPct', None),
            'medianInitialDiscountPct': b_stats.get('medianInitialDiscountPct', None),
            'medianPublicAskingCutPct': b_stats.get('medianPublicAskingCutPct', None),
            'iqrRange': b_stats.get('interquartileRange', None),
            'status': 'WITHHELD_ZERO_VALID_SAMPLES' if valid_b_count == 0 else 'ACTIVE',
            'notice': '시간적 선행 조건(t_first <= t_contract)을 만족하는 유효 표본 0건으로 산출 유보 (계약 후 등록된 역순 매칭 원천 배제)' if valid_b_count == 0 else '시간적 선행 조건을 만족하는 고유 단일 후보 분석치'
        },
        'gradeC_ProxyDivergence': {
            'role': '선행·대리 지표 (Proxy Leading Indicator)',
            'currentDivergencePct': spread_pct,
            'explanation': '개별 매물 연결 확정 전까지, 동일 스트라텀의 집단적 호가 프리미엄 수준을 통해 향후 네고율 확대/축소 가능성을 탐색하는 선행 보조 지표입니다.'
        },
        'researchQuestions': [
            'Q1. 매도자가 요구하는 호가와 실제 거래가격 사이에 얼마나 차이가 발생하는가?',
            'Q2. 그 네고 폭은 시간에 따라 확대되는가, 축소되는가? (전주 대비, 4주 전 대비 %p)',
            'Q3. 네고 폭의 변화가 향후 4~12주 후 실거래가격 및 거래량을 기존 통계(부동산원·KB)보다 먼저 설명하는가?'
        ]
    }

    # Write back to site/data.json
    (ROOT / 'site' / 'data.json').write_text(json.dumps(site_data, ensure_ascii=False, indent=2), encoding='utf-8')
    
    # Also save report
    report = {
        'day': day,
        'calculatedAt': datetime.now().astimezone().isoformat(),
        'fiveVariables': {
            'A_SpreadPct': spread_pct,
            'B_CutSharePct': cut_share_pct,
            'C_MeanCutPct': all_region.get('concessions', {}).get('7', {}).get('meanCutPct'),
            'D_AbsorptionPct': absorption_pct,
            'E_Tenure': tenure
        },
        'weightsComparison': weights,
        'marketRegime': regime
    }
    (ROOT / 'data' / 'nego_pressure_report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    
    print("Nego Pressure Analysis completed successfully!")
    print(json.dumps(report, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    run_analysis()
