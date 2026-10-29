"""Risk invariants: fixed first-entry stop, causal gate and whole-campaign stale exit."""
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import pandas as pd

spec = importlib.util.spec_from_file_location('risk_controls', Path(__file__).with_name('NFIRiskControls.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RiskControlsTest(unittest.TestCase):
    def test_overheat_is_directional_and_preserves_neutral_signals(self):
        strategy=module.NFIRiskOverheat80.__new__(module.NFIRiskOverheat80)
        data=pd.DataFrame({'RSI_14_4h':[19,20,50,80,81],
                           'enter_long':[1]*5,'enter_short':[1]*5})
        with patch.object(module.NFI24Hour,'populate_entry_trend',side_effect=lambda df,meta:df):
            result=strategy.populate_entry_trend(data,{'pair':'X'})
        self.assertEqual(result.enter_long.tolist(),[1,1,1,0,0])
        self.assertEqual(result.enter_short.tolist(),[0,0,1,1,1])

    def test_profit_protection_arms_from_closed_price_and_persists(self):
        strategy=module.NFIRiskProfitProtect.__new__(module.NFIRiskProfitProtect)
        state={}
        frame=pd.DataFrame({'close':[101.9]})
        strategy.dp=SimpleNamespace(get_analyzed_dataframe=lambda *args:(frame,None))
        trade=SimpleNamespace(entry_side='buy',is_short=False,leverage=3,
                             open_date_utc=datetime(2026,7,1,tzinfo=timezone.utc),
                             select_filled_orders=lambda side:[SimpleNamespace(safe_price=100)],
                             get_custom_data=lambda key,default=None:state.get(key,default),
                             set_custom_data=lambda key,value:state.update({key:value}))
        self.assertIsNone(strategy.protection_price('X',trade))
        frame.loc[0,'close']=102
        self.assertAlmostEqual(strategy.protection_price('X',trade),100.15)
        frame.loc[0,'close']=101
        self.assertAlmostEqual(strategy.protection_price('X',trade),100.15)
        self.assertEqual(strategy.custom_exit('X',trade,trade.open_date_utc+timedelta(hours=1),100,-.01),
                         'research_profit_protect_gap')
        state.clear();trade.is_short=True;frame.loc[0,'close']=98
        self.assertAlmostEqual(strategy.protection_price('X',trade),99.85)

    def test_price_stop_uses_first_entry_and_bypasses_native_veto(self):
        strategy = module.NFIRiskStop3.__new__(module.NFIRiskStop3)
        trade = SimpleNamespace(entry_side='buy', open_rate=80, leverage=3, is_short=False,
                                select_filled_orders=lambda side:[SimpleNamespace(safe_price=100),SimpleNamespace(safe_price=80)])
        now = datetime(2026,7,1,tzinfo=timezone.utc)
        self.assertAlmostEqual(strategy.custom_stoploss('X',trade,now,100,-.1,after_fill=True),.09)
        trade.is_short=True
        self.assertAlmostEqual(strategy.custom_stoploss('X',trade,now,100,-.1),.09)
        with patch.object(module.NFI24Hour,'confirm_trade_exit',return_value=False):
            self.assertTrue(strategy.confirm_trade_exit('X',trade,'limit',1,1,'GTC','stop_loss',now))
            self.assertFalse(strategy.confirm_trade_exit('X',trade,'limit',1,1,'GTC','custom_exit',now))

    def test_stale_tests_net_campaign_not_residual_loss(self):
        strategy = module.NFIRiskStale12.__new__(module.NFIRiskStale12)
        opened = datetime(2026,7,1,tzinfo=timezone.utc)
        trade=SimpleNamespace(open_date_utc=opened, entry_side='buy',exit_side='sell',select_filled_orders=lambda side:[])
        with patch.object(strategy,'calc_total_profit',return_value=(10,0,0,0)):
            self.assertFalse(strategy.stale(trade,opened+timedelta(hours=13),1))
        with patch.object(strategy,'calc_total_profit',return_value=(-10,0,0,0)):
            self.assertFalse(strategy.stale(trade,opened+timedelta(hours=11),1))
            self.assertTrue(strategy.stale(trade,opened+timedelta(hours=12),1))

    def test_four_hour_close_not_known_before_last_base_candle_closes(self):
        strategy=module.NFIRiskTrendGate.__new__(module.NFIRiskTrendGate)
        data=pd.DataFrame({'date':pd.to_datetime(['2026-07-01T03:50Z','2026-07-01T03:55Z']),
                           'EMA_12_4h':[110,110],'EMA_200_4h':[100,100],
                           'enter_long':[1,1],'enter_short':[1,1]})
        info=pd.DataFrame({'date':pd.to_datetime(['2026-06-30T20:00Z','2026-07-01T00:00Z','2026-07-01T04:00Z']),
                           'close':[90,120,1]})
        strategy.dp=SimpleNamespace(get_pair_dataframe=lambda *args:info)
        with patch.object(module.NFI24Hour,'populate_entry_trend',side_effect=lambda df,meta:df):
            result=strategy.populate_entry_trend(data,{'pair':'X'})
        self.assertEqual(result.enter_long.tolist(),[0,1])
        self.assertEqual(result.enter_short.tolist(),[0,0])


if __name__ == '__main__':unittest.main()
