import sys,unittest
from pathlib import Path
from unittest.mock import patch
import pandas as pd
sys.path.insert(0,str(Path(__file__).parent))
from NFIShortLongDelayed import delayed_long
from NFIShortLongEntry import long_features,failed_rebound,NFIShortLETurn,NFIShortLEBreak,NFIShortATRGated

class LongEntryTest(unittest.TestCase):
    def test_features_prefix_invariant(self):
        df=pd.DataFrame({'close':range(1,31),'high':range(2,32),'low':range(30)})
        pd.testing.assert_frame_equal(long_features(df.iloc[:20]),long_features(df).iloc[:20])
    def test_break_requires_prior_high_not_current_high(self):
        df=pd.DataFrame({'close':[10,10,10,12],'high':[11,11,11,15],'low':[9]*4})
        self.assertTrue(long_features(df).le_break.iloc[-1])
    def test_turn_rejects_lower_low_despite_rising_close(self):
        df=pd.DataFrame({'close':[10,11],'high':[12,12],'low':[9,8]})
        self.assertFalse(long_features(df).le_turn.iloc[-1])
    def test_failure_needs_time_loss_and_structure(self):
        self.assertFalse(failed_rebound(5.99,80,100,95,2))
        self.assertFalse(failed_rebound(6,101,100,110,2))
        self.assertFalse(failed_rebound(6,94,100,95,2))
        self.assertTrue(failed_rebound(6,93.9,100,95,2))
        self.assertFalse(failed_rebound(6,80,100,float('nan'),2))
    def test_filters_preserve_short_signals_and_tags(self):
        for cls,column in [(NFIShortLETurn,'le_turn'),(NFIShortLEBreak,'le_break')]:
            obj=cls.__new__(cls)
            df=pd.DataFrame({'enter_long':[1,1],'enter_short':[1,0],'enter_tag':['a','b'],column:[True,False]})
            with patch.object(NFIShortATRGated,'populate_entry_trend',return_value=df):out=obj.populate_entry_trend(df,{'pair':'X'})
            self.assertEqual(out.enter_short.tolist(),[1,0]);self.assertEqual(out.enter_tag.tolist(),['a','b']);self.assertEqual(out.enter_long.tolist(),[1,0])
    def delayed_frame(self):
        return pd.DataFrame({'date':pd.date_range('2026-01-01',periods=9,freq='5min',tz='UTC'),'enter_long':[1]+[0]*8,'enter_short':[0]*9,'enter_tag':['64']+['']*8,'volume':[1]*9,'le_turn':[False]+[True]*8})
    def test_delayed_signal_expires_and_preserves_tag(self):
        r=delayed_long(self.delayed_frame(),'le_turn')
        self.assertEqual(r.enter_long.tolist(),[0,1,1,1,1,1,1,0,0])
        self.assertEqual(r.enter_tag.iloc[1],'64')
    def test_delay_gap_cannot_extend_thirty_minutes(self):
        f=self.delayed_frame();f.loc[1:,'date']+=pd.Timedelta(hours=1)
        self.assertEqual(delayed_long(f,'le_turn').enter_long.sum(),0)
    def test_delay_prefix_invariance(self):
        f=self.delayed_frame();a=delayed_long(f.iloc[:5].copy(),'le_turn');b=delayed_long(f.copy(),'le_turn').iloc[:5]
        pd.testing.assert_frame_equal(a,b)
    def test_delay_never_overwrites_short_tag(self):
        f=self.delayed_frame();f.loc[2,['enter_short','enter_tag']]=[1,'501']
        r=delayed_long(f,'le_turn');self.assertEqual(r.enter_tag.iloc[2],'501');self.assertEqual(r.enter_long.iloc[2],0)
if __name__=='__main__':unittest.main()
