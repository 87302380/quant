"""Audit frozen short-horizon RS experiments, source provenance and ledger invariants."""
import hashlib,json,re,zipfile
from pathlib import Path
from nfi_analyze import load_result
from nfi_atr_verify import sha,class_ast
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/fast_rs'


def main():
    manifest=json.loads((OUT/'source_manifest.json').read_text())
    for name,digest in manifest['files'].items():assert sha(ROOT/name)==digest,name
    results=json.loads((OUT/'comparison.json').read_text());assert len(results)==20
    records={};control=None
    for name,r in results.items():
        folder=OUT/name;archives=list(folder.glob('*.zip'));assert len(archives)==1
        archive=archives[0];s=load_result(archive);execution=json.loads((folder/'execution.json').read_text())
        source=ROOT/'research/nfi/fast_rs'/('NFIShortFastTurning.py' if name.startswith('improving_long') else 'NFIShortFastShortHorizons.py' if name.split('_')[0] in ['short15','short240'] else 'NFIShortFastRS.py')
        assert execution['status']=='success' and execution['returncode']==0
        assert execution['source_sha256']==sha(source)
        assert sha(archive)==r['archive_sha256']
        assert len(s['trades'])==r['campaigns'] and abs(100*s['profit_total']-r['return_pct'])<1e-8
        assert abs(s['profit_total_abs']-r['profit_usdt'])<1e-8
        assert r['deadline_audit']['qualified'] and r['max_holding_hours']<=24
        assert r['campaigns_with_adds']==0 and r['pairs_configured']==57
        assert s['starting_balance']==10000 and all(t['leverage']==3 for t in s['trades'])
        assert abs(r['equity_audit']['final_equity_error_usdt'])<.01
        assert r['equity_audit']['max_campaign_ledger_error_usdt']<.01
        expected=.001 if name.endswith('_fee10') else .0005
        assert all(t['fee_open']==expected and t['fee_close']==expected and t.get('funding_fees',0)==0 for t in s['trades'])
        with zipfile.ZipFile(archive) as z:archived=z.read(next(n for n in z.namelist() if n.endswith('_'+s['strategy_name']+'.py'))).decode()
        assert class_ast(archived,s['strategy_name'])==class_ast(source.read_text(),s['strategy_name'])
        if name=='control':control=s
        records[name]={'archive_sha256':sha(archive),'campaigns':r['campaigns'],'qualified':True,'fee':expected,'class_ast_matches':True,'source_sha_matches_execution':True}
    prior=load_result(next((ROOT/'results/nfi/atr_short/gated').glob('*.zip')))
    identity=lambda s:[(t['pair'],t['open_date'],t['close_date'],t['profit_abs'],t['enter_tag']) for t in s['trades']]
    assert identity(control)==identity(prior)
    with zipfile.ZipFile(OUT/'execution_evidence.zip') as z:log=z.read('tests.log').decode()
    counts=[int(n) for n in re.findall(r'Ran (\d+) test',log)];assert sum(counts)==106 and len(counts)==10
    assert 'FAILED' not in log and 'Traceback' not in log
    diag=json.loads((OUT/'entry_diagnosis.json').read_text())
    assert diag['control_archive_sha256']==results['control']['archive_sha256']
    assert diag['feature_sha256']==sha(ROOT/'research/nfi/fast_rs/NFIShortFastRS.py')
    assert len(diag['trades'])==len(control['trades'])
    snapshot=json.loads((OUT/'latest_snapshot.json').read_text());rows=snapshot['ranked_ex_btc']
    assert snapshot['frozen_history_not_live'] and len(rows)==56 and not snapshot['unavailable']
    assert [r['relative_1h_rank'] for r in rows]==list(range(1,57))
    assert all(r['pair']!='BTC/USDT:USDT' for r in rows)
    assert all(a['btc_ratio_60m_return_pct']>=b['btc_ratio_60m_return_pct'] for a,b in zip(rows,rows[1:]))
    verification={'status':'passed','engine_replays':len(results),'unit_tests':sum(counts),'control_matches_previous_gated_exactly':True,'funding_excluded':True,'independent_oos':False,'snapshot_not_live':True,'records':records}
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    print('Verified 20 engine replays, 106 tests, exact prior control, source hashes, deadlines, no adds, ledger reconciliation and historical snapshot.')
if __name__=='__main__':main()
