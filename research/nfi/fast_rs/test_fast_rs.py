import sys,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import numpy as np
sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from NFIShortFastTurning import NFIShortFastTurning
from NFIShortFastRS import strength_features,NFIShortFast60,NFIShortFastShort60,NFIShortFastLong60,NFIShortFastMomentum,NFIShortATRGated


def frames(n=2200):
    x=np.sin(np.arange(n)*.17)*.001+.0001
    date=pd.date_range('2026-01-01',periods=n,freq='5min',tz='UTC')
    btc=pd.DataFrame({'date':date,'close':100*np.exp(np.cumsum(x))})
    coin=pd.DataFrame({'date':date,'close':20*np.exp(np.cumsum(2*x))})
    return coin,btc

class FastTest(unittest.TestCase):
    def test_log_ratio_matches_relative_price_change(self):
        coin,btc=frames(60);f=strength_features(coin,btc)
        want=np.log((coin.close.iloc[-1]/coin.close.iloc[-13])/(btc.close.iloc[-1]/btc.close.iloc[-13]))
        self.assertAlmostEqual(f.rs_60.iloc[-1],want)
    def test_no_future_rows_change_earlier_features(self):
        coin,btc=frames();prefix=strength_features(coin.iloc[:2100],btc.iloc[:2100])
        future=strength_features(coin,btc).iloc[:2100]
        pd.testing.assert_frame_equal(prefix,future)
    def test_exact_match_no_stale_benchmark_forward_fill(self):
        coin,btc=frames(60);btc=btc.drop(index=45)
        f=strength_features(coin,btc)
        self.assertTrue(f.rs_60.iloc[45:58].isna().all())
        self.assertTrue(np.isfinite(f.rs_60.iloc[58]))
    def test_coin_missing_bar_invalidates_trailing_window(self):
        coin,btc=frames(60);coin=coin.drop(index=45).reset_index(drop=True)
        f=strength_features(coin,btc)
        self.assertTrue(f.rs_60.iloc[45:57].isna().all())
        self.assertTrue(np.isfinite(f.rs_60.iloc[57]))
    def test_beta_removes_known_twofold_market_sensitivity(self):
        coin,btc=frames();f=strength_features(coin,btc)
        self.assertAlmostEqual(f.beta_estimate.iloc[-1],2,places=8)
        self.assertAlmostEqual(f.beta_60.iloc[-1],0,places=10)
    def test_beta_fit_ends_before_score_hour(self):
        coin,btc=frames();before=strength_features(coin,btc).beta_estimate.iloc[-1]
        coin.loc[coin.index[-12:],'close']*=np.linspace(1.1,2,12)
        after=strength_features(coin,btc).beta_estimate.iloc[-1]
        self.assertEqual(before,after)
    def filtered(self,kind,values,own=None,pair='X'):
        s=kind.__new__(kind)
        df=pd.DataFrame({'enter_long':[1]*len(values),'enter_short':[1]*len(values),'fast_rs_60':values,'fast_own_60':own if own is not None else values})
        with patch.object(NFIShortATRGated,'populate_entry_trend',return_value=df):return s.populate_entry_trend(df,{'pair':pair})
    def test_both_sides_require_opposite_relative_sign(self):
        r=self.filtered(NFIShortFast60,[.1,-.1,float('nan'),0])
        self.assertEqual(r.enter_long.tolist(),[1,0,0,0]);self.assertEqual(r.enter_short.tolist(),[0,1,0,0])
    def test_single_side_ablation_preserves_other_direction(self):
        r=self.filtered(NFIShortFastShort60,[-.1,.1]);self.assertEqual(r.enter_long.tolist(),[1,1])
        r=self.filtered(NFIShortFastLong60,[-.1,.1]);self.assertEqual(r.enter_short.tolist(),[1,1])
    def test_benchmark_is_exempt_from_self_ranking(self):
        r=self.filtered(NFIShortFast60,[0],pair='BTC/USDT:USDT')
        self.assertEqual(r.enter_long.tolist(),[1]);self.assertEqual(r.enter_short.tolist(),[1])
    def test_relative_strength_does_not_replace_absolute_direction(self):
        r=self.filtered(NFIShortFastMomentum,[.01,-.01],[-.01,.01])
        self.assertEqual(r.enter_long.tolist(),[0,0]);self.assertEqual(r.enter_short.tolist(),[0,0])
    def test_turning_can_accept_improving_still_negative_relative_strength(self):
        s=NFIShortFastTurning.__new__(NFIShortFastTurning)
        df=pd.DataFrame({'fast_rs_15':[-.04,-.04,-.04,-.02,-.06,-.04],'enter_long':[1]*6,'enter_short':[1]*6})
        with patch.object(NFIShortATRGated,'populate_entry_trend',return_value=df):r=s.populate_entry_trend(df,{'pair':'X'})
        self.assertEqual(r.enter_long.tolist(),[0,0,0,1,0,0]);self.assertEqual(r.enter_short.tolist(),[1]*6)
    def test_turning_preserves_benchmark_native_signals(self):
        s=NFIShortFastTurning.__new__(NFIShortFastTurning)
        df=pd.DataFrame({'enter_long':[1],'enter_short':[0]})
        with patch.object(NFIShortATRGated,'populate_entry_trend',return_value=df):r=s.populate_entry_trend(df,{'pair':'BTC/USDT:USDT'})
        self.assertEqual(r.enter_long.tolist(),[1])
    def test_snapshot_excludes_unclosed_and_future_rows(self):
        from nfi_rs_snapshot import closed_rows
        at=pd.Timestamp('2026-01-02T00:00Z');t=int(at.timestamp()*1000)
        rows=[[t-600000],[t-300000],[t],[t+300000]]
        self.assertEqual(closed_rows(rows,at),rows[:2])
    def test_raw_same_window_relative_ranks_equal_usdt_return_ranks(self):
        dates=pd.date_range('2026-01-01',periods=30,freq='5min',tz='UTC')
        btc=pd.DataFrame({'date':dates,'close':np.exp(np.arange(30)*.0007)})
        scores=[];returns=[]
        for drift in [.001,.002,-.001]:
            coin=pd.DataFrame({'date':dates,'close':np.exp(np.arange(30)*drift)})
            scores.append(strength_features(coin,btc).rs_60.iloc[-1]);returns.append(coin.close.iloc[-1]/coin.close.iloc[-13]-1)
        self.assertEqual(np.argsort(scores).tolist(),np.argsort(returns).tolist())
if __name__=='__main__':unittest.main()
