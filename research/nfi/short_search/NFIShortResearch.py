"""Isolated short hypotheses on top of the frozen profitable long core."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import talib
from freqtrade.strategy import stoploss_from_absolute
from freqtrade.persistence import Trade

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'return_search'))
from NFIExtensions import NFIOptWeightedNoAdds
from NFIOptimize import NFIRiskOverheat80


def inverse_ohlcv(frame):
    """Synthetic signal features only; execution always uses original market data."""
    out=frame.copy()
    out['open']=1/frame.open;out['high']=1/frame.low
    out['low']=1/frame.high;out['close']=1/frame.close
    # Keep observed activity weight. This is not a tradeable inverse contract.
    return out


class InverseProvider:
    def __init__(self,provider):self.provider=provider
    def __getattr__(self,key):return getattr(self.provider,key)
    def get_pair_dataframe(self,*args,**kwargs):
        return inverse_ohlcv(self.provider.get_pair_dataframe(*args,**kwargs))


def align_hourly(base,info):
    i=info[['date','close']].copy()
    i['short_atr']=talib.ATR(info.high.to_numpy(dtype=float),info.low.to_numpy(dtype=float),info.close.to_numpy(dtype=float),14)
    i['short_ema']=talib.EMA(info.close.to_numpy(dtype=float),20)
    i['available']=i.date.astype('datetime64[ns, UTC]')+pd.Timedelta(hours=1)-pd.Timedelta(minutes=5)
    left=pd.DataFrame({'date':base.date.astype('datetime64[ns, UTC]')})
    return pd.merge_asof(left,i[['available','short_atr','short_ema']].sort_values('available'),left_on='date',right_on='available')


class NFIShortBase(NFIOptWeightedNoAdds):
    use_custom_stoploss=True
    short_tag='research_short'
    atr_multiple=2.
    reward_multiple=2.

    def populate_indicators(self,df,metadata):
        df=super().populate_indicators(df,metadata)
        info=self.dp.get_pair_dataframe(metadata['pair'],'1h')
        aligned=align_hourly(df,info)
        df['research_short_atr']=aligned.short_atr.to_numpy()
        df['research_short_ema']=aligned.short_ema.to_numpy()
        return df

    def short_signal(self,df,metadata):return pd.Series(False,index=df.index)

    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        signal=self.short_signal(df,metadata)&(df.enter_long!=1)&(df.volume>0)
        df['enter_short']=0
        df.loc[signal,'enter_short']=1;df.loc[signal,'enter_tag']=self.short_tag
        return df

    @staticmethod
    def own_trade(trade):return (trade.enter_tag or '').startswith('research_short')

    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        if side!='short' or not (entry_tag or '').startswith('research_short'):
            return super().custom_stake_amount(pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs)
        frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
        if frame.empty:return 0.
        atr=frame.iloc[-1].research_short_atr
        if not np.isfinite(atr) or atr<=0:return 0.
        distance=max(self.atr_multiple*atr,current_rate*.01)
        equity=self.wallets.get_total_stake_amount()
        # No more than half an ordinary slot, and 1% planned realized-equity loss.
        fee=self.config.get('fee',.0005)
        loss_per_notional=distance/current_rate+fee*(2+distance/current_rate)
        margin=min(proposed_stake*.5,max_stake,equity*.01/(leverage*loss_per_notional))
        self.__dict__.setdefault('_short_pending',{})[pair]=distance
        return margin if min_stake is None or margin>=min_stake else 0.

    def order_filled(self,pair,trade,order,current_time,**kwargs):
        super().order_filled(pair,trade,order,current_time,**kwargs)
        if self.own_trade(trade) and order.ft_order_side==trade.entry_side and trade.nr_of_successful_entries==1:
            distance=self._short_pending[pair]
            first=trade.select_filled_orders(trade.entry_side)[0].safe_price
            trade.set_custom_data(key='short_stop',value=first+distance)
            trade.set_custom_data(key='short_target',value=max(first-self.reward_multiple*distance,first*.001))
            self.__dict__.setdefault('_short_level_cache',{})[trade.id]=(first+distance,max(first-self.reward_multiple*distance,first*.001))

    def short_levels(self,trade):
        cache=self.__dict__.setdefault('_short_level_cache',{})
        if trade.id not in cache:
            # Restore persisted state once after a restart. Repeated backtest
            # reads otherwise scan every historical custom-data record.
            cache[trade.id]=(trade.get_custom_data(key='short_stop',default=None),trade.get_custom_data(key='short_target',default=None))
        return cache[trade.id]

    def custom_stoploss(self,pair,trade,current_time,current_rate,current_profit,after_fill=False,**kwargs):
        if not self.own_trade(trade):return None
        stop,_=self.short_levels(trade)
        return None if stop is None else stoploss_from_absolute(stop,current_rate,is_short=True,leverage=trade.leverage)

    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if self.expired(trade,current_time):return self.deadline_reason
        if not self.own_trade(trade):return super().custom_exit(pair,trade,current_time,current_rate,current_profit,**kwargs)
        stop,target=self.short_levels(trade)
        if stop is not None and current_rate>=stop:return 'research_short_stop_gap'
        if target is not None and current_rate<=target:return 'research_short_target'
        return None

    def confirm_trade_exit(self,pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs):
        if self.own_trade(trade) and (exit_reason.startswith('research_short') or exit_reason in ['stop_loss','trailing_stop_loss']):return True
        return super().confirm_trade_exit(pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs)

    def adjust_trade_position(self,trade,*args,**kwargs):
        if self.own_trade(trade):return None
        return super().adjust_trade_position(trade,*args,**kwargs)


class NFIShortLongControl(NFIShortBase):
    pass


class NFIShortPullback(NFIShortBase):
    short_tag='research_short_pullback'

    def short_signal(self,df,metadata):
        bear=(df.EMA_12_4h<df.EMA_200_4h)&(df.RSI_14_4h.between(25,50))&(df.ROC_9_1d<0)
        rejection=(df.close<df.EMA_20)&(df.close.shift(1)>=df.EMA_20.shift(1))
        bounce=(df.high.rolling(6).max()>=df.research_short_ema*.998)&(df.RSI_14.rolling(6).max()>=60)
        return bear&rejection&bounce&(df.volume>=df.volume.rolling(20).mean()*.7)


class NFIShortBreakdown(NFIShortBase):
    short_tag='research_short_breakdown'

    def short_signal(self,df,metadata):
        bear=(df.EMA_12_4h<df.EMA_200_4h)&(df.RSI_14_4h.between(25,50))&(df.ROC_9_1d<0)
        breakdown=df.close<df.low.rolling(12).min().shift(1)
        return bear&breakdown&(df.RSI_14>25)&(df.close>df.research_short_ema*.95)&(df.volume>df.volume.rolling(20).mean()*1.2)


class NFIShortMirror(NFIShortBase):
    short_tag='research_short_mirror'

    def populate_indicators(self,df,metadata):
        provider=self.dp
        try:
            self.dp=InverseProvider(provider)
            mirrored=NFIRiskOverheat80.populate_indicators(self,inverse_ohlcv(df),metadata)
            mirrored=NFIRiskOverheat80.populate_entry_trend(self,mirrored,metadata)
            allowed=set(self.long_normal_mode_tags+self.long_top_coins_mode_tags)
            selected=mirrored.enter_tag.fillna('').map(lambda tag:bool(set(tag.split())&allowed))
            self.__dict__.setdefault('_mirror_signals',{})[metadata['pair']]=((mirrored.enter_long==1)&selected).to_numpy().copy()
            del mirrored
        finally:self.dp=provider
        return super().populate_indicators(df,metadata)

    def short_signal(self,df,metadata):
        return pd.Series(self._mirror_signals[metadata['pair']],index=df.index)


class ShortSlotCap:
    def confirm_trade_entry(self,pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs):
        if side=='short' and (entry_tag or '').startswith('research_short'):
            count=sum(t.is_short and self.own_trade(t) for t in Trade.get_trades_proxy(is_open=True))
            if count>=2:return False
        return super().confirm_trade_entry(pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs)


class NFIShortPullbackSlots(ShortSlotCap,NFIShortPullback):
    pass


class NFIShortBreakdownSlots(ShortSlotCap,NFIShortBreakdown):
    pass


class NFIShortMirrorSlots(ShortSlotCap,NFIShortMirror):
    pass


class NFIShortExpanded(NFIOptWeightedNoAdds):
    """Separate control: enable existing implemented normal/quick/rebuy shorts."""
    short_entry_signal_params={**NFIOptWeightedNoAdds.short_entry_signal_params,
        **{f'short_entry_condition_{tag}_enable':True for tag in [505,506,543,544,545,546,548,561,563]}}


class NFIShortBreakdownRR1(NFIShortBreakdownSlots):
    reward_multiple=1.


class NFIShortIncumbent(NFIOptWeightedNoAdds):
    pass


class NFIShortRegimeSlots(NFIShortBreakdownSlots):
    def short_signal(self,df,metadata):
        btc=self.dp.get_pair_dataframe('BTC/USDT:USDT','4h')
        close=btc.close.to_numpy(dtype=float);ema=talib.EMA(close,200)
        slope=pd.Series(ema).diff(6).to_numpy()
        info=pd.DataFrame({'available':btc.date.astype('datetime64[ns, UTC]')+pd.Timedelta(hours=4)-pd.Timedelta(minutes=5),
                           'bear':(close<ema)&(slope<0)})
        left=pd.DataFrame({'date':df.date.astype('datetime64[ns, UTC]')})
        state=pd.merge_asof(left,info,left_on='date',right_on='available').bear.fillna(False)
        return super().short_signal(df,metadata)&pd.Series(state.to_numpy(),index=df.index)


def btc_bear_state(df,btc):
    close=btc.close.to_numpy(dtype=float);ema=talib.EMA(close,200)
    slope=pd.Series(ema).diff(6).to_numpy()
    info=pd.DataFrame({'available':btc.date.astype('datetime64[ns, UTC]')+pd.Timedelta(hours=4)-pd.Timedelta(minutes=5),
                       'bear':(close<ema)&(slope<0)})
    left=pd.DataFrame({'date':df.date.astype('datetime64[ns, UTC]')})
    state=pd.merge_asof(left,info,left_on='date',right_on='available').bear.fillna(False)
    return pd.Series(state.to_numpy(),index=df.index)


class NFIShortGated(NFIShortExpanded):
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        bear=btc_bear_state(df,self.dp.get_pair_dataframe('BTC/USDT:USDT','4h'))
        new={'505','506','543','544','545','546','548','561','563'}
        native={'501','502','542','562'}
        mask=(df.enter_short==1)&~bear
        if mask.any():
            remaining=df.loc[mask,'enter_tag'].fillna('').map(lambda tag:' '.join(t for t in tag.split() if t not in new))
            df.loc[mask,'enter_tag']=remaining
            df.loc[mask,'enter_short']=remaining.map(lambda tag:int(bool(set(tag.split())&native))).astype('int64')
        return df
