"""Plot actual marked wallet equity; drawdowns computed before resampling."""
import os
os.environ.setdefault('MPLCONFIGDIR','/tmp/nfi-mpl');os.environ.setdefault('XDG_CACHE_HOME','/tmp/nfi-cache')
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg');matplotlib.rcParams['timezone']='Asia/Shanghai'
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/opportunities'
def main():
    fig,axs=plt.subplots(2,1,figsize=(12,8),sharex=True)
    for name in ['control','compression','native','retest','context']:
        eq=pd.read_csv(OUT/name/'equity.csv',parse_dates=['time']).set_index('time').equity.tz_convert('Asia/Shanghai')
        axs[0].plot(eq.resample('h').last(),label=name)
        axs[1].plot((100*(eq/eq.cummax().clip(lower=10000)-1)).resample('h').min())
    axs[0].set_ylabel('Equity (USDT)');axs[0].legend(ncol=3)
    axs[1].set_ylabel('5m MTM drawdown (%)');axs[1].set_xlabel('Asia/Shanghai; retrospective selection; funding excluded')
    fig.tight_layout();fig.savefig(OUT/'comparison.png',dpi=140);plt.close(fig)
if __name__=='__main__':main()
