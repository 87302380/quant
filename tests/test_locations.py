import unittest
from btc_locations import Rules,prepare,signals,simulate
from test_pullback import candles
from pullback import Config


class LocationTests(unittest.TestCase):
    def test_cost_space_rejects_uneconomic_entry(self):
        h=dict(t=0,atr=2,close=100);f=dict(ema25=101,ema99=99,adx=25)
        bars=[dict(t=i*300,open=100,high=101,low=99,close=100,h1=h,h4=f) for i in range(4)]
        e=dict(index=0,direction=1,stop=98,target=106,atr1h=2,level=99,source='4h_pivot')
        m,t,_=simulate(bars,Rules('cost',max_cost_fraction=.1),Config(fee=.005),events=[e])
        self.assertEqual(t,[])
        self.assertEqual(m['rejections']['cost_fraction'],1)

    def test_context_and_pivots_are_causal(self):
        rows=candles(7001);base=rows[0]['t']//14400*14400
        for i,b in enumerate(rows):b['t']=base+300*i
        a=prepare(rows[:6001]);full=prepare(rows)
        self.assertEqual(a,full[:len(a)])
        r=Rules('test')
        self.assertEqual(list(signals(a,r)),[e for e in signals(full,r) if e['index']<len(a)])
        for b in full:
            for key,seconds in [('h1',3600),('h4',14400)]:
                if b[key]:self.assertLessEqual(b[key]['t']+seconds,b['t']+300)

    def test_partial_exit_is_one_net_trade(self):
        h=dict(t=0,atr=2,close=102.5);f=dict(ema25=101,ema99=99,adx=25)
        bars=[dict(t=i*300,open=100,high=101,low=99,close=100,h1=h,h4=f) for i in range(4)]
        bars[1].update(high=103,close=102.5)
        e=dict(index=0,direction=1,stop=98,target=106,atr1h=2,level=99,source='4h_pivot')
        m,t,curve=simulate(bars,Rules('split'),events=[e])
        self.assertEqual(len(t),1)
        self.assertEqual(len(t[0]['parts']),2)
        self.assertGreater(t[0]['net_pnl'],0)
        self.assertAlmostEqual(sum(p['quantity'] for p in t[0]['parts']),t[0]['quantity'])
        self.assertAlmostEqual(m['end_equity'],10000+sum(x['net_pnl'] for x in t))
        self.assertLessEqual(t[0]['planned_risk'],100)


if __name__=='__main__':unittest.main()
