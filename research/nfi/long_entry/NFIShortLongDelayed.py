"""Retain a causal original long signal for at most thirty minutes."""
import pandas as pd
from NFIShortLongEntry import NFIShortLEControl

def delayed_long(df,column):
    original=(df.enter_long==1)&(df.enter_short!=1)
    tags=df.enter_tag.where(original).ffill(limit=6)
    # Wall-clock bound as well as row bound: a gap cannot prolong signal life.
    time=df.date.where(original).ffill(limit=6)
    eligible=tags.notna()&((df.date-time)<=pd.Timedelta(minutes=30))&df[column].fillna(False)&(df.enter_short!=1)&(df.volume>0)
    df['enter_long']=eligible.astype(int)
    df.loc[eligible,'enter_tag']=tags.loc[eligible]
    return df

class NFIShortLEDelayTurn(NFIShortLEControl):
    confirmation='le_turn'
    def populate_entry_trend(self,df,metadata):
        return delayed_long(super().populate_entry_trend(df,metadata),self.confirmation)
class NFIShortLEDelayBreak(NFIShortLEDelayTurn):confirmation='le_break'
