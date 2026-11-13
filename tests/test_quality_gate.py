import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import observation_quality as oq  # noqa: E402
import apply_publication_hold as aph  # noqa: E402
import divergence_dynamics as dd  # noqa: E402


def make_db():
    db = sqlite3.connect(':memory:')
    db.execute("CREATE TABLE batches(day, complex, observed, success)")
    db.execute("CREATE TABLE listings(day, complex, id, price, payload)")
    return db


def add(db, day, cx, ids_prices, ok=1, name='A단지'):
    db.execute("INSERT OR REPLACE INTO batches VALUES (?,?,?,?)", (day, cx, day + 'T00:00:00Z', ok))
    for i, p in ids_prices:
        db.execute("INSERT INTO listings VALUES (?,?,?,?,?)",
                   (day, cx, str(i), p, json.dumps({'complex_name': name, 'exclusive_area_m2': 84.0, 'asking_price_manwon': p})))


class QualityJudgeTest(unittest.TestCase):
    def test_baseline_then_consistent_day_is_valid(self):
        db = make_db()
        add(db, '2026-01-01', 'c1', [(i, 100000 + i) for i in range(30)])
        add(db, '2026-01-02', 'c1', [(i, 100000 + i) for i in range(5, 35)])
        oq.assess_day(db, '2026-01-01')
        s = oq.assess_day(db, '2026-01-02')
        self.assertEqual(s['valid'], 1)

    def test_silent_zero_after_large_reference_is_suspect(self):
        db = make_db()
        add(db, '2026-01-01', 'c1', [(i, 100000) for i in range(40)])
        add(db, '2026-01-02', 'c1', [])
        oq.assess_day(db, '2026-01-01')
        oq.assess_day(db, '2026-01-02')
        st = db.execute("SELECT status, kind FROM observation_quality WHERE day='2026-01-02'").fetchone()
        self.assertEqual(st, ('SUSPECT', 'ZERO_LISTINGS'))

    def test_price_level_shift_is_not_valid(self):
        db = make_db()
        add(db, '2026-01-01', 'c1', [(i, 170000) for i in range(100)])
        add(db, '2026-01-02', 'c1', [(1000 + i, 23000) for i in range(5)])   # different ids, 1/7 price level
        oq.assess_day(db, '2026-01-01')
        oq.assess_day(db, '2026-01-02')
        self.assertNotEqual(db.execute("SELECT status FROM observation_quality WHERE day='2026-01-02'").fetchone()[0], 'VALID')

    def test_failed_batch_is_invalid_and_excluded(self):
        db = make_db()
        add(db, '2026-01-01', 'c1', [], ok=0)
        oq.assess_day(db, '2026-01-01')
        self.assertEqual(db.execute("SELECT kind, status FROM observation_quality").fetchone(), ('FAILED', 'INVALID'))
        self.assertEqual(oq.valid_complexes(db, '2026-01-01'), set())

    def test_retry_store_rejected_when_inconsistent(self):
        main = make_db()
        add(main, '2026-01-01', 'c1', [(i, 170000) for i in range(100)])
        add(main, '2026-01-02', 'c1', [], ok=0)
        oq.assess_day(main, '2026-01-01')
        retry = make_db()
        add(retry, '2026-01-02', 'c1', [(5000 + i, 23000) for i in range(5)])
        verdicts = oq.validate_retry_store(main, retry, '2026-01-02', [{'complex': 'c1', 'name': 'A단지'}])
        self.assertFalse(verdicts['c1'][0])

    def test_retry_store_accepted_when_consistent(self):
        main = make_db()
        add(main, '2026-01-01', 'c1', [(i, 100000) for i in range(40)])
        oq.assess_day(main, '2026-01-01')
        retry = make_db()
        add(retry, '2026-01-02', 'c1', [(i, 100000) for i in range(3, 43)])
        verdicts = oq.validate_retry_store(main, retry, '2026-01-02', [{'complex': 'c1', 'name': 'A단지'}])
        self.assertTrue(verdicts['c1'][0])


class StabilityGuardTest(unittest.TestCase):
    def _strata(self, spreads):
        return {('d', 'x', str(i), 'n', 84, 1): {'spreadPct': v, 'askMedian': 1.0, 'tradeMedian': 1.0,
                                                'tradeDaysList': [], 'listingCount': 1} for i, v in enumerate(spreads)}

    def test_single_group_outlier_withholds_change(self):
        prev = self._strata([5.0] * 40)
        curr = self._strata([5.0] * 39 + [-45.0])
        res = dd.decompose_with_stability_guard(curr, prev, {}, {})
        self.assertEqual(res['status'], 'WITHHELD_STABILITY')
        self.assertIsNone(res['deltaPctPoint'])

    def test_too_few_groups_withholds_change(self):
        prev = self._strata([5.0] * 10)
        curr = self._strata([5.1] * 10)
        res = dd.decompose_with_stability_guard(curr, prev, {}, {})
        self.assertEqual(res['status'], 'WITHHELD_STABILITY')


class PublicationGateTest(unittest.TestCase):
    def test_published_site_exposes_no_numbers_for_held_day(self):
        site = json.loads((ROOT / 'site' / 'data.json').read_text(encoding='utf-8'))
        hold = aph.load_holds()
        n = site['negoIndex']
        if n.get('asOf') in hold['holdDays']:
            self.assertEqual(n['status'], 'HELD_VERIFICATION')
            self.assertIsNone(n['currentNegoLevel'])
            for h in ('1d', '7d', '28d'):
                self.assertIsNone(n['changes'][h]['deltaPctPoint'])
            self.assertEqual(site['market']['spreadDynamics']['seoulOverall']['seriesB_FixedSamplePanel'], [])

    def test_unassessed_day_is_held_by_gate(self):
        site = {'negoIndex': {'asOf': '2099-01-01', 'changes': {}}, 'market': {}}
        level, _ = aph.evaluate_gate(site, {'holdDays': []})
        self.assertTrue(level)


if __name__ == '__main__':
    unittest.main()
