"""Return-oriented exploratory hypotheses, fixed before comparing this batch."""
from pathlib import Path
import sys
import pandas as pd
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'risk_study'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ytd_research'))
from NFIRiskControls import NFI24Hour,NFIRiskOverheat80
from NFIYtdRisk import NFIYtdBudget


class NFIOptLongOnly(NFI24Hour):
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata);df['enter_short']=0
        return df


class NFIOptNoShortRebuy(NFI24Hour):
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        weak=df.enter_tag.fillna('').map(lambda tag:bool(set(tag.split())&set(self.short_rebuy_mode_tags)))
        df.loc[weak,'enter_short']=0
        return df


class NFIOptNoAdds(NFI24Hour):
    def adjust_trade_position(self,*args,**kwargs):
        adjustment=super().adjust_trade_position(*args,**kwargs)
        value=adjustment[0] if isinstance(adjustment,tuple) else adjustment
        return adjustment if value is None or value<0 else None


class NFIOptOverheatLong(NFIRiskOverheat80):
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata);df['enter_short']=0
        return df


def closed_relative_strength(base,own,btc):
    """4h close-to-close 24h return vs BTC, available at close of base 5m."""
    def transform(frame,name):
        result=pd.DataFrame({'available':pd.to_datetime(frame.date,utc=True).astype('datetime64[ns, UTC]')+pd.Timedelta(hours=4)-pd.Timedelta(minutes=5),
                             name:frame.close.pct_change(6,fill_method=None).to_numpy()})
        return result.sort_values('available')
    left=pd.DataFrame({'date':pd.to_datetime(base.date,utc=True).astype('datetime64[ns, UTC]')})
    for frame,name in [(own,'own'),(btc,'btc')]:
        left=pd.merge_asof(left,transform(frame,name),left_on='date',right_on='available').drop(columns='available')
    return pd.Series((left.own-left.btc).to_numpy(),index=base.index)


class NFIOptRelativeStrength(NFIRiskOverheat80):
    def populate_entry_trend(self,df,metadata):
        df=super().populate_entry_trend(df,metadata)
        rs=closed_relative_strength(df,self.dp.get_pair_dataframe(metadata['pair'],'4h'),self.dp.get_pair_dataframe('BTC/USDT:USDT','4h'))
        # BTC itself is exempt: its relative return to itself is identically zero.
        if metadata['pair']!='BTC/USDT:USDT':
            df.loc[~(rs>=0),'enter_long']=0;df.loc[~(rs<=0),'enter_short']=0
        return df


class NFIOptWeighted(NFIRiskOverheat80):
    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        stake=super().custom_stake_amount(pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs)
        tags=set((entry_tag or '').split())
        strong=tags&set(self.long_top_coins_mode_tags+self.long_normal_mode_tags)
        weak=tags&set(self.short_rebuy_mode_tags)
        factor=1.5 if side=='long' and strong else .5 if side=='short' and weak else 1.
        result=min(stake*factor,max_stake)
        return result if min_stake is None or result>=min_stake else 0.


class NFIOptCampaignTrail(NFIRiskOverheat80):
    """Close-based whole-campaign net P&L trail, retaining 60% after 3% first margin."""
    reason='research_campaign_profit_trail'

    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if self.expired(trade,current_time):return self.deadline_reason
        frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
        entries=trade.select_filled_orders(trade.entry_side)
        if entries and not frame.empty:
            first=entries[0];margin=first.safe_filled*first.safe_price/trade.leverage
            # Evaluate at the last known CLOSED bar, not the current bar's future high.
            pnl=self.calc_total_profit(trade,entries,trade.select_filled_orders(trade.exit_side),float(frame.iloc[-1].close))[0]
            peak=max(trade.get_custom_data(key='opt_profit_peak',default=0.),pnl)
            trade.set_custom_data(key='opt_profit_peak',value=peak)
            if peak>=margin*.03 and pnl<=peak*.6:return self.reason
        return super().custom_exit(pair,trade,current_time,current_rate,current_profit,**kwargs)

    def confirm_trade_exit(self,pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs):
        if exit_reason==self.reason:return True
        return super().confirm_trade_exit(pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs)


class NFIOptSizeOnly(NFIYtdBudget):
    """Control: ATR-based initial sizing, original adds and exits, no ATR stop."""
    use_custom_stoploss=False
    adjust_trade_position=NFI24Hour.adjust_trade_position
    confirm_trade_exit=NFI24Hour.confirm_trade_exit
    order_filled=NFI24Hour.order_filled
