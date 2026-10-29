import importlib.util
from pathlib import Path
from datetime import datetime,timezone
from types import SimpleNamespace
from unittest.mock import patch
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location('ytdrisk',Path(__file__).with_name('NFIYtdRisk.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class RiskTest(unittest.TestCase):
    def test_sizing_reserves_roundtrip_cost_and_risk_scales(self):
        stake=m.margin_for_risk(50,100,97,3)
        self.assertAlmostEqual(stake*3*(.03+.0005*(1+.97)),50)
        short=m.margin_for_risk(50,100,103,3)
        self.assertAlmostEqual(short*3*(.03+.0005*(1+1.03)),50)
        self.assertEqual(m.margin_for_risk(-1,100,97,3),0)
        self.assertLess(m.margin_for_risk(50,100,94,3),stake)

    def test_atr_uses_closed_bar_and_direction_budget(self):
        s=m.NFIYtdDirection.__new__(m.NFIYtdDirection)
        now=datetime(2026,1,1,tzinfo=timezone.utc);stamp=int(now.timestamp()*1000)
        s._risk_frames={'X':(np.array([stamp,stamp+14400000]),np.array([2.,90.]))}
        self.assertEqual(s.stop_price('X',now,100,False),96)
        self.assertEqual(s.stop_price('X',now,100,True),104)
        trades=[SimpleNamespace(is_short=False,get_custom_data=lambda **k:50),SimpleNamespace(is_short=True,get_custom_data=lambda **k:100)]
        with patch.object(m.Trade,'get_trades_proxy',return_value=trades):
            self.assertEqual(s.remaining_direction(False,10000),100)
            self.assertEqual(s.remaining_direction(True,10000),50)

    def test_adds_share_frozen_campaign_budget(self):
        s=m.NFIYtdBudget.__new__(m.NFIYtdBudget)
        t=SimpleNamespace(is_short=False,entry_side='buy',exit_side='sell',leverage=3,
                          get_custom_data=lambda key,default=None: {'research_stop':97,'research_budget':50}.get(key,default),
                          select_filled_orders=lambda side:[])
        with (patch.object(m.NFI24Hour,'adjust_trade_position',return_value=(1000,'add')),
              patch.object(s,'calc_total_profit',return_value=(-45,0,0,0))):
            amount,tag=s.adjust_trade_position(t,datetime.now(timezone.utc),100,current_profit=-.1,min_stake=1)
            self.assertAlmostEqual(amount*3*(.03+.0005*(1+.97)),5)
            self.assertEqual(tag,'add')

    def test_final_exit_has_no_remaining_stop_exposure(self):
        s=m.NFIYtdBudget.__new__(m.NFIYtdBudget)
        order=SimpleNamespace(ft_order_side='sell',safe_filled=1)
        trade=SimpleNamespace(entry_side='buy',exit_side='sell',
                              get_custom_data=lambda **kw:97,
                              select_filled_orders=lambda side:[order])
        with (patch.object(m.NFI24Hour,'order_filled'),
              patch.object(s,'calc_total_profit',side_effect=AssertionError('zero remaining notional'))):
            s.order_filled('X',trade,order,datetime.now(timezone.utc))


if __name__=='__main__':unittest.main()
