"""Extra meaningful longs with native signal priority and disciplined independent exits."""
from pathlib import Path
import sys,json,logging
import numpy as np
from freqtrade.persistence import Trade
from freqtrade.strategy import stoploss_from_absolute
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'breadth'))
from NFIShortBreadthClimax import NFIShortBRClimax
from op_features import retest_features
PULLBACK={48,165,167};BREAKOUT={7,8,166,169,171};EXTRA=PULLBACK|BREAKOUT
ORIGINAL=dict(NFIShortBRClimax.long_entry_signal_params)
PREFIX='research_op_long_'
log=logging.getLogger(__name__)
def params(tags):return {**ORIGINAL,**{f'long_entry_condition_{n}_enable':True for n in tags}}
def owned_tag(tag):return (tag or '').startswith(PREFIX)
def extra_tokens(tag,tags):return sorted(set(str(tag or '').split())&{str(n) for n in tags},key=int)
def planned_margin(native,proposed,maximum,equity,rate,distance,leverage,fee,minimum):
    per_coin=distance+fee*(2*rate-distance)
    stake=min(native,proposed*.25,maximum,equity*.005*rate/(leverage*per_coin))
    return stake if minimum is None or stake>=minimum else 0.
class NFIShortOPControl(NFIShortBRClimax):
    extras=set()
    add_retest=False
    extra_slots=2
    def populate_indicators(self,df,metadata):
        df=super().populate_indicators(df,metadata)
        if self.add_retest:
            f=retest_features(df,self.dp.get_pair_dataframe(metadata['pair'],'1h'),self.dp.get_pair_dataframe(metadata['pair'],'4h'),self.dp.get_pair_dataframe('BTC/USDT:USDT','5m'))
            for c in f:df[c]=f[c].to_numpy()
        return df
    def populate_entry_trend(self,df,metadata):
        expanded_params=self.long_entry_signal_params
        try:
            self.long_entry_signal_params=ORIGINAL.copy()
            original=super().populate_entry_trend(df.copy(deep=False),metadata)
        finally:self.long_entry_signal_params=expanded_params
        allowed=(original.enter_long!=1)&(original.enter_short!=1)&(original.volume>0)
        tags=original.enter_tag.copy();signal=allowed&False
        if self.extras:
            expanded=super().populate_entry_trend(df.copy(deep=False),metadata)
            tokens=expanded.enter_tag.map(lambda t:extra_tokens(t,self.extras))
            signal=allowed&(expanded.enter_long==1)&tokens.map(bool)
            tags.loc[signal]=tokens.loc[signal].map(lambda ts:PREFIX+'native_'+'_'.join(ts))
        if self.add_retest:
            retest=allowed&~signal&original.op_retest.eq(True)&original.bre_known.eq(True)&~original.bre_raw.eq(True)
            signal |= retest;tags.loc[retest]=PREFIX+'retest'
        original.loc[signal,'enter_long']=1;original.loc[signal,'enter_tag']=tags.loc[signal]
        return original
    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        native=super().custom_stake_amount(pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs)
        if side!='long' or not owned_tag(entry_tag):return native
        frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
        if frame.empty:return 0.
        atr=frame.iloc[-1].research_short_atr
        if not np.isfinite(atr) or atr<=0:return 0.
        distance=min(max(2*atr,current_rate*.01),current_rate*.99);equity=self.wallets.get_total_stake_amount();fee=self.config.get('fee',.0005)
        stake=planned_margin(native,proposed_stake,max_stake,equity,current_rate,distance,leverage,fee,min_stake)
        self.__dict__.setdefault('_op_pending',{})[pair]={'distance':distance,'equity':equity,'ceiling':proposed_stake*.25,'fee':fee}
        return stake
    def confirm_trade_entry(self,pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs):
        if owned_tag(entry_tag):
            if sum(owned_tag(t.enter_tag) for t in Trade.get_trades_proxy(is_open=True))>=self.extra_slots:return False
        return super().confirm_trade_entry(pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs)
    def order_filled(self,pair,trade,order,current_time,**kwargs):
        super().order_filled(pair,trade,order,current_time,**kwargs)
        if not trade.is_short and owned_tag(trade.enter_tag) and order.ft_order_side==trade.entry_side and trade.nr_of_successful_entries==1:
            pending=self._op_pending[pair];first=trade.select_filled_orders(trade.entry_side)[0].safe_price;d=pending['distance'];levels=(first-d,first+2*d)
            trade.set_custom_data(key='op_levels',value=list(levels));self.__dict__.setdefault('_op_levels',{})[trade.id]=levels
            risk=trade.amount*(d+pending['fee']*(first+levels[0]))
            log.info('OP_RISK_AUDIT %s',json.dumps({'pair':pair,'time':str(current_time),'trade_id':trade.id,'equity':pending['equity'],'ceiling':pending['ceiling'],'risk':risk,'margin':trade.amount*first/trade.leverage,'entry':first,'stop':levels[0],'target':levels[1]}))
    def levels(self,trade):
        cache=self.__dict__.setdefault('_op_levels',{})
        if trade.id not in cache:cache[trade.id]=trade.get_custom_data(key='op_levels',default=[None,None])
        return cache[trade.id]
    def custom_stoploss(self,pair,trade,current_time,current_rate,current_profit,after_fill=False,**kwargs):
        if owned_tag(trade.enter_tag) and not trade.is_short:
            stop,_=self.levels(trade)
            return None if stop is None else stoploss_from_absolute(stop,current_rate,is_short=False,leverage=trade.leverage)
        return super().custom_stoploss(pair,trade,current_time,current_rate,current_profit,after_fill=after_fill,**kwargs)
    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if self.expired(trade,current_time):return self.deadline_reason
        if owned_tag(trade.enter_tag):
            stop,target=self.levels(trade)
            if stop is not None and current_rate<=stop:return 'research_op_long_stop_gap'
            if target is not None and current_rate>=target:return 'research_op_long_target'
            return None
        return super().custom_exit(pair,trade,current_time,current_rate,current_profit,**kwargs)
    def confirm_trade_exit(self,pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs):
        if owned_tag(trade.enter_tag) and (exit_reason.startswith('research_op_long') or exit_reason in ['stop_loss','trailing_stop_loss']):return True
        return super().confirm_trade_exit(pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs)
    def adjust_trade_position(self,trade,*args,**kwargs):
        if owned_tag(trade.enter_tag):return None
        return super().adjust_trade_position(trade,*args,**kwargs)
class NFIShortOPPullback(NFIShortOPControl):
    extras=PULLBACK;long_entry_signal_params=params(PULLBACK)
class NFIShortOPBreakout(NFIShortOPControl):
    extras=BREAKOUT;long_entry_signal_params=params(BREAKOUT)
class NFIShortOPNative(NFIShortOPControl):
    extras=EXTRA;long_entry_signal_params=params(EXTRA)
class NFIShortOPRetest(NFIShortOPControl):add_retest=True
class NFIShortOPCombined(NFIShortOPNative):add_retest=True
