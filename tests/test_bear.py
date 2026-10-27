import unittest
from btc_v2 import Strategy,run


class BearTests(unittest.TestCase):
    def test_short_only_does_not_trade_bullish_signal(self):
        rows=[dict(t=i*900,open=100,high=101,low=99,close=100,volume=1) for i in range(40)]
        h=[dict(t=0,ema25=101,ema99=99,close=100,atr=1,daily={}),
           dict(t=14400,ema25=99,ema99=101,close=100,atr=1,daily={})]
        _,trades,_=run(rows,h,Strategy('bear','trend',short=True,long=False))
        self.assertTrue(trades)
        self.assertTrue(all(t['side']=='short' for t in trades))
        self.assertGreaterEqual(trades[0]['entry_time'],28800)


if __name__=='__main__':unittest.main()
