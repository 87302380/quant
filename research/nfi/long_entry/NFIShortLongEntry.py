"""Frozen long-entry/failed-rebound hypotheses; short implementation unchanged."""
from pathlib import Path
import sys
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'atr_short'))
from NFIShortATR import NFIShortATRGated


def long_features(df):
    out=df.copy()
    out['le_break']=out.close>out.high.shift(1).rolling(3).max()
    out['le_turn']=(out.close>out.close.shift(1))&(out.low>=out.low.shift(1))
    out['le_floor']=out.low.rolling(12).min()
    return out


def failed_rebound(age,rate,entry,floor,atr):
    # Fixed six-hour thesis deadline plus actual structural deterioration.
    return age>=6 and rate<entry and rate<floor-.5*atr


class NFIShortLEControl(NFIShortATRGated):
    entry_mode='none'
    failure=False
    def populate_indicators(self,df,metadata):
        return long_features(super().populate_indicators(df,metadata))
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        if self.entry_mode!='none':
            allowed=df['le_break' if self.entry_mode=='break' else 'le_turn'].fillna(False)
            df.loc[(df.enter_long==1)&~allowed,'enter_long']=0
        return df
    def order_filled(self,pair,trade,order,current_time,**kwargs):
        super().order_filled(pair,trade,order,current_time,**kwargs)
        if self.failure and not trade.is_short and order.ft_order_side==trade.entry_side and trade.nr_of_successful_entries==1:
            frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
            row=frame.iloc[-1]
            self.__dict__.setdefault('_le_levels',{})[trade.id]=(float(row.le_floor),float(row.research_short_atr))
    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if self.expired(trade,current_time):return self.deadline_reason
        if self.failure and not trade.is_short:
            floor,atr=self.__dict__.get('_le_levels',{}).get(trade.id,(float('nan'),float('nan')))
            if failed_rebound((current_time-trade.open_date_utc).total_seconds()/3600,current_rate,trade.open_rate,floor,atr):
                return 'research_long_failure'
        return super().custom_exit(pair,trade,current_time,current_rate,current_profit,**kwargs)
    def confirm_trade_exit(self,pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs):
        if exit_reason=='research_long_failure':return True
        return super().confirm_trade_exit(pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs)

class NFIShortLETurn(NFIShortLEControl):entry_mode='turn'
class NFIShortLEBreak(NFIShortLEControl):entry_mode='break'
class NFIShortLEFailure(NFIShortLEControl):failure=True
