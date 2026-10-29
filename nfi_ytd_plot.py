"""Export the frozen comparison with sampled drawdowns visible."""
from pathlib import Path
import json
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

ROOT=Path(__file__).resolve().parent/'results/nfi/ytd_research'


def main():
    fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True,gridspec_kw={'height_ratios':[2,1]})
    for name in ['baseline','overheat','budget','direction']:
        df=pd.read_csv(ROOT/name/'equity.csv',parse_dates=['time'])
        eq=df.set_index('time')['equity'];peak=eq.cummax().clip(lower=10000)
        axes[0].plot(eq.index,100*(eq/10000-1),label=name,linewidth=1)
        axes[1].plot(eq.index,-100*(peak-eq)/peak,label=name,linewidth=1)
    axes[0].set(title='NFI X8: frozen 57 pairs, max 24h, 2026 YTD',ylabel='Wallet return (%)')
    axes[1].set(ylabel='Sampled drawdown (%)')
    for ax in axes:ax.grid(alpha=.25)
    axes[0].legend(ncol=4)
    fig.text(.08,.015,'Retrospective static universe; 5 bps fee per fill; funding excluded; 5m closed-price equity, not intrabar extremes.',fontsize=9)
    fig.tight_layout(rect=(0,.035,1,1));fig.savefig(ROOT/'comparison.png',dpi=170);plt.close(fig)


if __name__=='__main__':main()
