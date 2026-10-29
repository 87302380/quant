"""Independent source/order/risk/ledger audits of every valid replay."""
import hashlib,json,re,zipfile
from pathlib import Path
from nfi_analyze import load_result,filled_orders
from nfi_op_audit import risk_audit,extra
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/opportunities'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def identity(s):return [(t['pair'],t['is_short'],t['open_date'],t['close_date'],t['profit_abs'],t['enter_tag'],[(o['ft_is_entry'],o['amount'],o['safe_price']) for o in filled_orders(t)]) for t in s['trades']]
def main():
    m=json.loads((OUT/'source_manifest.json').read_text())
    for p,h in m['files'].items():assert sha(ROOT/p)==h,p
    for p,h in m['artifacts'].items():assert sha(OUT/p)==h,p
    src=ROOT/'research/nfi/opportunities';plan=json.loads((src/'plan.json').read_text());correction=json.loads((src/'implementation_correction.json').read_text())
    before=json.loads((OUT/'implementation_failure/diagnosis.json').read_text())['source_before_fix']
    assert hashlib.sha256(before.encode()).hexdigest()==correction['failed_source_sha256']==plan['sources']['NFIShortOpportunities.py']
    assert sha(src/'NFIShortOpportunities.py')==correction['source_sha256'];assert sha(src/'op_features.py')==plan['sources']['op_features.py']
    for n,h in json.loads((src/'adaptive_plan.json').read_text())['sources'].items():assert sha(src/n)==h
    alloc=json.loads((src/'allocation_plan.json').read_text());assert alloc['source_sha256']==sha(src/'NFIShortOPFixed.py')
    rs=json.loads((OUT/'comparison.json').read_text());sel=json.loads((OUT/'selection.json').read_text())
    expected={'control','pullback','breakout','native','retest','combined','compression','context','control_fixed',sel['fixed_candidate']}
    if sel['fixed_qualified']:expected|={n+x for n in ['control_fixed',sel['fixed_candidate']] for x in ['_fee10','_july']}
    if sel['reverse_tested']:expected|={n+'_reverse' for n in ['control_fixed',sel['fixed_candidate']]}
    assert set(rs)==expected
    canonical=ROOT/'research/nfi/ytd2026/config.backtest.json';config=json.loads(canonical.read_text());pairs=load_result(next((OUT/'control').glob('*.zip')))['pairlist'];audited=0
    for n,a in rs.items():
        f=OUT/n;e=json.loads((f/'execution.json').read_text());s=load_result(next(f.glob('*.zip')))
        source='NFIShortOpportunities.py'
        if '_fixed' in n:source='NFIShortOPFixed.py'
        if n in ['compression','context']:source='NFIShortOPMore.py'
        if n.startswith(('compression_fixed','context_fixed')):source='NFIShortOPMoreFixed.py'
        assert e['status']=='success' and e['returncode']==0 and e['source_sha256']==sha(src/source) and e['feature_sha256']==sha(src/'op_features.py')
        assert e['base_config_sha256']==sha(canonical)
        if n.endswith('_reverse'):
            payload=json.loads((f/'config.reverse.json').read_text());payload['exchange']['pair_whitelist'].reverse();assert payload==config
            assert e['config_sha256']==sha(f/'config.reverse.json') and e['reverse_pairs'] and s['pairlist']==list(reversed(pairs))
        else:assert e['config_sha256']==sha(canonical) and s['pairlist']==pairs
        assert a['archive_sha256']==sha(next(f.glob('*.zip'))) and len(s['trades'])==a['campaigns']
        assert abs(s['profit_total']*100-a['return_pct'])<1e-8 and s['starting_balance']==10000 and len(s['pairlist'])==57
        assert s['max_open_trades']==6 and a['max_holding_hours']<=24 and a['campaigns_with_adds']==0 and a['deadline_audit']['qualified']
        assert abs(a['equity_audit']['final_equity_error_usdt'])<.01 and a['equity_audit']['max_campaign_ledger_error_usdt']<.01
        fee=.001 if n.endswith('_fee10') else .0005
        assert all(t['leverage']==3 and t['fee_open']==fee and t['fee_close']==fee and t.get('funding_fees',0)==0 for t in s['trades'])
        risk=risk_audit(f,s);audited+=risk['entries_audited']
        lookup={(r['pair'],r['entry_timestamp']):r for r in risk['records']}
        for t in s['trades']:
            if not extra(t):continue
            orders=filled_orders(t);assert sum(not o['ft_is_entry'] for o in orders)==1
            levels=lookup[(t['pair'],t['open_timestamp'])]
            if t['exit_reason']=='research_op_long_target':assert t['close_rate']>=levels['target']-1e-9
            if t['exit_reason']=='research_op_long_stop_gap':assert t['close_rate']<=levels['stop']+1e-9
    read=lambda p:load_result(next(p.glob('*.zip')))
    assert identity(read(OUT/'control'))==identity(read(ROOT/'results/nfi/breadth/climax'))
    for n in ['control','compression']:assert identity(read(OUT/n))==identity(read(OUT/(n+'_fixed')))
    with zipfile.ZipFile(OUT/'execution_evidence.zip') as z:
        log=z.read('tests.log').decode();counts=[int(x) for x in re.findall(r'Ran (\d+) tests?',log)]
        assert sum(counts)==183 and len(counts)==15 and 'FAILED' not in log and 'Traceback' not in log
        assert 'Cloud verification completed successfully.' in z.read('cloud_verification.log').decode()
    result={'status':'passed','engine_replays':len(rs),'unit_tests':183,'extra_risk_entries_independently_audited':audited,'control_exact':True,'fixed_cap_nonbinding_exact':True,'sources_orders_ledgers_verified':True,'compression_posthoc':True,'independent_oos':False,'funding_excluded':True}
    (OUT/'verification.json').write_text(json.dumps(result,indent=2)+'\n');print(result)
if __name__=='__main__':main()
