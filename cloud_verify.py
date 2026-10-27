"""Restore bundled data, run tests, optionally replay the current bear research."""
import argparse
import subprocess
import sys
import json
import hashlib
from datetime import datetime,timezone
from pathlib import Path
from cloud_data import restore


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backtest',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    record=dict(started_at=datetime.now(timezone.utc).isoformat(),python=sys.version,stages=[],
                dataset_manifest_sha256=hashlib.sha256((root/'datasets'/'manifest.json').read_bytes()).hexdigest())
    try:
        restore();record['stages'].append('datasets_verified')
        subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-q'],cwd=root,check=True)
        record['stages'].append('tests_passed')
        if args.backtest:
            subprocess.run([sys.executable,'btc_bear.py'],cwd=root,check=True)
            record['stages'].append('bear_backtest_completed')
        record['status']='success'
    except Exception:
        record['status']='failed'
        raise
    finally:
        record['finished_at']=datetime.now(timezone.utc).isoformat()
        (root/'results').mkdir(exist_ok=True)
        (root/'results'/'cloud_execution.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    print('Cloud verification completed successfully.')


if __name__=='__main__':main()
