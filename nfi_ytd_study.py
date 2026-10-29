"""Frozen full-YTD unified-wallet experiments, with isolated process state."""
import argparse
from datetime import datetime,timezone
import hashlib,json,subprocess,tempfile
from pathlib import Path
from nfi_data import millis

ROOT=Path(__file__).resolve().parent
STRATEGIES={'baseline':('NFI24Hour','study'), 'overheat':('NFIRiskOverheat80','risk_study'),
            'budget':('NFIYtdBudget','ytd_research'), 'direction':('NFIYtdDirection','ytd_research')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('variants',nargs='+',choices=STRATEGIES)
    args=parser.parse_args()
    u=json.loads((ROOT/'research/nfi/ytd2026/universe.json').read_text())
    timerange=f"{millis(u['evaluation_start'])//1000}-{millis(u['end_exclusive'])//1000}"
    runtime=ROOT/'data/nfi_ytd2026/runtime';runtime.mkdir(parents=True,exist_ok=True)
    config=ROOT/'research/nfi/ytd2026/config.backtest.json'
    for name in args.variants:
        strategy,folder=STRATEGIES[name]
        out=ROOT/'results/nfi/ytd_research'/name;out.mkdir(parents=True,exist_ok=True)
        command=[str(ROOT/'.venv/bin/freqtrade'),'backtesting','--userdir',tempfile.mkdtemp(prefix=name,dir=runtime),
                 '--config',str(config),'--strategy-path',str(ROOT/'research/nfi'/folder),'--strategy',strategy,
                 '--datadir',str(ROOT/'data/nfi_ytd2026/freqtrade'),'--data-format-ohlcv','jsongz',
                 '--timerange',timerange,'--fee','0.0005','--cache','none','--export','trades',
                 '--breakdown','month','--backtest-directory',str(out)]
        record={'started_at':datetime.now(timezone.utc).isoformat(),'status':'running','command':command,
                'config_sha256':hashlib.sha256(config.read_bytes()).hexdigest(),
                'strategy_files_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in sorted((ROOT/'research/nfi'/folder).glob('*.py'))}}
        path=out/'execution.json';path.write_text(json.dumps(record,indent=2))
        print('START',name,flush=True)
        with (out/'run.log').open('w') as log:
            proc=subprocess.run(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
        record.update(status='success' if not proc.returncode else 'failed',returncode=proc.returncode,
                      finished_at=datetime.now(timezone.utc).isoformat())
        path.write_text(json.dumps(record,indent=2));print('END',name,record['status'],flush=True)
        if proc.returncode:raise SystemExit(proc.returncode)


if __name__=='__main__':main()
