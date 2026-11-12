import unittest
import sqlite3
import json
from collect_naver import price_manwon
from nego_pressure import compare_weights, analyze_market_regime
from market_metrics import concession, market_window
from apt_watch import events, SCHEMA

class PriceParsingTests(unittest.TestCase):
    def test_single_price_parsing(self):
        self.assertEqual(price_manwon('8억'), 80000)
        self.assertEqual(price_manwon('15억 5,000'), 155000)
        self.assertEqual(price_manwon('22억 3,000'), 223000)
        self.assertEqual(price_manwon('9억 8,500'), 98500)

    def test_range_price_string_rejected(self):
        self.assertIsNone(price_manwon('매매 22억 ~ 22억 3,000'))
        self.assertIsNone(price_manwon('22억 ~ 22억 3,000'))

class WeightingModelTests(unittest.TestCase):
    def test_stock_vs_equal_weights_differ(self):
        complexes = [
            {'complex': '1', 'district': '11470', 'total_households': 1000},
            {'complex': '2', 'district': '11470', 'total_households': 100}
        ]
        db = sqlite3.connect(':memory:')
        db.execute("CREATE TABLE listings(complex TEXT, price REAL, payload TEXT, day TEXT)")
        db.execute("INSERT INTO listings VALUES ('1', 100000, '{}', '2026-11-12')")
        db.execute("INSERT INTO listings VALUES ('2', 200000, '{}', '2026-11-12')")
        
        weights = compare_weights(db, '2026-11-12', complexes)
        self.assertEqual(weights['equalWeight'], 150000.0)
        self.assertAlmostEqual(weights['stockWeight'], 109090.9, places=1)
        self.assertNotEqual(weights['equalWeight'], weights['stockWeight'])

class MarketRegimeTests(unittest.TestCase):
    def test_insufficient_sample_regime(self):
        res = analyze_market_regime(None, None, None, None)
        self.assertEqual(res['regime'], '데이터 축적 중')
        self.assertEqual(res['leverage'], '데이터 축적 중 (판별 유예)')

class AskingAdjustmentTests(unittest.TestCase):
    def test_asking_adjustment_dod_metrics(self):
        db = sqlite3.connect(':memory:')
        db.executescript(SCHEMA)

        day1 = '2026-11-12'
        day2 = '2026-11-13'
        cid = '11708'

        # Day 1: 101 ~ 110 at 80,000
        db.execute("INSERT INTO batches VALUES (?, ?, ?, 1)", (day1, cid, f"{day1}T06:00:00+09:00"))
        for i in range(101, 111):
            db.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?)", (day1, cid, str(i), 80000.0, '{}'))

        # Day 2:
        # 101, 102 cut to 76,000 (5% cut)
        # 103 rise to 84,000 (5% rise)
        # 104 ~ 108 unchanged at 80,000
        # 109, 110 delisted
        # 111, 112 new at 82,000
        db.execute("INSERT INTO batches VALUES (?, ?, ?, 1)", (day2, cid, f"{day2}T06:00:00+09:00"))
        for i in ('101', '102'):
            db.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?)", (day2, cid, i, 76000.0, '{}'))
        db.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?)", (day2, cid, '103', 84000.0, '{}'))
        for i in range(104, 109):
            db.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?)", (day2, cid, str(i), 80000.0, '{}'))
        for i in ('111', '112'):
            db.execute("INSERT INTO listings VALUES (?, ?, ?, ?, ?)", (day2, cid, i, 82000.0, '{}'))

        evs = events(db)
        res = concession(evs, day2, 1, {cid})

        self.assertEqual(res['sample'], 8) # exactly 8 continuous
        self.assertEqual(res['cutListings'], 2)
        self.assertEqual(res['riseListings'], 1)
        self.assertAlmostEqual(res['cutShare'], 25.0, places=2)
        self.assertAlmostEqual(res['riseShare'], 12.5, places=2)
        self.assertAlmostEqual(res['netAdjustmentShare'], -12.5, places=2)
        self.assertAlmostEqual(res['meanCutPct'], 5.0, places=2)
        self.assertAlmostEqual(res['meanRisePct'], 5.0, places=2)

class VitalityReportingLagTests(unittest.TestCase):
    def test_vitality_provisional_vs_mature_definition(self):
        db = sqlite3.connect(':memory:')
        db.executescript(SCHEMA)

        # Verified crosswalk target
        targets = {
            '1': {
                'tradeCrosswalkVerified': True,
                'tradeComplex': ['11470', '신월동', '1033', '대성유니드'],
                'district': '11470'
            }
        }
        # Incomplete inventory returns percent=None
        res_mature = market_window(db, targets, '2026-11-12', 30, {}, [], require_mature=True)
        res_provisional = market_window(db, targets, '2026-11-12', 30, {}, [], require_mature=False)
        
        self.assertTrue(res_mature['isMature'])
        self.assertIsNone(res_mature['reportingLagNote'])
        self.assertFalse(res_provisional['isMature'])
        self.assertIn('신고 시차', res_provisional['reportingLagNote'])

if __name__ == '__main__':
    unittest.main()
