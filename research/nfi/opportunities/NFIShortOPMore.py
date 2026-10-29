"""Explicit adaptive follow-up: compression entries and context-gated full expansion."""
from NFIShortOpportunities import NFIShortOPControl,NFIShortOPNative,params,owned_tag
from op_features import retest_features
class NFIShortOPCompression(NFIShortOPControl):
    extras={166,169}
    long_entry_signal_params=params(extras)
class NFIShortOPContext(NFIShortOPNative):
    def populate_indicators(self,df,metadata):
        df=super().populate_indicators(df,metadata)
        f=retest_features(df,self.dp.get_pair_dataframe(metadata['pair'],'1h'),self.dp.get_pair_dataframe(metadata['pair'],'4h'),self.dp.get_pair_dataframe('BTC/USDT:USDT','5m'))
        for c in f:df[c]=f[c].to_numpy()
        return df
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        own=df.enter_tag.map(owned_tag)
        allowed=df.op_h_up.eq(True)&df.op_4h_up.eq(True)&(df.op_rs60>0)&df.bre_known.eq(True)&~df.bre_raw.eq(True)
        df.loc[own&~allowed,'enter_long']=0
        return df
