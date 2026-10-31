"""Build an intermediate plot, summary and reproduction-evidence bundle."""
import csv
import hashlib
import json
import os
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / 'results/nfi/target_review'
OUTPUT = ROOT / 'work/target-review/export'


def main():
    result = json.loads((RESULTS / 'comparison.json').read_text())
    verification = json.loads((RESULTS / 'verification.json').read_text())
    assert verification['status'] == 'passed' and verification['valid_engine_replays'] == 9
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / 'REPORT.md').write_text((RESULTS / 'REPORT.md').read_text())
    (OUTPUT / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    (OUTPUT / 'verification.json').write_text(json.dumps(verification, indent=2) + '\n')
    names = ['canonical', 'canonical_r15', 'canonical_r10', 'canonical_fee8',
             'canonical_r15_fee8', 'canonical_fee12', 'canonical_r15_fee12', 'cp', 'r15']
    with (OUTPUT / 'summary.csv').open('w', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['variant', 'return_pct', 'mtm_drawdown_pct', 'closed_drawdown_pct', 'hourly_mark_drawdown_pct',
                         'profit_factor', 'return_over_mtm_drawdown', 'ulcer_pct', 'daily_ES95_pct',
                         'long_pnl_usdt', 'short_pnl_usdt', 'average_margin_equity_pct'])
        for name in names:
            r = result['results'][name]
            writer.writerow([name, r['return_pct'], r['equity_audit']['mtm_drawdown_pct'], r['closed_trade_drawdown_pct'],
                             r['equity_audit']['hourly_mark_drawdown_pct'], r['profit_factor'], r['profit_dd_mtm'],
                             r['tail_metrics']['ulcer_index_pct'], r['tail_metrics']['daily_es95_pct'],
                             r['by_direction']['long']['profit_usdt'], r['by_direction']['short']['profit_usdt'],
                             r['average_margin_equity_pct']])
    scratch = ROOT / 'work/target-review/mpl'
    scratch.mkdir(parents=True, exist_ok=True)
    os.environ['MPLCONFIGDIR'] = str(scratch)
    font_cache = ROOT / 'work/target-review/font-cache'
    font_cache.mkdir(parents=True, exist_ok=True)
    os.environ['XDG_CACHE_HOME'] = str(font_cache)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import pandas as pd
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    for name, label in [('canonical', '2R'), ('canonical_r15', '1.5R'), ('canonical_r10', '1R')]:
        frame = pd.read_csv(RESULTS / name / 'equity.csv', parse_dates=['time']).set_index('time')
        eq = frame.equity
        axes[0].plot(eq.index, 100*(eq/10000-1), label=label, linewidth=1)
        axes[1].plot(eq.index, 100*(eq/eq.cummax().clip(lower=10000)-1), linewidth=1)
    axes[0].set(ylabel='Return (%)', title='Short target only: 57 pairs, 3x, 6 slots, 24h maximum')
    axes[0].legend()
    axes[1].set(ylabel='Floating-equity drawdown (%)')
    for ax in axes:
        ax.grid(alpha=.25)
    fig.text(.10, .015, '5m closed-price equity; 5bps each side; funding excluded. Retrospective static universe; no independent OOS.', fontsize=8)
    fig.tight_layout(rect=[0,.04,1,1]); fig.savefig(OUTPUT/'equity_drawdown.png', dpi=160); plt.close(fig)
    report = OUTPUT / 'REPORT.md'
    report.write_text(report.read_text() + '\n![Equity and floating drawdown](equity_drawdown.png)\n')
    included = {}
    for name in ['nfi_target_review.py', 'nfi_target_engine.py', 'nfi_target_memory.py', 'nfi_target_report.py',
                 'nfi_target_package.py', 'RESEARCH_SCOPE.md']:
        included[name] = ROOT/name
    for path in (ROOT/'research/nfi/ablation').glob('*'):
        if path.is_file():
            included[str(path.relative_to(ROOT))] = path
    for path in RESULTS.rglob('*'):
        if path.is_file() and path.suffix in ['.zip', '.json', '.md', '.py', '.log', '.jsonl']:
            # Engine exports include reproducible trades; omit disposable dataframe CSVs.
            if path.name.endswith('.meta.json') or path.name == '.last_result.json':
                continue
            included[str(path.relative_to(ROOT))] = path
    for path in (ROOT/'work/target-review').glob('*.json'):
        if path.stat().st_size:
            included[str(path.relative_to(ROOT))] = path
    included['work/target-review/tests.log'] = ROOT/'work/target-review/tests.log'
    readme = ('基于87302380/quant提交0528f47459d23fc57969653c49979b391c76e53c。将本包解压到该仓库；保留已有研究结果。\n'
              'Python3.12，Freqtrade2026.9，Pandas3.1.0，Numpy2.5.4，CCXT4.5.90，TA-Lib0.8.3。\n'
              '先按仓库README恢复数据并执行nfi_verify.py、nfi_ytd_verify.py和nfi_ytd_engine_verify.py。\n'
              '运行nfi_target_review.py canonical canonical_r15 canonical_r10 cp r15；费用重跑加--fee .0008 --suffix _fee8和--fee .0012 --suffix _fee12，仅需canonical canonical_r15。\n'
              '已存在的尝试目录拒绝覆盖；复现前将随包results/nfi/target_review移到另一个归档位置，再以空的同名目录重跑，勿覆盖原结果。\n'
              '运行nfi_target_report.py生成审计。需继承平台代理和CA变量；不关闭TLS，不需要交易所密钥。\n'
              '原版控制逐笔一致；仅目标变化候选复用精确缓存信号，订单/共享钱包均逐组真实重跑。\n'
              'implementation_failure仅为启动/内存/实现中断证据，无有效金融结果。\n')
    with zipfile.ZipFile(OUTPUT/'reproduction_evidence.zip', 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr('REPRODUCE.txt', readme)
        manifest = {}
        for name, path in sorted(included.items()):
            raw = path.read_bytes()
            archive.writestr(name, raw)
            manifest[name] = hashlib.sha256(raw).hexdigest()
        archive.writestr('SHA256.json', json.dumps(manifest, indent=2)+'\n')
    print(str(OUTPUT), flush=True)


if __name__ == '__main__':
    main()
