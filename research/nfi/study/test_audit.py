"""Accounting tests for partial exits, short cashflows, fees and reconciliation."""
import gzip
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import nfi_analyze
import importlib.util
import pandas as pd


class EquityAuditTest(unittest.TestCase):
    def test_filter_waits_for_daily_close_and_ignores_future_days(self):
        spec = importlib.util.spec_from_file_location('filter_control', Path(__file__).with_name('NFIHistoricalFilters.py'))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        dates = pd.Series(pd.to_datetime(['2026-07-03T23:55Z', '2026-07-04T00:00Z']))
        daily = pd.DataFrame({'date':pd.date_range('2026-07-01', periods=4, tz='UTC'),
                              'high':[110,110,110,1000], 'low':[100,100,100,1]})
        listed = pd.Timestamp('2026-01-01', tz='UTC')
        expected = [False, True]
        self.assertEqual(module.historical_eligibility(dates, daily, listed).tolist(), expected)
        self.assertEqual(module.historical_eligibility(dates, daily.iloc[:3], listed).tolist(), expected)
        self.assertFalse(module.historical_eligibility(dates, daily, pd.Timestamp('2026-06-01',tz='UTC')).any())

    def test_partial_exits_and_short_cashflows_reconcile(self):
        start = 1782864000000
        def trade(pair, short, fills):
            orders = []
            pnl = 0
            for i, side, qty, price, entry in fills:
                pnl += (1 if side == 'sell' else -1) * qty * price - qty * price * .001
                orders.append(dict(amount=qty, safe_price=price, ft_order_side=side,
                                   ft_is_entry=entry, order_filled_timestamp=start + i * 300000))
            return dict(pair=pair, is_short=short, orders=orders, profit_abs=pnl,
                        fee_open=.001, fee_close=.001, leverage=3)
        long = trade('LONG/USDT:USDT', False, [(0,'buy',10,100,True), (1,'buy',5,90,True),
                     (2,'sell',8,110,False), (3,'sell',7,105,False)])
        short = trade('SHORT/USDT:USDT', True, [(0,'sell',2,200,True), (3,'buy',2,190,False)])
        s = dict(trades=[long, short], starting_balance=10000,
                 final_balance=10000+long['profit_abs']+short['profit_abs'],
                 backtest_start_ts=start, backtest_end_ts=start+3600000)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'data/nfi/freqtrade/futures'
            folder.mkdir(parents=True)
            for pair, price in [('LONG_USDT_USDT',100), ('SHORT_USDT_USDT',200)]:
                for tf, kind, step in [('5m','futures',300000),('1h','mark',3600000)]:
                    rows = [[i,price,price,price,price,1] for i in range(start-step,start+3600001,step)]
                    (folder/f'{pair}-{tf}-{kind}.json.gz').write_bytes(gzip.compress(json.dumps(rows).encode()))
            with patch.object(nfi_analyze, 'ROOT', root):
                metrics, frame = nfi_analyze.equity_audit(s)
                self.assertAlmostEqual(frame.equity.iloc[-1], 10181.155)
                self.assertAlmostEqual(metrics['fees_usdt'], 3.845)
                self.assertAlmostEqual(metrics['max_margin_basis_usdt'], 1850/3)
                self.assertAlmostEqual(frame.margin_basis.iloc[-1], 0)
                self.assertLess(metrics['max_campaign_ledger_error_usdt'], 1e-8)
                s['trades'][0]['profit_abs'] += 10
                with self.assertRaisesRegex(ValueError, 'ledger differs'):
                    nfi_analyze.equity_audit(s)


if __name__ == '__main__':
    unittest.main()
