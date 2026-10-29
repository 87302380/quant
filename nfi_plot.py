"""Plot audited X8 portfolio equity and drawdowns; run nfi_analyze.py first."""
import os
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR', '/tmp/nfi-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent


def main():
    out = ROOT / 'results/nfi/study'
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), sharex=True,
                             gridspec_kw={'height_ratios': [2, 1]})
    for key, label in [('baseline100', '100 pairs, original 3x'),
                       ('official', '57 official-static pairs, original 3x'),
                       ('official_1x', '57 pairs, 1x control'),
                       ('official_no_adjust', '57 pairs, no position adjustment')]:
        folder = ROOT / ('results/nfi/baseline100' if key == 'baseline100' else f'results/nfi/study/{key}')
        frame = pd.read_csv(folder / 'equity.csv', parse_dates=['time'])
        equity = frame.equity
        axes[0].plot(frame.time, (equity / 10000 - 1) * 100, label=label, lw=1)
        axes[1].plot(frame.time, (equity / equity.cummax().clip(lower=10000) - 1) * 100, lw=.8)
    axes[0].set_ylabel('Net portfolio return (%)')
    axes[1].set_ylabel('MTM drawdown (%)')
    axes[0].legend(loc='upper left', fontsize=8)
    for axis in axes:
        axis.grid(alpha=.25)
    fig.suptitle('Pinned NFI X8 / OKX perpetuals / 2026-07-01 to 2026-10-28 UTC\n'
                 '5 bps each fill; no funding; 5-minute closed-price marks; exploratory universe')
    fig.tight_layout()
    fig.savefig(out / 'equity_drawdown.png', dpi=170)
    fig.savefig(out / 'equity_drawdown.svg')
    plt.close(fig)


if __name__ == '__main__':
    main()
