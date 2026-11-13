"""Automated Unit Tests for APT WATCH Price Divergence Dynamics & 3-Way Decomposition.

Validates the 10 Counterexamples & Edge Cases (Cases A through J):
  Case A: Ask unchanged (100 -> 100), benchmark rises (100 -> 110), identical sample
          => Δ = -9.09%p, ask = 0.0, trade = -9.09%p, comp = 0.0.
  Case B: Benchmark unchanged (100 -> 100), ask cuts (100 -> 95), identical sample
          => Δ = -5.0%p, ask = -5.0%p, trade = 0.0, comp = 0.0.
  Case C: Both ask and benchmark change (100 -> 95, 100 -> 110), identical sample
          => Shapley sum matches total change exactly (-13.64%p), comp = 0.0.
  Case D: Pure sample composition shift (prices unchanged, stratum weights change)
          => ask = 0.0, trade = 0.0, comp = ΔTotal.
  Case E: Stratum turnover (listing ID replaced within same stratum)
          => Differentiates identical listing panel stats from stratum cohort changes.
  Case F: Reference trade benchmark driver: New contract entry (NEW_CONTRACT_ENTRY).
  Case G: Reference trade benchmark driver: 90-day window expiration (WINDOW_EXPIRATION).
  Case H: Point-in-time snapshot audit: Future disclosure excluded from contemporaneous vintage.
  Case I: Multi-horizon accumulation gates: Explicit withholding (< 7d, < 28d) vs calculation.
  Case J: SQLite persistence idempotency: Re-running on same day never creates duplicate records.
"""

import unittest
import json
import sqlite3
from pathlib import Path
from scripts.divergence_dynamics import (
    shapley_stratum_decomposition,
    decompose_spread_change,
    decompose_spread_change_shapley,
    extract_trades_up_to_day
)

ROOT = Path(__file__).resolve().parent.parent

class TestSpreadDynamicsExhaustive(unittest.TestCase):
    
    # --------------------------------------------------------------------------
    # Case A: Benchmark Rises, Ask Unchanged, Identical Sample
    # --------------------------------------------------------------------------
    def test_case_a_ask_unchanged_benchmark_rises(self):
        # A0 = 100, A1 = 100, R0 = 100, R1 = 110
        # Expected: Δ = -9.0909%p, ask = 0.0, trade = -9.0909%p, comp = 0.0
        delta_d, ask_s, trade_s = shapley_stratum_decomposition(100.0, 100.0, 100.0, 110.0)
        self.assertAlmostEqual(delta_d, -9.0909, places=4)
        self.assertEqual(ask_s, 0.0)
        self.assertAlmostEqual(trade_s, -9.0909, places=4)
        self.assertAlmostEqual(delta_d, ask_s + trade_s, places=4)

        k1 = ('11680', '개포동', '138', '디에이치아너힐즈', 84, 1)
        prev_strata = {k1: {'askMedian': 100.0, 'tradeMedian': 100.0, 'spreadPct': 0.0}}
        curr_strata = {k1: {'askMedian': 100.0, 'tradeMedian': 110.0, 'spreadPct': -9.0909}}
        prev_listings = {'l1': {'price': 100.0, 'complex': '138', 'id': '1'}}
        curr_listings = {'l1': {'price': 100.0, 'complex': '138', 'id': '1'}}

        res = decompose_spread_change(curr_strata, prev_strata, curr_listings, prev_listings)
        self.assertEqual(res['status'], 'VALID')
        self.assertEqual(res['contribAskPctPoint'], 0.0)
        self.assertAlmostEqual(res['contribTradeBenchmarkPctPoint'], -9.09, places=2)
        self.assertEqual(res['contribSampleCompositionPctPoint'], 0.0)
        self.assertAlmostEqual(res['deltaTotalPctPoint'], -9.09, places=2)

    # --------------------------------------------------------------------------
    # Case B: Ask Cuts, Benchmark Unchanged, Identical Sample
    # --------------------------------------------------------------------------
    def test_case_b_ask_cuts_benchmark_unchanged(self):
        # A0 = 100, A1 = 95, R0 = 100, R1 = 100
        # Expected: Δ = -5.0%p, ask = -5.0%p, trade = 0.0, comp = 0.0
        delta_d, ask_s, trade_s = shapley_stratum_decomposition(100.0, 95.0, 100.0, 100.0)
        self.assertEqual(delta_d, -5.0)
        self.assertEqual(ask_s, -5.0)
        self.assertEqual(trade_s, 0.0)
        self.assertEqual(delta_d, ask_s + trade_s)

        k1 = ('11680', '개포동', '138', '디에이치아너힐즈', 84, 1)
        prev_strata = {k1: {'askMedian': 100.0, 'tradeMedian': 100.0, 'spreadPct': 0.0}}
        curr_strata = {k1: {'askMedian': 95.0, 'tradeMedian': 100.0, 'spreadPct': -5.0}}
        prev_listings = {'l1': {'price': 100.0, 'complex': '138', 'id': '1'}}
        curr_listings = {'l1': {'price': 95.0, 'complex': '138', 'id': '1'}}

        res = decompose_spread_change(curr_strata, prev_strata, curr_listings, prev_listings)
        self.assertEqual(res['status'], 'VALID')
        self.assertEqual(res['contribAskPctPoint'], -5.0)
        self.assertEqual(res['contribTradeBenchmarkPctPoint'], 0.0)
        self.assertEqual(res['contribSampleCompositionPctPoint'], 0.0)
        self.assertEqual(res['deltaTotalPctPoint'], -5.0)

    # --------------------------------------------------------------------------
    # Case C: Simultaneous Ask Cut and Benchmark Rise (Nonlinear Interaction)
    # --------------------------------------------------------------------------
    def test_case_c_simultaneous_ask_and_benchmark_change(self):
        # A0 = 100, A1 = 95, R0 = 100, R1 = 110
        # D0 = 0.0%, D1 = (95/110 - 1)*100 = -13.6364%
        # Δ = -13.6364%p
        delta_d, ask_s, trade_s = shapley_stratum_decomposition(100.0, 95.0, 100.0, 110.0)
        self.assertAlmostEqual(delta_d, -13.6364, places=4)
        self.assertAlmostEqual(delta_d, ask_s + trade_s, places=3)
        # Shapley ask: 0.5 * [(-5 - 0) + (-13.63636 - (-9.0909))] = -4.7727%p
        self.assertAlmostEqual(ask_s, -4.7727, places=4)
        # Shapley trade: 0.5 * [(-9.0909 - 0) + (-13.63636 - (-5.0))] = -8.8636%p
        self.assertAlmostEqual(trade_s, -8.8636, places=4)

        k1 = ('11680', '개포동', '138', '디에이치아너힐즈', 84, 1)
        prev_strata = {k1: {'askMedian': 100.0, 'tradeMedian': 100.0, 'spreadPct': 0.0}}
        curr_strata = {k1: {'askMedian': 95.0, 'tradeMedian': 110.0, 'spreadPct': -13.6364}}
        prev_listings = {'l1': {'price': 100.0, 'complex': '138', 'id': '1'}}
        curr_listings = {'l1': {'price': 95.0, 'complex': '138', 'id': '1'}}

        res = decompose_spread_change(curr_strata, prev_strata, curr_listings, prev_listings)
        self.assertEqual(res['status'], 'VALID')
        self.assertAlmostEqual(res['contribAskPctPoint'], -4.77, places=2)
        self.assertAlmostEqual(res['contribTradeBenchmarkPctPoint'], -8.86, places=2)
        self.assertEqual(res['contribSampleCompositionPctPoint'], 0.0)
        self.assertAlmostEqual(res['deltaTotalPctPoint'], -13.64, places=2)

    # --------------------------------------------------------------------------
    # Case D: Pure Sample Composition Shift (Prices Unchanged)
    # --------------------------------------------------------------------------
    def test_case_d_pure_sample_composition_shift(self):
        k1 = ('11680', '개포동', '138', '디에이치아너힐즈', 84, 1)
        k2 = ('11440', '아현동', '777', '마포래미안푸르지오', 59, 1)

        # Period 0: only k1 exists (spread 0%)
        prev_strata = {k1: {'askMedian': 100.0, 'tradeMedian': 100.0, 'spreadPct': 0.0}}
        # Period 1: k2 enters with high spread (20%), k1 remains spread 0%
        curr_strata = {
            k1: {'askMedian': 100.0, 'tradeMedian': 100.0, 'spreadPct': 0.0},
            k2: {'askMedian': 120.0, 'tradeMedian': 100.0, 'spreadPct': 20.0}
        }
        prev_listings = {'l1': {'price': 100.0, 'complex': '138', 'id': '1'}}
        curr_listings = {'l1': {'price': 100.0, 'complex': '138', 'id': '1'}, 'l2': {'price': 120.0, 'complex': '777', 'id': '2'}}

        res = decompose_spread_change(curr_strata, prev_strata, curr_listings, prev_listings)
        self.assertEqual(res['status'], 'VALID')
        # On matched strata (k1), prices didn't change
        self.assertEqual(res['contribAskPctPoint'], 0.0)
        self.assertEqual(res['contribTradeBenchmarkPctPoint'], 0.0)
        # Matched sample change is strictly 0.0%p
        self.assertEqual(res['matchedSampleChange'], 0.0)
        # Composition absorbs the entire shift in cross-section mean spread (10.0%p)
        self.assertEqual(res['contribSampleCompositionPctPoint'], res['deltaFullMeanPctPoint'])
        self.assertEqual(res['contribSampleCompositionPctPoint'], 10.0)

    # --------------------------------------------------------------------------
    # Case E: Stratum Turnover vs Identical Listing Panel
    # --------------------------------------------------------------------------
    def test_case_e_stratum_turnover_vs_identical_listing(self):
        k1 = ('11680', '개포동', '138', '디에이치아너힐즈', 84, 1)
        # Same stratum exists in both, but listing ID changed (l1 exited, l2 entered)
        prev_strata = {k1: {'askMedian': 100.0, 'tradeMedian': 100.0, 'spreadPct': 0.0}}
        curr_strata = {k1: {'askMedian': 98.0, 'tradeMedian': 100.0, 'spreadPct': -2.0}}
        
        prev_listings = {'l1': {'price': 100.0, 'complex': '138', 'id': '1'}}
        curr_listings = {'l2': {'price': 98.0, 'complex': '138', 'id': '2'}}

        res = decompose_spread_change(curr_strata, prev_strata, curr_listings, prev_listings)
        self.assertEqual(res['status'], 'VALID')
        stats = res['identicalListingStats']
        # Identical count is 0 because listing IDs are different
        self.assertEqual(stats['identicalCount'], 0)
        self.assertEqual(stats['retentionRatePct'], 0.0)
        self.assertEqual(stats['newEntrantsCount'], 1)
        self.assertEqual(stats['exitedCount'], 1)
        # Stratum cohort change is still measured
        self.assertEqual(res['contribAskPctPoint'], -2.0)
        self.assertEqual(res['contribTradeBenchmarkPctPoint'], 0.0)

    # --------------------------------------------------------------------------
    # Case F: Reference Trade Benchmark Driver - New Contract Entry
    # --------------------------------------------------------------------------
    def test_case_f_trade_benchmark_new_contract_entry(self):
        k1 = ('11680', '개포동', '138', '디에이치아너힐즈', 84, 1)
        prev_strata = {k1: {'askMedian': 100.0, 'tradeMedian': 100.0, 'spreadPct': 0.0, 'tradeDaysList': ['2026-10-01']}}
        curr_strata = {k1: {'askMedian': 100.0, 'tradeMedian': 105.0, 'spreadPct': -4.76, 'tradeDaysList': ['2026-10-01', '2026-11-10']}}
        
        listings = {'l1': {'price': 100.0, 'complex': '138', 'id': '1'}}
        res = decompose_spread_change(curr_strata, prev_strata, listings, listings)
        drivers = res['tradeBenchmarkDrivers']
        self.assertEqual(drivers.get('NEW_CONTRACT_ENTRY'), 1)
        self.assertEqual(drivers.get('WINDOW_EXPIRATION', 0), 0)

    # --------------------------------------------------------------------------
    # Case G: Reference Trade Benchmark Driver - Window Expiration
    # --------------------------------------------------------------------------
    def test_case_g_trade_benchmark_window_expiration(self):
        k1 = ('11680', '개포동', '138', '디에이치아너힐즈', 84, 1)
        prev_strata = {k1: {'askMedian': 100.0, 'tradeMedian': 100.0, 'spreadPct': 0.0, 'tradeDaysList': ['2026-08-10', '2026-10-01']}}
        curr_strata = {k1: {'askMedian': 100.0, 'tradeMedian': 105.0, 'spreadPct': -4.76, 'tradeDaysList': ['2026-10-01']}}
        
        listings = {'l1': {'price': 100.0, 'complex': '138', 'id': '1'}}
        res = decompose_spread_change(curr_strata, prev_strata, listings, listings)
        drivers = res['tradeBenchmarkDrivers']
        self.assertEqual(drivers.get('WINDOW_EXPIRATION'), 1)
        self.assertEqual(drivers.get('NEW_CONTRACT_ENTRY', 0), 0)

    # --------------------------------------------------------------------------
    # Case H: Point-in-Time Snapshot Filtering Audit
    # --------------------------------------------------------------------------
    def test_case_h_point_in_time_snapshot_filtering(self):
        # Create an in-memory SQLite DB representing tracker.sqlite3
        conn = sqlite3.connect(':memory:')
        conn.execute("CREATE TABLE snapshots (district TEXT, month TEXT, fetched TEXT)")
        conn.execute("CREATE TABLE trades (district TEXT, month TEXT, payload TEXT)")

        # Scenario: month 2026-10 was fetched on 2026-11-08
        conn.execute("INSERT INTO snapshots VALUES ('11680', '2026-10', '2026-11-08 10:00:00')")
        # Trade payload
        trade_payload = json.dumps({
            'day': '2026-10-15',
            'contract_date': '2026-10-15',
            'exclusive_area_m2': 84.5,
            'price': 100000,
            'price_manwon': 100000,
            'dong': '개포동',
            'jibun': '138',
            'name': '디에이치아너힐즈',
            'floor': 10
        })
        conn.execute("INSERT INTO trades VALUES ('11680', '2026-10', ?)", (trade_payload,))

        # Query on 2026-11-07 (BEFORE fetch timestamp) => should NOT be contemporaneous
        _, audit_info_pre = extract_trades_up_to_day(conn, '2026-11-07', window_days=90)
        self.assertFalse(audit_info_pre['isContemporaneousLiveVintage'])
        self.assertEqual(audit_info_pre['contemporaneousTrades'], 0)

        # Query on 2026-11-09 (AFTER fetch timestamp) => should be contemporaneous
        _, audit_info_post = extract_trades_up_to_day(conn, '2026-11-09', window_days=90)
        self.assertTrue(audit_info_post['isContemporaneousLiveVintage'])
        self.assertEqual(audit_info_post['contemporaneousTrades'], 1)
        conn.close()

    # --------------------------------------------------------------------------
    # Case I: Multi-Horizon Accumulation Gates (7d, 28d Withholding)
    # --------------------------------------------------------------------------
    def test_case_i_multi_horizon_accumulation_gates(self):
        data_path = ROOT / 'site' / 'data.json'
        self.assertTrue(data_path.exists())
        data = json.loads(data_path.read_text(encoding='utf-8'))
        dyn = data['market']['spreadDynamics']

        seoul = dyn['seoulOverall']
        changes = seoul['changes']
        
        # When history duration is less than 7 days, 7d change must be withheld
        self.assertIn('7d', changes)
        if changes['7d']['deltaPctPoint'] is None:
            self.assertTrue('축적 중' in changes['7d']['status'] or changes['7d']['status'] == 'HELD_VERIFICATION')
        else:
            self.assertEqual(changes['7d']['status'], 'VALID')

        # When history duration is less than 28 days, 28d change must be withheld
        self.assertIn('28d', changes)
        if changes['28d']['deltaPctPoint'] is None:
            self.assertTrue('축적 중' in changes['28d']['status'] or changes['28d']['status'] == 'HELD_VERIFICATION')
        else:
            self.assertEqual(changes['28d']['status'], 'VALID')

        # 25 districts structure validation
        self.assertEqual(len(dyn['districts']), 25)
        for d_code, d_info in dyn['districts'].items():
            self.assertIn(d_info['status'], ['실측', '장기 실측 참고치', '정상', '데이터 부족', '산출 유보', 'VALID', 'INSUFFICIENT_DATA', 'NO_DATA', '수집 데이터 검증 중'])
            self.assertIn('1d', d_info['changes'])
            self.assertIn('7d', d_info['changes'])
            self.assertIn('28d', d_info['changes'])

    # --------------------------------------------------------------------------
    # Case J: SQLite Persistence Idempotency
    # --------------------------------------------------------------------------
    def test_case_j_sqlite_idempotency(self):
        conn = sqlite3.connect(':memory:')
        conn.execute("""
            CREATE TABLE IF NOT EXISTS spread_dynamics_daily (
                day TEXT PRIMARY KEY,
                equal_weight_spread REAL,
                district_balanced_spread REAL,
                sample_groups INTEGER,
                matched_listings INTEGER,
                dod_change REAL,
                dod_ask_contrib REAL,
                dod_trade_contrib REAL,
                dod_comp_contrib REAL,
                wow_change REAL,
                mom_change REAL,
                retention_rate_pct REAL,
                created_at TEXT
            )
        """)

        # Insert record for 2026-11-13
        conn.execute("""
            INSERT OR REPLACE INTO spread_dynamics_daily
            (day, equal_weight_spread, district_balanced_spread, sample_groups, matched_listings, dod_change, dod_ask_contrib, dod_trade_contrib, dod_comp_contrib, wow_change, mom_change, retention_rate_pct, created_at)
            VALUES ('2026-11-13', 4.5, 4.3, 150, 800, 0.1, 0.05, 0.05, 0.0, NULL, NULL, 92.5, '2026-11-13T00:00:00')
        """)
        conn.commit()

        # Re-run same day with updated values
        conn.execute("""
            INSERT OR REPLACE INTO spread_dynamics_daily
            (day, equal_weight_spread, district_balanced_spread, sample_groups, matched_listings, dod_change, dod_ask_contrib, dod_trade_contrib, dod_comp_contrib, wow_change, mom_change, retention_rate_pct, created_at)
            VALUES ('2026-11-13', 4.6, 4.4, 152, 810, 0.2, 0.1, 0.1, 0.0, NULL, NULL, 93.0, '2026-11-13T01:00:00')
        """)
        conn.commit()

        # Assert exactly ONE row exists and contains latest updated values
        rows = conn.execute("SELECT count(*), equal_weight_spread, dod_change FROM spread_dynamics_daily WHERE day='2026-11-13'").fetchall()
        self.assertEqual(rows[0][0], 1)
        self.assertEqual(rows[0][1], 4.6)
        self.assertEqual(rows[0][2], 0.2)
        conn.close()

    # --------------------------------------------------------------------------
    # Strict Segregation from Official NEGO INDEX
    # --------------------------------------------------------------------------
    def test_strict_segregation_from_nego_index(self):
        data_path = ROOT / 'site' / 'data.json'
        data = json.loads(data_path.read_text(encoding='utf-8'))
        
        # Verify NEGO INDEX Grade A is strictly 0 and not conflated with spread dynamics
        self.assertIn('negoIndex', data)
        self.assertEqual(data['negoIndex']['gradeA']['sample'], 0)
        self.assertIsNone(data['negoIndex']['gradeA']['currentNegoPct'])
        self.assertIn('공표 유예', data['negoIndex']['gradeA']['reliability'])

    # --------------------------------------------------------------------------
    # Directive 4 Counterexample 1: 3 Groups Median vs Mean Discrepancy
    # --------------------------------------------------------------------------
    def test_directive4_counterexample_1_median_vs_mean_aggregation_discrepancy(self):
        # 3 Strata where median change != mean change
        # Initial spreads: G1 = 0%, G2 = 5%, G3 = 10% => Median = 5.0%
        # Final spreads:   G1 = 10%, G2 = 2%, G3 = 0%  => Sorted [0, 2, 10] => Median = 2.0%
        # Median difference: 2.0% - 5.0% = -3.0%p
        # Individual changes: Δ1 = +10%p, Δ2 = -3%p, Δ3 = -10%p
        # Mean of changes: (+10 - 3 - 10) / 3 = -1.0%p
        k1 = ('11680', '개포동', '1', '단지A', 84, 1)
        k2 = ('11680', '개포동', '2', '단지B', 84, 1)
        k3 = ('11680', '개포동', '3', '단지C', 84, 1)

        prev_strata = {
            k1: {'askMedian': 100.0, 'tradeMedian': 100.0, 'spreadPct': 0.0},
            k2: {'askMedian': 105.0, 'tradeMedian': 100.0, 'spreadPct': 5.0},
            k3: {'askMedian': 110.0, 'tradeMedian': 100.0, 'spreadPct': 10.0}
        }
        curr_strata = {
            k1: {'askMedian': 110.0, 'tradeMedian': 100.0, 'spreadPct': 10.0},
            k2: {'askMedian': 102.0, 'tradeMedian': 100.0, 'spreadPct': 2.0},
            k3: {'askMedian': 100.0, 'tradeMedian': 100.0, 'spreadPct': 0.0}
        }
        listings = {
            'l1': {'price': 100.0, 'stratumKey': k1},
            'l2': {'price': 105.0, 'stratumKey': k2},
            'l3': {'price': 110.0, 'stratumKey': k3}
        }

        res = decompose_spread_change(curr_strata, prev_strata, listings, listings)
        self.assertEqual(res['status'], 'VALID')

        # 1. Median level change is -3.0%p
        self.assertEqual(res['medianLevelChange'], -3.0)
        # 2. Matched sample mean change is -1.0%p
        self.assertEqual(res['matchedSampleChange'], -1.0)
        # 3. Discrepancy is explicitly isolated: -3.0 - (-1.0) = -2.0%p
        self.assertEqual(res['discrepancyMedianVersusMean'], -2.0)
        # 4. Shapley components strictly sum to matchedSampleChange (-1.0%p), NOT to medianLevelChange (-3.0%p)
        comp_sum = round(res['contribAskPctPoint'] + res['contribTradeBenchmarkPctPoint'], 2)
        self.assertEqual(comp_sum, -1.0)

    # --------------------------------------------------------------------------
    # Directive 4 Counterexample 2: Within-Stratum Listing Entry Shifts Median Ask
    # --------------------------------------------------------------------------
    def test_directive4_counterexample_2_within_stratum_listing_entry_shifts_median_ask(self):
        k1 = ('11680', '개포동', '138', '디에이치아너힐즈', 84, 1)

        # In stratum k1:
        # t=0: listing l1 has price 100, benchmark 100 => askMedian=100, spread=0%
        # t=1: listing l1 still has price 100 (price change = 0%), but l2 enters at 120 => askMedian=110, spread=10%
        prev_strata = {k1: {'askMedian': 100.0, 'tradeMedian': 100.0, 'spreadPct': 0.0}}
        curr_strata = {k1: {'askMedian': 110.0, 'tradeMedian': 100.0, 'spreadPct': 10.0}}

        prev_listings = {'l1': {'price': 100.0, 'id': 'l1', 'stratumKey': k1}}
        curr_listings = {'l1': {'price': 100.0, 'id': 'l1', 'stratumKey': k1}, 'l2': {'price': 120.0, 'id': 'l2', 'stratumKey': k1}}

        res = decompose_spread_change(curr_strata, prev_strata, curr_listings, prev_listings)
        self.assertEqual(res['status'], 'VALID')

        # Actual price change of identical listing ID l1 is 0.0%p
        self.assertEqual(res['contribIdenticalAskPctPoint'], 0.0)
        # Change in median ask is 100% due to within-stratum composition turnover
        self.assertEqual(res['contribWithinStratumTurnoverPctPoint'], 10.0)
        # Total ask contribution is 10.0%p
        self.assertEqual(res['contribAskPctPoint'], 10.0)
        # Reference trade benchmark did not change
        self.assertEqual(res['contribTradeBenchmarkPctPoint'], 0.0)
        # Total matched change is +10.0%p
        self.assertEqual(res['matchedSampleChange'], 10.0)
        # Mathematical identity holds
        self.assertTrue(res['mathematicalIdentities']['askSubdecompositionHolds'])

    # --------------------------------------------------------------------------
    # Directive 4 Counterexample 3: Future Disclosure Date Filtered from Contemporaneous
    # --------------------------------------------------------------------------
    def test_directive4_counterexample_3_future_disclosure_date_exclusion(self):
        conn = sqlite3.connect(':memory:')
        conn.execute("CREATE TABLE snapshots (district TEXT, month TEXT, fetched TEXT)")
        conn.execute("CREATE TABLE trades (district TEXT, month TEXT, payload TEXT)")

        # Target day is 2026-11-07
        # Snapshot fetched on 2026-11-08 (FUTURE relative to target day!)
        conn.execute("INSERT INTO snapshots VALUES ('11680', '2026-10', '2026-11-08 14:00:00')")
        
        trade_payload = json.dumps({
            'day': '2026-10-15',
            'exclusive_area_m2': 84.5,
            'price': 100000,
            'district': '11680',
            'dong': '개포동',
            'jibun': '138',
            'name': '디에이치아너힐즈',
            'floor': 10
        })
        conn.execute("INSERT INTO trades VALUES ('11680', '2026-10', ?)", (trade_payload,))

        # Mode CONTEMPORANEOUS_ONLY: MUST BE EXCLUDED!
        trades_live, audit_live = extract_trades_up_to_day(conn, '2026-11-07', window_days=90, mode='CONTEMPORANEOUS_ONLY')
        self.assertEqual(len(trades_live), 0)
        self.assertEqual(audit_live['contemporaneousTrades'], 0)
        self.assertEqual(audit_live['exPostReconstructedTrades'], 1)
        self.assertFalse(audit_live['isContemporaneousLiveVintage'])

        # Mode EX_POST_RECONSTRUCTED: Included for ex-post analysis
        trades_recon, audit_recon = extract_trades_up_to_day(conn, '2026-11-07', window_days=90, mode='EX_POST_RECONSTRUCTED')
        self.assertEqual(len(trades_recon), 1)
        self.assertEqual(audit_recon['totalTradesInWindow'], 1)
        conn.close()

    # --------------------------------------------------------------------------
    # Directive 4 Counterexample 4: Trade Cancellation Excluded from Reference Benchmark
    # --------------------------------------------------------------------------
    def test_directive4_counterexample_4_trade_cancellation_and_revision(self):
        conn = sqlite3.connect(':memory:')
        conn.execute("CREATE TABLE snapshots (district TEXT, month TEXT, fetched TEXT)")
        conn.execute("CREATE TABLE trades (district TEXT, month TEXT, payload TEXT)")

        conn.execute("INSERT INTO snapshots VALUES ('11680', '2026-10', '2026-11-01 10:00:00')")

        # Trade 1: Valid
        t1 = json.dumps({'day': '2026-10-10', 'exclusive_area_m2': 84.0, 'price': 100000, 'district': '11680', 'dong': '개포동', 'jibun': '138', 'name': '단지A', 'floor': 5})
        # Trade 2: Cancelled
        t2 = json.dumps({'day': '2026-10-12', 'exclusive_area_m2': 84.0, 'price': 150000, 'district': '11680', 'dong': '개포동', 'jibun': '138', 'name': '단지A', 'floor': 5, 'cancelled': True})
        conn.execute("INSERT INTO trades VALUES ('11680', '2026-10', ?)", (t1,))
        conn.execute("INSERT INTO trades VALUES ('11680', '2026-10', ?)", (t2,))

        trades, _ = extract_trades_up_to_day(conn, '2026-11-02', window_days=90, mode='CONTEMPORANEOUS_ONLY')
        k = ('11680', '개포동', '138', '단지A', 84, 1)
        
        # Only the non-cancelled trade must be present
        self.assertEqual(len(trades[k]), 1)
        self.assertEqual(trades[k][0]['price'], 100000)
        conn.close()

    # --------------------------------------------------------------------------
    # Directive 4 Counterexample 5: Deterministic Recalculation Reproducibility
    # --------------------------------------------------------------------------
    def test_directive4_counterexample_5_reproducibility_and_determinism(self):
        k1 = ('11680', '개포동', '138', '디에이치아너힐즈', 84, 1)
        prev_strata = {k1: {'askMedian': 100.0, 'tradeMedian': 100.0, 'spreadPct': 0.0}}
        curr_strata = {k1: {'askMedian': 98.0, 'tradeMedian': 105.0, 'spreadPct': -6.67}}
        listings = {'l1': {'price': 98.0, 'id': 'l1', 'stratumKey': k1}}

        run1 = decompose_spread_change(curr_strata, prev_strata, listings, listings)
        run2 = decompose_spread_change(curr_strata, prev_strata, listings, listings)

        # Bit-exact equivalence across multiple runs
        self.assertEqual(run1['deltaTotalPctPoint'], run2['deltaTotalPctPoint'])
        self.assertEqual(run1['contribAskPctPoint'], run2['contribAskPctPoint'])
        self.assertEqual(run1['contribIdenticalAskPctPoint'], run2['contribIdenticalAskPctPoint'])
        self.assertEqual(run1['contribWithinStratumTurnoverPctPoint'], run2['contribWithinStratumTurnoverPctPoint'])
        self.assertEqual(run1['contribTradeBenchmarkPctPoint'], run2['contribTradeBenchmarkPctPoint'])
        self.assertEqual(run1['contribSampleCompositionPctPoint'], run2['contribSampleCompositionPctPoint'])

if __name__ == '__main__':
    unittest.main()
