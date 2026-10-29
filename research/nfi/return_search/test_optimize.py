import importlib.util
from pathlib import Path
from unittest.mock import patch
import unittest
import pandas as pd
import numpy as np
import sys
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).parent))
from NFIExtensions import NFIOptTrendRunner

spec=importlib.util.spec_from_file_location('optimize',Path(__file__).with_name('NFIOptimize.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class OptimizeTest(unittest.TestCase):
    def test_relative_strength_never_reads_unclosed_four_hour_bar(self):
        dates=pd.date_range('2026-01-01',periods=8,freq='4h',tz='UTC')
        own=pd.DataFrame({'date':dates,'close':[100.]*6+[110.,10000.]})
        btc=pd.DataFrame({'date':dates,'close':[100.]*8})
        base=pd.DataFrame({'date':pd.to_datetime(['2026-01-02T03:50:00Z','2026-01-02T03:55:00Z','2026-01-02T07:50:00Z'])})
        rs=m.closed_relative_strength(base,own,btc)
        self.assertTrue(np.isnan(rs.iloc[0]));self.assertAlmostEqual(rs.iloc[1],.1);self.assertAlmostEqual(rs.iloc[2],.1)

    def test_no_adds_keeps_partial_reductions(self):
        s=m.NFIOptNoAdds.__new__(m.NFIOptNoAdds)
        with patch.object(m.NFI24Hour,'adjust_trade_position',return_value=(-30,'reduce')):
            self.assertEqual(s.adjust_trade_position(None,None),(-30,'reduce'))
        with patch.object(m.NFI24Hour,'adjust_trade_position',return_value=(30,'add')):
            self.assertIsNone(s.adjust_trade_position(None,None))

    def test_size_control_restores_original_management(self):
        self.assertFalse(m.NFIOptSizeOnly.use_custom_stoploss)
        self.assertIs(m.NFIOptSizeOnly.adjust_trade_position,m.NFI24Hour.adjust_trade_position)
        self.assertIs(m.NFIOptSizeOnly.order_filled,m.NFI24Hour.order_filled)

    def test_runner_cannot_postpone_deadline(self):
        s=NFIOptTrendRunner.__new__(NFIOptTrendRunner)
        now=datetime(2026,1,2,tzinfo=timezone.utc)
        t=SimpleNamespace(open_date_utc=now-timedelta(hours=24))
        self.assertEqual(s.custom_exit('X',t,now,100,1),s.deadline_reason)

    def test_runner_does_not_delay_a_net_losing_campaign(self):
        s=NFIOptTrendRunner.__new__(NFIOptTrendRunner)
        now=datetime(2026,1,2,tzinfo=timezone.utc)
        df=pd.DataFrame({'close':[100,101],'EMA_20':[98,99],'EMA_12_4h':[100,100],'EMA_50_4h':[90,90]})
        s.dp=SimpleNamespace(get_analyzed_dataframe=lambda *a:(df,None))
        t=SimpleNamespace(open_date_utc=now-timedelta(hours=1),is_short=False,entry_side='buy',exit_side='sell',
                          get_custom_data=lambda **kw:False,select_filled_orders=lambda side:[])
        with (patch.object(m.NFIRiskOverheat80,'custom_exit',return_value='exit_profit_long'),
              patch.object(s,'calc_total_profit',return_value=(-1,0,0,0))):
            self.assertEqual(s.custom_exit('X',t,now,101,.01),'exit_profit_long')


if __name__=='__main__':unittest.main()
