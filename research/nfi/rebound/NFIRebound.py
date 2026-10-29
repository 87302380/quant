"""Causal rebound-state hypotheses; no calendar-month trading switches."""
from pathlib import Path
import sys
import numpy as np
import pandas as pd
import talib
from datetime import timedelta
from freqtrade.persistence import Trade
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'short_search'))
from NFIShortResearch import NFIShortExpanded,NFIShortIncumbent


def fast_state(base,btc):
    close=btc.close.to_numpy(dtype=float)
    fast=talib.EMA(close,12);slow=talib.EMA(close,50)
    state=np.select([(close>slow)&(fast>slow),(close<slow)&(fast<slow)],[1,-1],default=0)
    info=pd.DataFrame({'available':btc.date.astype('datetime64[ns, UTC]')+pd.Timedelta(hours=4)-pd.Timedelta(minutes=5),'state':state})
    left=pd.DataFrame({'date':base.date.astype('datetime64[ns, UTC]')})
    merged=pd.merge_asof(left,info,left_on='date',right_on='available')
    return pd.Series(merged.state.fillna(0).to_numpy(dtype=int),index=base.index)


def filter_shorts(df,mask,allowed,all_short):
    if mask.any():
        remaining=df.loc[mask,'enter_tag'].fillna('').map(lambda tag:' '.join(t for t in tag.split() if t not in all_short or t in allowed))
        df.loc[mask,'enter_tag']=remaining
        df.loc[mask,'enter_short']=remaining.map(lambda tag:int(bool(set(tag.split())&allowed))).astype('int64')
    return df


class NFIReboundBase(NFIShortExpanded):
    def populate_indicators(self,df,metadata):
        df=super().populate_indicators(df,metadata)
        df['research_btc_fast_state']=fast_state(df,self.dp.get_pair_dataframe('BTC/USDT:USDT','4h'))
        return df

    def state_now(self,pair):
        frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
        return int(frame.iloc[-1].research_btc_fast_state) if not frame.empty else 0

    def active_short_tags(self):
        return {k.split('_')[3] for k,v in self.short_entry_signal_params.items() if v}


class NFIReboundFast(NFIReboundBase):
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        tags=self.active_short_tags();state=df.research_btc_fast_state
        df=filter_shorts(df,(df.enter_short==1)&(state==1),set(),tags)
        return filter_shorts(df,(df.enter_short==1)&(state==0),{'501','502','542','562'},tags)


class NFIReboundSoft(NFIReboundBase):
    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        stake=super().custom_stake_amount(pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs)
        if side=='short':stake*={1:.25,0:.5,-1:1.}[self.state_now(pair)]
        return stake if min_stake is None or stake>=min_stake else 0.


class NFIReboundLong(NFIReboundFast):
    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        stake=super().custom_stake_amount(pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs)
        if side=='long' and self.state_now(pair)==1:stake=min(stake*1.25,max_stake)
        return stake if min_stake is None or stake>=min_stake else 0.


class NFIReboundLocal(NFIReboundBase):
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        weak=(df.EMA_12_4h<df.EMA_50_4h)&(df.RSI_14_4h<50)
        return filter_shorts(df,(df.enter_short==1)&~weak,set(),self.active_short_tags())


class NFIReboundIncumbent(NFIShortIncumbent):
    pass


class NFIReboundCover(NFIReboundBase):
    reason='research_rebound_short_invalidation'

    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if self.expired(trade,current_time):return self.deadline_reason
        if trade.is_short and current_time>=trade.open_date_utc+timedelta(hours=1) and self.state_now(pair)==1:
            pnl=self.calc_total_profit(trade,trade.select_filled_orders(trade.entry_side),trade.select_filled_orders(trade.exit_side),current_rate)[0]
            if pnl<0:return self.reason
        return super().custom_exit(pair,trade,current_time,current_rate,current_profit,**kwargs)

    def confirm_trade_exit(self,pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs):
        if exit_reason==self.reason:return True
        return super().confirm_trade_exit(pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs)


class NFIReboundCooldown(NFIReboundBase):
    def blocked(self,tag,now,trades):
        recent=[t for t in trades if t.is_short and t.close_date is not None and t.close_date_utc<=now and (t.enter_tag or '').split()[:1]==[tag]]
        recent=sorted(recent,key=lambda t:t.close_date_utc,reverse=True)[:5]
        return len(recent)==5 and sum(float(t.close_profit or 0.) for t in recent)<0 and now<recent[0].close_date_utc+timedelta(hours=72)

    def confirm_trade_entry(self,pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs):
        tags=(entry_tag or '').split();new={'505','506','543','544','545','546','548','561','563'}
        if side=='short' and tags and tags[0] in new and not set(tags)&{'501','502','542','562'}:
            if self.blocked(tags[0],current_time,Trade.get_trades_proxy(is_open=False)):return False
        return super().confirm_trade_entry(pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs)


class NFIReboundAllocation(NFIReboundBase):
    """Isolate long allocation from the unsuccessful fast entry filter."""
    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        stake=super().custom_stake_amount(pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs)
        if side=='long' and self.state_now(pair)==1:stake=min(stake*1.25,max_stake)
        return stake if min_stake is None or stake>=min_stake else 0.


class NFIReboundStyles(NFIReboundBase):
    """Differentiate native exhaustion/rejection patterns from continuation."""
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        # Preserve original four plus overbought exhaustion, failed breakout,
        # and BB-upper rejection. Keep losing545 too: taxonomy, not P&L pruning.
        counter={'501','502','542','562','543','545','546'}
        mask=(df.enter_short==1)&(df.research_btc_fast_state!=-1)
        return filter_shorts(df,mask,counter,self.active_short_tags())


class NFIReboundCoreAllocation(NFIReboundAllocation):
    short_entry_signal_params={**NFIShortIncumbent.short_entry_signal_params}
