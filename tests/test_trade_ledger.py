import gzip
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
import trade_ledger as tl  # noqa: E402

D, M = '11110', '202611'


def item(day=3, price='100,000', floor='5', jibun='1-1', cdeal='', dong='101'):
    return {'sggCd': D, 'umdCd': '10100', 'umdNm': '동', 'aptNm': '테스트', 'jibun': jibun, 'aptSeq': '11110-1',
            'aptDong': dong, 'excluUseAr': '84.9', 'floor': floor, 'dealYear': '2026', 'dealMonth': '11',
            'dealDay': str(day), 'dealAmount': price, 'cdealType': 'O' if cdeal else '', 'cdealDay': cdeal}


def xml(items):
    body = ''.join('<item>' + ''.join(f'<{k}>{v}</{k}>' for k, v in it.items()) + '</item>' for it in items)
    return (f'<response><header><resultCode>000</resultCode></header><body><items>{body}</items>'
            f'<totalCount>{len(items)}</totalCount></body></response>').encode('utf-8')


class LedgerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ev = Path(self.tmp.name) / 'ev'
        self.db = sqlite3.connect(':memory:')
        self.db.executescript(tl.DDL)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def rec(self, at, items):
        return tl.record_snapshot(self.db, D, M, at, [xml(items)], len(items), evidence_dir=self.ev)

    def asof(self, day):
        return tl.trades_as_of(self.db, day, window_days=20, districts=[D])

    def events(self):
        return [r[0] for r in self.db.execute("SELECT event FROM trade_events ORDER BY id")]

    def test_new_trade_first_seen_is_query_time_not_contract_day(self):
        self.rec('2026-11-14T07:00:00+09:00', [item(day=3)])
        rows, audit = self.asof('2026-11-14')
        self.assertFalse(audit['tradeLevelFirstSeenVerified'])   # 2026-10 of the window was never queried
        tl.record_snapshot(self.db, D, '202610', '2026-11-14T07:01:00+09:00', [xml([])], 0, evidence_dir=self.ev)
        rows, audit = self.asof('2026-11-14')
        self.assertEqual(rows[0]['day'], '2026-11-03')
        self.assertEqual(rows[0]['firstSeenAt'], '2026-11-14T07:00:00+09:00')
        self.assertTrue(audit['tradeLevelFirstSeenVerified'])

    def test_duplicate_deals_on_same_key_are_kept_and_change_is_ambiguous(self):
        self.rec('2026-11-14T07:00:00+09:00', [item(), item()])
        rows, _ = self.asof('2026-11-14')
        self.assertEqual(len(rows), 2)
        self.rec('2026-11-15T07:00:00+09:00', [item(), item(price='99,000')])
        self.assertIn('AMBIGUOUS', self.events())

    def test_cancellation_is_tracked_and_not_backdated(self):
        self.rec('2026-11-14T07:00:00+09:00', [item()])
        self.rec('2026-11-16T07:00:00+09:00', [item(cdeal='26.11.15')])
        self.assertIn('CANCELLED', self.events())
        r14, _ = self.asof('2026-11-14')
        r16, _ = self.asof('2026-11-16')
        self.assertFalse(r14[0]['cancelled'])     # on 11-14 the cancellation was not yet visible
        self.assertTrue(r16[0]['cancelled'])

    def test_correction_keeps_both_versions_and_old_day_uses_old_price(self):
        self.rec('2026-11-14T07:00:00+09:00', [item(price='100,000')])
        self.rec('2026-11-15T07:00:00+09:00', [item(price='98,000')])
        self.assertIn('CORRECTED', self.events())
        self.assertEqual(self.asof('2026-11-14')[0][0]['price'], 100000)
        self.assertEqual(self.asof('2026-11-15')[0][0]['price'], 98000)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM trade_versions").fetchone()[0], 2)

    def test_late_report_does_not_enter_earlier_index_day(self):
        self.rec('2026-11-14T07:00:00+09:00', [item(day=3)])
        self.rec('2026-11-16T07:00:00+09:00', [item(day=3), item(day=5, jibun='2-2')])   # reported later
        self.assertEqual(len(self.asof('2026-11-14')[0]), 1)
        self.assertEqual(len(self.asof('2026-11-16')[0]), 2)
        self.assertIn('NEW', self.events())

    def test_future_fetch_is_blocked_and_unfetched_day_is_unverified(self):
        self.rec('2026-11-16T07:00:00+09:00', [item()])
        rows, audit = self.asof('2026-11-14')         # no query existed on or before 11-14
        self.assertEqual(rows, [])
        self.assertFalse(audit['tradeLevelFirstSeenVerified'])

    def test_removed_trade_is_logged(self):
        self.rec('2026-11-14T07:00:00+09:00', [item(), item(jibun='9-9')])
        self.rec('2026-11-15T07:00:00+09:00', [item()])
        self.assertIn('REMOVED', self.events())

    def test_tampered_evidence_makes_day_unverified(self):
        self.rec('2026-11-14T07:00:00+09:00', [item()])
        path = Path(self.db.execute("SELECT raw_path FROM fetches").fetchone()[0])
        with gzip.open(path, 'wb') as f:
            f.write(b'tampered')
        self.assertFalse(self.asof('2026-11-14')[1]['tradeLevelFirstSeenVerified'])

    def test_seoul_verification_requires_all_25_districts(self):
        self.rec('2026-11-14T07:00:00+09:00', [item(day=10)])
        rows, audit = tl.trades_as_of(self.db, '2026-11-14', window_days=10)   # default = all of Seoul
        self.assertEqual(audit['districts'], 25)
        self.assertFalse(audit['tradeLevelFirstSeenVerified'])
        self.assertEqual(len(audit['districtMonthsMissing']), 24)

    def test_incomplete_page_set_is_rejected(self):
        with self.assertRaises(ValueError):
            tl.record_snapshot(self.db, D, M, '2026-11-14T07:00:00+09:00', [xml([item()])], 2, evidence_dir=self.ev)


if __name__ == '__main__':
    unittest.main()
