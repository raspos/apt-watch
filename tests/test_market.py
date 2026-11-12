import math
import unittest
from market_metrics import absorption, concession, estimated_spread, realized_nego
from price_models import fixed_effects

class MarketTests(unittest.TestCase):
    def test_absorption_requires_full_denominator(self):
        self.assertIsNone(absorption(1,[10],2,True)['percent'])
        self.assertIsNone(absorption(1,[10,20],2,False)['percent'])
        self.assertAlmostEqual(absorption(1,[10,20],2,True)['percent'],100/15)

    def test_consecutive_cuts_use_daily_observation_and_distinct_ids(self):
        rows=[dict(day=d,complex='c',id='a',before=a,after=b,firstPrice=100)
              for d,a,b in [('2026-11-05',100,90),('2026-11-06',90,81)]]
        r=concession(rows,'2026-11-06',7,{'c'})
        self.assertEqual((r['sample'],r['cutEvents'],r['consecutiveCutShare']),(1,2,100))
        self.assertAlmostEqual(r['meanCutPct'],10)
        self.assertAlmostEqual(r['firstToLatestMedianPct'],-19)
        self.assertIsNone(r['cutToRiseRatio'])

    def test_spread_rejects_future_trade_capture(self):
        key=dict(district='11110',dong='d',jibun='1',name='n',area=84,floor=4)
        trades=[dict(**key,day='2026-11-01',price=100,cancelled=False)]*3
        asks=[dict(**key,observed='2026-11-12T06:00:00+09:00',crosswalkVerified=True,asking_price_manwon=110)]
        self.assertIsNone(estimated_spread(asks,trades,'2026-11-12','2026-11-12T07:00:00+09:00')['percent'])
        self.assertAlmostEqual(estimated_spread(asks,trades,'2026-11-12','2026-11-12T05:00:00+09:00')['percent'],10)

    def test_realized_rejects_duplicate_contract_evidence(self):
        row=dict(source='provider',listingId='id',contractId='contract',verified=True,evidence='record',
                 cancelled=False,askObserved='2026-11-10T06:00:00+09:00',contractDay='2026-11-11',
                 lastAsk=100,contractPrice=95)
        self.assertAlmostEqual(realized_nego([row])['percent'],5)
        self.assertIsNone(realized_nego([row,{**row,'listingId':'another'}])['percent'])
        self.assertIsNone(realized_nego([{**row,'cancelled':True}])['percent'])

    def test_month_effects_are_identified_through_overlapping_groups(self):
        group={'a':{'2019-01':[math.log(100)],'2019-02':[math.log(110)]},
               'b':{'2019-02':[math.log(220)],'2019-03':[math.log(242)]},
               'c':{'2019-04':[math.log(999)]}}
        levels,_=fixed_effects(group,['2019-01','2019-02','2019-03','2019-04'])
        self.assertAlmostEqual(levels['2019-03'],121)
        self.assertNotIn('2019-04',levels)
