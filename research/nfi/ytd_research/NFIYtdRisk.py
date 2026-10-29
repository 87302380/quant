"""Exploratory campaign-risk sizing; gaps and execution may exceed planned risk."""
from pathlib import Path
import sys
import logging,json
import numpy as np
import talib
from freqtrade.strategy import stoploss_from_absolute
from freqtrade.persistence import Trade

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'study'))
from NFI24Hour import NFI24Hour


def margin_for_risk(budget,rate,stop,leverage):
    return max(0.,budget)/(leverage*(abs(rate-stop)/rate+.0005*(1+stop/rate)))


class NFIYtdBudget(NFI24Hour):
    use_custom_stoploss=True
    campaign_fraction=.005
    direction_fraction=None

    def populate_indicators(self,df,metadata):
        info=self.dp.get_pair_dataframe(metadata['pair'],'4h')
        cache=self.__dict__.setdefault('_risk_frames',{})
        cache[metadata['pair']]=(info.date.astype('datetime64[ns, UTC]').astype('int64').to_numpy()//1000000+14400000,
                                  talib.ATR(info.high.to_numpy(dtype=float),info.low.to_numpy(dtype=float),info.close.to_numpy(dtype=float),14))
        return super().populate_indicators(df,metadata)

    def stop_price(self,pair,now,rate,short):
        dates,atr=self._risk_frames[pair]
        idx=np.searchsorted(dates,int(now.timestamp()*1000),side='right')-1
        if idx<0 or not np.isfinite(atr[idx]):return None
        distance=max(2*atr[idx],rate*.01)
        return rate+distance if short else max(rate-distance,rate*.001)

    def equity(self):return self.wallets.get_total_stake_amount()

    def remaining_direction(self,short,equity,exclude=None):
        if self.direction_fraction is None:return float('inf')
        occupied=0.
        for t in Trade.get_trades_proxy(is_open=True):
            if t is exclude or t.is_short!=short:continue
            occupied+=t.get_custom_data(key='research_budget',default=equity*self.campaign_fraction)
        return max(0.,equity*self.direction_fraction-occupied)

    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        original=super().custom_stake_amount(pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs)
        stop=self.stop_price(pair,current_time,current_rate,side=='short')
        if stop is None:return 0.
        equity=self.equity();budget=min(equity*self.campaign_fraction,self.remaining_direction(side=='short',equity))
        stake=min(original,margin_for_risk(budget,current_rate,stop,leverage),max_stake)
        self.__dict__.setdefault('_pending_risk',{})[pair]=(budget,abs(current_rate-stop))
        return stake if min_stake is None or stake>=min_stake else 0.

    def confirm_trade_entry(self,pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs):
        pending=self.__dict__.get('_pending_risk',{}).get(pair)
        if pending is None:return False
        budget,distance=pending
        stop=rate+distance if side=='short' else max(rate-distance,rate*.001)
        if amount*(distance+.0005*(rate+stop))>budget+1e-6:return False
        if budget>self.remaining_direction(side=='short',self.equity())+1e-6:return False
        return super().confirm_trade_entry(pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs)

    def order_filled(self,pair,trade,order,current_time,**kwargs):
        super().order_filled(pair,trade,order,current_time,**kwargs)
        if order.ft_order_side==trade.entry_side and trade.nr_of_successful_entries==1:
            budget,distance=self._pending_risk[pair]
            first=trade.select_filled_orders(trade.entry_side)[0].safe_price
            trade.set_custom_data(key='research_budget',value=budget)
            trade.set_custom_data(key='research_stop',value=first+distance if trade.is_short else max(first-distance,first*.001))
        stop=trade.get_custom_data(key='research_stop',default=None)
        # Upstream calc_total_profit also divides by remaining notional;
        # a fully closed campaign has no remaining stop exposure to audit.
        entries=trade.select_filled_orders(trade.entry_side)
        exits=trade.select_filled_orders(trade.exit_side)
        remaining=sum(o.safe_filled for o in entries)-sum(o.safe_filled for o in exits)
        if stop is not None and remaining>1e-12:
            loss=max(0.,-self.calc_total_profit(trade,entries,exits,stop)[0])
            logging.getLogger(__name__).info('RISK_AUDIT '+json.dumps({'pair':pair,'trade_id':trade.id,'time':current_time.isoformat(),'budget':trade.get_custom_data(key='research_budget'),'planned_stop_loss':loss,'stop':stop,'is_short':trade.is_short}))

    def custom_stoploss(self,pair,trade,current_time,current_rate,current_profit,after_fill=False,**kwargs):
        stop=trade.get_custom_data(key='research_stop',default=None)
        if stop is None:return None
        return stoploss_from_absolute(stop,current_rate,is_short=trade.is_short,leverage=trade.leverage)

    def confirm_trade_exit(self,pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs):
        if exit_reason in ('stop_loss','trailing_stop_loss'):return True
        return super().confirm_trade_exit(pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs)

    def adjust_trade_position(self,trade,current_time,current_rate,*args,**kwargs):
        adjustment=super().adjust_trade_position(trade,current_time,current_rate,*args,**kwargs)
        if adjustment is None:return None
        amount,tag=adjustment if isinstance(adjustment,tuple) else (adjustment,None)
        if amount is None or amount<=0:return adjustment
        stop=trade.get_custom_data(key='research_stop',default=None)
        budget=trade.get_custom_data(key='research_budget',default=0.)
        if stop is None or (not trade.is_short and current_rate<=stop) or (trade.is_short and current_rate>=stop):return None
        entries=trade.select_filled_orders(trade.entry_side);exits=trade.select_filled_orders(trade.exit_side)
        loss=max(0.,-self.calc_total_profit(trade,entries,exits,stop)[0])
        allowed=margin_for_risk(max(0.,budget-loss),current_rate,stop,trade.leverage)
        capped=min(amount,allowed)
        minimum=kwargs.get('min_stake',args[1] if len(args)>1 else None)
        if capped<=0 or (minimum is not None and capped<minimum):return None
        return (capped,tag) if isinstance(adjustment,tuple) else capped


class NFIYtdDirection(NFIYtdBudget):
    direction_fraction=.015
