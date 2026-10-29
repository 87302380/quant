"""Verify long study sources, complete native replays and audit evidence."""
import hashlib,json,re,zipfile
from pathlib import Path
from nfi_analyze import load_result
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/long_entry'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    m=json.loads((OUT/'source_manifest.json').read_text())
    for p,h in m['files'].items():assert sha(ROOT/p)==h,p
    r=json.loads((OUT/'comparison.json').read_text())
    assert {'control','turn','break','failure','delay_turn','delay_break','failure_fee10','failure_july'}==set(r)
    identity=lambda s:[(t['pair'],t['open_date'],t['close_date'],t['profit_abs'],t['enter_tag']) for t in s['trades']]
    assert identity(load_result(next((OUT/'control').glob('*.zip'))))==identity(load_result(next((ROOT/'results/nfi/portfolio_risk/control').glob('*.zip'))))
    for name,a in r.items():
        folder=OUT/name;z=next(folder.glob('*.zip'));s=load_result(z);e=json.loads((folder/'execution.json').read_text())
        src=ROOT/'research/nfi/long_entry'/('NFIShortLongDelayed.py' if name.startswith('delay_') else 'NFIShortLongEntry.py')
        assert e['status']=='success' and e['source_sha256']==sha(src)
        assert e['config_sha256']==sha(ROOT/'research/nfi/ytd2026/config.backtest.json')
        assert sha(z)==a['archive_sha256']
        assert abs(100*s['profit_total']-a['return_pct'])<1e-8
        assert len(s['pairlist'])==57 and s['starting_balance']==10000
        assert a['deadline_audit']['qualified'] and a['max_holding_hours']<=24 and a['campaigns_with_adds']==0
        assert all(t['leverage']==3 and t.get('funding_fees',0)==0 for t in s['trades'])
        fee=.001 if name.endswith('_fee10') else .0005
        assert all(t['fee_open']==fee and t['fee_close']==fee for t in s['trades'])
        assert abs(a['equity_audit']['final_equity_error_usdt'])<.01 and a['equity_audit']['max_campaign_ledger_error_usdt']<.01
    flags={(x['pair'],x['open_timestamp']):x for x in json.loads((OUT/'original_path_failure_flags.json').read_text())['records']}
    failure=load_result(next((OUT/'failure').glob('*.zip')))
    audited=0
    for t in failure['trades']:
        if t['exit_reason']=='research_long_failure':
            f=flags[(t['pair'],t['open_timestamp'])];assert f['failure_detected'] and t['close_timestamp']==f['first_failure_closed_ms'];audited+=1
    assert audited==19
    with zipfile.ZipFile(OUT/'execution_evidence.zip') as z:
        t=z.read('tests.log').decode();counts=[int(x) for x in re.findall(r'Ran (\d+) tests?',t)]
        assert sum(counts)==132 and len(counts)==12 and 'FAILED' not in t and 'Traceback' not in t
    v={'status':'passed','engine_replays':len(r),'unit_tests':sum(counts),'control_exact':True,'independently_timed_failure_exits':audited,'funding_excluded':True,'independent_oos':False,'sources_and_ledgers_verified':True}
    (OUT/'verification.json').write_text(json.dumps(v,indent=2)+'\n');print(v)
if __name__=='__main__':main()
