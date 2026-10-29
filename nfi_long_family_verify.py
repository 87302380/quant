"""Verify complete native runs, preserved failure, sources and risk/ledger constraints."""
import hashlib,json,re,zipfile,math,sys,gzip
import numpy as np
import talib
from pathlib import Path
from nfi_analyze import load_result
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/long_family'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def identity(s):return [(t['pair'],t['open_date'],t['close_date'],t['profit_abs'],t['enter_tag']) for t in s['trades']]
def main():
    manifest=json.loads((OUT/'source_manifest.json').read_text())
    for n,d in manifest['files'].items():assert sha(ROOT/n)==d,n
    source=ROOT/'research/nfi/long_family/NFIShortLongFamily.py'
    correction=json.loads((ROOT/'research/nfi/long_family/implementation_correction.json').read_text());assert correction['source_sha256']==sha(source)
    old=json.loads((OUT/'implementation_failure/diagnosis.json').read_text())['failed_source']
    plan=json.loads((ROOT/'research/nfi/long_family/plan.json').read_text());assert hashlib.sha256(old.encode()).hexdigest()==plan['source_sha256']
    assert not list((OUT/'implementation_failure').rglob('*.zip'))
    results=json.loads((OUT/'comparison.json').read_text());names={'control','trend_gate','trend_exit','trend_both','dip_recovery','dip_limit'}
    chosen=json.loads((OUT/'validation_selection.json').read_text())['selected']
    assert names|{chosen+'_fee10',chosen+'_july'}==set(results)
    hourly={};exit_audits=0
    for n,r in results.items():
        folder=OUT/n;s=load_result(next(folder.glob('*.zip')));execution=json.loads((folder/'execution.json').read_text())
        assert execution['status']=='success' and execution['returncode']==0 and execution['source_sha256']==sha(source)
        assert execution['config_sha256']==sha(ROOT/'research/nfi/ytd2026/config.backtest.json')
        assert sha(next(folder.glob('*.zip')))==r['archive_sha256'] and len(s['trades'])==r['campaigns']
        assert abs(s['profit_total']*100-r['return_pct'])<1e-8
        assert len(s['pairlist'])==57 and s['starting_balance']==10000 and all(t['leverage']==3 for t in s['trades'])
        assert r['deadline_audit']['qualified'] and r['max_holding_hours']<=24 and r['campaigns_with_adds']==0
        assert abs(r['equity_audit']['final_equity_error_usdt'])<.01 and r['equity_audit']['max_campaign_ledger_error_usdt']<.01
        fee=.001 if n.endswith('_fee10') else .0005
        assert all(t['fee_open']==fee and t['fee_close']==fee and t.get('funding_fees',0)==0 for t in s['trades'])
        for t in s['trades']:
            if t['exit_reason']!='research_long_trend_failure':continue
            assert not t['is_short'] and set(t['enter_tag'].split())<={'21','47','64','65','161'} and t['trade_duration']>=120
            pair=t['pair']
            if pair not in hourly:
                stem=pair.replace('/','_').replace(':','_')
                with gzip.open(ROOT/'data/nfi_ytd2026/freqtrade/futures'/f'{stem}-1h-futures.json.gz','rt') as stream:h=np.array(json.load(stream),dtype=float)
                hourly[pair]=(h,talib.EMA(h[:,4],50))
            h,ema=hourly[pair];i=np.searchsorted(h[:,0]+3600000,t['close_timestamp'],side='right')-1
            assert i>=1 and h[i,0]-h[i-1,0]==3600000 and h[i,4]<ema[i] and h[i-1,4]<ema[i-1]
            exit_audits+=1
        assert all(math.isfinite(r['tail_metrics'][k]) for k in ['ulcer_index_pct','daily_es95_pct','worst_rolling_24h_pct'])
    control=load_result(next((OUT/'control').glob('*.zip')));prior=load_result(next((ROOT/'results/nfi/long_entry/control').glob('*.zip')))
    assert identity(control)==identity(prior)
    with zipfile.ZipFile(OUT/'execution_evidence.zip') as z:
        log=z.read('tests.log').decode();counts=[int(x) for x in re.findall(r'Ran (\d+) tests?',log)]
        assert sum(counts)==145 and len(counts)==13 and 'FAILED' not in log and 'Traceback' not in log
    record={'status':'passed','engine_replays':len(results),'unit_tests':145,'control_exact':True,'sources_and_ledgers_verified':True,'independently_audited_trend_exits':exit_audits,'implementation_failure_preserved':True,'funding_excluded':True,'independent_oos':False}
    (OUT/'verification.json').write_text(json.dumps(record,indent=2)+'\n');print(record)
if __name__=='__main__':main()
