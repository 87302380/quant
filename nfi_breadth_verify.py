"""Independent breadth-exit timing, data/source hashes and native replay audits."""
import hashlib,json,re,zipfile,gzip
from pathlib import Path
import numpy as np
import pandas as pd
import talib
from nfi_analyze import load_result
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/breadth'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def identity(s):return [(t['pair'],t['open_date'],t['close_date'],t['profit_abs'],t['enter_tag']) for t in s['trades']]
def main():
    m=json.loads((OUT/'source_manifest.json').read_text())
    for p,h in m['files'].items():assert sha(ROOT/p)==h,p
    for p,h in m['artifacts'].items():assert sha(OUT/p)==h,p
    plan=json.loads((ROOT/'research/nfi/breadth/plan.json').read_text())
    for p,h in plan['sources'].items():assert sha(ROOT/'research/nfi/breadth'/p)==h
    climaxplan=json.loads((ROOT/'research/nfi/breadth/climax_plan.json').read_text());assert climaxplan['source_sha256']==sha(ROOT/'research/nfi/breadth/NFIShortBreadthClimax.py')
    r=json.loads((OUT/'comparison.json').read_text());main={'control','gate','exit','both','btc_exit','long_cap','climax','climax_after'}
    sel=json.loads((OUT/'validation_selection.json').read_text());extra=json.loads((OUT/'climax_validation_selection.json').read_text())
    selected=sel['selected']+([extra['selected']] if extra['selected'] else [])
    expected=main|{'control_reverse','climax_reverse'}|{n+suffix for n in selected for suffix in ['_fee10','_july']};assert set(r)==expected
    canonical=ROOT/'research/nfi/ytd2026/config.backtest.json'
    original_config=json.loads(canonical.read_text())
    original_pairlist=load_result(next((OUT/'control').glob('*.zip')))['pairlist']
    features=pd.read_csv(OUT/'market_features.csv.gz',parse_dates=['date']);features.index=pd.DatetimeIndex(features.date)+pd.Timedelta(minutes=5)
    with gzip.open(ROOT/'data/nfi_ytd2026/freqtrade/futures/BTC_USDT_USDT-5m-futures.json.gz','rt') as f:btc=np.array(json.load(f),dtype=float)
    with gzip.open(ROOT/'data/nfi_ytd2026/freqtrade/futures/BTC_USDT_USDT-1h-futures.json.gz','rt') as f:hour=np.array(json.load(f),dtype=float)
    atr=talib.ATR(hour[:,2],hour[:,3],hour[:,4],14);audited=0;btc_audited=0;cap_peak=0
    for n,a in r.items():
        folder=OUT/n;s=load_result(next(folder.glob('*.zip')));e=json.loads((folder/'execution.json').read_text())
        source=ROOT/'research/nfi/breadth'/('NFIShortBreadthClimax.py' if n.startswith('climax') else 'NFIShortBreadth.py')
        assert e['status']=='success' and e['returncode']==0 and e['source_sha256']==sha(source) and e['feature_sha256']==sha(source.with_name('breadth.py'))
        if n.endswith('_reverse'):
            alternate=folder/'config.reverse.json';payload=json.loads(alternate.read_text())
            assert e['config_sha256']==sha(alternate) and e['base_config_sha256']==sha(canonical) and e['reverse_pairs']
            payload['exchange']['pair_whitelist'].reverse();assert payload==original_config
            assert s['pairlist']==list(reversed(original_pairlist))
        else:assert e['config_sha256']==sha(canonical)
        assert a['archive_sha256']==sha(next(folder.glob('*.zip'))) and len(s['trades'])==a['campaigns']
        assert abs(100*s['profit_total']-a['return_pct'])<1e-8 and s['starting_balance']==10000 and len(s['pairlist'])==57
        assert a['deadline_audit']['qualified'] and a['max_holding_hours']<=24 and a['campaigns_with_adds']==0
        assert abs(a['equity_audit']['final_equity_error_usdt'])<.01 and a['equity_audit']['max_campaign_ledger_error_usdt']<.01
        fee=.001 if n.endswith('_fee10') else .0005
        assert all(t['leverage']==3 and t['fee_open']==fee and t['fee_close']==fee and t.get('funding_fees',0)==0 for t in s['trades'])
        for t in s['trades']:
            reason=t['exit_reason'];stamp=t['close_timestamp']
            if reason=='research_breadth_exit':
                assert not t['is_short'] and stamp>t['open_timestamp'];row=features.loc[pd.to_datetime(stamp,unit='ms',utc=True)];assert bool(row.bre_raw) and bool(row.bre_known);audited+=1
            if reason=='research_btc_shock_exit':
                assert not t['is_short'] and stamp>t['open_timestamp']
                i=np.searchsorted(btc[:,0]+300000,stamp,side='right')-1;j=np.searchsorted(hour[:,0]+3600000,stamp,side='right')-1
                assert i>=3 and j>=0 and btc[i,0]-btc[i-3,0]==900000
                assert np.log(btc[i,4]/btc[i-3,4])< -1.5*atr[j]/btc[i,4]+1e-12;btc_audited+=1
        if n.startswith('long_cap'):
            ls=[t for t in s['trades'] if not t['is_short']]
            observed=max((sum(x['open_timestamp']<=t['open_timestamp']<x['close_timestamp'] for x in ls) for t in ls),default=0)
            assert observed<=2;cap_peak=max(cap_peak,observed)
    assert identity(load_result(next((OUT/'control').glob('*.zip'))))==identity(load_result(next((ROOT/'results/nfi/long_family/control').glob('*.zip'))))
    with zipfile.ZipFile(OUT/'execution_evidence.zip') as z:
        log=z.read('tests.log').decode();counts=[int(x) for x in re.findall(r'Ran (\d+) tests?',log)]
        assert sum(counts)==163 and len(counts)==14 and 'FAILED' not in log and 'Traceback' not in log
    record={'status':'passed','engine_replays':len(r),'unit_tests':163,'control_exact':True,'independent_breadth_exit_audits':audited,'independent_btc_exit_audits':btc_audited,'max_observed_long_cap_overlap':cap_peak,'sources_and_ledgers_verified':True,'funding_excluded':True,'independent_oos':False,'climax_posthoc':True,'reverse_pair_order_verified':True}
    (OUT/'verification.json').write_text(json.dumps(record,indent=2)+'\n');print(record)
if __name__=='__main__':main()
