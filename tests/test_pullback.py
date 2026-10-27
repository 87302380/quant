import unittest
from unittest.mock import patch
import random
from dataclasses import replace
from pullback import Config, features, candidates, run, round_step


def candles(n=2000):
    rng = random.Random(42)
    rows, price = [], 10000.
    for i in range(n):
        close = price + rng.uniform(-40, 45)
        rows.append(dict(t=1800000000//14400*14400+i*900, open=price,
                         high=max(price,close)+20, low=min(price,close)-20,
                         close=close, volume=rng.uniform(10,100)))
        price = close
    return rows


class Tests(unittest.TestCase):
    def test_causality(self):
        rows, c = candles(), Config()
        full, prefix = features(rows,c), features(rows[:1800],c)
        self.assertEqual(prefix,full[:1800])
        self.assertEqual(list(candidates(prefix,c)),[x for x in candidates(full,c) if x['index']<1800])

    def test_htf_is_closed(self):
        for b in features(candles(),Config()):
            for key, seconds in [('h1',3600),('h4',14400)]:
                if b[key]: self.assertLessEqual(b[key]['t']+seconds,b['t']+900)

    def test_risk_and_ambiguous_bar(self):
        rows = candles(3)
        rows[1].update(open=100, high=120, low=90, close=105)
        event = dict(index=0,direction=1,side='long',stop=99,target=110,
                     structure=99,atr=10,rsi_ok=True,volume_ok=True,score=90)
        c = Config(contract_value=.01, tick_size=.1)
        with patch('pullback.features',return_value=rows), patch('pullback.candidates',return_value=iter([event])):
            trades,audit = run(rows,c)
        self.assertEqual(audit[0]['status'],'filled')
        self.assertEqual(trades[0]['exit_reason'],'stop')
        self.assertLessEqual(trades[0]['planned_risk'],c.equity*c.risk)
        self.assertAlmostEqual(trades[0]['entry'],100*(1+c.slippage))
        self.assertLess(trades[0]['net_pnl'],0)

    def test_short_costs(self):
        rows = candles(3)
        rows[1].update(open=100,high=100.5,low=85,close=90)
        event = dict(index=0,direction=-1,side='short',stop=101,target=90,
                     structure=101,atr=10,rsi_ok=True,volume_ok=True,score=90)
        with patch('pullback.features',return_value=rows), patch('pullback.candidates',return_value=iter([event])):
            trades,_ = run(rows,Config())
        self.assertEqual(trades[0]['exit_reason'],'target')
        self.assertGreater(trades[0]['net_pnl'],0)

    def test_decimal_rounding(self):
        self.assertEqual(round_step(.3,.1),.3)
        self.assertEqual(round_step(.39,.1),.3)

    def test_invalid_config(self):
        for overrides in [dict(risk=.02),dict(leverage=20),dict(fee=-1),dict(min_rr=1)]:
            with self.assertRaises(ValueError): replace(Config(),**overrides)


if __name__ == '__main__': unittest.main()
