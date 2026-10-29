import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime,timedelta,timezone
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).parent))
from breadth import market_features
from NFIShortBreadthClimax import NFIShortBRClimax,NFIShortBRClimaxAfter
from NFIShortBreadth import NFIShortBRControl,NFIShortBRGate,NFIShortBRExit,NFIShortBRLongCap,NFIShortATRGated,Trade

def frames(n=400,count=24,shock=True):
    ret=np.sin(np.arange(n)*.27)*.001
    if shock:ret[-3:]=-.02
    close=100*np.exp(np.cumsum(ret))
    return {str(k):pd.DataFrame({'date':pd.date_range('2026-01-01',periods=n,freq='5min',tz='UTC'),'close':close*(1+k*.01)}) for k in range(count)}
class BreadthTest(unittest.TestCase):
    def test_prefix_invariance(self):
        f=frames();a=market_features({k:v.iloc[:350] for k,v in f.items()});b=market_features(f).iloc[:350]
        pd.testing.assert_frame_equal(a,b)
    def test_future_listing_does_not_change_past_denominator(self):
        f=frames();base=market_features(f);new=f['0'].copy();new.date+=pd.Timedelta(days=20);f['future']=new
        pd.testing.assert_frame_equal(base,market_features(f).iloc[:len(base)])
    def test_large_synchronized_decline_is_detected(self):
        r=market_features(frames()).iloc[-1];self.assertTrue(r.bre_raw);self.assertEqual(r.bre_down_fraction,1);self.assertEqual(r.bre_valid_count,24)
    def test_price_rally_is_not_a_short_signal(self):
        f=frames()
        for v in f.values():v.loc[v.index[-3:],'close']=v.close.iloc[-4]*np.exp(np.array([.02,.04,.06]))
        self.assertFalse(market_features(f).bre_raw.iloc[-1])
    def test_many_small_declines_are_not_extreme_shock(self):
        f=frames()
        for v in f.values():v.loc[v.index[-3:],'close']=v.close.iloc[-4]*np.exp(np.array([-.00001,-.00002,-.00003]))
        r=market_features(f).iloc[-1];self.assertEqual(r.bre_down_fraction,1);self.assertFalse(r.bre_raw)
    def test_fewer_than_twenty_coins_is_unknown(self):
        r=market_features(frames(count=19)).iloc[-1];self.assertFalse(r.bre_known);self.assertFalse(r.bre_raw)
    def test_missing_current_coins_do_not_shrink_mature_denominator(self):
        f=frames()
        for k in list(f)[:5]:f[k]=f[k].iloc[:-1]
        r=market_features(f).iloc[-1];self.assertEqual(r.bre_mature_count,24);self.assertEqual(r.bre_valid_count,19);self.assertFalse(r.bre_known)
    def test_gap_invalidates_volatility_window(self):
        f=frames();f['0']=f['0'].drop(index=370)
        self.assertEqual(market_features(f).bre_valid_count.iloc[-1],23)
    def test_current_shock_is_excluded_from_normalization(self):
        a=frames(shock=False);b=frames(shock=True)
        ra=market_features(a);rb=market_features(b)
        self.assertTrue(rb.bre_raw.iloc[-1]);self.assertFalse(ra.bre_raw.iloc[-1])
        prior=np.sin(np.arange(400)*.27)*.001
        expected=-.06/(np.std(prior[109:397],ddof=1)*np.sqrt(3))
        self.assertAlmostEqual(rb.bre_median_z.iloc[-1],expected,places=8)
        pd.testing.assert_frame_equal(ra.iloc[:-3],rb.iloc[:-3])
    def test_duplicate_observations_are_rejected(self):
        f=frames();f['0']=pd.concat([f['0'],f['0'].iloc[-1:]])
        with self.assertRaises(ValueError):market_features(f)
    def test_gate_blocks_unknown_and_shock_but_preserves_shorts(self):
        s=NFIShortBRGate.__new__(NFIShortBRGate);df=pd.DataFrame({'enter_long':[1]*3,'enter_short':[1]*3,'enter_tag':['a','b','c'],'bre_known':[False,True,True],'bre_recent':[False,True,False]})
        with patch.object(NFIShortATRGated,'populate_entry_trend',return_value=df):r=s.populate_entry_trend(df,{'pair':'X'})
        self.assertEqual(r.enter_long.tolist(),[0,0,1]);self.assertEqual(r.enter_short.tolist(),[1]*3);self.assertEqual(r.enter_tag.tolist(),['a','b','c'])
    def test_exit_ignores_pre_entry_and_future_observations(self):
        s=NFIShortBRExit.__new__(NFIShortBRExit);now=datetime(2026,1,1,tzinfo=timezone.utc);t=SimpleNamespace(open_date_utc=now,is_short=False)
        frame=pd.DataFrame({'date':[now-timedelta(minutes=5)],'bre_raw':[True]});s.dp=SimpleNamespace(get_analyzed_dataframe=lambda *a:(frame,None))
        with patch.object(s,'expired',return_value=False),patch.object(NFIShortATRGated,'custom_exit',return_value='native'):
            self.assertEqual(s.custom_exit('X',t,now,1,0),'native')
            frame.loc[0,'date']=now;self.assertEqual(s.custom_exit('X',t,now+timedelta(minutes=5),1,0),'research_breadth_exit')
            self.assertEqual(s.custom_exit('X',t,now,1,0),'native')
    def test_deadline_has_priority_and_shorts_use_native(self):
        s=NFIShortBRExit.__new__(NFIShortBRExit);now=datetime(2026,1,1,tzinfo=timezone.utc);t=SimpleNamespace(open_date_utc=now,is_short=True)
        with patch.object(s,'expired',return_value=True):self.assertEqual(s.custom_exit('X',t,now,1,0),s.deadline_reason)
        with patch.object(s,'expired',return_value=False),patch.object(NFIShortATRGated,'custom_exit',return_value='native'):self.assertEqual(s.custom_exit('X',t,now,1,0),'native')
    def test_long_cap_reserves_pending_longs_and_preserves_shorts(self):
        s=NFIShortBRLongCap.__new__(NFIShortBRLongCap)
        trades=[SimpleNamespace(is_short=False),SimpleNamespace(is_short=False),SimpleNamespace(is_short=True)]
        with patch.object(Trade,'get_trades_proxy',return_value=trades),patch.object(NFIShortATRGated,'confirm_trade_entry',return_value=True):
            args=['X','limit',1,1,'gtc',None,'a']
            self.assertFalse(s.confirm_trade_entry(*args,'long'));self.assertTrue(s.confirm_trade_entry(*args,'short'))
    def climax_frame(self):
        return pd.DataFrame({'enter_long':[1]*4,'enter_short':[1]*4,'enter_tag':['141','64','64 141','141'],'bre_known':[True]*4,'bre_recent':[False,False,False,True],'bre_raw':[False,False,False,True]})
    def test_climax_uses_shock_only_for_pure_dip_family(self):
        s=NFIShortBRClimax.__new__(NFIShortBRClimax);f=self.climax_frame()
        with patch.object(NFIShortBRControl,'populate_entry_trend',return_value=f):r=s.populate_entry_trend(f,{'pair':'X'})
        self.assertEqual(r.enter_long.tolist(),[0,1,1,1]);self.assertEqual(r.enter_short.tolist(),[1]*4)
    def test_climax_after_rejects_current_shock(self):
        s=NFIShortBRClimaxAfter.__new__(NFIShortBRClimaxAfter);f=self.climax_frame()
        with patch.object(NFIShortBRControl,'populate_entry_trend',return_value=f):r=s.populate_entry_trend(f,{'pair':'X'})
        self.assertEqual(r.enter_long.tolist(),[0,1,1,0])
    def test_climax_unknown_does_not_create_opportunity(self):
        s=NFIShortBRClimax.__new__(NFIShortBRClimax);f=self.climax_frame();f.loc[3,'bre_known']=False
        with patch.object(NFIShortBRControl,'populate_entry_trend',return_value=f):r=s.populate_entry_trend(f,{'pair':'X'})
        self.assertEqual(r.enter_long.iloc[3],0)
    def test_climax_after_accepts_recent_but_not_current_shock(self):
        s=NFIShortBRClimaxAfter.__new__(NFIShortBRClimaxAfter);f=self.climax_frame();f.loc[3,'bre_raw']=False
        with patch.object(NFIShortBRControl,'populate_entry_trend',return_value=f):r=s.populate_entry_trend(f,{'pair':'X'})
        self.assertEqual(r.enter_long.iloc[3],1);self.assertEqual(r.enter_tag.tolist(),['141','64','64 141','141'])
if __name__=='__main__':unittest.main()
