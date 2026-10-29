"""Independent original-path structural-failure flags; no simulated strategy PnL."""
import json,gzip
from pathlib import Path
import numpy as np
import talib
ROOT=Path(__file__).resolve().parent;DATA=ROOT/'data/nfi_ytd2026/freqtrade/futures'
def main():
    d=json.loads((ROOT/'results/nfi/long_entry/diagnosis.json').read_text());cache={};out=[]
    def rows(pair,tf):
        key=(pair,tf)
        if key not in cache:
            cache[key]=np.array(json.loads(gzip.decompress((DATA/(pair.replace('/','_').replace(':','_')+f'-{tf}-futures.json.gz')).read_bytes())),dtype=float)
        return cache[key]
    for t in d['campaigns']:
        a=rows(t['pair'],'5m');h=rows(t['pair'],'1h');opened=t['open_timestamp']
        first=np.searchsorted(a[:,0]+300000,opened,side='right')
        hi=np.searchsorted(h[:,0]+3600000,opened,side='right')-1
        floor=float(a[max(0,first-12):first,3].min())
        atr=float(talib.ATR(h[:,2],h[:,3],h[:,4],14)[hi])
        # Initial margin and ledger data do not expose entry price directly here:
        # feature close is not substituted; use native export's exact first fill.
        from nfi_analyze import load_result,filled_orders
        if 'native' not in cache:
            ts=load_result(next((ROOT/'results/nfi/portfolio_risk/control').glob('*.zip')))['trades']
            cache['native']={(x['pair'],x['open_timestamp']):x for x in ts}
        native=cache['native'][(t['pair'],opened)]
        entry=next(o['safe_price'] for o in filled_orders(native) if o['ft_is_entry'])
        mask=(a[:,0]+300000>=opened+21600000)&(a[:,0]+300000<native['close_timestamp'])&(a[:,4]<entry)&(a[:,4]<floor-.5*atr)
        hits=np.flatnonzero(mask)
        out.append({'pair':t['pair'],'open_timestamp':opened,'original_winner':t['profit_usdt']>0,'entry_floor':floor,'entry_atr':atr,'failure_detected':bool(len(hits)),'first_failure_closed_ms':int(a[hits[0],0]+300000) if len(hits) else None})
    result={'warning':'Entry-time closed bars, first-fill price; original-path flagging only, not actual engine exits or revised profits. No benefit attributed by deleting trades.',
            'flagged_winners':sum(x['failure_detected'] and x['original_winner'] for x in out),'flagged_losers':sum(x['failure_detected'] and not x['original_winner'] for x in out),'records':out}
    (ROOT/'results/nfi/long_entry/original_path_failure_flags.json').write_text(json.dumps(result,indent=2)+'\n')
    print('flagged winners',result['flagged_winners'],'losers',result['flagged_losers'])
def matched_exits():
    from nfi_analyze import load_result
    out=ROOT/'results/nfi/long_entry'
    a=load_result(next((out/'control').glob('*.zip')));b=load_result(next((out/'failure').glob('*.zip')))
    original={(t['pair'],t['open_date']):t for t in a['trades'] if not t['is_short']};records=[]
    for t in b['trades']:
        if t['is_short'] or t['exit_reason']!='research_long_failure':continue
        old=original.get((t['pair'],t['open_date']))
        if old is None:continue
        records.append({'pair':t['pair'],'open_date':t['open_date'],'original_profit_ratio':old['profit_ratio'],'new_profit_ratio':t['profit_ratio'],'original_winner':old['profit_abs']>0,'new_winner':t['profit_abs']>0})
    r={'warning':'Matched entries only, actual engine normalized campaign ratios. Wallet compounding changes absolute sizes. Not causal portfolio attribution. Price-below-entry can coexist with positive total PnL after partial exits.',
       'matched_original_winners':sum(x['original_winner'] for x in records),'winners_turned_into_losses':sum(x['original_winner'] and not x['new_winner'] for x in records),'matched_original_losers':sum(not x['original_winner'] for x in records),
       'original_losers_improved':sum(not x['original_winner'] and x['new_profit_ratio']>x['original_profit_ratio'] for x in records),'original_losers_worsened':sum(not x['original_winner'] and x['new_profit_ratio']<x['original_profit_ratio'] for x in records),'records':records}
    (out/'matched_failure_exits.json').write_text(json.dumps(r,indent=2)+'\n')
if __name__=='__main__':
    main()
    if list((ROOT/'results/nfi/long_entry/failure').glob('*.zip')):matched_exits()
