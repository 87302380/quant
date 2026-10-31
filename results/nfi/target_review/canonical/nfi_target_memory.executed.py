"""Lossless column retention after full-precision indicator/signal calculation."""
import ast
import gc
import inspect
import logging

from freqtrade.strategy.interface import IStrategy, StrategyResultValidator

original_signals = IStrategy.ft_advise_signals
MARKER = 'target_review_signals_complete'


def runtime_columns(strategy):
    """Conservative union of literal/dotted columns in every inherited runtime method."""
    columns = {'date', 'open', 'high', 'low', 'close', 'volume', 'enter_long',
               'enter_short', 'exit_long', 'exit_short', 'enter_tag', 'exit_tag'}
    sources = set()
    for cls in type(strategy).__mro__:
        functions = [getattr(v, '__func__', v) for v in cls.__dict__.values()]
        path = next((inspect.getsourcefile(v) for v in functions if inspect.isfunction(v)), None)
        if path is None or path in sources:
            continue
        sources.add(path)
        with open(path) as stream:
            tree = ast.parse(stream.read())
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for method in node.body:
                if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if 'indicator' in method.name or method.name in {
                    'populate_entry_trend', 'populate_exit_trend', 'short_signal',
                    'populate_buy_trend', 'populate_sell_trend'}:
                    continue
                for value in ast.walk(method):
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        columns.add(value.value)
                    elif isinstance(value, ast.Attribute):
                        columns.add(value.attr)
    return columns


def precomputed_signals(self, dataframe, metadata):
    if dataframe.attrs.get(MARKER):
        return dataframe
    return original_signals(self, dataframe, metadata)


def compact_indicators(self, data):
    columns = runtime_columns(self)
    result = {}
    for pair, raw in data.items():
        validator = StrategyResultValidator(raw, warn_only=self.disable_dataframe_checks)
        frame = self.advise_indicators(raw.copy(), {'pair': pair})
        validator.assert_df(frame)
        frame = original_signals(self, frame, {'pair': pair})
        before = len(frame.columns)
        frame = frame.loc[:, [c for c in frame.columns if c in columns]].copy()
        frame.attrs[MARKER] = True
        validator.assert_df(frame)
        result[pair] = frame
        logging.getLogger(__name__).info('TARGET_FULL_PRECISION_COLUMNS %s %s -> %s', pair, before, len(frame.columns))
        gc.collect()
    return result


def install():
    IStrategy.advise_all_indicators = compact_indicators
    IStrategy.ft_advise_signals = precomputed_signals
