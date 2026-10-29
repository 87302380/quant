"""Fast BTC-relative strength research on the fixed ATR gated framework."""
import argparse,hashlib,json,subprocess,tempfile
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
from nfi_data import millis

ROOT=Path(__file__).resolve().parent
VARIANTS={'short15':'NFIShortFastShort15','short240':'NFIShortFastShort240','improving_long':'NFIShortFastTurning','control':'NFIShortFastControl','both15':'NFIShortFast15','both60':'NFIShortFast60','both240':'NFIShortFast240','short60':'NFIShortFastShort60','long60':'NFIShortFastLong60','confirm':'NFIShortFastConfirm','beta60':'NFIShortFastBeta','momentum60':'NFIShortFastMomentum'}


def run(name,fee=.0005,suffix='',start=None):
    out=ROOT/'results/nfi/fast_rs'/(name+suffix);out.mkdir(parents=True,exist_ok=True)
    if list(out.glob('*.zip')):raise ValueError('Completed result preserved')
    config=ROOT/'research/nfi/ytd2026/config.backtest.json';source=ROOT/'research/nfi/fast_rs/NFIShortFastRS.py'
    if name in ['short15','short240']:source=ROOT/'research/nfi/fast_rs/NFIShortFastShortHorizons.py'
    if name=='improving_long':source=ROOT/'research/nfi/fast_rs/NFIShortFastTurning.py'
    u=json.loads((ROOT/'research/nfi/ytd2026/universe.json').read_text())
    runtime=ROOT/'data/nfi_ytd2026/runtime';runtime.mkdir(parents=True,exist_ok=True)
    window=f"{millis(start or u['evaluation_start'])//1000}-{millis(u['end_exclusive'])//1000}"
    command=[str(ROOT/'.venv/bin/python'),str(ROOT/'nfi_short_engine.py'),'--precision-fix','--deadline-trace',str(out/'deadline_trace.jsonl'),
             'backtesting','--userdir',tempfile.mkdtemp(prefix='rebound-'+name,dir=runtime),'--config',str(config),
             '--strategy-path',str(source.parent),'--strategy',VARIANTS[name],
             '--datadir',str(ROOT/'data/nfi_ytd2026/freqtrade'),'--data-format-ohlcv','jsongz',
             '--timerange',window,'--fee',str(fee),'--cache','none','--export','trades','--breakdown','month','--backtest-directory',str(out)]
    record={'started_at':datetime.now(timezone.utc).isoformat(),'status':'running','command':command,
            'evaluation_start':start or u['evaluation_start'],'fee':fee,
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'config_sha256':hashlib.sha256(config.read_bytes()).hexdigest()}
    (out/'execution.json').write_text(json.dumps(record,indent=2)+'\n');print('START',name,suffix,flush=True)
    with (out/'run.log').open('w') as stream:p=subprocess.run(command,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    record.update(status='success' if p.returncode==0 else 'failed',returncode=p.returncode,finished_at=datetime.now(timezone.utc).isoformat())
    (out/'execution.json').write_text(json.dumps(record,indent=2)+'\n');print('END',name,suffix,record['status'],flush=True)
    return p.returncode


def main():
    p=argparse.ArgumentParser();p.add_argument('variants',nargs='+',choices=VARIANTS);p.add_argument('--workers',type=int,choices=[1,2],default=2)
    p.add_argument('--fee',type=float,default=.0005);p.add_argument('--suffix',default='');p.add_argument('--start');a=p.parse_args()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:codes=list(pool.map(lambda n:run(n,a.fee,a.suffix,a.start),a.variants))
    if any(codes):raise SystemExit(1)


if __name__=='__main__':main()
