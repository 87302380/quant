"""Frozen breadth-entry and existing-long exit ablations; shorts unchanged."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
from freqtrade.persistence import Trade
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'atr_short'))
from NFIShortATR import NFIShortATRGated
from NFIShortResearch import align_hourly
from breadth import market_features

class NFIShortBRControl(NFIShortATRGated):
    breadth_gate=False
    breadth_exit=False
    btc_exit=False
    long_cap=False
    def populate_indicators(self,df,metadata):
        df=super().populate_indicators(df,metadata)
        if '_br_market' not in self.__dict__:
            frames={p:self.dp.get_pair_dataframe(p,'5m')[['date','close']] for p in sorted(self.dp.current_whitelist())}
            market=market_features(frames)
            btc=self.dp.get_pair_dataframe('BTC/USDT:USDT','5m');atr=align_hourly(btc,self.dp.get_pair_dataframe('BTC/USDT:USDT','1h')).short_atr
            log=np.log(btc.close.astype(float));step=btc.date.diff().eq(pd.Timedelta(minutes=5))
            r15=log.diff(3).where(step.rolling(3,min_periods=3).sum().eq(3))
            b=pd.DataFrame({'date':pd.to_datetime(btc.date,utc=True).astype('datetime64[ns, UTC]'),'bre_btc_raw':r15.to_numpy()< -1.5*atr.to_numpy()/btc.close.to_numpy()})
            self._br_market=market.merge(b,on='date',how='left',validate='one_to_one')
        left=pd.DataFrame({'date':pd.to_datetime(df.date,utc=True).astype('datetime64[ns, UTC]')})
        aligned=left.merge(self._br_market,on='date',how='left',validate='one_to_one',sort=False)
        for col in self._br_market:
            if col!='date':df[col]=aligned[col].to_numpy()
        return df
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        if self.breadth_gate:df.loc[~df.bre_known.eq(True)|df.bre_recent.eq(True),'enter_long']=0
        return df
    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if self.expired(trade,current_time):return self.deadline_reason
        if not trade.is_short and (self.breadth_exit or self.btc_exit):
            frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
            if not frame.empty:
                row=frame.iloc[-1];closed=row.date+pd.Timedelta(minutes=5)
                column='bre_raw' if self.breadth_exit else 'bre_btc_raw'
                if trade.open_date_utc<closed<=current_time and row[column]==True:
                    return 'research_breadth_exit' if self.breadth_exit else 'research_btc_shock_exit'
        return super().custom_exit(pair,trade,current_time,current_rate,current_profit,**kwargs)
    def confirm_trade_exit(self,pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs):
        if exit_reason in ['research_breadth_exit','research_btc_shock_exit']:return True
        return super().confirm_trade_exit(pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs)
    def confirm_trade_entry(self,pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs):
        if self.long_cap and side=='long' and sum(not t.is_short for t in Trade.get_trades_proxy(is_open=True))>=2:return False
        return super().confirm_trade_entry(pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs)
class NFIShortBRGate(NFIShortBRControl):breadth_gate=True
class NFIShortBRExit(NFIShortBRControl):breadth_exit=True
class NFIShortBRBoth(NFIShortBRGate):breadth_exit=True
class NFIShortBRBTCExit(NFIShortBRControl):btc_exit=True
class NFIShortBRLongCap(NFIShortBRControl):long_cap=True
