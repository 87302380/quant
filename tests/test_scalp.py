import unittest
from btc_scalp import Mode,simulate


def fixture():
    h=dict(atr=1,adx=10,ema99=99,ema25=101)
    return [dict(t=i*900,open=100,high=101,low=100,close=100,volume=1,atr=1,
        hour=h,regime={},signals={},rsi2=5 if i==0 else 50,mean=110,sd=1) for i in range(8)]


class ScalpTests(unittest.TestCase):
    def test_known_market_open_can_hit_entry_bar_target(self):
        b=fixture();b[1].update(high=105,low=99)
        _,t,_=simulate(b,Mode('market',maker=False),market_entry_target=True)
        self.assertEqual(t[0]['exit_reason'],'entry_bar_target')
        self.assertGreater(t[0]['net_pnl'],0)
    def test_limit_touch_does_not_fill(self):
        b=fixture();b[1]['low']=99.7
        m,t,_=simulate(b,Mode('test'))
        self.assertEqual(t,[])
        self.assertEqual(m['filled'],0)

    def test_no_entry_candle_target_and_fees_reconcile(self):
        b=fixture();b[1].update(low=99,high=105);b[2]['high']=100.4
        m,t,_=simulate(b,Mode('test'))
        self.assertEqual(len(t),1)
        self.assertEqual(t[0]['exit_time'],4*900)
        self.assertEqual(t[0]['exit_reason'],'target')
        self.assertAlmostEqual(m['end_equity'],10000+sum(x['net_pnl'] for x in t))
        self.assertLessEqual(t[0]['planned_risk'],25)

    def test_entry_bar_stop_has_priority(self):
        b=fixture();b[1].update(low=95,high=105)
        _,t,_=simulate(b,Mode('test'))
        self.assertEqual(t[0]['exit_reason'],'entry_bar_stop')
        self.assertLess(t[0]['net_pnl'],0)


if __name__=='__main__':unittest.main()
