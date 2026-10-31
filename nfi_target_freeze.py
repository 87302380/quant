"""Freeze compact execution evidence and SHA256 lineage for Git publication."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'results/nfi/target_review'


def main():
    with zipfile.ZipFile(OUT / 'execution_evidence.zip', 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for folder in sorted(OUT.iterdir()):
            if folder.is_dir() and list(folder.glob('*.zip')):
                for name in ['run.log', 'deadline_trace.jsonl']:
                    path = folder / name
                    if path.exists():
                        archive.write(path, str(path.relative_to(OUT)))
        for path in sorted((OUT / 'implementation_failure').rglob('*')):
            if path.is_file():
                archive.write(path, str(path.relative_to(OUT)))
        for name in ['tests.log', 'cache_validation_migration.json', 'plot-constraints.txt']:
            path = ROOT / 'work/target-review' / name
            if path.exists():
                archive.write(path, 'review/' + name)
    versions = {'python': platform.python_version(), **{
        name: importlib.metadata.version(name) for name in ['freqtrade', 'ccxt', 'numpy', 'pandas', 'TA-Lib', 'matplotlib']}}
    (OUT / 'runtime_versions.json').write_text(json.dumps(versions, indent=2) + '\n')
    sources = [ROOT / name for name in ['nfi_target_review.py', 'nfi_target_engine.py', 'nfi_target_memory.py',
               'nfi_target_report.py', 'nfi_target_package.py', 'nfi_target_freeze.py', 'RESEARCH_SCOPE.md']]
    sources += [p for p in (ROOT / 'research/nfi/ablation').iterdir() if p.is_file()]
    artifacts = [p for p in OUT.rglob('*') if p.is_file() and
                 (p.suffix in ['.zip', '.png'] or p.name == 'nfi_target_memory.executed.py')]
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    manifest = {'base_git_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                'sources': {str(p.relative_to(ROOT)): sha(p) for p in sorted(sources)},
                'artifacts': {str(p.relative_to(OUT)): sha(p) for p in sorted(artifacts)},
                'notes': 'Existing financial sources remain frozen; exact reference replay. All history examined; funding excluded.'}
    (OUT / 'source_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('Frozen execution logs, runtime versions and source/artifact SHA256 manifest')


if __name__ == '__main__':
    main()
