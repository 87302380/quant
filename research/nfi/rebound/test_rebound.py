import sys,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import pandas as pd
import numpy as np
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).parent))
from NFIRebound import fast_state,filter_shorts,NFIReboundFast,NFIReboundSoft,NFIReboundLong,NFIShortExpanded,NFIReboundCover,NFIReboundCooldown,NFIReboundStyles


class ReboundTest(unittest.TestCase):
    def test_four_hour_bull_switch_waits_for_close(self):
        dates=pd.date_range('2026-01-01',periods=80,freq='4h',tz='UTC')
        prices=np.linspace(100,50,80);prices[-1]=1000
        btc=pd.DataFrame({'date':dates,'close':prices})
        base=pd.DataFrame({'date':[dates[-1]+pd.Timedelta(hours=3,minutes=50),dates[-1]+pd.Timedelta(hours=3,minutes=55)]})
        self.assertEqual(fast_state(base,btc).tolist(),[-1,1])

    def test_filter_preserves_long_and_original_short_tags(self):
        df=pd.DataFrame({'enter_long':[1,0],'enter_short':[1,1],'enter_tag':['2 543','506 562']})
        r=filter_shorts(df,pd.Series([True,True]),{'562'},{'506','543','562'})
        self.assertEqual(r.enter_long.tolist(),[1,0]);self.assertEqual(r.enter_short.tolist(),[0,1])
        self.assertEqual(r.enter_tag.tolist(),['2','562'])

    def test_empty_mask_does_not_change_integer_signals(self):
        df=pd.DataFrame({'enter_short':[0],'enter_tag':['141']})
        r=filter_shorts(df,pd.Series([False]),set(),{'543'})
        self.assertEqual(r.enter_short.dtype,np.dtype('int64'))

    def test_soft_sizing_never_clamps_small_short_up_to_minimum(self):
        s=NFIReboundSoft.__new__(NFIReboundSoft)
        with (patch.object(NFIShortExpanded,'custom_stake_amount',return_value=10),patch.object(s,'state_now',return_value=1)):
            self.assertEqual(s.custom_stake_amount('X',None,100,100,5,100,3,'543','short'),0)

    def test_bull_long_sizing_respects_wallet_max(self):
        s=NFIReboundLong.__new__(NFIReboundLong)
        with (patch.object(NFIShortExpanded,'custom_stake_amount',return_value=100),patch.object(s,'state_now',return_value=1)):
            self.assertEqual(s.custom_stake_amount('X',None,100,100,1,110,3,'141','long'),110)

    def test_fast_gate_differentiates_bull_mixed_and_bear(self):
        s=NFIReboundFast.__new__(NFIReboundFast)
        df=pd.DataFrame({'enter_short':[1,1,1],'enter_long':[0,0,0],
                         'enter_tag':['562','506 562','543'],'research_btc_fast_state':[1,0,-1]})
        with patch.object(NFIShortExpanded,'populate_entry_trend',return_value=df):
            result=s.populate_entry_trend(df,{'pair':'X'})
        self.assertEqual(result.enter_short.tolist(),[0,1,1])
        self.assertEqual(result.enter_tag.tolist(),['','562','543'])

    def test_cooldown_excludes_future_closes_and_expires(self):
        s=NFIReboundCooldown.__new__(NFIReboundCooldown);now=datetime(2026,1,10,tzinfo=timezone.utc)
        trades=[SimpleNamespace(is_short=True,close_date=now-timedelta(hours=i+1),close_date_utc=now-timedelta(hours=i+1),enter_tag='543 ',close_profit=-.01) for i in range(5)]
        self.assertTrue(s.blocked('543',now,trades))
        self.assertFalse(s.blocked('543',now+timedelta(hours=73),trades))
        future=SimpleNamespace(is_short=True,close_date=now+timedelta(hours=1),close_date_utc=now+timedelta(hours=1),enter_tag='543',close_profit=-1)
        self.assertFalse(s.blocked('543',now,trades[:4]+[future]))

    def test_cover_uses_whole_campaign_net_pnl(self):
        s=NFIReboundCover.__new__(NFIReboundCover);now=datetime(2026,1,2,tzinfo=timezone.utc)
        t=SimpleNamespace(is_short=True,open_date_utc=now-timedelta(hours=2),entry_side='sell',exit_side='buy',select_filled_orders=lambda side:[])
        with (patch.object(s,'state_now',return_value=1),patch.object(s,'calc_total_profit',return_value=(-10,0,0,0))):
            self.assertEqual(s.custom_exit('X',t,now,100,.1),s.reason)

    def test_cover_cannot_postpone_deadline(self):
        s=NFIReboundCover.__new__(NFIReboundCover);now=datetime(2026,1,2,tzinfo=timezone.utc)
        t=SimpleNamespace(open_date_utc=now-timedelta(hours=24))
        self.assertEqual(s.custom_exit('X',t,now,100,-.5),s.deadline_reason)

    def test_style_gate_keeps_failed_breakout_but_filters_continuation(self):
        s=NFIReboundStyles.__new__(NFIReboundStyles)
        df=pd.DataFrame({'enter_short':[1,1,1],'enter_long':[0,0,0],'enter_tag':['545','506','543'],
                         'research_btc_fast_state':[1,1,0]})
        with patch.object(NFIShortExpanded,'populate_entry_trend',return_value=df):
            result=s.populate_entry_trend(df,{'pair':'X'})
        self.assertEqual(result.enter_short.tolist(),[1,0,1])


if __name__=='__main__':unittest.main()
