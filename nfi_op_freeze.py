"""Freeze reproducible source lineage, versions, logs and interruption evidence."""
import argparse,hashlib,json,subprocess,zipfile,platform,importlib.metadata
from pathlib import Path
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/opportunities'
def main():
    p=argparse.ArgumentParser();p.add_argument('--tests-log',type=Path,required=True);p.add_argument('--data-log',type=Path,required=True);p.add_argument('--cloud-log',type=Path,required=True);a=p.parse_args()
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    prior=json.loads((ROOT/'results/nfi/breadth/source_manifest.json').read_text())
    for n,h in prior['files'].items():
        if n not in ['RESEARCH_SCOPE.md','research/nfi/README.md']:assert sha(ROOT/n)==h,n
    paths={ROOT/n for n in prior['files']};paths.update(ROOT.glob('nfi_op*.py'));paths.update((ROOT/'research/nfi/opportunities').iterdir())
    paths.update([ROOT/'RESEARCH_SCOPE.md',ROOT/'research/nfi/README.md'])
    m={'base_git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'files':{str(p.relative_to(ROOT)):sha(p) for p in sorted(paths) if p.is_file()},'artifacts':{n:sha(OUT/n) for n in ['selection.json','compression_cohorts.json']},'notes':'Source lineage inherited unchanged; explicit posthoc compression selection. Funding excluded; all history examined.'}
    (OUT/'source_manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    (OUT/'runtime_versions.json').write_text(json.dumps({'python':platform.python_version(),**{k:importlib.metadata.version(k) for k in ['freqtrade','ccxt','numpy','pandas','TA-Lib']}},indent=2)+'\n')
    with zipfile.ZipFile(OUT/'execution_evidence.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(OUT.iterdir()):
            if f.is_dir() and list(f.glob('*.zip')):
                for name in ['run.log','deadline_trace.jsonl']:
                    if (f/name).exists():z.write(f/name,str((f/name).relative_to(OUT)))
        for f in (OUT/'implementation_failure').rglob('*'):
            if f.is_file():z.write(f,str(f.relative_to(OUT)))
        for name,f in [('tests.log',a.tests_log),('data_verification.log',a.data_log),('cloud_verification.log',a.cloud_log)]:z.write(f,name)
if __name__=='__main__':main()
