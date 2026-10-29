"""Fixed-window short-side experiments with identical existing long core."""
import argparse,hashlib,json,subprocess,tempfile
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
from nfi_data import millis

ROOT=Path(__file__).resolve().parent
VARIANTS={'long_control':'NFIShortLongControl','pullback':'NFIShortPullback','breakdown':'NFIShortBreakdown','mirror':'NFIShortMirror',
          'pullback_slots':'NFIShortPullbackSlots','breakdown_slots':'NFIShortBreakdownSlots','mirror_slots':'NFIShortMirrorSlots',
          'expanded_native':'NFIShortExpanded','breakdown_rr1':'NFIShortBreakdownRR1',
          'incumbent_precision':'NFIShortIncumbent','long_precision':'NFIShortLongControl',
          'expanded_precision':'NFIShortExpanded','gated_precision':'NFIShortGated'}


def run(name,fee=.0005,suffix=''):
    out=ROOT/'results/nfi/short_search'/(name+suffix);out.mkdir(parents=True,exist_ok=True)
    if list(out.glob('*.zip')):raise ValueError('Completed result preserved')
    config=ROOT/'research/nfi/ytd2026/config.backtest.json';source=ROOT/'research/nfi/short_search/NFIShortResearch.py'
    universe=json.loads((ROOT/'research/nfi/ytd2026/universe.json').read_text())
    runtime=ROOT/'data/nfi_ytd2026/runtime';runtime.mkdir(parents=True,exist_ok=True)
    window=f"{millis(universe['evaluation_start'])//1000}-{millis(universe['end_exclusive'])//1000}"
    command=[str(ROOT/'.venv/bin/freqtrade'),'backtesting','--userdir',tempfile.mkdtemp(prefix='short-'+name,dir=runtime),
             '--config',str(config),'--strategy-path',str(source.parent),'--strategy',VARIANTS[name],
             '--datadir',str(ROOT/'data/nfi_ytd2026/freqtrade'),'--data-format-ohlcv','jsongz',
             '--timerange',window,'--fee',str(fee),'--cache','none','--export','trades','--breakdown','month','--backtest-directory',str(out)]
    if name=='breakdown_rr1' or name.endswith('_precision'):
        extra=['--precision-fix'] if name.endswith('_precision') else []
        command=[str(ROOT/'.venv/bin/python'),str(ROOT/'nfi_short_engine.py'),'--deadline-trace',str(out/'deadline_trace.jsonl')]+extra+command[1:]
    record={'started_at':datetime.now(timezone.utc).isoformat(),'status':'running','command':command,
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'config_sha256':hashlib.sha256(config.read_bytes()).hexdigest()}
    (out/'execution.json').write_text(json.dumps(record,indent=2)+'\n');print('START',name,suffix,flush=True)
    with (out/'run.log').open('w') as stream:p=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    record.update(status='success' if p.returncode==0 else 'failed',returncode=p.returncode,finished_at=datetime.now(timezone.utc).isoformat())
    (out/'execution.json').write_text(json.dumps(record,indent=2)+'\n');print('END',name,record['status'],flush=True)
    return p.returncode


def main():
    p=argparse.ArgumentParser();p.add_argument('variants',nargs='+',choices=VARIANTS);p.add_argument('--workers',type=int,choices=[1,2],default=2)
    p.add_argument('--fee',type=float,default=.0005);p.add_argument('--suffix',default='');a=p.parse_args()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:codes=list(pool.map(lambda n:run(n,a.fee,a.suffix),a.variants))
    if any(codes):raise SystemExit(1)


if __name__=='__main__':main()
