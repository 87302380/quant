import sys,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
from datetime import datetime,timedelta,timezone
import pandas as pd
import numpy as np
sys.path.insert(0,str(Path(__file__).parent))
from NFIShortLongFamily import *
class FamilyTest(unittest.TestCase):
    def hours(self):
        c=np.r_[np.arange(100.,165.),[160.,155.,150.,145.,140.]]
        return pd.DataFrame({'date':pd.date_range('2026-01-01',periods=len(c),freq='h',tz='UTC'),'close':c})
    def filtered(self,cls,pair='X'):
        f=pd.DataFrame({'enter_long':[1]*5,'enter_short':[1]*5,'enter_tag':['64','141','64 141','999','65'],'lf_up':[False]*5,'lf_recover':[False]*5})
        s=cls.__new__(cls)
        with patch.object(NFIShortATRGated,'populate_entry_trend',return_value=f):return s.populate_entry_trend(f,{'pair':pair})
    def test_families_cover_all_enabled_tags(self):
        enabled={k.split('_')[-2] for k,v in NFIShortATRGated.long_entry_signal_params.items() if v}
        self.assertEqual(TREND|DIP,enabled);self.assertFalse(TREND&DIP)
    def test_mixed_and_unknown_are_not_relabelled(self):
        self.assertEqual(signal_family('64 141'),'mixed_or_unknown');self.assertEqual(signal_family('999'),'mixed_or_unknown');self.assertEqual(signal_family(''),'mixed_or_unknown')
    def test_trend_guard_preserves_dips_mixed_unknown(self):self.assertEqual(self.filtered(NFIShortLFTrendGate).enter_long.tolist(),[0,1,1,1,0])
    def test_dip_guard_preserves_trend_mixed_unknown(self):self.assertEqual(self.filtered(NFIShortLFDipRecovery).enter_long.tolist(),[1,0,1,1,1])
    def test_short_signals_and_tags_are_preserved(self):
        f=self.filtered(NFIShortLFTrendGate);self.assertEqual(f.enter_short.tolist(),[1]*5);self.assertEqual(f.enter_tag.tolist(),['64','141','64 141','999','65'])
    def test_btc_is_exempt_from_self_relative_filter(self):self.assertEqual(self.filtered(NFIShortLFDipRecovery,'BTC/USDT:USDT').enter_long.tolist(),[1]*5)
    def test_hour_is_not_available_before_close(self):
        h=self.hours();at=h.date.iloc[60];base=pd.DataFrame({'date':[at+pd.Timedelta(minutes=50),at+pd.Timedelta(minutes=55)]})
        altered=h.copy();altered.loc[60,'close']=1
        a=hourly_state(base,h);b=hourly_state(base,altered)
        self.assertEqual(a.lf_up.iloc[0],b.lf_up.iloc[0]);self.assertNotEqual(a.lf_up.iloc[1],b.lf_up.iloc[1])
    def test_future_hours_do_not_change_earlier_features(self):
        h=self.hours();b=pd.DataFrame({'date':pd.date_range(h.date.iloc[55],h.date.iloc[60],freq='5min')})
        pd.testing.assert_frame_equal(hourly_state(b,h),hourly_state(b,h.iloc[:61]))
    def test_missing_hour_does_not_carry_old_state(self):
        h=self.hours();at=h.date.iloc[60]+pd.Timedelta(minutes=55);h=h.iloc[:60]
        self.assertFalse(hourly_state(pd.DataFrame({'date':[at]}),h).iloc[0].any())
    def test_native_timestamp_units_are_normalized(self):
        h=self.hours();h['date']=h.date.astype('datetime64[us, UTC]')
        b=pd.DataFrame({'date':[h.date.iloc[60]+pd.Timedelta(minutes=55)]});b['date']=b.date.astype('datetime64[ms, UTC]')
        self.assertTrue(hourly_state(b,h).lf_up.iloc[0])
    def test_limit_is_bounded_and_missing_atr_preserves_quote(self):
        self.assertEqual(dip_limit(100,2),99);self.assertEqual(dip_limit(100,100),98.1);self.assertEqual(dip_limit(100,float('nan')),100)
    def test_entry_price_preserves_shorts_and_trend_signals(self):
        s=NFIShortLFDipLimit.__new__(NFIShortLFDipLimit)
        for side,tag in [('short','141'),('long','64')]:self.assertEqual(s.custom_entry_price('X',None,None,100,tag,side),100)
    def test_exit_needs_two_hours_and_does_not_override_short(self):
        s=NFIShortLFTrendExit.__new__(NFIShortLFTrendExit);s.dp=SimpleNamespace(get_analyzed_dataframe=lambda *a:(pd.DataFrame({'lf_failed':[True]}),None))
        now=datetime(2026,1,1,tzinfo=timezone.utc);trade=SimpleNamespace(open_date_utc=now,enter_tag='64',is_short=False)
        with patch.object(NFIShortLFTrendExit,'expired',return_value=False),patch.object(NFIShortATRGated,'custom_exit',return_value='native'):
            self.assertEqual(s.custom_exit('X',trade,now+timedelta(hours=1),90,-.1),'native')
            self.assertEqual(s.custom_exit('X',trade,now+timedelta(hours=2),90,-.1),'research_long_trend_failure')
            trade.is_short=True;self.assertEqual(s.custom_exit('X',trade,now+timedelta(hours=2),90,.1),'native')
if __name__=='__main__':unittest.main()
