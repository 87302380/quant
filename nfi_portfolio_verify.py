"""Verify recorded portfolio-risk experiments and source/ledger/risk-budget evidence."""
import json,re,zipfile,math
from pathlib import Path
from nfi_analyze import load_result
from nfi_atr_verify import sha,class_ast
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/portfolio_risk'


def main():
    manifest=json.loads((OUT/'source_manifest.json').read_text())
    for name,digest in manifest['files'].items():assert sha(ROOT/name)==digest,name
    results=json.loads((OUT/'comparison.json').read_text())
    main_names={'control','half_all','half_long','long_budget','long_stop','long_atr','portfolio','cooldown','shock','volatility','correlation','side_cap','shock_corr','atr_corr'}
    fee_names={'half_all','half_long','portfolio','correlation','side_cap','shock','shock_corr','atr_corr'}
    july_names={'half_all','half_long','portfolio','side_cap','shock','shock_corr','atr_corr'}
    expected=main_names|{n+'_fee10' for n in fee_names}|{n+'_july' for n in july_names}
    assert set(results)==expected and len(results)==29
    records={};control=None
    for name,r in results.items():
        folder=OUT/name;archives=list(folder.glob('*.zip'));assert len(archives)==1
        archive=archives[0];s=load_result(archive);execution=json.loads((folder/'execution.json').read_text())
        base=name.removesuffix('_fee10').removesuffix('_july')
        file='NFIShortPMUniform.py' if base=='half_all' else 'NFIShortPMCombined.py' if base in ['shock_corr','atr_corr'] else 'NFIShortPortfolioRisk.py'
        source=ROOT/'research/nfi/portfolio_risk'/file
        assert execution['status']=='success' and execution['returncode']==0
        assert execution['source_sha256']==sha(source)
        assert execution['config_sha256']==sha(ROOT/'research/nfi/ytd2026/config.backtest.json')
        assert sha(archive)==r['archive_sha256'] and r['campaigns']==len(s['trades'])
        assert abs(r['return_pct']-100*s['profit_total'])<1e-8 and abs(r['profit_usdt']-s['profit_total_abs'])<1e-8
        assert r['deadline_audit']['qualified'] and r['max_holding_hours']<=24 and r['campaigns_with_adds']==0
        assert len(s['pairlist'])==57 and s['starting_balance']==10000 and all(t['leverage']==3 for t in s['trades'])
        assert abs(r['equity_audit']['final_equity_error_usdt'])<.01 and r['equity_audit']['max_campaign_ledger_error_usdt']<.01
        fee=.001 if name.endswith('_fee10') else .0005
        assert all(t['fee_open']==fee and t['fee_close']==fee and t.get('funding_fees',0)==0 for t in s['trades'])
        assert all(math.isfinite(r['tail_metrics'][k]) for k in ['ulcer_index_pct','daily_es95_pct','worst_rolling_24h_pct'])
        with zipfile.ZipFile(archive) as z:archived=z.read(next(n for n in z.namelist() if n.endswith('_'+s['strategy_name']+'.py'))).decode()
        assert class_ast(archived,s['strategy_name'])==class_ast(source.read_text(),s['strategy_name'])
        if name=='control':control=s
        records[name]={'archive_sha256':sha(archive),'campaigns':r['campaigns'],'qualified':True,'fee':fee,'source_hash_matches_execution':True}
    prior=load_result(next((ROOT/'results/nfi/atr_short/gated').glob('*.zip')))
    identity=lambda s:[(t['pair'],t['open_date'],t['close_date'],t['profit_abs'],t['enter_tag']) for t in s['trades']]
    assert identity(control)==identity(prior)
    audits=json.loads((OUT/'risk_budget_audit.json').read_text())
    assert set(audits)=={'portfolio','cooldown','portfolio_fee10','portfolio_july'}
    for name,a in audits.items():
        assert a['qualified'] and a['entries_audited']==results[name]['campaigns']
        for row in a['records']:
            assert row['occupied_planned_loss']<=row['equity_basis']*.03+.02
            assert row['independently_rebuilt_current_risk']<=row['equity_basis']*.01+.02
    with zipfile.ZipFile(OUT/'execution_evidence.zip') as z:log=z.read('tests.log').decode()
    counts=[int(n) for n in re.findall(r'Ran (\d+) test',log)]
    assert sum(counts)==123 and len(counts)==11 and 'FAILED' not in log and 'Traceback' not in log
    verified={'status':'passed','engine_replays':29,'unit_tests':123,'control_matches_prior_exactly':True,'planned_risk_audit_verified':True,'independent_oos':False,'funding_excluded':True,'records':records}
    (OUT/'verification.json').write_text(json.dumps(verified,indent=2)+'\n')
    print('Verified 29 replays, 123 tests, exact prior control, source hashes, 24h/no-add rules, ledgers, tail metrics and independent planned-risk audits.')
if __name__=='__main__':main()
