import sqlite3
import unittest
from seoul_feed import import_delivery
from apt_watch import SCHEMA, events, ingest, price_indices, DISTRICTS, save_trade_vintage, read_trade_vintage, withhold_recent_seoul

class WatchTests(unittest.TestCase):
    def test_retry_failure_and_reappearance(self):
        db = sqlite3.connect(':memory:')
        db.executescript(SCHEMA)
        def observe(day, prices, success=True):
            ingest(db, dict(observed=day+'T06:00:00+09:00',complex='sample',success=success,
                            rows=[dict(article_no='a',asking_price_manwon=p) for p in prices]))
        observe('2026-11-01',[100])
        observe('2026-11-01',[80])
        observe('2026-11-02',[],False)
        observe('2026-11-03',[90])
        observe('2026-11-04',[])
        observe('2026-11-05',[85])
        self.assertEqual([e['kind'] for e in events(db)],['신규 관측','인하','관측 중단','재등장'])
        self.assertEqual(db.execute('SELECT COUNT(*) FROM listings').fetchone()[0],3)

    def test_matched_index_ignores_cancellation_and_unmatched_trade(self):
        coverage = {(d,m):('2019-03-31T06:00:00+09:00',0) for d in DISTRICTS for m in ('201901','201902','201903')}
        rows=[]
        for i in range(10):
            for day,price in [('2019-01-01',100),('2019-03-01',110)]:
                rows.append(dict(cancelled=False,district='11110',dong='동',jibun=str(i+1),name='단지',
                                 area='84.9',floor='7',price=price,day=day))
        rows.append({**rows[-1],'price':900,'cancelled':True})
        rows.append({**rows[-1],'price':999,'jibun':'100'})
        points=price_indices(coverage,rows)['series']['all']
        self.assertEqual([p['index'] for p in points],[100,None,110])
        self.assertEqual(points[-1]['matched'],10)
        self.assertEqual(points[-1]['comparison'],'201901')

    def test_vintage_uses_only_capture_available_at_cutoff(self):
        db = sqlite3.connect(':memory:')
        db.executescript(SCHEMA)
        first, second = '2026-11-12T08:00:00+09:00', '2026-11-13T08:00:00+09:00'
        row = dict(district='11110',day='2026-11-01',price=100)
        save_trade_vintage(db,first,{('11110','202611'):(first,1)},[row])
        save_trade_vintage(db,second,{('11110','202611'):(second,1)},[{**row,'price':120}])
        _,_,old = read_trade_vintage(db,'2026-11-12T23:00:00+09:00')
        self.assertEqual(old,[row])
        with self.assertRaises(ValueError):
            read_trade_vintage(db,'2026-11-01T08:00:00+09:00')

    def test_recent_sparse_seoul_is_withheld(self):
        data = {'series':{'all':[{'index':297.87,'provisional':True,'matched':62},
                                 {'index':296.,'provisional':True,'matched':120}]}}
        withhold_recent_seoul(data)
        self.assertIsNone(data['series']['all'][0]['index'])
        self.assertEqual(data['series']['all'][1]['index'],296.)

    def test_delivery_distinguishes_missing_failed_and_completed(self):
        db = sqlite3.connect(':memory:')
        db.executescript(SCHEMA)
        roster = [dict(complex=str(i),district='11110',name='단지') for i in range(3)]
        observed = '2026-11-12T06:00:00+09:00'
        complete = dict(complex='0',observed=observed,success=True,expectedCount=1,
                        rows=[dict(article_no='a',asking_price_manwon=100)])
        failed = dict(complex='1',observed=observed,success=False,rows=[])
        result = import_delivery(db,roster,[complete,failed],'2026-11-12')
        self.assertEqual((result['success'],result['failed'],result['missing']), (1,1,1))
        with self.assertRaises(ValueError):
            import_delivery(db,roster,[{**complete,'expectedCount':2}],'2026-11-12')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM listings').fetchone()[0],1)

if __name__ == '__main__':
    unittest.main()
