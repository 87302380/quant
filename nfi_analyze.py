"""Campaign attribution and order-ledger equity audit of real X8 backtest exports."""
from collections import defaultdict
import gzip
import json
from pathlib import Path
import zipfile

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def load_result(path):
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if n.endswith('.json') and not n.endswith('_config.json'))
        strategies = json.loads(z.read(name))['strategy']
        if len(strategies) != 1:
            raise ValueError('Expected one engine strategy result')
        return next(iter(strategies.values()))


def filled_orders(trade):
    return [o for o in trade['orders'] if o.get('order_filled_timestamp') is not None]


def family(tag):
    inventory = json.loads((ROOT / 'research/nfi/strategy_inventory.json').read_text())['mode_tags']
    found = set()
    for token in (tag or '').split():
        for key, values in inventory.items():
            if token in values and key in (
                'long_normal_mode_tags', 'long_pump_mode_tags', 'long_quick_mode_tags',
                'long_rebuy_mode_tags', 'long_high_profit_mode_tags', 'long_rapid_mode_tags',
                'long_grind_mode_tags', 'long_btc_mode_tags', 'long_top_coins_mode_tags',
                'long_scalp_mode_tags', 'short_normal_mode_tags', 'short_pump_mode_tags',
                'short_quick_mode_tags', 'short_rebuy_mode_tags', 'short_high_profit_mode_tags',
                'short_rapid_mode_tags', 'short_grind_mode_tags', 'short_top_coins_mode_tags',
                'short_scalp_mode_tags'):
                found.add(key.replace('_mode_tags', ''))
    return '+'.join(sorted(found)) or 'unknown'


def groups(trades, key):
    buckets = defaultdict(list)
    for t in trades:
        buckets[key(t)].append(t)
    return {k: {'campaigns': len(v), 'profit_usdt': sum(t['profit_abs'] for t in v),
                'win_rate_pct': 100 * sum(t['profit_abs'] > 0 for t in v) / len(v),
                'max_hours': max(t['trade_duration'] for t in v) / 60}
            for k, v in sorted(buckets.items(), key=lambda x: -sum(t['profit_abs'] for t in x[1]))}


def equity_audit(s, datadir=None):
    """Signed fill cashflows + remaining inventory value; margin changes do not count as P&L."""
    axis = np.arange(s['backtest_start_ts'], s['backtest_end_ts'] + 1, 300_000, dtype=np.int64)
    cash_delta = np.zeros(len(axis))
    margin_delta = np.zeros(len(axis))
    flows = defaultdict(lambda: np.zeros(len(axis)))
    total_fees = 0.0
    turnover = 0.0
    per_trade_errors = []
    for t in s['trades']:
        qty, basis, pnl = 0.0, 0.0, 0.0
        for o in filled_orders(t):
            q, price = o['amount'], o['safe_price']
            fee = q * price * t['fee_open' if o['ft_is_entry'] else 'fee_close']
            sign = 1 if o['ft_order_side'] == 'buy' else -1
            cash = -sign * q * price - fee
            pnl += cash
            total_fees += fee
            turnover += q * price
            idx = min(np.searchsorted(axis, o['order_filled_timestamp']), len(axis) - 1)
            cash_delta[idx] += cash
            flows[t['pair']][idx] += sign * q
            if o['ft_is_entry']:
                margin_change = q * price / t['leverage']
                qty += q
                basis += margin_change
            else:
                margin_change = -basis * min(q / qty, 1) if qty else 0
                qty -= q
                basis += margin_change
            margin_delta[idx] += margin_change
        per_trade_errors.append(pnl - t['profit_abs'])
    # Reconcile exported order accounting before interpreting any equity metric.
    error = max(map(abs, per_trade_errors), default=0)
    if error > 0.01:
        raise ValueError(f'Order ledger differs from engine campaign P&L by {error}')
    equity = s['starting_balance'] + np.cumsum(cash_delta)
    gross = np.zeros(len(axis))
    mark_equity = equity.copy()
    for pair, delta in flows.items():
        qty = np.cumsum(delta)
        stem = pair.replace('/', '_').replace(':', '_')
        folder = Path(datadir) if datadir else ROOT / 'data/nfi/freqtrade/futures'
        for tf, kind, target in [('5m', 'futures', equity), ('1h', 'mark', mark_equity)]:
            rows = json.loads(gzip.decompress((folder / f'{stem}-{tf}-{kind}.json.gz').read_bytes()))
            step = 300_000 if tf == '5m' else 3_600_000
            dates = np.array([r[0] + step for r in rows], dtype=np.int64)
            prices = np.array([r[4] for r in rows])
            indices = np.searchsorted(dates, axis, side='right') - 1
            if np.any((indices < 0) & (abs(qty) > 1e-6)):
                raise ValueError('No closed marking candle for open inventory')
            px = prices[np.maximum(indices, 0)]
            target += qty * px
            if tf == '5m':
                gross += abs(qty) * px
        if abs(qty[-1]) > 1e-5:
            raise ValueError(f'Unclosed inventory: {pair}: {qty[-1]}')
    final_error = equity[-1] - s['final_balance']
    if abs(final_error) > 0.01:
        raise ValueError(f'Final equity does not reconcile: {final_error}')
    peak = np.maximum.accumulate(np.maximum(equity, s['starting_balance']))
    dd = (peak - equity) / peak
    synchronized_marks = mark_equity[axis % 3_600_000 == 0]
    mark_peak = np.maximum.accumulate(np.maximum(synchronized_marks, s['starting_balance']))
    margin = np.cumsum(margin_delta)
    frame = pd.DataFrame({'time': pd.to_datetime(axis, unit='ms', utc=True),
                          'equity': equity, 'hourly_mark_equity': mark_equity,
                          'margin_basis': margin, 'gross_notional': gross})
    metrics = {'fees_usdt': total_fees, 'turnover_usdt': turnover,
               'max_campaign_ledger_error_usdt': error, 'final_equity_error_usdt': final_error,
               'mtm_drawdown_pct': 100 * float(dd.max()),
               'hourly_mark_drawdown_pct': 100 * float(((mark_peak - synchronized_marks) / mark_peak).max()),
               'minimum_equity_usdt': float(equity.min()),
               'max_margin_basis_usdt': float(margin.max()),
               'average_margin_basis_usdt': float(margin.mean()),
               'max_gross_notional_usdt': float(gross.max()),
               'exposed_time_pct': 100 * float((gross > 0.01).mean()),
               'drawdown_trough_time': str(frame.iloc[int(dd.argmax())]['time']),
               'sampling': '5m grid, most recently closed futures candle; mark sensitivity sampled only at synchronized whole hours (no stale-price intrahour marks); no intrabar extrema'}
    monthly = frame.set_index('time')['equity'].resample('ME').last()
    prev = s['starting_balance']
    metrics['monthly_mtm'] = {}
    for date, value in monthly.items():
        metrics['monthly_mtm'][str(date.date())] = {'profit_usdt': float(value - prev),
                                                  'return_pct': 100 * float(value / prev - 1)}
        prev = value
    return metrics, frame


def analyze(path, datadir=None):
    s = load_result(path)
    ts = s['trades']
    audit, frame = equity_audit(s, datadir)
    entries = [sum(o['ft_is_entry'] for o in filled_orders(t)) for t in ts]
    exits = [sum(not o['ft_is_entry'] for o in filled_orders(t)) for t in ts]
    result = {'archive': str(path.relative_to(ROOT)), 'archive_sha256': __import__('hashlib').sha256(path.read_bytes()).hexdigest(),
              'campaigns': len(ts), 'pairs_configured': len(s['pairlist']),
              'profit_usdt': s['profit_total_abs'], 'return_pct': 100 * s['profit_total'],
              'win_rate_pct': 100 * s['winrate'], 'closed_trade_drawdown_pct': 100 * s['max_drawdown_account'],
              'forced_end_campaigns': sum(t['exit_reason'] == 'force_exit' for t in ts),
              'forced_end_profit_usdt': sum(t['profit_abs'] for t in ts if t['exit_reason'] == 'force_exit'),
              'max_holding_hours': max((t['trade_duration'] for t in ts), default=0) / 60,
              'campaigns_with_adds': sum(n > 1 for n in entries), 'max_entries_in_campaign': max(entries, default=0),
              'campaigns_with_partial_exits': sum(n > 1 for n in exits),
              'by_pair': groups(ts, lambda t: t['pair']),
              'by_direction': groups(ts, lambda t: 'short' if t['is_short'] else 'long'),
              'by_family': groups(ts, lambda t: family(t['enter_tag'])),
              'by_exact_tag': groups(ts, lambda t: (t['enter_tag'] or '').strip()),
              'by_exit': groups(ts, lambda t: t['exit_reason'].split(' (')[0]),
              'by_close_month': groups(ts, lambda t: t['close_date'][:7]),
              'with_adds_vs_single': groups(ts, lambda t: 'with_adds' if sum(o['ft_is_entry'] for o in filled_orders(t)) > 1 else 'single_entry'),
              'worst_campaigns': [{k: t[k] for k in ('pair', 'enter_tag', 'open_date', 'close_date', 'profit_abs', 'exit_reason')} for t in sorted(ts, key=lambda t: t['profit_abs'])[:5]],
              'equity_audit': audit}
    result['fixed_path_slippage_stress'] = {
        str(bps): {'profit_usdt': result['profit_usdt'] - audit['turnover_usdt'] * bps / 10000,
                   'return_pct': 100 * (result['profit_usdt'] - audit['turnover_usdt'] * bps / 10000) / s['starting_balance']}
        for bps in (2, 5, 10)}
    if s['strategy_name'] == 'NFI24Hour' or s['strategy_name'].startswith(('NFIRisk', 'NFIYtd','NFIOpt')):
        violations = [t for t in ts if t['close_timestamp'] > t['open_timestamp'] + 86_400_000]
        late_adds = [o for t in ts for o in filled_orders(t)
                     if o['ft_is_entry'] and o['order_filled_timestamp'] >= t['open_timestamp'] + 86_400_000]
        if violations or late_adds:
            raise ValueError(f'Deadline violated: {len(violations)} overdue campaigns, {len(late_adds)} late adds')
        timed = [t for t in ts if t['exit_reason'] == 'research_time_limit_24h']
        result['deadline_audit'] = {'hours': 24, 'overdue_campaigns': 0, 'late_adds': 0,
                                    'deadline_exits': len(timed),
                                    'deadline_profit_usdt': sum(t['profit_abs'] for t in timed),
                                    'deadline_losing_exits': sum(t['profit_abs'] < 0 for t in timed)}
    path.with_name('analysis.json').write_text(json.dumps(result, indent=2) + '\n')
    frame.to_csv(path.with_name('equity.csv'), index=False)
    return result


def main():
    roots = [ROOT / 'results/nfi/baseline100', ROOT / 'results/nfi/study']
    results = {}
    for root in roots:
        for path in sorted(root.rglob('*.zip')):
            key = path.parent.name
            results[key] = analyze(path)
            r = results[key]
            print(key, r['campaigns'], round(r['return_pct'], 2), 'MTM DD', round(r['equity_audit']['mtm_drawdown_pct'], 2))
    out = ROOT / 'results/nfi/study/comparison.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
