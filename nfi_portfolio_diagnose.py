"""Explain worst drawdowns using actual holdings and pre-entry correlation only."""
import gzip,json,sys
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import numpy as np
from nfi_analyze import load_result
from nfi_atr_report import trough_holdings
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/portfolio_risk'
sys.path.insert(0,str(ROOT/'research/nfi/portfolio_risk'))
from NFIShortPortfolioRisk import NFIShortPMBase


def main():
    results=json.loads((OUT/'comparison.json').read_text());records={};frames={}
    def fetch(pair,tf):
        assert tf=='1h'
        if pair not in frames:
            stem=pair.replace('/','_').replace(':','_')
            with gzip.open(ROOT/'data/nfi_ytd2026/freqtrade/futures'/f'{stem}-1h-futures.json.gz','rt') as stream:rows=json.load(stream)
            df=pd.DataFrame(rows,columns=['time','open','high','low','close','volume']);df['date']=pd.to_datetime(df.time,unit='ms',utc=True);frames[pair]=df
        return frames[pair]
    s=NFIShortPMBase.__new__(NFIShortPMBase);s.dp=SimpleNamespace(get_pair_dataframe=fetch)
    for name in ['control','half_all','half_long','portfolio','side_cap','correlation','shock','volatility','shock_corr','atr_corr']:
        if name not in results:continue
        engine=load_result(next((OUT/name).glob('*.zip')));holding=trough_holdings(results[name],engine);active=holding['holdings']
        matrix={};when=None
        if active:
            when=max(pd.Timestamp(t['open_date']) for t in active)
            for item in active:
                pair=item['pair'];s.hourly_returns(pair,refresh=True)
                matrix[pair]={other['pair']:s.pair_correlation(pair,other['pair'],when) for other in active if other['pair']!=pair}
        records[name]={'drawdown_holdings':holding,'correlations_at_last_entry_shanghai':str(when.tz_convert('Asia/Shanghai')) if when is not None else None,'pre_entry_correlation_matrix':matrix,'warning':'Holdings are selected ex post at worst drawdown for explanation. Correlations use only hours closed before last entry; not an entry rule fitted to this event.'}
    (OUT/'drawdown_diagnosis.json').write_text(json.dumps(records,indent=2)+'\n')
    for name,r in records.items():
        h=r['drawdown_holdings']['holdings'];values=[v for a,row in r['pre_entry_correlation_matrix'].items() for b,v in row.items() if a<b]
        print(name,'longs',sum(t['side']=='long' for t in h),'shorts',sum(t['side']=='short' for t in h),'pairwise median',round(float(np.median(values)),3) if values else None)
if __name__=='__main__':main()
