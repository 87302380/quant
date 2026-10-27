import unittest
from btc_v2 import Strategy,run
from btc_v2 import prepare
from btc_v3 import ensemble
from pullback import Config
from test_pullback import candles


class V3Tests(unittest.TestCase):
    def test_ensemble_reconciles_real_subaccounts(self):
        rows=candles(5000);h=prepare(rows)
        specs=[Strategy(str(i),'trend') for i in range(3)]
        m,trades,curve=ensemble(rows,h,specs,Config(),rows[0]['t'],rows[-1]['t']+900)
        self.assertAlmostEqual(m['end_equity'],10000+sum(t['net_pnl'] for t in trades))
        for t in trades:
            self.assertAlmostEqual(t['quantity']/.0001,round(t['quantity']/.0001),places=7)

    def test_adx_only_filters_entry(self):
        rows=[dict(t=i*900,open=100,high=101,low=99,close=100,volume=1) for i in range(40)]
        h=[dict(t=0,ema25=101,ema99=99,close=100,atr=1,adx=15,daily={})]
        _,trades,_=run(rows,h,Strategy('filtered','trend',min_adx=20))
        self.assertEqual(trades,[])

    def test_breakeven_uses_next_bar_both_directions(self):
        for d in (1,-1):
            with self.subTest(direction=d):
                rows=[dict(t=i*900,open=100,high=101,low=99,close=100,volume=1) for i in range(40)]
                h=[dict(t=0,ema25=100+d,ema99=100-d,close=100,atr=1,daily={}),
                   dict(t=14400,ema25=100+3*d,ema99=100-d,close=100+4*d,atr=1,daily={})]
                rows[31].update(high=105 if d==1 else 102,low=98 if d==1 else 95,close=100+4*d)
                rows[32].update(open=100+4*d,high=105 if d==1 else 101,low=99 if d==1 else 95)
                _,trades,_=run(rows,h,Strategy('lock','trend',short=True,breakeven_r=1))
                self.assertEqual(len(trades),1)
                self.assertEqual(trades[0]['exit_time'],33*900)
                self.assertGreaterEqual(trades[0]['net_pnl'],0)


if __name__=='__main__':unittest.main()
