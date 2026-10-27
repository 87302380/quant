import unittest
from unittest.mock import patch
from dataclasses import replace
from pullback import Config, features, run
from research import alternative_events, metrics
from test_pullback import candles


class ResearchTests(unittest.TestCase):
    def test_alternatives_causal(self):
        bars=features(candles(8000),Config())
        prefix=features(candles(6000),Config())
        for mode in ('donchian','slow_break20','slow_pullback'):
            a=list(alternative_events(prefix,Config(),mode,3))
            b=[e for e in alternative_events(bars,Config(),mode,3) if e['index']<6000]
            self.assertEqual(a,b)

    def test_no_entries_before_period(self):
        bars=candles(4)
        event=dict(index=0,direction=1,side='long',stop=99,target=110,
                   structure=99,atr=10,rsi_ok=True,volume_ok=True,score=90)
        trades,_=run([],Config(),prepared_bars=bars,event_source=[event],start_time=bars[2]['t'])
        self.assertEqual(trades,[])

    def test_marked_equity_includes_underwater_position(self):
        bars=candles(5)
        for i,b in enumerate(bars): b.update(open=100,high=101,low=98,close=99)
        trade=dict(entry_time=bars[0]['t'],exit_time=bars[-1]['t']+900,quantity=10,
            entry=100,exit=110,stop=90,direction=1,side='long',score=90,
            net_pnl=100,exit_reason='target')
        m,curve,_=metrics([trade],bars,Config(),bars[0]['t'])
        self.assertLess(curve[0][1],10000)
        self.assertEqual(curve[-1][1],10100)
        self.assertGreater(m['max_drawdown_pct'],0)


if __name__=='__main__': unittest.main()
