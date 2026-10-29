"""Isolated research control: original X8 with an unconditional 24-hour deadline."""
from datetime import timedelta
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'upstream'))
from NostalgiaForInfinityX8 import NostalgiaForInfinityX8


class NFI24Hour(NostalgiaForInfinityX8):
    deadline_reason = 'research_time_limit_24h'

    @staticmethod
    def expired(trade, now):
        return now >= trade.open_date_utc + timedelta(hours=24)

    def custom_exit(self, pair, trade, current_time, current_rate, current_profit, **kwargs):
        if self.expired(trade, current_time):
            return self.deadline_reason
        return super().custom_exit(pair, trade, current_time, current_rate, current_profit, **kwargs)

    def confirm_trade_exit(self, pair, trade, order_type, amount, rate, time_in_force,
                           exit_reason, current_time, **kwargs):
        if exit_reason == self.deadline_reason:
            return True
        return super().confirm_trade_exit(pair, trade, order_type, amount, rate, time_in_force,
                                          exit_reason, current_time, **kwargs)

    def adjust_trade_position(self, trade, current_time, *args, **kwargs):
        if self.expired(trade, current_time):
            return None
        return super().adjust_trade_position(trade, current_time, *args, **kwargs)

    def check_entry_timeout(self, pair, trade, order, current_time, **kwargs):
        if self.expired(trade, current_time):
            return True
        return super().check_entry_timeout(pair, trade, order, current_time, **kwargs)
