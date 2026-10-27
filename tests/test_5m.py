import unittest
from btc_5m import resample,prepare
from btc_scalp import Mode,simulate
from test_scalp import fixture
from test_pullback import candles


class FiveMinuteTests(unittest.TestCase):
    def test_resample_preserves_ohlc_volume(self):
        rows=candles(12)
        for i,b in enumerate(rows):b['t']=i*300
        result=resample(rows,900)
        self.assertEqual(len(result),4)
        self.assertEqual(result[0]['volume'],sum(b['volume'] for b in rows[:3]))
        self.assertEqual(result[0]['close'],rows[2]['close'])

    def test_fine_execution_keeps_signal_cadence(self):
        bars=fixture()
        for i,b in enumerate(bars):b['t']=i*300
        m,trades,_=simulate(bars,Mode('cadence'),bar_seconds=300,decision_seconds=900)
        self.assertEqual(trades,[])
        bars[2]['rsi2']=5;bars[3]['low']=99
        _,trades,_=simulate(bars,Mode('cadence'),bar_seconds=300,decision_seconds=900)
        self.assertEqual(trades[0]['entry_time'],900)

    def test_5m_context_is_causal(self):
        rows=candles(6001)
        first=rows[0]['t']//14400*14400
        for i,b in enumerate(rows):b['t']=first+i*300
        a,p,_=prepare(rows[:5001]);full,projected,_=prepare(rows)
        self.assertEqual(a,full[:len(a)])
        self.assertEqual(p,projected[:len(p)])
        for b in full:
            if b['hour']:
                self.assertLessEqual(b['hour']['t']+3600,b['t']+300)


if __name__=='__main__':unittest.main()
