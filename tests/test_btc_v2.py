import unittest
from dataclasses import replace
from btc_v2 import Strategy,prepare,run
from pullback import Config
from test_pullback import candles


class V2Tests(unittest.TestCase):
    def test_entry_candle_stop_and_cost_reconciliation(self):
        rows=[dict(t=i*900,open=100,high=101,low=99,close=100,volume=1) for i in range(20)]
        rows[16].update(low=90,close=95)
        h=[dict(t=0,ema25=101,ema99=99,close=100,atr=2,daily={})]
        m,trades,curve=run(rows,h,Strategy('test','trend',stop_atr=3),Config())
        self.assertEqual(len(trades),1)
        self.assertEqual(trades[0]['exit_reason'],'stop')
        self.assertEqual(trades[0]['entry_time'],14400)
        self.assertEqual(trades[0]['exit_time'],15300)
        self.assertLessEqual(trades[0]['planned_risk'],100)
        self.assertLess(trades[0]['net_pnl'],0)
        self.assertAlmostEqual(m['end_equity'],10000+sum(t['net_pnl'] for t in trades))
        self.assertAlmostEqual(m['fees'],sum(t['entry_fee']+t['quantity']*t['exit']*.0005 for t in trades))

    def test_prefix_causality(self):
        rows=candles(5000);prefix=rows[:4000]
        h=prepare(rows);hp=prepare(prefix)
        self.assertEqual(hp,h[:len(hp)])
        s=Strategy('test','trend')
        _,_,full=run(rows,h,s)
        _,_,part=run(prefix,hp,s)
        self.assertEqual(part[:-1],full[:len(part)-1])

    def test_cash_schedule_does_not_trade(self):
        rows=candles(2500)
        m,t,_=run(rows,prepare(rows),Strategy('test','trend'),schedule={})
        self.assertEqual(t,[])
        self.assertEqual(m['end_equity'],10000)


if __name__=='__main__':unittest.main()
