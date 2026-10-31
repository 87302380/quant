"""Reconcile real order ledgers; separate target effects from wallet path changes."""
from collections import Counter
from functools import lru_cache
import gzip
import hashlib
import json
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import talib

from nfi_analyze import analyze, filled_orders, load_result
from nfi_portfolio_report import tail_metrics
from nfi_rebound_report import collect

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'results/nfi/target_review'
DATA = ROOT / 'data/nfi_ytd2026/freqtrade/futures'


@lru_cache(maxsize=128)
def prices(pair, timeframe):
    stem = pair.replace('/', '_').replace(':', '_')
    with gzip.open(DATA / f'{stem}-{timeframe}-futures.json.gz', 'rt') as stream:
        values = np.array(json.load(stream), dtype=float)
    return values


@lru_cache(maxsize=64)
def hourly_atr(pair):
    values = prices(pair, '1h')
    return values[:, 0] + 3600000, talib.ATR(values[:, 2], values[:, 3], values[:, 4], 14)


def levels(trade, multiple):
    entries = [o for o in filled_orders(trade) if o['ft_is_entry']]
    assert len(entries) == 1
    entry = entries[0]
    dates, atr = hourly_atr(trade['pair'])
    i = np.searchsorted(dates, trade['open_timestamp'], side='right') - 1
    assert i >= 0 and np.isfinite(atr[i])
    distance = max(2 * atr[i], entry['safe_price'] * .01)
    stop = entry['safe_price'] + distance
    target = max(entry['safe_price'] - multiple * distance, entry['safe_price'] * .001)
    return entry, distance, stop, target


def short_audit(engine, multiple):
    records = []
    for trade in engine['trades']:
        if not trade['is_short']:
            continue
        entry, distance, stop, target = levels(trade, multiple)
        if trade['exit_reason'] == 'research_short_target':
            assert trade['close_rate'] <= target + max(1e-15, abs(target) * 1e-10)
        records.append({'pair': trade['pair'], 'open_timestamp': trade['open_timestamp'],
                        'entry': entry['safe_price'], 'atr_distance': distance,
                        'unrounded_stop': stop, 'expected_target': target,
                        'exported_stop': trade['stop_loss_abs'],
                        'stop_rounding_difference_pct_of_distance': 100 * (trade['stop_loss_abs'] - stop) / distance,
                        'planned_loss_usdt': entry['amount'] * (distance + trade['fee_open'] * entry['safe_price'] + trade['fee_close'] * stop),
                        'exit_reason': trade['exit_reason'], 'profit_usdt': trade['profit_abs']})
    return {'short_entries_audited': len(records), 'target_exit_prices_checked': True, 'records': records}


def identity(engine):
    return [(t['pair'], t['is_short'], t['open_timestamp'], t['close_timestamp'], t['enter_tag'],
             t['profit_abs'], [(o['ft_is_entry'], o['amount'], o['safe_price']) for o in filled_orders(t)])
            for t in engine['trades']]


def match(base, candidate):
    key = lambda t: (t['pair'], t['is_short'], t['open_timestamp'])
    a = {key(t): t for t in base['trades']}
    b = {key(t): t for t in candidate['trades']}
    common = sorted(a.keys() & b.keys())
    rescued, sacrificed, stops_changed = [], [], []
    callback_opportunities = []
    for k in common:
        x, y = a[k], b[k]
        if x['is_short']:
            if x['stop_loss_abs'] != y['stop_loss_abs']:
                stops_changed.append({'key': k, 'old_stop': x['stop_loss_abs'], 'new_stop': y['stop_loss_abs']})
            row = {'pair': x['pair'], 'open_timestamp': x['open_timestamp'], 'old_exit': x['exit_reason'],
                   'new_exit': y['exit_reason'], 'old_pnl_usdt': x['profit_abs'], 'new_pnl_usdt': y['profit_abs'],
                   'old_duration_min': x['trade_duration'], 'new_duration_min': y['trade_duration']}
            if x['profit_abs'] <= 0 < y['profit_abs']:
                rescued.append(row)
            if y['profit_abs'] <= 0 < x['profit_abs']:
                sacrificed.append(row)
    for x in base['trades']:
        if not x['is_short'] or x['profit_abs'] > 0:
            continue
        _, _, _, target = levels(x, 1.5)
        p = prices(x['pair'], '5m')
        # Callback receives the candle open. Exclude entry and final exit candle,
        # so the diagnosis cannot depend on ambiguous intrabar event order.
        seen = (p[:, 0] > x['open_timestamp']) & (p[:, 0] < x['close_timestamp'])
        touched = seen & (p[:, 1] <= target)
        if np.any(touched):
            callback_opportunities.append({'pair': x['pair'], 'open_timestamp': x['open_timestamp'],
                                           'first_callback_timestamp': int(p[np.flatnonzero(touched)[0], 0]),
                                           'original_exit': x['exit_reason'], 'original_pnl_usdt': x['profit_abs']})
    return {'common_entries': len(common), 'base_only_entries': len(a.keys() - b.keys()),
            'candidate_only_entries': len(b.keys() - a.keys()), 'rescued_common_shorts': rescued,
            'sacrificed_common_shorts': sacrificed, 'common_short_exported_stop_differences': stops_changed,
            'baseline_losing_shorts_with_prior_15R_callback_price': callback_opportunities,
            'common_entry_pnl_difference_usdt': sum(b[k]['profit_abs'] - a[k]['profit_abs'] for k in common),
            'missing_original_pnl_usdt': sum(a[k]['profit_abs'] for k in a.keys() - b.keys()),
            'new_entry_pnl_usdt': sum(b[k]['profit_abs'] for k in b.keys() - a.keys()),
            'caveat': 'Actual wallet paths and quantities may differ; matched PnL deltas are not independent alpha attribution.'}


def main():
    results, engines = {}, {}
    provenance = {}
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    frozen_config = ROOT / 'research/nfi/ytd2026/config.backtest.json'
    expected_pairs = json.loads(frozen_config.read_text())['exchange']['pair_whitelist']
    for folder in sorted(OUT.iterdir()):
        if not folder.is_dir() or not list(folder.glob('*.zip')):
            continue
        execution = json.loads((folder / 'execution.json').read_text())
        assert execution['status'] == 'success'
        assert sha(frozen_config) == execution['base_config_sha256']
        assert sha(ROOT / 'datasets/nfi_ytd2026/manifest.json') == execution['dataset_manifest_sha256']
        snapshots = []
        for name, expected in execution['sources'].items():
            if Path(name).name.startswith('test'):
                continue
            if sha(ROOT / name) != expected:
                saved = folder / 'nfi_target_memory.executed.py'
                assert name == 'nfi_target_memory.py' and saved.exists() and sha(saved) == expected, name
                snapshots.append(name)
        provenance[folder.name] = {'financial_sources_verified': True, 'config_data_verified': True,
                                   'executed_source_snapshots': snapshots}
        archive = next(folder.glob('*.zip'))
        engine = load_result(archive)
        assert engine['starting_balance'] == 10000 and len(engine['pairlist']) == 57
        assert engine['pairlist'] == expected_pairs
        for trade in engine['trades']:
            assert trade['leverage'] == 3 and trade.get('funding_fees', 0) == 0
            assert trade['fee_open'] == trade['fee_close'] == execution['fee']
            assert trade['close_timestamp'] <= trade['open_timestamp'] + 86400000
            assert sum(o['ft_is_entry'] for o in filled_orders(trade)) == 1
        if (folder / 'run.log').exists():
            log = (folder / 'run.log').read_text()
        else:
            with zipfile.ZipFile(OUT / 'execution_evidence.zip') as evidence:
                log = evidence.read(folder.name + '/run.log').decode()
        assert 'TARGET_METADATA_VERIFIED 57 markets' in log
        assert 'Traceback' not in log and ' - ERROR - ' not in log
        result = collect(folder)
        assert result['campaigns_with_adds'] == 0
        result['tail_metrics'] = tail_metrics(folder)
        local = pd.read_csv(folder / 'equity.csv', parse_dates=['time']).set_index('time').equity.tz_convert('Asia/Shanghai').resample('ME').last()
        prior = engine['starting_balance']
        result['monthly_mtm_shanghai'] = {}
        for at, value in local.items():
            result['monthly_mtm_shanghai'][at.strftime('%Y-%m')] = {'profit_usdt': float(value-prior), 'return_pct': float(100*(value/prior-1))}
            prior = value
        result['profit_dd_mtm'] = result['return_pct'] / result['equity_audit']['mtm_drawdown_pct']
        result['profit_dd_closed'] = result['return_pct'] / result['closed_trade_drawdown_pct']
        shorts = [t for t in engine['trades'] if t['is_short']]
        result['short_exits'] = dict(Counter(t['exit_reason'] for t in shorts))
        result['long_exits'] = dict(Counter(t['exit_reason'] for t in engine['trades'] if not t['is_short']))
        multiple = 1.5 if 'r15' in folder.name else 1. if 'r10' in folder.name else 2.
        result['short_level_audit'] = short_audit(engine, multiple)
        results[folder.name], engines[folder.name] = result, engine
        print(folder.name, round(result['return_pct'], 4), round(result['equity_audit']['mtm_drawdown_pct'], 4),
              'closed DD', round(result['closed_trade_drawdown_pct'], 4), flush=True)
    pairs = [('canonical', 'canonical_r15'), ('canonical', 'canonical_r10'), ('cp', 'r15'),
             ('canonical_fee8', 'canonical_r15_fee8'), ('canonical_fee12', 'canonical_r15_fee12'),
             ('canonical', 'cp')]
    comparisons = {a + '__' + b: match(engines[a], engines[b]) for a, b in pairs if a in engines and b in engines}
    reference = load_result(next((ROOT / 'results/nfi/opportunities/compression').glob('*.zip')))
    canonical_exact = identity(reference) == identity(engines['canonical']) if 'canonical' in engines else None
    troughs = {}
    for name in ['canonical', 'canonical_r15', 'canonical_r10']:
        if name not in results:
            continue
        at = pd.Timestamp(results[name]['equity_audit']['drawdown_trough_time'])
        held = [t for t in engines[name]['trades'] if pd.Timestamp(t['open_date']) <= at < pd.Timestamp(t['close_date'])]
        troughs[name] = {'time_utc': str(at), 'time_shanghai': str(at.tz_convert('Asia/Shanghai')),
                        'holdings': [{'pair': t['pair'], 'is_short': t['is_short'], 'tag': t['enter_tag']} for t in held],
                        'warning': 'Inventory at the trough; not attribution of the entire peak-to-trough loss.'}
    summary = {'results': results, 'entry_matching': comparisons, 'canonical_exact_vs_archive': canonical_exact,
               'drawdown_trough_holdings': troughs,
               'execution_provenance': provenance,
               'calendar_metric_timezones': {'monthly_mtm': 'UTC engine convention', 'daily_es95': 'Asia/Shanghai'},
               'independent_oos': False, 'funding_excluded': True}
    (OUT / 'comparison.json').write_text(json.dumps(summary, indent=2) + '\n')
    (OUT / 'verification.json').write_text(json.dumps({
        'status': 'passed', 'valid_engine_replays': len(results),
        'canonical_exact_vs_archive': canonical_exact,
        'cp_equal_to_canonical': identity(engines['cp']) == identity(engines['canonical']),
        'cp_r15_equal_to_primary_r15': identity(engines['r15']) == identity(engines['canonical_r15']),
        'financial_sources_config_dataset_verified': True,
        'all_trade_deadlines_and_single_entries_checked': True,
        'all_target_exit_prices_checked': True, 'funding_excluded': True,
        'independent_oos': False,
    }, indent=2) + '\n')
    window = engines['canonical']
    start_local = pd.to_datetime(window['backtest_start_ts'], unit='ms', utc=True).tz_convert('Asia/Shanghai')
    end_local = pd.to_datetime(window['backtest_end_ts'], unit='ms', utc=True).tz_convert('Asia/Shanghai')
    lines = ['# 空头止盈目标独立复核', '',
             f'回放窗口（北京时间）：{start_local} 至 {end_local}。', '',
             '57固定币、同一10000USDT钱包、3倍、最多6仓、禁止补仓、首次入场24小时。2026年初至冻结截止，资金费排除。单边5/8/12bps是真实引擎重新成交和复利回放。全部历史已查看，没有独立样本外或实盘结论。', '',
             '|方案|收益%|含浮亏回撤%|平仓回撤%|PF|收益/含浮亏回撤|收益/平仓回撤|空头止盈|空头止损|',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    display_order = ['canonical', 'canonical_r15', 'canonical_r10', 'canonical_fee8',
                     'canonical_r15_fee8', 'canonical_fee12', 'canonical_r15_fee12', 'cp', 'r15']
    for name in display_order:
        if name not in results:
            continue
        r = results[name]
        e = r['short_exits']; stops = sum(v for k, v in e.items() if k in ['stop_loss', 'trailing_stop_loss', 'research_short_stop_gap'])
        lines.append(f"|{name}|{r['return_pct']:.2f}|{r['equity_audit']['mtm_drawdown_pct']:.2f}|{r['closed_trade_drawdown_pct']:.2f}|{r['profit_factor']:.2f}|{r['profit_dd_mtm']:.2f}|{r['profit_dd_closed']:.2f}|{e.get('research_short_target',0)}|{stops}|")
    lines += ['', 'canonical为仓库原compression；canonical_r15/r10只改reward_multiple。cp/r15为用户描述的C后置过滤重建组，不混用基线。', '',
              f'原版与旧归档是否逐笔一致：{canonical_exact}。若不一致，须报告环境/市场规格差异，不声称精确复现旧结果。', '',
              '## 判断', '']
    if 'canonical_r15' in results:
        a, b = results['canonical'], results['canonical_r15']
        lines += [f"主实验2R→1.5R：收益{a['return_pct']:.2f}%→{b['return_pct']:.2f}%，平仓回撤{a['closed_trade_drawdown_pct']:.2f}%→{b['closed_trade_drawdown_pct']:.2f}%，含浮亏回撤{a['equity_audit']['mtm_drawdown_pct']:.5f}%→{b['equity_audit']['mtm_drawdown_pct']:.5f}%。必须分别解释兑现效率与最大持仓风险，不能将平仓回撤改善称为全部风险下降。", '']
        for side in ['short', 'long']:
            x, y = a['by_direction'][side]['profit_usdt'], b['by_direction'][side]['profit_usdt']
            lines.append(f"{side}实际路径净利润：{x:.2f}→{y:.2f}USDT，变化{y-x:.2f}USDT。")
        lines += ['多头规则未修改但现金流、空闲槽位和仓位随钱包发生变化；多头利润差混合机会挤占和复利，不是单独的alpha证明。空头目标退出增加不代表空头本身净利必然增加。', '']
        june = b['monthly_mtm_shanghai']['2026-06']['profit_usdt'] - a['monthly_mtm_shanghai']['2026-06']['profit_usdt']
        total = b['profit_usdt'] - a['profit_usdt']
        lines += [f'收益优势集中度：按北京时间自然月，6月实际利润差{june:.2f}USDT，而全区间利润差{total:.2f}USDT，其余月份净差合计{total-june:.2f}USDT。这是事后路径诊断，不是按月份启停规则；不同费率仍沿用同一历史，不能替代不同市场的前向验证。', '']
    lines += ['## 平均回撤与资金占用', '',
              '|方案|Ulcer%|日ES95%|最长已观察水下时长h|平均保证金/权益%|',
              '|---|---:|---:|---:|---:|']
    for name in ['canonical', 'canonical_r15', 'canonical_r10', 'canonical_fee12', 'canonical_r15_fee12']:
        if name not in results:
            continue
        r = results[name]; t = r['tail_metrics']
        lines.append(f"|{name}|{t['ulcer_index_pct']:.2f}|{t['daily_es95_pct']:.2f}|{t['max_observed_underwater_hours']:.2f}|{r['average_margin_equity_pct']:.2f}|")
    lines += ['', 'Ulcer与日尾部损失在此历史有所改善；但12bps下最长已观察水下时长增加，不能声称每项稳定性指标都更好。水下时长受窗口截断，不等于未来回本期限。', '']
    for name, t in troughs.items():
        lines.append(f"{name}最大含浮亏回撤谷底在北京时间{t['time_shanghai']}，当时持有{len(t['holdings'])}仓，其中空头{sum(x['is_short'] for x in t['holdings'])}仓。具体币种见comparison.json；不是整段回撤的收益归因。")
    lines += ['',
              '## 逐笔机制检查', '']
    for name, m in comparisons.items():
        lines.append(f"- {name}：共同入场{m['common_entries']}；仅原组{m['base_only_entries']}；仅新组{m['candidate_only_entries']}；共同空头亏转盈{len(m['rescued_common_shorts'])}；盈转亏{len(m['sacrificed_common_shorts'])}；相同入场空头导出止损不同{len(m['common_short_exported_stop_differences'])}；原亏损空单曾有1.5R回调报价{len(m['baseline_losing_shorts_with_prior_15R_callback_price'])}。")
    lines += ['', '5m权益回撤来自所有订单现金流和剩余持仓逐格估值，并与引擎最终钱包对账。小时标记价回撤、Ulcer、日ES95、月份及方向归因见comparison.json；平仓余额回撤不代表持仓风险，5m权益回撤也不代表盘中最坏风险。', '',
              '止盈按真实引擎5m开盘回调价触发，未使用最低价补成交；止损使用原引擎。R是价格距离，净R包含费用后会改变。共同入场止损和新增/消失交易分别披露，不能凭止损次数一样判定路径一样。', '',
              '执行失败与元数据限流、并行内存不足尝试保留在implementation_failure。最终回放串行，限定拉取57币真实杠杆规格且恢复完整市场注册表，未替换市场或伪造规格。未运行其他七个S/C/P组合挑选新基线。']
    if (OUT / 'equity_drawdown.png').exists():
        lines += ['', '![权益与含浮亏回撤](equity_drawdown.png)']
    (OUT / 'REPORT.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
