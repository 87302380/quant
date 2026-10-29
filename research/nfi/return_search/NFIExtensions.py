"""Second-stage hypotheses: combine known mechanisms, or extend strong winners."""
from NFIOptimize import NFIOptNoAdds,NFIOptWeighted,NFIRiskOverheat80


class NFIOptOverheatNoAdds(NFIOptNoAdds,NFIRiskOverheat80):
    pass


class NFIOptWeightedNoAdds(NFIOptNoAdds,NFIOptWeighted):
    pass


class NFIOptTrendRunner(NFIRiskOverheat80):
    reason='research_trend_runner_end'

    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if self.expired(trade,current_time):return self.deadline_reason
        original=super().custom_exit(pair,trade,current_time,current_rate,current_profit,**kwargs)
        frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
        if len(frame)<2:return original
        last,previous=frame.iloc[-1],frame.iloc[-2]
        strong=(last.close<last.EMA_20 and last.EMA_20<previous.EMA_20 and last.EMA_12_4h<last.EMA_50_4h) if trade.is_short else (last.close>last.EMA_20 and last.EMA_20>previous.EMA_20 and last.EMA_12_4h>last.EMA_50_4h)
        armed=trade.get_custom_data(key='opt_runner_armed',default=False)
        if armed and not strong:return self.reason
        if original and str(original).startswith('exit_profit_') and strong:
            entries=trade.select_filled_orders(trade.entry_side)
            pnl=self.calc_total_profit(trade,entries,trade.select_filled_orders(trade.exit_side),current_rate)[0]
            if pnl>0:
                trade.set_custom_data(key='opt_runner_armed',value=True)
                return None
        return original

    def confirm_trade_exit(self,pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs):
        if exit_reason==self.reason:return True
        return super().confirm_trade_exit(pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs)
