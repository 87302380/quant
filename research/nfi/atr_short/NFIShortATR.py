"""Fixed-allocation short exit and relative-strength ablation; no exposure boost."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'short_search'))
from NFIShortResearch import NFIShortBase,btc_bear_state
from NFI24Hour import NFI24Hour

EXTRA=[505,506,543,544,545,546,548,561,563]


def relative_weak(base,coin,btc):
    def prepare(frame,name):
        return pd.DataFrame({'available':pd.to_datetime(frame.date,utc=True).astype("datetime64[ns, UTC]")+pd.Timedelta(hours=4)-pd.Timedelta(minutes=5),name:frame.close.pct_change(6,fill_method=None)})
    left=pd.DataFrame({'date':pd.to_datetime(base.date,utc=True).astype('datetime64[ns, UTC]')})
    a=pd.merge_asof(left,prepare(coin,'coin'),left_on='date',right_on='available')
    b=pd.merge_asof(left,prepare(btc,'btc'),left_on='date',right_on='available')
    return pd.Series((a.coin<b.btc).to_numpy(),index=base.index)


class NFIShortATRControl(NFI24Hour):
    def adjust_trade_position(self,trade,*args,**kwargs):
        if trade.is_short:return None
        result=NFI24Hour.adjust_trade_position(self,trade,*args,**kwargs)
        amount=result[0] if isinstance(result,tuple) else result
        return result if amount is not None and amount<0 else None


class NFIShortATRNative(NFIShortATRControl):
    short_entry_signal_params={**NFI24Hour.short_entry_signal_params,**{f'short_entry_condition_{tag}_enable':True for tag in EXTRA}}


class NFIShortATRStop(NFIShortBase):
    short_entry_signal_params=NFIShortATRNative.short_entry_signal_params
    gate=False
    weak=False
    target=False
    @staticmethod
    def own_trade(trade):return trade.is_short

    def populate_entry_trend(self,df,metadata):
        df=NFI24Hour.populate_entry_trend(self,df,metadata)
        allowed=pd.Series(True,index=df.index)
        btc=self.dp.get_pair_dataframe('BTC/USDT:USDT','4h')
        if self.gate:allowed &= btc_bear_state(df,btc)
        if self.weak:allowed &= relative_weak(df,self.dp.get_pair_dataframe(metadata['pair'],'4h'),btc)
        mask=(df.enter_short==1)&~allowed
        df.loc[mask,'enter_short']=0
        return df

    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        native=NFI24Hour.custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs)
        if side!='short':return native
        frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
        if frame.empty:return 0.
        atr=frame.iloc[-1].research_short_atr
        if not np.isfinite(atr) or atr<=0:return 0.
        distance=max(2*atr,current_rate*.01)
        fee=self.config.get('fee',.0005)
        budget=self.wallets.get_total_stake_amount()*.01
        margin=min(native,max_stake,budget/(leverage*(distance/current_rate+fee*(2+distance/current_rate))))
        self.__dict__.setdefault('_short_pending',{})[pair]=distance
        return margin if min_stake is None or margin>=min_stake else 0.

    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if self.expired(trade,current_time):return self.deadline_reason
        if not trade.is_short or not self.target:
            return NFI24Hour.custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs)
        return NFIShortBase.custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs)

    def adjust_trade_position(self,trade,*args,**kwargs):
        return NFIShortATRControl.adjust_trade_position(self,trade,*args,**kwargs)


class NFIShortATRTarget(NFIShortATRStop):
    target=True

class NFIShortATRGated(NFIShortATRTarget):
    gate=True

class NFIShortATRWeak(NFIShortATRGated):
    weak=True

class NFIShortATRBaseRisk(NFIShortATRTarget):
    short_entry_signal_params=NFI24Hour.short_entry_signal_params

class NFIShortATRBudget(NFIShortATRStop):
    """Same ATR-based stake cap, but native exits and no actual ATR stop."""
    use_custom_stoploss=False

class NFIShortATRGatedStop(NFIShortATRStop):
    gate=True

class NFIShortATRWeakStop(NFIShortATRGatedStop):
    weak=True
