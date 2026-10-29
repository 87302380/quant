"""Package source fingerprints and execution logs after completed offline research."""
import argparse,hashlib,json,subprocess,zipfile,platform,importlib.metadata
from pathlib import Path
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/breadth'
def main():
    p=argparse.ArgumentParser();p.add_argument('--tests-log',type=Path,required=True);p.add_argument('--data-log',type=Path,required=True);p.add_argument('--cloud-log',type=Path,required=True);a=p.parse_args()
    prior=json.loads((ROOT/'results/nfi/long_family/source_manifest.json').read_text())
    sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    for n,h in prior['files'].items():
        if n not in ['RESEARCH_SCOPE.md','research/nfi/README.md']:assert sha(ROOT/n)==h,n
    paths={ROOT/n for n in prior['files']}
    paths.update(ROOT.glob('nfi_breadth*.py'));paths.update((ROOT/'research/nfi/breadth').iterdir())
    paths.update([ROOT/'RESEARCH_SCOPE.md',ROOT/'research/nfi/README.md'])
    files={str(p.relative_to(ROOT)):sha(p) for p in sorted(paths) if p.is_file()}
    m={'base_git_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'files':files,'artifacts':{n:sha(OUT/n) for n in ['market_features.csv.gz','baseline_event_diagnosis.json','baseline_entry_exit_flags.json','baseline_cohorts.json','climax_cohort_audit.json']},'notes':'Frozen per-run strategy hashes checked against current source; previous baseline files unchanged. Includes native replay evidence; all history already examined.'}
    (OUT/'source_manifest.json').write_text(json.dumps(m,indent=2)+'\n')
    versions={'python':platform.python_version(),**{k:importlib.metadata.version(k) for k in ['freqtrade','ccxt','numpy','pandas','TA-Lib']}}
    (OUT/'runtime_versions.json').write_text(json.dumps(versions,indent=2)+'\n')
    with zipfile.ZipFile(OUT/'execution_evidence.zip','w',compression=zipfile.ZIP_DEFLATED) as z:
        for folder in sorted(OUT.iterdir()):
            if folder.is_dir() and list(folder.glob('*.zip')):
                for name in ['run.log','deadline_trace.jsonl']:
                    f=folder/name
                    if f.exists():z.write(f,str(f.relative_to(OUT)))
        for f in (OUT/'implementation_failure').rglob('*'):
            if f.is_file():z.write(f,str(f.relative_to(OUT)))
        for name,f in [('tests.log',a.tests_log),('data_verification.log',a.data_log),('cloud_verification.log',a.cloud_log)]:z.write(f,name)
if __name__=='__main__':main()
