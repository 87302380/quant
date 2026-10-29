import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from datetime import datetime,timezone,timedelta
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).parent))
from NFIShortPMUniform import NFIShortPMHalfAll
from NFIShortPortfolioRisk import btc_risk_features,loss_per_coin,recent_long_stop_guard,NFIShortPMBase,NFIShortPMPortfolio,NFIShortPMLongATR,NFIShortPMHalf,NFIShortPMCorrelation,NFIShortPMSideCap,NFIShortATRGated,Trade

class PortfolioTest(unittest.TestCase):
    def setup_strategy(self,kind=NFIShortPMPortfolio):
        s=kind.__new__(kind);s.config={'fee':.0005}
        s.wallets=SimpleNamespace(get_total_stake_amount=lambda:10000.)
        frame=pd.DataFrame({'research_short_atr':[1.],'pm_vol_ratio':[1.],'pm_btc_hour_return':[0.]})
        s.dp=SimpleNamespace(get_analyzed_dataframe=lambda *a:(frame,None))
        return s
    def test_directional_fee_aware_loss(self):
        self.assertAlmostEqual(loss_per_coin(100,2,False,.0005),2.099)
        self.assertAlmostEqual(loss_per_coin(100,2,True,.0005),2.101)
    def test_features_are_prefix_causal(self):
        n=3000;dates=pd.date_range('2026-01-01',periods=n,freq='5min',tz='UTC')
        btc=pd.DataFrame({'date':dates,'close':100*np.exp(np.cumsum(np.sin(np.arange(n)*.1)*.001))})
        hdates=pd.date_range('2026-01-01',periods=260,freq='h',tz='UTC')
        hourly=pd.DataFrame({'date':hdates,'close':100.,'high':101.,'low':99.})
        prefix=btc_risk_features(btc.iloc[:2500],hourly[hourly.date<=dates[2499]])
        full=btc_risk_features(btc,hourly).iloc[:2500]
        pd.testing.assert_frame_equal(prefix,full)
    def test_sizing_caps_single_and_portfolio_budget(self):
        s=self.setup_strategy()
        with patch.object(NFIShortATRGated,'custom_stake_amount',return_value=10000),patch.object(Trade,'get_trades_proxy',return_value=[]):
            stake=s.custom_stake_amount('X',None,100,10000,1,10000,3,'141','long')
        self.assertLessEqual(stake*3/100*loss_per_coin(100,2,False,.0005),100.000001)
    def test_portfolio_residual_budget_is_shared_not_per_trade(self):
        s=self.setup_strategy();s._pm_long_cache={1:98.}
        trade=SimpleNamespace(id=1,is_short=False,amount=100.,open_rate=100.,nr_of_successful_entries=1)
        with patch.object(Trade,'get_trades_proxy',return_value=[trade]),patch.object(NFIShortATRGated,'custom_stake_amount',return_value=10000):
            self.assertAlmostEqual(s.remaining_risk(10000),90.1)
            stake=s.custom_stake_amount('X',None,100,10000,1,10000,3,'141','long')
            self.assertAlmostEqual(stake*3/100*loss_per_coin(100,2,False,.0005),90.1)
    def test_unknown_open_risk_blocks_new_portfolio_allocation(self):
        s=self.setup_strategy();t=SimpleNamespace(is_short=False,nr_of_successful_entries=0,pair='X')
        with patch.object(Trade,'get_trades_proxy',return_value=[t]):self.assertEqual(s.remaining_risk(10000),0)
    def test_only_real_open_pending_trades_reserve_budget(self):
        s=self.setup_strategy();s._pm_pending={'X':{'risk_reserved':100.}}
        with patch.object(Trade,'get_trades_proxy',return_value=[]):self.assertEqual(s.remaining_risk(10000),300)
        t=SimpleNamespace(is_short=False,nr_of_successful_entries=0,pair='X')
        with patch.object(Trade,'get_trades_proxy',return_value=[t]):self.assertEqual(s.remaining_risk(10000),200)
    def test_half_long_does_not_increase_or_resize_shorts(self):
        s=self.setup_strategy(NFIShortPMHalf)
        with patch.object(NFIShortATRGated,'custom_stake_amount',return_value=100):
            self.assertEqual(s.custom_stake_amount('X',None,100,100,1,1000,3,'141','long'),50)
            self.assertEqual(s.custom_stake_amount('X',None,100,100,1,1000,3,'543','short'),100)
    def test_native_long_profit_exit_retained_and_deadline_prioritized(self):
        s=self.setup_strategy(NFIShortPMLongATR);now=datetime.now(timezone.utc)
        t=SimpleNamespace(is_short=False,id=1,open_date_utc=now)
        s._pm_long_cache={1:98}
        with patch.object(NFIShortATRGated,'custom_exit',return_value='native_profit'):
            self.assertEqual(s.custom_exit('X',t,now,101,.03),'native_profit')
        t.open_date_utc=now-timedelta(hours=24)
        self.assertEqual(s.custom_exit('X',t,now,90,-.3),s.deadline_reason)
    def test_stop_cannot_be_vetoed_by_original_exit_logic(self):
        s=self.setup_strategy(NFIShortPMLongATR);t=SimpleNamespace(is_short=False)
        self.assertTrue(s.confirm_trade_exit('X',t,'limit',1,98,'GTC','stop_loss',None))
    def test_future_and_non_stop_closes_do_not_trigger_guard(self):
        now=datetime.now(timezone.utc)
        t=SimpleNamespace(pair='X',is_short=False,close_date_utc=now+timedelta(minutes=1),exit_reason='stop_loss')
        self.assertFalse(recent_long_stop_guard([t],'X',now))
        t.close_date_utc=now-timedelta(minutes=1);t.exit_reason='native_profit'
        self.assertFalse(recent_long_stop_guard([t],'X',now))
        t.exit_reason='stop_loss';self.assertTrue(recent_long_stop_guard([t],'X',now))
        self.assertFalse(recent_long_stop_guard([t],'Y',now))
    def test_correlation_only_uses_closed_hours(self):
        s=self.setup_strategy();dates=pd.date_range('2026-01-01',periods=170,freq='h',tz='UTC')
        a=pd.Series(np.sin(np.arange(170)*.3),index=dates)
        b=a.copy();b.iloc[-1]=-1000
        s._pm_hour_returns={'A':a,'B':b}
        now=dates[-1]-pd.Timedelta(minutes=5)
        self.assertAlmostEqual(s.pair_correlation('A','B',now),1.)
    def test_side_cap_rejects_third_same_side(self):
        s=self.setup_strategy(NFIShortPMSideCap);now=datetime.now(timezone.utc)
        with patch.object(Trade,'get_trades_proxy',return_value=[SimpleNamespace(is_short=False),SimpleNamespace(is_short=False)]):
            self.assertFalse(s.confirm_trade_entry('X','limit',1,100,'GTC',now,'141','long'))
    def test_correlation_cap_does_not_reject_uncorrelated_second_cluster(self):
        s=self.setup_strategy(NFIShortPMCorrelation);now=datetime.now(timezone.utc)
        trades=[SimpleNamespace(is_short=False,pair=x) for x in ['A','B']]
        with patch.object(Trade,'get_trades_proxy',return_value=trades),patch.object(s,'pair_correlation',side_effect=[.8,.1]),patch.object(NFIShortATRGated,'confirm_trade_entry',return_value=True):
            self.assertTrue(s.confirm_trade_entry('X','limit',1,100,'GTC',now,'141','long'))
    def test_open_position_risk_scales_down_after_partial_exit(self):
        s=self.setup_strategy();s._pm_long_cache={1:98}
        t=SimpleNamespace(id=1,is_short=False,amount=100,open_rate=100,nr_of_successful_entries=1)
        with patch.object(Trade,'get_trades_proxy',return_value=[t]):
            a=s.occupied_risk(10000);t.amount=50
            self.assertAlmostEqual(s.occupied_risk(10000),a/2)

    def test_uniform_control_halves_short_as_well_as_long(self):
        s=self.setup_strategy(NFIShortPMHalfAll)
        with patch.object(NFIShortPMBase,'custom_stake_amount',return_value=100):
            self.assertEqual(s.custom_stake_amount('X',None,100,100,1,1000,3,'141','long'),50)
            self.assertEqual(s.custom_stake_amount('X',None,100,100,1,1000,3,'543','short'),50)
    def test_opposite_directions_do_not_cancel_planned_loss(self):
        s=self.setup_strategy();s._pm_long_cache={1:98};s._short_level_cache={2:(102,96)}
        positions=[SimpleNamespace(id=1,is_short=False,amount=100,open_rate=100,nr_of_successful_entries=1),SimpleNamespace(id=2,is_short=True,amount=100,open_rate=100,nr_of_successful_entries=1)]
        with patch.object(Trade,'get_trades_proxy',return_value=positions):
            self.assertAlmostEqual(s.occupied_risk(10000),420.)
            self.assertEqual(s.remaining_risk(10000),0.)
    def test_global_stop_guard_is_a_rolling_count(self):
        now=datetime.now(timezone.utc)
        stops=[SimpleNamespace(pair=p,is_short=False,exit_reason='trailing_stop_loss',close_date_utc=now-timedelta(minutes=m)) for p,m in [('A',45),('B',30)]]
        self.assertTrue(recent_long_stop_guard(stops,'C',now))
        self.assertFalse(recent_long_stop_guard(stops,'C',now+timedelta(minutes=20)))
if __name__=='__main__':unittest.main()
