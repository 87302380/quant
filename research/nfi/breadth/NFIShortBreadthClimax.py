"""Adaptive exploration: treat breadth shock as dip opportunity, not a risk veto."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'long_family'))
from NFIShortLongFamily import signal_family
from NFIShortBreadth import NFIShortBRControl
class NFIShortBRClimax(NFIShortBRControl):
    after=False
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        dip=df.enter_tag.map(signal_family).eq('dip')
        allowed=df.bre_known.eq(True)&df.bre_recent.eq(True)
        if self.after:allowed &= ~df.bre_raw.eq(True)
        df.loc[dip&~allowed,'enter_long']=0
        return df
class NFIShortBRClimaxAfter(NFIShortBRClimax):after=True
