"""Lossless column retention after full-precision indicator/signal calculation."""
import ast
import gc
import inspect
import logging
import hashlib
import json
from pathlib import Path
import shutil

import pandas as pd

from freqtrade.strategy.interface import IStrategy, StrategyResultValidator

original_signals = IStrategy.ft_advise_signals
MARKER = 'target_review_signals_complete'


def signal_cache(strategy):
    # These tested classes share signal methods and differ only in reward_multiple.
    families = {'NFIShortOPCompression': 'canonical', 'NFIShortTargetR15': 'canonical',
                'NFIShortTargetR10': 'canonical', 'NFIShortStop_2_0_R2_0': 'cp',
                'NFIShortStop_2_0_R1_5': 'cp', 'NFIShortStop_2_0_R1_0': 'cp'}
    family = families.get(type(strategy).__name__)
    if family is None:
        return None
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted((root / 'research/nfi').rglob('*.py')):
        digest.update(str(path.relative_to(root)).encode()); digest.update(path.read_bytes())
    digest.update(Path(__file__).read_bytes())
    for path in [root/'datasets/nfi_ytd2026/manifest.json', root/'research/nfi/ytd2026/config.backtest.json']:
        digest.update(path.read_bytes())
    digest.update(json.dumps({'family': family, 'fee': strategy.config.get('fee'),
                              'timerange': strategy.config.get('timerange')}, sort_keys=True).encode())
    base = root / 'data/nfi_ytd2026/target_review_signal_cache'
    base.mkdir(exist_ok=True)
    key = digest.hexdigest()
    # Sequential runs only. These are disposable generated indicator caches.
    for child in base.iterdir():
        if child.is_dir() and child.name != key and len(child.name) == 64 and all(c in '0123456789abcdef' for c in child.name):
            shutil.rmtree(child)
    target = base / key
    target.mkdir(exist_ok=True)
    return target


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
    cache = signal_cache(self)
    result = {}
    for pair, raw in data.items():
        validator = StrategyResultValidator(raw, warn_only=self.disable_dataframe_checks)
        saved = cache / (pair.replace('/', '_').replace(':', '_') + '.pkl.gz') if cache else None
        if saved and saved.exists():
            frame = pd.read_pickle(saved, compression='gzip')
            base_columns = ['date', 'open', 'high', 'low', 'close', 'volume']
            pd.testing.assert_frame_equal(frame[base_columns], raw[base_columns], check_exact=True)
            if not frame.attrs.get(MARKER):
                raise ValueError('Incomplete signal cache')
            validator.assert_df(frame)
            result[pair] = frame
            logging.getLogger(__name__).info('TARGET_EXACT_SIGNAL_CACHE %s', pair)
            continue
        frame = self.advise_indicators(raw.copy(), {'pair': pair})
        validator.assert_df(frame)
        frame = original_signals(self, frame, {'pair': pair})
        before = len(frame.columns)
        frame = frame.loc[:, [c for c in frame.columns if c in columns]].copy()
        frame.attrs[MARKER] = True
        validator.assert_df(frame)
        result[pair] = frame
        if saved:
            temporary = saved.with_suffix('.tmp')
            frame.to_pickle(temporary, compression={'method': 'gzip', 'compresslevel': 1, 'mtime': 0})
            temporary.replace(saved)
        logging.getLogger(__name__).info('TARGET_FULL_PRECISION_COLUMNS %s %s -> %s', pair, before, len(frame.columns))
        gc.collect()
    return result


def install():
    IStrategy.advise_all_indicators = compact_indicators
    IStrategy.ft_advise_signals = precomputed_signals
