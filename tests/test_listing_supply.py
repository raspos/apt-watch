import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import listing_supply as ls  # noqa: E402

D0, D1 = '2026-12-01', '2026-12-02'
PANEL = [{'complex': f'c{i}', 'district': '11110' if i < 2 else '11140'} for i in range(4)]
HOLDS = {'minValidRate': 0.75, 'holdDays': [], 'minReferenceDay': D0}


def db_with(rows, quality):
    db = sqlite3.connect(':memory:')
    db.execute("CREATE TABLE batches(day, complex, observed, success)")
    db.execute("CREATE TABLE listings(day, complex, id, price, payload)")
    db.execute("CREATE TABLE observation_quality(day, complex, status)")
    for day, cx, lid, price, floor in rows:
        db.execute("INSERT INTO listings VALUES (?,?,?,?,?)",
                   (day, cx, lid, price, json.dumps({'exclusive_area_m2': 84.0, 'floor': floor})))
    for day, cx, st in quality:
        db.execute("INSERT INTO batches VALUES (?,?,?,1)", (day, cx, day + 'T21:10:00Z'))
        db.execute("INSERT INTO observation_quality VALUES (?,?,?)", (day, cx, st))
    return db


class SupplyTest(unittest.TestCase):
    def base(self):
        rows = []
        for cx in ('c0', 'c1', 'c2', 'c3'):
            rows += [(D0, cx, f'{cx}-{k}', 100000 + k, '5') for k in range(10)]
            rows += [(D1, cx, f'{cx}-{k}', 100000 + k, '5') for k in range(2, 10)]   # 2 ended per complex
        return rows

    def test_same_complex_change_and_counts(self):
        q = [(d, cx, 'VALID') for d in (D0, D1) for cx in ('c0', 'c1', 'c2', 'c3')]
        s = ls.Supply(db_with(self.base(), q), PANEL, HOLDS)
        c = s.change(D1, D0, districts=['11110', '11140'])
        self.assertTrue(c['published'])
        self.assertEqual((c['listingsRef'], c['listings'], c['change']), (40, 32, -8))
        self.assertEqual(c['changePct'], -20.0)
        self.assertEqual((c['endedListings'], c['newListings']), (8, 0))
        self.assertTrue(c['districts']['11110']['published'])

    def test_failed_complex_does_not_look_like_a_drop(self):
        rows = [r for r in self.base() if not (r[0] == D1 and r[1] == 'c3')]   # c3 collection failed on D1
        q = [(D0, cx, 'VALID') for cx in ('c0', 'c1', 'c2', 'c3')] + \
            [(D1, cx, 'VALID') for cx in ('c0', 'c1', 'c2')] + [(D1, 'c3', 'INVALID')]
        s = ls.Supply(db_with(rows, q), PANEL, HOLDS)
        c = s.change(D1, D0, districts=['11110', '11140'])
        self.assertEqual(c['commonComplexes'], 3)
        self.assertEqual((c['listingsRef'], c['listings']), (30, 24))   # c3 excluded on both sides
        self.assertFalse(c['districts']['11140']['published'])          # district not complete
        self.assertIsNone(c['districts']['11140']['change'])

    def test_too_few_common_complexes_withholds_rate(self):
        q = [(D0, cx, 'VALID') for cx in ('c0', 'c1', 'c2', 'c3')] + [(D1, cx, 'VALID') for cx in ('c0', 'c1')]
        s = ls.Supply(db_with(self.base(), q), PANEL, HOLDS)
        c = s.change(D1, D0)
        self.assertFalse(c['published'])
        self.assertIsNone(c['changePct'])

    def test_reregistered_id_is_not_a_new_listing(self):
        rows = [(D0, 'c0', 'old', 100000, '5'), (D1, 'c0', 'new', 100000, '5'), (D1, 'c0', 'fresh', 120000, '7')]
        q = [(d, cx, 'VALID') for d in (D0, D1) for cx in ('c0', 'c1', 'c2', 'c3')]
        s = ls.Supply(db_with(rows, q), PANEL, HOLDS)
        c = s.change(D1, D0)
        self.assertEqual(c['relistSuspected'], 1)
        self.assertEqual((c['newListings'], c['endedListings']), (1, 0))

    def test_duplicate_id_across_complexes_counted_once(self):
        rows = [(D0, 'c0', 'x', 100000, '5'), (D0, 'c1', 'x', 100000, '5')]
        q = [(D0, cx, 'VALID') for cx in ('c0', 'c1', 'c2', 'c3')]
        lvl = ls.Supply(db_with(rows, q), PANEL, HOLDS).level(D0)
        self.assertEqual((lvl['listings'], lvl['duplicateIdsSkipped']), (1, 1))

    def test_held_day_is_not_a_reference(self):
        q = [(d, cx, 'VALID') for d in (D0, D1) for cx in ('c0', 'c1', 'c2', 'c3')]
        s = ls.Supply(db_with(self.base(), q), PANEL, dict(HOLDS, holdDays=[D0]))
        self.assertFalse(s.change(D1, D0)['published'])

    def test_quadrant_is_descriptive_and_needs_both(self):
        self.assertEqual(ls.quadrant(0.5, -1.0)[0], 'Q1')
        self.assertEqual(ls.quadrant(-0.5, 1.0)[0], 'Q2')
        self.assertEqual(ls.quadrant(0.5, None)[0], None)
        self.assertEqual(ls.quadrant(0.0, 1.0)[0], 'FLAT')


if __name__ == '__main__':
    unittest.main()
