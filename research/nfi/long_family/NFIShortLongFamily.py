"""Source-defined entry families; causal hourly trend and dip-specific execution."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import talib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'atr_short'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'fast_rs'))
from NFIShortATR import NFIShortATRGated
from NFIShortFastRS import strength_features
TREND={'21','47','64','65','161'}
DIP={'1','2','3','4','5','6','41','42','43','44','45','46','61','62','63','101','102','103','104','120','141','142','143','144','145','162','163'}
def signal_family(tag):
    tags=set(str(tag or '').split())
    if tags and tags<=TREND:return 'trend'
    if tags and tags<=DIP:return 'dip'
    return 'mixed_or_unknown'
def hourly_state(base,info):
    close=info.close.astype(float);ema=pd.Series(talib.EMA(close.to_numpy(),50),index=info.index)
    continuous=info.date.diff().eq(pd.Timedelta(hours=1))
    frame=pd.DataFrame({'available':pd.to_datetime(info.date,utc=True).astype('datetime64[ns, UTC]')+pd.Timedelta(minutes=55),
        'lf_up':(close>ema)&(ema>ema.shift(6)),
        'lf_failed':(close<ema)&(close.shift()<ema.shift())&continuous})
    left=pd.DataFrame({'date':pd.to_datetime(base.date,utc=True).astype('datetime64[ns, UTC]')})
    joined=pd.merge_asof(left,frame,left_on='date',right_on='available',tolerance=pd.Timedelta(minutes=55))
    return joined[['lf_up','lf_failed']].fillna(False).astype(bool).set_axis(base.index)
def dip_limit(rate,atr):
    return rate-min(.5*atr,.019*rate) if np.isfinite(atr) and atr>0 else rate
class NFIShortLFControl(NFIShortATRGated):
    trend_gate=False
    trend_exit=False
    dip_recovery=False
    limit_dip=False
    def populate_indicators(self,df,metadata):
        df=super().populate_indicators(df,metadata)
        features=hourly_state(df,self.dp.get_pair_dataframe(metadata['pair'],'1h'))
        for col in features:df[col]=features[col].to_numpy()
        if '_lf_btc' not in self.__dict__:self._lf_btc=self.dp.get_pair_dataframe('BTC/USDT:USDT','5m')
        rs=strength_features(df,self._lf_btc).rs_15
        df['lf_recover']=(rs-rs.shift(3))>1e-12
        return df
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        families=df.enter_tag.map(signal_family)
        if self.trend_gate:df.loc[(families=='trend')&~df.lf_up,'enter_long']=0
        if self.dip_recovery and metadata['pair']!='BTC/USDT:USDT':df.loc[(families=='dip')&~df.lf_recover,'enter_long']=0
        return df
    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if self.expired(trade,current_time):return self.deadline_reason
        age=(current_time-trade.open_date_utc).total_seconds()/3600
        if self.trend_exit and age>=2 and not trade.is_short and signal_family(trade.enter_tag)=='trend':
            frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
            if not frame.empty and bool(frame.iloc[-1].lf_failed):return 'research_long_trend_failure'
        return super().custom_exit(pair,trade,current_time,current_rate,current_profit,**kwargs)
    def confirm_trade_exit(self,pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs):
        if exit_reason=='research_long_trend_failure':return True
        return super().confirm_trade_exit(pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs)
    def custom_entry_price(self,pair,trade,current_time,proposed_rate,entry_tag,side,**kwargs):
        if self.limit_dip and side=='long' and signal_family(entry_tag)=='dip':
            frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
            if not frame.empty:return dip_limit(proposed_rate,float(frame.iloc[-1].research_short_atr))
        return proposed_rate
class NFIShortLFTrendGate(NFIShortLFControl):trend_gate=True
class NFIShortLFTrendExit(NFIShortLFControl):trend_exit=True
class NFIShortLFTrendBoth(NFIShortLFTrendGate):trend_exit=True
class NFIShortLFDipRecovery(NFIShortLFControl):dip_recovery=True
class NFIShortLFDipLimit(NFIShortLFControl):limit_dip=True
