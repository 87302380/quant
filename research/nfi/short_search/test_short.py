import sys,unittest
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).parent))
sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from nfi_precision import candle_contains
from NFIShortResearch import inverse_ohlcv,align_hourly,NFIShortBase,NFIShortPullbackSlots,Trade,btc_bear_state,NFIShortGated,NFIShortExpanded


class ShortTest(unittest.TestCase):
    def test_inverse_is_involution_and_preserves_ohlc_bounds(self):
        df=pd.DataFrame({'open':[100.,120.],'high':[110.,130.],'low':[90.,100.],'close':[105.,110.],'volume':[10.,20.]})
        x=inverse_ohlcv(df)
        np.testing.assert_allclose(inverse_ohlcv(x),df)
        self.assertTrue((x.high>=x[['open','close']].max(axis=1)).all())
        self.assertTrue((x.low<=x[['open','close']].min(axis=1)).all())
        pd.testing.assert_series_equal(x.volume,df.volume)

    def test_hourly_atr_is_unavailable_until_bar_closes(self):
        date=pd.date_range('2026-01-01',periods=20,freq='h',tz='UTC')
        info=pd.DataFrame({'date':date,'close':100.,'high':101.,'low':99.})
        info.loc[19,['high','low']]=[200.,1.]
        base=pd.DataFrame({'date':pd.to_datetime(['2026-01-01T19:50Z','2026-01-01T19:55Z'])})
        x=align_hourly(base,info)
        self.assertEqual(x.short_atr.iloc[0],2.)
        self.assertGreater(x.short_atr.iloc[1],2.)

    def test_native_longs_have_no_new_custom_stop(self):
        s=NFIShortBase.__new__(NFIShortBase)
        self.assertIsNone(s.custom_stoploss('X',SimpleNamespace(enter_tag='141'),datetime.now(timezone.utc),100,0))

    def test_short_deadline_cannot_be_postponed(self):
        s=NFIShortBase.__new__(NFIShortBase);now=datetime.now(timezone.utc)
        t=SimpleNamespace(enter_tag='research_short_mirror',open_date_utc=now-timedelta(hours=24))
        self.assertEqual(s.custom_exit('X',t,now,100,-.5),s.deadline_reason)

    def test_level_cache_restores_same_persisted_values_only_once(self):
        s=NFIShortBase.__new__(NFIShortBase);reads=[]
        def read(key,default=None):
            reads.append(key);return {'short_stop':105.,'short_target':90.}[key]
        t=SimpleNamespace(id=42,get_custom_data=read)
        self.assertEqual(s.short_levels(t),(105.,90.))
        self.assertEqual(s.short_levels(t),(105.,90.))
        self.assertEqual(reads,['short_stop','short_target'])

    def test_reserved_slots_reject_third_short_but_allow_long(self):
        s=NFIShortPullbackSlots.__new__(NFIShortPullbackSlots);now=datetime.now(timezone.utc)
        trades=[SimpleNamespace(is_short=True,enter_tag='research_short_pullback') for _ in range(2)]
        with (patch.object(Trade,'get_trades_proxy',return_value=trades),
              patch.object(NFIShortBase,'confirm_trade_entry',return_value=True)):
            self.assertFalse(s.confirm_trade_entry('X','limit',1,100,'GTC',now,'research_short_pullback','short'))
            self.assertTrue(s.confirm_trade_entry('X','limit',1,100,'GTC',now,'141','long'))

    def test_roundoff_fix_accepts_same_decimal_but_not_a_real_tick(self):
        self.assertFalse(.08477000000000001<=.08477)
        self.assertTrue(candle_contains(.08477,.08477000000000001,.08497))
        self.assertFalse(candle_contains(.08476,.08477000000000001,.08497))
        self.assertFalse(candle_contains(.08498,.08477000000000001,.08497))

    def test_btc_gate_uses_only_closed_four_hour_state(self):
        dates=pd.date_range('2026-01-01',periods=210,freq='4h',tz='UTC')
        close=np.linspace(100,50,210);close[-1]=1000
        btc=pd.DataFrame({'date':dates,'close':close})
        base=pd.DataFrame({'date':[dates[-1]+pd.Timedelta(hours=3,minutes=50),dates[-1]+pd.Timedelta(hours=3,minutes=55)]})
        self.assertEqual(btc_bear_state(base,btc).tolist(),[True,False])

    def test_false_gate_keeps_original_short_and_long_tags(self):
        import NFIShortResearch as module
        s=NFIShortGated.__new__(NFIShortGated)
        df=pd.DataFrame({'enter_long':[0,1],'enter_short':[1,1],'enter_tag':['506 562','2 506']})
        s.dp=SimpleNamespace(get_pair_dataframe=lambda *a:None)
        with (patch.object(NFIShortExpanded,'populate_entry_trend',return_value=df),
              patch.object(module,'btc_bear_state',return_value=pd.Series([False,False]))):
            result=s.populate_entry_trend(df,{'pair':'X'})
        self.assertEqual(result.enter_short.tolist(),[1,0])
        self.assertEqual(result.enter_long.tolist(),[0,1])
        self.assertEqual(result.enter_tag.tolist(),['562','2'])

    def test_empty_gate_selection_preserves_integer_signal_columns(self):
        import NFIShortResearch as module
        s=NFIShortGated.__new__(NFIShortGated)
        df=pd.DataFrame({'enter_long':[1],'enter_short':[0],'enter_tag':['141']})
        s.dp=SimpleNamespace(get_pair_dataframe=lambda *a:None)
        with (patch.object(NFIShortExpanded,'populate_entry_trend',return_value=df),
              patch.object(module,'btc_bear_state',return_value=pd.Series([False]))):
            result=s.populate_entry_trend(df,{'pair':'X'})
        self.assertEqual(result.enter_short.dtype,np.dtype('int64'))
        self.assertEqual(result.enter_long.tolist(),[1])


if __name__=='__main__':unittest.main()
