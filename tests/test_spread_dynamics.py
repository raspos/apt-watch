"""Automated Unit Tests for APT WATCH Price Divergence Dynamics & 3-Way Decomposition.

Validates:
  1. Identical listing price revision vs composition shift separation
  2. Reference trade benchmark point-in-time updating
  3. Mathematical identity: Total ΔSpread = Contrib_ask + Contrib_trade + Contrib_composition
  4. Accumulation quality gates: Withholding WoW (< 7d) and MoM (< 28d) changes
  5. Distinction between Price Divergence Dynamics and Official NEGO INDEX
"""

import unittest
import json
from pathlib import Path
from scripts.divergence_dynamics import decompose_spread_change

ROOT = Path(__file__).resolve().parent.parent

class TestSpreadDynamics(unittest.TestCase):
    def test_mathematical_decomposition_identity(self):
        # Scenario:
        # Prev stratum: ask 100,000, trade 90,000 -> spread = (100/90 - 1)*100 = 11.111%
        # Curr stratum: ask 98,000, trade 92,000  -> spread = (98/92 - 1)*100 = 6.522%
        k1 = ('11680', '개포동', '138', '디에이치아너힐즈', 84, 1)
        prev_strata = {
            k1: {
                'askMedian': 100000.0,
                'tradeMedian': 90000.0,
                'spreadPct': 11.111,
                'logSpread': 0.10536
            }
        }
        curr_strata = {
            k1: {
                'askMedian': 98000.0,
                'tradeMedian': 92000.0,
                'spreadPct': 6.522,
                'logSpread': 0.06318
            }
        }
        prev_listings = {'naver_1_1': {'price': 100000.0}}
        curr_listings = {'naver_1_1': {'price': 98000.0}}

        decomp = decompose_spread_change(curr_strata, prev_strata, curr_listings, prev_listings)
        
        self.assertEqual(decomp['status'], 'VALID')
        self.assertIsNotNone(decomp['deltaTotalPctPoint'])
        self.assertIsNotNone(decomp['contribAskPctPoint'])
        self.assertIsNotNone(decomp['contribTradeBenchmarkPctPoint'])
        self.assertIsNotNone(decomp['contribSampleCompositionPctPoint'])

        # Check identity: Total ΔSpread = Ask + Trade + Composition
        total = decomp['deltaTotalPctPoint']
        components_sum = round(decomp['contribAskPctPoint'] + decomp['contribTradeBenchmarkPctPoint'] + decomp['contribSampleCompositionPctPoint'], 2)
        self.assertAlmostEqual(total, components_sum, places=2)

        # Ask cut from 100,000 to 98,000 on 90,000 base -> -2,000 / 90,000 * 100 = -2.22%p
        self.assertAlmostEqual(decomp['contribAskPctPoint'], -2.22, places=1)
        # Trade rise from 90,000 to 92,000 on 90,000 base -> -(2,000 / 90,000 * 100) = -2.22%p
        self.assertAlmostEqual(decomp['contribTradeBenchmarkPctPoint'], -2.22, places=1)

    def test_sample_composition_shift_separation(self):
        # When new stratum enters or composition changes without identical price revision
        k1 = ('11680', '개포동', '138', '디에이치아너힐즈', 84, 1)
        k2 = ('11440', '아현동', '777', '마포래미안푸르지오', 59, 1)
        
        prev_strata = {
            k1: {'askMedian': 100000.0, 'tradeMedian': 100000.0, 'spreadPct': 0.0, 'logSpread': 0.0}
        }
        # In current period, a new high-premium stratum k2 enters
        curr_strata = {
            k1: {'askMedian': 100000.0, 'tradeMedian': 100000.0, 'spreadPct': 0.0, 'logSpread': 0.0},
            k2: {'askMedian': 120000.0, 'tradeMedian': 100000.0, 'spreadPct': 20.0, 'logSpread': 0.1823}
        }
        prev_listings = {'naver_1_1': {}}
        curr_listings = {'naver_1_1': {}, 'naver_2_2': {}}

        decomp = decompose_spread_change(curr_strata, prev_strata, curr_listings, prev_listings)

        # On matched stratum k1, ask and trade did not change (0.0%p)
        self.assertEqual(decomp['contribAskPctPoint'], 0.0)
        self.assertEqual(decomp['contribTradeBenchmarkPctPoint'], 0.0)
        # The entire shift in median spread is correctly attributed to composition
        self.assertEqual(decomp['contribSampleCompositionPctPoint'], decomp['deltaTotalPctPoint'])

    def test_spread_dynamics_quality_gates(self):
        data_path = ROOT / 'site' / 'data.json'
        self.assertTrue(data_path.exists())
        data = json.loads(data_path.read_text(encoding='utf-8'))

        self.assertIn('spreadDynamics', data['market'])
        dyn = data['market']['spreadDynamics']

        # 1. Seoul Overall Structure
        seoul = dyn['seoulOverall']
        self.assertIn('currentSpreadPct', seoul)
        self.assertIn('changes', seoul)
        
        # 2. Quality gate: 7d and 28d changes must be withheld when history < duration
        changes = seoul['changes']
        self.assertIn('축적 중', changes['7d']['status'])
        self.assertIsNone(changes['7d']['deltaPctPoint'])
        self.assertIn('축적 중', changes['28d']['status'])
        self.assertIsNone(changes['28d']['deltaPctPoint'])

        # 3. 25 Districts coverage
        districts = dyn['districts']
        self.assertEqual(len(districts), 25)
        for d_code, d_info in districts.items():
            self.assertIn('status', d_info)
            self.assertIn('changes', d_info)
            self.assertIn('1d', d_info['changes'])
            self.assertIn('7d', d_info['changes'])
            self.assertIn('28d', d_info['changes'])

        # 4. Strict segregation: Price Divergence is NOT NEGO INDEX
        self.assertIn('negoIndex', data)
        self.assertEqual(data['negoIndex']['gradeA']['sample'], 0)
        self.assertIsNone(data['negoIndex']['gradeA']['currentNegoPct'])

if __name__ == '__main__':
    unittest.main()
