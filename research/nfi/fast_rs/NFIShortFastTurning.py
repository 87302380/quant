"""Adaptive follow-up: relative recovery, instead of already-positive strength."""
from NFIShortFastRS import NFIShortFastBase,NFIShortATRGated


class NFIShortFastTurning(NFIShortFastBase):
    def populate_entry_trend(self,df,metadata):
        df=NFIShortATRGated.populate_entry_trend(self,df,metadata)
        if metadata['pair']=='BTC/USDT:USDT':return df
        # Compare two nonoverlapping 15m relative-return windows. No threshold
        # fitting or new entry trigger. All shorts retain the original framework.
        improvement=df.fast_rs_15-df.fast_rs_15.shift(3)
        df.loc[~(improvement>1e-12),'enter_long']=0
        return df
