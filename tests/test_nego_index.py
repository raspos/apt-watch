"""Automated Unit Tests for APT WATCH NEGO INDEX Architecture.
Validates:
  1. Strict separation of 3 prices: P_ask,0, P_ask,last, P_contract
  2. Distinct discount mathematical identities:
     - Initial discount: (P_ask,0 - P_contract) / P_ask,0
     - Closing Nego discount: (P_ask,last - P_contract) / P_ask,last
     - Public asking cut: (P_ask,0 - P_ask,last) / P_ask,0
  3. Grade A/B/C verification hierarchy:
     - Grade A: Requires verified broker/contract evidence, default 0 sample
     - Grade B: Exploratory candidate tracking, strictly separated from official release
     - Grade C: Cohort proxy divergence benchmark
  4. Publication quality gate:
     - Official publication disallowed when Grade A sample < threshold
"""

import unittest
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

class TestNegoIndex(unittest.TestCase):
    def test_three_discount_formulas(self):
        # Case: Initial 15억 -> Cut to 14.7억 -> Contract at 14.4억
        p_initial = 150000 # 15억
        p_last = 147000    # 14.7억
        p_contract = 144000# 14.4억

        initial_discount = (p_initial - p_contract) / p_initial * 100.0
        closing_nego = (p_last - p_contract) / p_last * 100.0
        asking_cut = (p_initial - p_last) / p_initial * 100.0

        # Exact values:
        # Initial discount: (15 - 14.4) / 15 * 100 = 4.0%
        self.assertAlmostEqual(initial_discount, 4.0, places=2)
        # Closing nego: (14.7 - 14.4) / 14.7 * 100 = 2.0408%
        self.assertAlmostEqual(closing_nego, 2.0408, places=3)
        # Asking cut: (15 - 14.7) / 15 * 100 = 2.0%
        self.assertAlmostEqual(asking_cut, 2.0, places=2)

        # Verification of distinct denominators:
        self.assertNotEqual(initial_discount, closing_nego)
        self.assertNotEqual(closing_nego, asking_cut)

    def test_nego_index_schema_and_quality_gate(self):
        data_path = ROOT / 'site' / 'data.json'
        self.assertTrue(data_path.exists())
        data = json.loads(data_path.read_text(encoding='utf-8'))

        self.assertIn('negoIndex', data)
        nego = data['negoIndex']

        # Status & Quality Gate check
        self.assertEqual(nego['status'], 'VERIFICATION_STAGE')
        self.assertFalse(nego['officialPublicationAllowed'])
        self.assertIn('검증 단계', nego['statusLabel'])

        # Grade A: Unverified independent evidence must not emit false official numbers
        grade_a = nego['gradeA']
        self.assertEqual(grade_a['sample'], 0)
        self.assertIsNone(grade_a['currentNegoPct'])
        self.assertIsNone(grade_a['wowChangePctPoint'])
        self.assertIsNone(grade_a['momChangePctPoint'])

        # Grade B: Exploratory candidate tracking
        grade_b = nego['gradeB_Exploratory']
        self.assertGreater(grade_b['candidateMatchesCount'], 0)
        self.assertGreater(grade_b['medianClosingNegoPct'], 0.0)
        self.assertIn('공식 확정치 아님', grade_b['notice'])

        # Grade C: Proxy indicator linkage
        grade_c = nego['gradeC_ProxyDivergence']
        self.assertEqual(grade_c['role'], '선행·대리 지표 (Proxy Leading Indicator)')
        self.assertIsNotNone(grade_c['currentDivergencePct'])

    def test_matching_audit_report_integrity(self):
        audit_path = ROOT / 'data' / 'nego_matching_audit_report.json'
        self.assertTrue(audit_path.exists())
        audit = json.loads(audit_path.read_text(encoding='utf-8'))

        summary = audit['summaryCounts']
        self.assertGreater(summary['totalRecentTransactions180d'], 1000)
        self.assertGreater(summary['totalTrackedListingLifecycles'], 1000)
        self.assertEqual(summary['gradeA_ConfirmedIdentical'], 0)
        self.assertGreater(summary['gradeB_UniqueCandidateMatches'], 0)

if __name__ == '__main__':
    unittest.main()
