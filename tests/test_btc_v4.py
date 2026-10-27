import unittest
from btc_v2 import Strategy,run
from btc_v4 import entry_features
from test_pullback import candles


class V4Tests(unittest.TestCase):
    def test_hourly_features_do_not_use_future(self):
        rows=candles(6001)
        prefix,_=entry_features(rows[:4801])
        full,_=entry_features(rows)
        self.assertEqual(prefix,full[:len(prefix)])
        for h in full:
            if h['regime']:
                self.assertLessEqual(h['regime']['t']+14400,h['t']+3600)

    def test_hourly_signal_executes_next_open(self):
        rows=[dict(t=i*900,open=100,high=101,low=99,close=100,volume=1) for i in range(12)]
        h=[dict(t=0,ema25=101,ema99=99,close=100,atr=1,daily={},signals={'resume':1},
                regime=dict(ema25=101,ema99=99,atr=2))]
        _,trades,_=run(rows,h,Strategy('hour','resume',signal_seconds=3600,trail_on_regime=True))
        self.assertEqual(len(trades),1)
        self.assertEqual(trades[0]['entry_time'],3600)


if __name__=='__main__':unittest.main()
