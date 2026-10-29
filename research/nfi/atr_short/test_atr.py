import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
import pandas as pd
sys.path.insert(0,str(Path(__file__).parent))
from NFIShortATR import relative_weak,NFIShortATRStop,NFIShortATRControl,NFIShortATRGated,NFI24Hour

class ATRTest(unittest.TestCase):
    def test_relative_strength_waits_for_closed_bar(self):
        dates=pd.date_range('2026-01-01',periods=8,freq='4h',tz='UTC')
        coin=pd.DataFrame({'date':dates,'close':[100]*7+[200]})
        btc=pd.DataFrame({'date':dates,'close':[100]*6+[110,110]})
        base=pd.DataFrame({'date':[dates[-1]+pd.Timedelta(hours=3,minutes=50),dates[-1]+pd.Timedelta(hours=3,minutes=55)]})
        self.assertEqual(relative_weak(base,coin,btc).tolist(),[True,False])
    def test_no_future_strength_and_no_missing_warmup(self):
        dates=pd.date_range('2026-01-01',periods=8,freq='4h',tz='UTC')
        x=pd.DataFrame({'date':dates,'close':range(100,108)})
        b=pd.DataFrame({'date':[dates[0]]})
        self.assertEqual(relative_weak(b,x,x).tolist(),[False])
    def test_budget_never_increases_native_stake(self):
        s=NFIShortATRStop.__new__(NFIShortATRStop);s.config={'fee':.0005}
        s.dp=SimpleNamespace(get_analyzed_dataframe=lambda *a:(pd.DataFrame({'research_short_atr':[1.]}),None))
        s.wallets=SimpleNamespace(get_total_stake_amount=lambda:10000)
        with patch.object(NFI24Hour,'custom_stake_amount',return_value=100):
            self.assertEqual(s.custom_stake_amount('X',None,100,100,1,10000,3,'543','short'),100)
        with patch.object(NFI24Hour,'custom_stake_amount',return_value=10000):
            margin=s.custom_stake_amount('X',None,100,10000,1,10000,3,'543','short')
            self.assertLessEqual(margin*3*(.02+.0005*2.02),100.0000001)
    def test_longs_not_resized(self):
        s=NFIShortATRStop.__new__(NFIShortATRStop)
        with patch.object(NFI24Hour,'custom_stake_amount',return_value=123):
            self.assertEqual(s.custom_stake_amount('X',None,100,100,1,10000,3,'141','long'),123)
    def test_short_cannot_add_or_partially_reset(self):
        s=NFIShortATRStop.__new__(NFIShortATRStop)
        self.assertIsNone(s.adjust_trade_position(SimpleNamespace(is_short=True)))
    def test_deadline_prioritized(self):
        s=NFIShortATRStop.__new__(NFIShortATRStop);now=datetime.now(timezone.utc)
        t=SimpleNamespace(is_short=True,open_date_utc=now-timedelta(hours=24))
        self.assertEqual(s.custom_exit('X',t,now,100,-.5),s.deadline_reason)
    def test_gate_blocks_original_shorts_too(self):
        s=NFIShortATRGated.__new__(NFIShortATRGated)
        s.dp=SimpleNamespace(get_pair_dataframe=lambda *a:None)
        df=pd.DataFrame({'enter_short':[1,1],'enter_long':[0,1],'enter_tag':['562','141']})
        with patch.object(NFI24Hour,'populate_entry_trend',return_value=df),patch('NFIShortATR.btc_bear_state',return_value=pd.Series([False,False])):
            out=s.populate_entry_trend(df,{'pair':'X'})
        self.assertEqual(out.enter_short.tolist(),[0,0]);self.assertEqual(out.enter_long.tolist(),[0,1])
    def test_native_profit_exit_retained_for_stop_only(self):
        s=NFIShortATRStop.__new__(NFIShortATRStop);now=datetime.now(timezone.utc)
        t=SimpleNamespace(is_short=True,open_date_utc=now)
        with patch.object(NFI24Hour,'custom_exit',return_value='native_profit'):
            self.assertEqual(s.custom_exit('X',t,now,100,.1),'native_profit')
    def test_long_positive_add_rejected_but_reduction_retained(self):
        s=NFIShortATRStop.__new__(NFIShortATRStop);t=SimpleNamespace(is_short=False)
        with patch.object(NFI24Hour,'adjust_trade_position',return_value=(100,'add')):
            self.assertIsNone(s.adjust_trade_position(t))
        with patch.object(NFI24Hour,'adjust_trade_position',return_value=(-100,'reduce')):
            self.assertEqual(s.adjust_trade_position(t),(-100,'reduce'))
if __name__=='__main__':unittest.main()
