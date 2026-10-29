"""Frozen exploratory controls; original X8 remains unchanged."""
from datetime import timedelta
from pathlib import Path
import sys
import pandas as pd

from freqtrade.strategy import stoploss_from_absolute

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'study'))
from NFI24Hour import NFI24Hour


class NFIRiskStop3(NFI24Hour):
    use_custom_stoploss = True
    adverse_price_fraction = .03

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit,
                        after_fill=False, **kwargs):
        entries = trade.select_filled_orders(trade.entry_side)
        first = entries[0].safe_price if entries else trade.open_rate
        stop = first * (1 + self.adverse_price_fraction if trade.is_short else 1 - self.adverse_price_fraction)
        return stoploss_from_absolute(stop, current_rate, is_short=trade.is_short, leverage=trade.leverage)

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs):
        if exit_reason in ('stop_loss', 'trailing_stop_loss'):
            return True
        return super().confirm_trade_exit(pair, trade, order_type, amount, rate, time_in_force,
                                          exit_reason, current_time, **kwargs)


class NFIRiskStop6(NFIRiskStop3):
    adverse_price_fraction = .06


class NFIRiskStale12(NFI24Hour):
    stale_reason = 'research_negative_after_12h'

    def stale(self, trade, now, rate):
        if now < trade.open_date_utc + timedelta(hours=12):
            return False
        entries = trade.select_filled_orders(trade.entry_side)
        exits = trade.select_filled_orders(trade.exit_side)
        return self.calc_total_profit(trade, entries, exits, rate)[0] < 0

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        if not self.expired(trade, current_time) and self.stale(trade, current_time, current_rate):
            return self.stale_reason
        return super().custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)

    def adjust_trade_position(self, trade, current_time, current_rate, *args, **kwargs):
        if self.expired(trade, current_time) or self.stale(trade, current_time, current_rate):
            return None
        return super().adjust_trade_position(trade, current_time, current_rate, *args, **kwargs)

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs):
        if exit_reason == self.stale_reason:
            return True
        return super().confirm_trade_exit(pair, trade, order_type, amount, rate, time_in_force,
                                          exit_reason, current_time, **kwargs)


class NFIRiskTrendGate(NFI24Hour):
    def populate_entry_trend(self, dataframe, metadata):
        dataframe = super().populate_entry_trend(dataframe, metadata)
        info = self.dp.get_pair_dataframe(metadata['pair'], '4h')[['date', 'close']].copy()
        # Base rows are candle OPEN times: a 4h close is known at the end of the last5m candle.
        info['available'] = (info.date + pd.Timedelta(hours=4) - pd.Timedelta(minutes=5)).astype('datetime64[ns, UTC]')
        left = pd.DataFrame({'date': dataframe.date.astype('datetime64[ns, UTC]')})
        aligned = pd.merge_asof(left.sort_values('date'), info[['available', 'close']].sort_values('available'),
                                left_on='date', right_on='available')
        close4h = pd.Series(aligned.close.to_numpy(), index=dataframe.index)
        long_ok = (dataframe['EMA_12_4h'] > dataframe['EMA_200_4h']) & (close4h > dataframe['EMA_200_4h'])
        short_ok = (dataframe['EMA_12_4h'] < dataframe['EMA_200_4h']) & (close4h < dataframe['EMA_200_4h'])
        dataframe.loc[~long_ok, 'enter_long'] = 0
        dataframe.loc[~short_ok, 'enter_short'] = 0
        return dataframe


class NFIRiskProfitProtect(NFI24Hour):
    """After a CLOSED5m +2% favorable move, protect first-entry cost+0.15% price."""
    use_custom_stoploss = True

    def protection_price(self, pair, trade):
        entries = trade.select_filled_orders(trade.entry_side)
        if not entries:
            return None
        first = entries[0].safe_price
        frame, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if frame.empty:
            return None
        favorable = (1-frame.iloc[-1]['close']/first) if trade.is_short else (frame.iloc[-1]['close']/first-1)
        armed = trade.get_custom_data(key='research_profit_protect',default=False)
        if favorable >= .02:
            trade.set_custom_data(key='research_profit_protect',value=True)
            armed = True
        return first*(.9985 if trade.is_short else 1.0015) if armed else None

    def custom_stoploss(self, pair, trade, current_time, current_rate, current_profit,
                        after_fill=False, **kwargs):
        stop = self.protection_price(pair, trade)
        if stop is None:
            return None
        return stoploss_from_absolute(stop,current_rate,is_short=trade.is_short,leverage=trade.leverage)

    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        stop = self.protection_price(pair,trade)
        if stop is not None and ((trade.is_short and current_rate>=stop) or (not trade.is_short and current_rate<=stop)):
            return 'research_profit_protect_gap'
        return super().custom_exit(pair,trade,current_time,current_rate,current_profit,**kwargs)

    def confirm_trade_exit(self,pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs):
        if exit_reason in ('stop_loss','trailing_stop_loss','research_profit_protect_gap'):
            return True
        return super().confirm_trade_exit(pair,trade,order_type,amount,rate,time_in_force,exit_reason,current_time,**kwargs)


class NFIRiskOverheat80(NFI24Hour):
    """Post-diagnosis hypothesis: reject long4h RSI>=80 and short4h RSI<=20."""
    def populate_entry_trend(self,dataframe,metadata):
        dataframe=super().populate_entry_trend(dataframe,metadata)
        rsi=dataframe['RSI_14_4h']
        dataframe.loc[~(rsi<80),'enter_long']=0
        dataframe.loc[~(rsi>20),'enter_short']=0
        return dataframe
