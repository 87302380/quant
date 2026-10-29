"""Run Freqtrade's lookahead check while retaining full and sliced trade evidence."""
import json
from pathlib import Path
import sys
import tempfile

from freqtrade.optimize.analysis.lookahead import LookaheadAnalysis
from freqtrade.main import main
from freqtrade.resolvers import StrategyResolver

records = []
isolated = '--isolate-cache' in sys.argv
if isolated:
    sys.argv.remove('--isolate-cache')
prefix = 'lookahead_isolated' if isolated else 'lookahead'
original = LookaheadAnalysis.analyze_row
original_load = StrategyResolver.load_strategy
original_prepare = LookaheadAnalysis.prepare_data
trace = []


def prepare_isolated(self, holder, pairs):
    runtime = Path('data/nfi/lookahead-isolated')
    runtime.mkdir(parents=True, exist_ok=True)
    previous = self.local_config['user_data_dir']
    self.local_config['user_data_dir'] = Path(tempfile.mkdtemp(dir=runtime.resolve()))
    try:
        return original_prepare(self, holder, pairs)
    finally:
        self.local_config['user_data_dir'] = previous


def load_strategy(config):
    strategy = original_load(config)
    exit_original = strategy.custom_exit
    def traced_exit(pair, trade, current_time, current_rate, current_profit, **kwargs):
        result = exit_original(pair, trade, current_time, current_rate, current_profit, **kwargs)
        if pair == 'PYTH/USDT:USDT' and str(current_time).startswith('2026-07-01 15:'):
            df, _ = strategy.dp.get_analyzed_dataframe(pair, strategy.timeframe)
            trace.append(dict(timerange=config['timerange'], time=str(current_time), rate=current_rate,
                              profit=current_profit, result=result, last_date=str(df.iloc[-1]['date']),
                              first_date=str(df.iloc[0]['date']), candles=len(df)))
            Path(f'results/nfi/study/{prefix}_trace.json').write_text(json.dumps(trace, indent=2))
        return result
    strategy.custom_exit = traced_exit
    return strategy


def capture(self, idx, row):
    original(self, idx, row)
    columns = ['pair', 'open_date', 'close_date', 'open_rate', 'close_rate', 'profit_abs', 'exit_reason']
    def serial(holder):
        return holder.result['results'][columns].to_dict('records')
    records.append({'full_trade': {k: row[k] for k in columns},
                    'entry_slice': serial(self.entry_varHolders[idx]),
                    'exit_slice': serial(self.exit_varHolders[idx])})
    Path(f'results/nfi/study/{prefix}_detail.json').write_text(json.dumps(records, indent=2, default=str))


if __name__ == '__main__':
    LookaheadAnalysis.analyze_row = capture
    StrategyResolver.load_strategy = staticmethod(load_strategy)
    if isolated:
        LookaheadAnalysis.prepare_data = prepare_isolated
    sys.exit(main(sys.argv[1:]))
