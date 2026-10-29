"""Verify archived ATR experiments against frozen sources and ledger audits."""
import ast,hashlib,json,re,zipfile
from pathlib import Path
from nfi_analyze import load_result
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results/nfi/atr_short'

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def class_ast(source,name):
    return ast.dump(next(n for n in ast.parse(source).body if isinstance(n,ast.ClassDef) and n.name==name),include_attributes=False)
def main():
    manifest=json.loads((OUT/'source_manifest.json').read_text())
    for name,digest in manifest['files'].items():assert sha(ROOT/name)==digest,name
    results=json.loads((OUT/'comparison.json').read_text());assert len(results)==16
    source=(ROOT/'research/nfi/atr_short/NFIShortATR.py').read_text();records={}
    for name,r in results.items():
        folder=OUT/name;archives=list(folder.glob('*.zip'));assert len(archives)==1
        archive=archives[0];s=load_result(archive);execution=json.loads((folder/'execution.json').read_text())
        assert execution['status']=='success' and execution['returncode']==0
        assert sha(archive)==r['archive_sha256']
        assert r['deadline_audit']['qualified'] and r['max_holding_hours']<=24
        assert r['campaigns_with_adds']==0 and r['pairs_configured']==57
        assert s['starting_balance']==10000 and all(t['leverage']==3 for t in s['trades'])
        assert abs(r['equity_audit']['final_equity_error_usdt'])<.01
        assert r['equity_audit']['max_campaign_ledger_error_usdt']<.01
        expected=.001 if name.endswith('_fee10') else .0005
        assert all(t['fee_open']==expected and t['fee_close']==expected for t in s['trades'])
        with zipfile.ZipFile(archive) as z:
            archived=z.read(next(n for n in z.namelist() if n.endswith('_'+s['strategy_name']+'.py'))).decode()
        assert class_ast(archived,s['strategy_name'])==class_ast(source,s['strategy_name'])
        records[name]={'archive_sha256':sha(archive),'campaigns':r['campaigns'],'deadline_qualified':True,'no_adds':True,'selected_class_ast_matches_current':True,'fee':expected}
    with zipfile.ZipFile(OUT/'execution_evidence.zip') as z:log=z.read('tests.log').decode()
    counts=[int(n) for n in re.findall(r'Ran (\d+) test',log)];assert sum(counts)==92 and len(counts)==9
    assert 'FAILED' not in log and 'Traceback' not in log
    verification={'status':'passed','engine_replays':16,'unit_tests':sum(counts),'funding_excluded':True,'independent_oos':False,'records':records}
    (OUT/'verification.json').write_text(json.dumps(verification,indent=2)+'\n')
    print('Verified 16 engine replays, 92 tests, source hashes, archived classes, 24h deadlines, no adds and wallet ledgers.')
if __name__=='__main__':main()
