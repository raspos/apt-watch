"""Automated Unit Tests for APT WATCH Operational Quality Gates.
Tests strict boundary value conditions:
  - rate < 80.0%: CORE_QUALITY_BREACH (aborts analytics/deployment, exit 1)
  - 80.0% <= rate < 95.0%: PARTIAL_SUCCESS (preserves raw data, defers public release, exit 0)
  - rate >= 95.0%: FULL_SUCCESS (executes complete analytics and public release)
"""
import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from scripts.daily_operation import evaluate_quality_gate

class TestQualityGates(unittest.TestCase):
    def test_core_quality_breach_below_80_pct(self):
        # 79 out of 100 (79.0%) -> BREACH
        status, rate, msg = evaluate_quality_gate(100, 79)
        self.assertEqual(status, 'CORE_QUALITY_BREACH')
        self.assertAlmostEqual(rate, 0.79)
        self.assertIn('최소 품질 기준(80.0%)에 미달', msg)

        # 299 out of 375 (79.73%) -> BREACH
        status_375, rate_375, _ = evaluate_quality_gate(375, 299)
        self.assertEqual(status_375, 'CORE_QUALITY_BREACH')
        self.assertLess(rate_375, 0.80)

    def test_partial_success_exact_80_pct_boundary(self):
        # Exactly 80 out of 100 (80.0%) -> PARTIAL_SUCCESS
        status, rate, msg = evaluate_quality_gate(100, 80)
        self.assertEqual(status, 'PARTIAL_SUCCESS')
        self.assertAlmostEqual(rate, 0.80)
        self.assertIn('공식 확정지수 공표가 유예', msg)

        # 300 out of 375 (80.0%) -> PARTIAL_SUCCESS
        status_375, rate_375, _ = evaluate_quality_gate(375, 300)
        self.assertEqual(status_375, 'PARTIAL_SUCCESS')
        self.assertAlmostEqual(rate_375, 0.80)

    def test_partial_success_just_below_95_pct_boundary(self):
        # 94 out of 100 (94.0%) -> PARTIAL_SUCCESS
        status, rate, msg = evaluate_quality_gate(100, 94)
        self.assertEqual(status, 'PARTIAL_SUCCESS')
        self.assertAlmostEqual(rate, 0.94)
        self.assertIn('공식 확정지수 공표가 유예', msg)

        # 356 out of 375 (94.93%) -> PARTIAL_SUCCESS
        status_375, rate_375, _ = evaluate_quality_gate(375, 356)
        self.assertEqual(status_375, 'PARTIAL_SUCCESS')
        self.assertLess(rate_375, 0.95)
        self.assertGreaterEqual(rate_375, 0.80)

    def test_full_success_exact_95_pct_boundary(self):
        # Exactly 95 out of 100 (95.0%) -> FULL_SUCCESS
        status, rate, msg = evaluate_quality_gate(100, 95)
        self.assertEqual(status, 'FULL_SUCCESS')
        self.assertAlmostEqual(rate, 0.95)
        self.assertIsNone(msg)

        # 357 out of 375 (95.2%) -> FULL_SUCCESS
        status_375, rate_375, msg_375 = evaluate_quality_gate(375, 357)
        self.assertEqual(status_375, 'FULL_SUCCESS')
        self.assertGreaterEqual(rate_375, 0.95)
        self.assertIsNone(msg_375)

    def test_full_success_100_pct(self):
        status, rate, msg = evaluate_quality_gate(375, 375)
        self.assertEqual(status, 'FULL_SUCCESS')
        self.assertEqual(rate, 1.0)
        self.assertIsNone(msg)

    def test_zero_or_invalid_denominator(self):
        status, rate, msg = evaluate_quality_gate(0, 0)
        self.assertEqual(status, 'CORE_QUALITY_BREACH')
        self.assertEqual(rate, 0.0)

if __name__ == '__main__':
    unittest.main()
