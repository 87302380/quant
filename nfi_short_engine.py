"""Deadline diagnostics with optional roundoff-only candle-boundary correction."""
import json,sys
from pathlib import Path
from freqtrade.optimize.backtesting import Backtesting,LOW_IDX,HIGH_IDX,OPEN_IDX
from freqtrade.main import main
from nfi_precision import candle_contains

index=sys.argv.index('--deadline-trace');path=Path(sys.argv[index+1]);del sys.argv[index:index+2]
original=Backtesting._get_exit_for_signal
fill_original=Backtesting._get_order_filled
precision_fix='--precision-fix' in sys.argv
if precision_fix:sys.argv.remove('--precision-fix')


def precise_fill(self,rate,row):
    if fill_original(self,rate,row):return True
    return candle_contains(rate,row[LOW_IDX],row[HIGH_IDX])


def traced(self,trade,row,exit_,current_time,amount=None):
    result=original(self,trade,row,exit_,current_time,amount)
    duration=(current_time-trade.open_date_utc).total_seconds()/60
    if duration>=1440:
        last=trade.orders[-1] if trade.orders else None
        record={'pair':trade.pair,'trade_id':trade.id,'open':str(trade.open_date_utc),'time':str(current_time),
                'duration_min':duration,'exit_reason':exit_.exit_reason,'flag':exit_.exit_flag,
                'price_precision':trade.price_precision,'precision_mode':trade.precision_mode_price,
                'open_price':row[OPEN_IDX],'low':row[LOW_IDX],'high':row[HIGH_IDX],
                'result_created':result is not None,'last_order_rate':last.ft_price if last else None,
                'last_order_time':str(last.order_date_utc) if last else None}
        with path.open('a') as f:f.write(json.dumps(record)+'\n')
    return result


if __name__=='__main__':
    Backtesting._get_exit_for_signal=traced
    if precision_fix:Backtesting._get_order_filled=precise_fill
    sys.exit(main(sys.argv[1:]))
