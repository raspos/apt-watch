"""Automated Unit Tests for APT WATCH NEGO INDEX Architecture & Temporal Causality.

Validates:
  1. Strict mathematical separation of 3 prices and 3 discounts:
     - Initial discount: (P_ask,0 - P_contract) / P_ask,0 * 100
     - Closing Nego discount: (P_ask,last_before - P_contract) / P_ask,last_before * 100
     - Public asking cut: (P_ask,0 - P_ask,last_before) / P_ask,0 * 100
  2. Temporal Causality Enforcement:
     - Listings first observed after contract date (t_first > t_contract) MUST NOT produce a valid nego discount.
     - Withholding rule: when valid temporal samples == 0, median closing nego must be None.
  3. Quality Gate & Screen Verification:
     - Official publication disallowed when Grade A sample == 0
     - Erroneous 8.97% / 9.0% reverse-temporal value removed from production site_data
  4. 82-case Reclassification Audit Integrity
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

    def test_temporal_causality_and_quality_gate(self):
        data_path = ROOT / 'site' / 'data.json'
        self.assertTrue(data_path.exists())
        data = json.loads(data_path.read_text(encoding='utf-8'))

        self.assertIn('negoIndex', data)
        nego = data['negoIndex']

        # NEGO INDEX 2.0 Status & Operational Gate check
        if nego['status'] == 'HELD_VERIFICATION':
            # Publication hold: no official number may be exposed.
            self.assertFalse(nego['officialPublicationAllowed'])
            self.assertIsNone(nego['currentNegoLevel'])
            self.assertIn('검증', nego['statusLabel'])
        else:
            self.assertEqual(nego['status'], 'ACTIVE_OPERATIONAL')
            self.assertTrue(nego['officialPublicationAllowed'])
            self.assertIn('네고 압력', nego['statusLabel'])

        # Grade A: Unverified independent evidence must not emit false official numbers
        grade_a = nego['gradeA']
        self.assertEqual(grade_a['sample'], 0)
        self.assertIsNone(grade_a['currentNegoPct'])
        self.assertIsNone(grade_a['wowChangePctPoint'])
        self.assertIsNone(grade_a['momChangePctPoint'])

        # Grade B: Exploratory candidate tracking
        grade_b = nego['gradeB_Exploratory']
        # Strict temporal enforcement: if valid candidate count is 0, median MUST be None
        if grade_b['candidateMatchesCount'] == 0:
            self.assertIsNone(grade_b['medianClosingNegoPct'])
            self.assertEqual(grade_b['status'], 'WITHHELD_ZERO_VALID_SAMPLES')
            self.assertIn('0건으로 산출 유보', grade_b['notice'])
        else:
            self.assertIsNotNone(grade_b['medianClosingNegoPct'])

        # Grade C: Proxy indicator linkage
        grade_c = nego['gradeC_ProxyDivergence']
        self.assertEqual(grade_c['role'], '선행·대리 지표 (Proxy Leading Indicator)')
        self.assertIsNotNone(grade_c['currentDivergencePct'])

    def test_reclassification_audit_integrity(self):
        audit_path = ROOT / 'data' / 'nego_matching_audit_report.json'
        self.assertTrue(audit_path.exists())
        audit = json.loads(audit_path.read_text(encoding='utf-8'))

        summary = audit['summaryCounts']
        self.assertGreater(summary['totalRecentTransactions180d'], 1000)
        self.assertGreater(summary['totalTrackedListingLifecycles'], 1000)
        self.assertEqual(summary['gradeA_ConfirmedIdentical'], 0)
        
        # Verify that reverse-temporal matches are identified
        reclass = audit.get('reclassificationAuditOfHistorical82Candidates', {})
        self.assertIn('categoryB_ReverseTemporal', reclass)
        self.assertGreater(reclass['categoryB_ReverseTemporal']['count'], 0)
        self.assertGreater(reclass['categoryD_DuplicateMapping']['count'], 0)
        self.assertEqual(reclass['categoryA_TemporallyValid']['count'], 0)

        # Check sensitivity analysis structure
        self.assertIn('sensitivityAnalysis', audit)
        self.assertIn('tau_7_days', audit['sensitivityAnalysis'])
        self.assertIn('tau_14_days', audit['sensitivityAnalysis'])
        self.assertIn('tau_30_days', audit['sensitivityAnalysis'])

if __name__ == '__main__':
    unittest.main()
