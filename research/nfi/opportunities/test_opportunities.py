import sys,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).parent))
from NFIShortOpportunities import *
from NFIShortOPMore import NFIShortOPCompression,NFIShortOPContext
from NFIShortOPFixed import NFIShortOPFixedControl
from op_features import aligned_trend,retest_features
class OpportunityTest(unittest.TestCase):
    def test_shallow_copy_isolates_signal_column_writes(self):
        f=pd.DataFrame({'close':[10.,20.],'enter_long':[0,0]});a=f.copy(deep=False);b=f.copy(deep=False)
        a.loc[0,'enter_long']=1;a.loc[0,'close']=99
        self.assertEqual(b.enter_long.tolist(),[0,0]);self.assertEqual(f.close.tolist(),[10.,20.])
    def test_native_flags_preserve_original_enabled_set(self):
        p=params(EXTRA)
        self.assertTrue(all(p[k] for k,v in ORIGINAL.items() if v))
        changed={int(k.split('_')[-2]) for k,v in p.items() if v and not ORIGINAL.get(k,False)}
        self.assertEqual(changed,EXTRA)
    def signals(self):
        a=pd.DataFrame({'enter_long':[1,0,0,0],'enter_short':[0,1,0,0],'enter_tag':['141','505','',''],'volume':[1]*4})
        b=a.copy();b.enter_long=1;b.enter_tag=['141 165','505 165','141 165','141']
        return a,b
    def test_original_priority_and_new_tags_are_explicit(self):
        s=NFIShortOPNative.__new__(NFIShortOPNative);a,b=self.signals()
        with patch.object(NFIShortBRClimax,'populate_entry_trend',side_effect=[a,b]):r=s.populate_entry_trend(a.copy(),{'pair':'X'})
        self.assertEqual(r.enter_long.tolist(),[1,0,1,0]);self.assertEqual(r.enter_short.tolist(),[0,1,0,0]);self.assertEqual(r.enter_tag.tolist(),['141','505',PREFIX+'native_165',''])
    def test_parameter_state_restored_even_on_exception(self):
        s=NFIShortOPNative.__new__(NFIShortOPNative);before=s.long_entry_signal_params
        with patch.object(NFIShortBRClimax,'populate_entry_trend',side_effect=ValueError('test')):
            with self.assertRaises(ValueError):s.populate_entry_trend(pd.DataFrame(),{'pair':'X'})
        self.assertIs(s.long_entry_signal_params,before)
    def test_extra_token_matching_is_exact(self):
        self.assertEqual(extra_tokens('1650 165 141 48',EXTRA),['48','165'])
    def test_risk_budget_includes_fees(self):
        stake=planned_margin(1000,1000,1000,10000,100,20,3,.001,None)
        risk=stake*3/100*(20+.001*(100+80))
        self.assertAlmostEqual(risk,50)
    def test_quarter_slot_ceiling(self):self.assertEqual(planned_margin(1000,1000,1000,10000,100,1,3,.0005,None),250)
    def test_minimum_order_does_not_override_budget(self):self.assertEqual(planned_margin(1000,1000,1000,1000,100,20,3,.001,10),0)
    def test_higher_fee_reduces_binding_risk_allocation(self):
        a=planned_margin(10000,10000,10000,10000,100,20,3,.0005,None);b=planned_margin(10000,10000,10000,10000,100,20,3,.001,None);self.assertLess(b,a)
    def test_unclosed_hour_does_not_change_past(self):
        h=pd.DataFrame({'date':pd.date_range('2026-01-01',periods=100,freq='h',tz='UTC'),'close':np.arange(100.,200.)})
        at=h.date.iloc[-1];base=pd.DataFrame({'date':[at+pd.Timedelta(minutes=50),at+pd.Timedelta(minutes=55)]})
        a=aligned_trend(base,h,1,'h');h.loc[99,'close']=1;b=aligned_trend(base,h,1,'h')
        self.assertEqual(a[0],b[0]);self.assertNotEqual(a[1],b[1])
    def test_trend_prefix_invariance_across_timestamp_units(self):
        h=pd.DataFrame({'date':pd.date_range('2026-01-01',periods=120,freq='h',tz='UTC'),'close':np.arange(100.,220.)});h.date=h.date.astype('datetime64[us, UTC]')
        b=pd.DataFrame({'date':pd.date_range(h.date.iloc[60],h.date.iloc[80],freq='5min')});b.date=b.date.astype('datetime64[ms, UTC]')
        np.testing.assert_equal(aligned_trend(b,h,1,'x'),aligned_trend(b,h.iloc[:81],1,'x'))
    def pattern(self):
        n=80;f=pd.DataFrame({'date':pd.date_range('2026-01-01',periods=n,freq='5min',tz='UTC'),'open':[100.]*n,'high':[100.5]*n,'low':[99.5]*n,'close':[100.]*n,'volume':[1.]*n})
        f.loc[50,['open','high','low','close','volume']]=[100.1,101.2,99.9,101.,5.]
        f.loc[51,['open','high','low','close']]=[100.45,101.,100.4,100.6]
        btc=f[['date','close']].copy();btc.close=100.
        return f,btc
    def test_retest_requires_prior_breakout_and_is_prefix_causal(self):
        f,btc=self.pattern()
        with patch('op_features.aligned_trend',side_effect=lambda b,*a:np.ones(len(b),dtype=bool)):
            a=retest_features(f,pd.DataFrame(),pd.DataFrame(),btc);b=retest_features(f.iloc[:60],pd.DataFrame(),pd.DataFrame(),btc.iloc[:60])
        self.assertFalse(a.op_retest.iloc[50]);self.assertTrue(a.op_retest.iloc[51]);pd.testing.assert_frame_equal(a.iloc[:60],b)
    def test_missing_btc_invalidates_relative_confirmation(self):
        f,btc=self.pattern();btc=btc.drop(index=45)
        with patch('op_features.aligned_trend',side_effect=lambda b,*a:np.ones(len(b),dtype=bool)):r=retest_features(f,pd.DataFrame(),pd.DataFrame(),btc)
        self.assertTrue(np.isnan(r.op_rs60.iloc[51]));self.assertFalse(r.op_retest.iloc[51])
    def test_extra_slot_cap_does_not_block_original_signals(self):
        s=NFIShortOPCombined.__new__(NFIShortOPCombined);trades=[SimpleNamespace(enter_tag=PREFIX+'x') for _ in range(2)]
        with patch.object(Trade,'get_trades_proxy',return_value=trades),patch.object(NFIShortBRClimax,'confirm_trade_entry',return_value=True):
            args=['X','limit',1,1,'gtc',None]
            self.assertFalse(s.confirm_trade_entry(*args,PREFIX+'x','long'));self.assertTrue(s.confirm_trade_entry(*args,'141','long'))
    def test_new_trades_cannot_add_or_partially_reduce(self):
        s=NFIShortOPNative.__new__(NFIShortOPNative)
        self.assertIsNone(s.adjust_trade_position(SimpleNamespace(enter_tag=PREFIX+'native_165')))
    def test_new_stop_exits_bypass_native_veto_and_deadline_is_first(self):
        s=NFIShortOPNative.__new__(NFIShortOPNative);t=SimpleNamespace(enter_tag=PREFIX+'native_165')
        with patch.object(NFIShortBRClimax,'confirm_trade_exit',return_value=False):self.assertTrue(s.confirm_trade_exit('X',t,'limit',1,1,'gtc','stop_loss',None))
        with patch.object(s,'expired',return_value=True):self.assertEqual(s.custom_exit('X',t,None,1,0),s.deadline_reason)
    def test_fixed_slots_block_implicit_original_proposal_increase(self):
        s=NFIShortOPFixedControl.__new__(NFIShortOPFixedControl);s.config={'max_open_trades':6};s.wallets=SimpleNamespace(get_total_stake_amount=lambda:12000)
        with patch.object(NFIShortOPControl,'custom_stake_amount',side_effect=lambda *a,**k:a[3]):
            self.assertEqual(s.custom_stake_amount('X',None,100,3000,None,10000,3,'141','long'),2000)
    def test_fixed_slots_do_not_raise_a_smaller_proposal(self):
        s=NFIShortOPFixedControl.__new__(NFIShortOPFixedControl);s.config={'max_open_trades':6};s.wallets=SimpleNamespace(get_total_stake_amount=lambda:12000)
        with patch.object(NFIShortOPControl,'custom_stake_amount',side_effect=lambda *a,**k:a[3]):
            self.assertEqual(s.custom_stake_amount('X',None,100,1000,None,10000,3,'501','short'),1000)
    def test_compression_group_only_enables_shared_theme(self):
        self.assertEqual(NFIShortOPCompression.extras,{166,169})
        self.assertEqual({int(k.split('_')[-2]) for k,v in NFIShortOPCompression.long_entry_signal_params.items() if v and not ORIGINAL.get(k,False)},{166,169})
    def test_context_filter_changes_only_extra_long_entries(self):
        s=NFIShortOPContext.__new__(NFIShortOPContext)
        f=pd.DataFrame({'enter_long':[1,1,1],'enter_short':[0,0,1],'enter_tag':['141',PREFIX+'native_8','505'],'op_h_up':[False]*3,'op_4h_up':[True]*3,'op_rs60':[1.]*3,'bre_known':[True]*3,'bre_raw':[False]*3})
        with patch.object(NFIShortOPNative,'populate_entry_trend',return_value=f):r=s.populate_entry_trend(f,{'pair':'X'})
        self.assertEqual(r.enter_long.tolist(),[1,0,1]);self.assertEqual(r.enter_short.tolist(),[0,0,1])
if __name__=='__main__':unittest.main()
