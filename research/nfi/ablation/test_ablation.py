import ast
from datetime import datetime, timezone
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
import tempfile
from unittest.mock import patch

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import NFIAblation as ab
from NFIShortTargetOnly import NFIShortStop_2_0_R2_0, NFIShortStop_2_0_R1_5, NFIShortStop_2_0_R1_0
from NFIShortResearch import NFIShortBase, NFIOptWeightedNoAdds
from NFIShortATR import NFI24Hour
from NFITargetReview import NFIShortTargetR15, NFIShortTargetR10, NFIShortOPCompression


class AblationTest(unittest.TestCase):
    def test_all_eight_combinations_and_compression_flags(self):
        combinations = set()
        for name in ['base', 'S', 'C', 'P', 'SC', 'SP', 'CP', 'SCP']:
            cls = getattr(ab, 'NFIAblation_' + name)
            combinations.add((cls.shock_gate, cls.climax, cls.compression))
            self.assertEqual(cls.extras, {166, 169} if cls.compression else set())
        self.assertEqual(len(combinations), 8)

    def test_copied_management_methods_match_original_ast(self):
        root = Path(__file__).resolve().parents[1]
        def methods(path, name):
            c = next(n for n in ast.parse(path.read_text()).body if isinstance(n, ast.ClassDef) and n.name == name)
            return {n.name: ast.dump(n) for n in c.body if isinstance(n, ast.FunctionDef)}
        self.assertEqual(methods(root/'opportunities/NFIShortOpportunities.py', 'NFIShortOPControl'),
                         methods(root/'ablation/NFIAblation.py', '_OPNoClimax'))

    def test_climax_and_shock_filters_leave_shorts_unchanged(self):
        frame = pd.DataFrame({'enter_long': [1, 1, 1, 1], 'enter_short': [0, 0, 0, 1],
                              'enter_tag': ['dip', 'dip', 'trend', 'trend'],
                              'bre_known': [True, True, True, True],
                              'bre_recent': [False, True, False, False],
                              'pm_shock': [False, False, True, False]})
        s = ab.NFIAblation_SC.__new__(ab.NFIAblation_SC)
        with patch.object(ab._OPNoClimax, 'populate_entry_trend', return_value=frame.copy()), \
             patch.object(ab, 'signal_family', side_effect=lambda t: t):
            result = s.populate_entry_trend(frame, {})
        self.assertEqual(result.enter_long.tolist(), [0, 1, 0, 1])
        self.assertEqual(result.enter_short.tolist(), [0, 0, 0, 1])

    def test_original_rejected_dip_still_has_priority_before_post_filter(self):
        s = ab.NFIAblation_CP.__new__(ab.NFIAblation_CP)
        original = pd.DataFrame({'enter_long': [1], 'enter_short': [0], 'enter_tag': ['dip'],
                                 'volume': [1], 'bre_known': [True], 'bre_recent': [False]})
        expanded = original.copy(); expanded.enter_tag = '166'
        with patch.object(ab.NFIShortBRControl, 'populate_entry_trend', side_effect=[original, expanded]), \
             patch.object(ab, 'signal_family', side_effect=lambda t: t):
            result = s.populate_entry_trend(original.copy(), {})
        self.assertEqual(result.enter_long.tolist(), [0])
        self.assertEqual(result.enter_tag.tolist(), ['dip'])

    def make_strategy(self, cls):
        s = cls.__new__(cls)
        s.config = {'fee': .0005}
        s.wallets = SimpleNamespace(get_total_stake_amount=lambda: 10000.)
        s.dp = SimpleNamespace(get_analyzed_dataframe=lambda *args: (pd.DataFrame({'research_short_atr': [2.]}), None))
        return s

    def test_target_change_preserves_actual_stake_distance_and_budget(self):
        values = []
        for cls in [NFIShortStop_2_0_R2_0, NFIShortStop_2_0_R1_5, NFIShortStop_2_0_R1_0]:
            s = self.make_strategy(cls)
            with patch.object(NFI24Hour, 'custom_stake_amount', return_value=1000.):
                margin = s.custom_stake_amount('X', None, 100., 1000., None, 1000., 3., '505', 'short')
            values.append((margin, s._short_pending['X']))
            self.assertLessEqual(margin * 3 / 100 * (4 + .0005 * 204), 100 + 1e-8)
        self.assertEqual(values[0], values[1]); self.assertEqual(values[1], values[2])

    def test_primary_candidates_inherit_all_execution_methods(self):
        for cls in [NFIShortTargetR15, NFIShortTargetR10]:
            self.assertEqual(set(cls.__dict__) - {'__module__', '__doc__', '_abc_impl', '__abstractmethods__'}, {'reward_multiple'})
            for method in ['custom_stake_amount', 'order_filled', 'custom_stoploss',
                           'populate_entry_trend', 'custom_exit', 'adjust_trade_position']:
                self.assertIs(getattr(cls, method), getattr(NFIShortOPCompression, method))

    def test_metadata_scope_restores_registry_and_rejects_missing_tiers(self):
        import nfi_target_engine as engine
        markets = {'X': {'id': 'x'}, 'Y': {'id': 'y'}}
        fake = SimpleNamespace(_markets=markets, _config={'exchange': {'pair_whitelist': ['X']}})
        def fetch(s):
            self.assertEqual(set(s._markets), {'X'})
            return {'X': [{'maxLeverage': 3}]}
        with patch.object(engine, 'original', side_effect=fetch):
            self.assertEqual(set(engine.scoped_leverage_tiers(fake)), {'X'})
        self.assertIs(fake._markets, markets)
        with patch.object(engine, 'original', return_value={}):
            with self.assertRaises(ValueError):engine.scoped_leverage_tiers(fake)
        self.assertIs(fake._markets, markets)

    def test_memory_retention_keeps_float64_bits_and_precomputed_signals(self):
        import nfi_target_memory as memory
        value = np.nextafter(1., 2.)
        raw = pd.DataFrame({'date': pd.date_range('2026-01-01', periods=2, freq='5min', tz='UTC'),
                            'open': [1., 1.], 'high': [1., 1.], 'low': [1., 1.],
                            'close': [1., 1.], 'volume': [1., 1.]})
        full = raw.assign(keep=[value, np.nan], compute_only=[value, 1.], unused=[7., 8.])
        fake = SimpleNamespace(disable_dataframe_checks=False,
                               advise_indicators=lambda data, metadata: full.copy())
        def signals(s, frame, metadata):
            return frame.assign(enter_long=frame.compute_only.gt(1.).astype(int))
        columns = set(raw.columns) | {'keep', 'enter_long'}
        with patch.object(memory, 'runtime_columns', return_value=columns), \
             patch.object(memory, 'original_signals', side_effect=signals):
            result = memory.compact_indicators(fake, {'X': raw})['X']
        np.testing.assert_array_equal(result.keep.to_numpy().view('uint64'), full.keep.to_numpy().view('uint64'))
        self.assertEqual(result.enter_long.tolist(), [1, 0])
        self.assertNotIn('compute_only', result)
        with patch.object(memory, 'original_signals', side_effect=AssertionError('recomputed')):
            self.assertIs(memory.precomputed_signals(fake, result, {}), result)

    def test_signal_cache_roundtrip_is_exact_and_skips_calculation(self):
        import nfi_target_memory as memory
        raw = pd.DataFrame({'date': pd.date_range('2026-01-01', periods=2, freq='5min', tz='UTC'),
                            'open': [1., 1.], 'high': [1., 1.], 'low': [1., 1.],
                            'close': [1., 1.], 'volume': [1., 1.], 'open_count': [1,1]})
        fake = SimpleNamespace(disable_dataframe_checks=False, advise_indicators=lambda frame, metadata: frame)
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(memory, 'signal_cache', return_value=Path(temporary)), \
             patch.object(memory, 'runtime_columns', return_value=(set(raw.columns)-{'open_count'})|{'enter_long'}), \
             patch.object(memory, 'original_signals', side_effect=lambda s, frame, metadata: frame.assign(enter_long=[1,0])):
            first = memory.compact_indicators(fake, {'X': raw})['X']
            fake.advise_indicators = lambda *a: self.fail('cache recalculated')
            second = memory.compact_indicators(fake, {'X': raw})['X']
        pd.testing.assert_frame_equal(first, second, check_exact=True)

    def test_real_order_filled_updates_persistent_and_cached_target(self):
        for cls, target in [(NFIShortStop_2_0_R2_0, 92.), (NFIShortStop_2_0_R1_5, 94.), (NFIShortStop_2_0_R1_0, 96.)]:
            s = self.make_strategy(cls); s._short_pending = {'X': 4.}
            data = {}
            trade = SimpleNamespace(id=1, is_short=True, enter_tag='505', entry_side='sell', nr_of_successful_entries=1,
                                    select_filled_orders=lambda side: [SimpleNamespace(safe_price=100.)],
                                    set_custom_data=lambda key, value: data.update({key: value}),
                                    get_custom_data=lambda key, default=None: data.get(key, default))
            with patch.object(NFIOptWeightedNoAdds, 'order_filled', return_value=None):
                s.order_filled('X', trade, SimpleNamespace(ft_order_side='sell'), None)
            self.assertEqual(s.short_levels(trade), (104., target))
            self.assertEqual(data['short_target'], target)
            s._short_level_cache = {}
            self.assertEqual(s.short_levels(trade), (104., target))

    def test_real_exit_uses_callback_price_not_candle_low(self):
        s = self.make_strategy(NFIShortStop_2_0_R1_5)
        s._short_level_cache = {1: (104., 94.)}
        trade = SimpleNamespace(id=1, is_short=True)
        with patch.object(s, 'expired', return_value=False):
            self.assertIsNone(NFIShortBase.custom_exit(s, 'X', trade, None, 95., 0))
            self.assertEqual(NFIShortBase.custom_exit(s, 'X', trade, None, 94., 0), 'research_short_target')


if __name__ == '__main__':
    unittest.main()
