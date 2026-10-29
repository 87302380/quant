"""Run a predeclared return-search batch with at most two independent wallets."""
import argparse,hashlib,json,subprocess,tempfile
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
from nfi_data import millis

ROOT=Path(__file__).resolve().parent
VARIANTS={'long_only':'NFIOptLongOnly','no_short_rebuy':'NFIOptNoShortRebuy','no_adds':'NFIOptNoAdds',
          'overheat_long':'NFIOptOverheatLong','relative_strength':'NFIOptRelativeStrength',
          'weighted':'NFIOptWeighted','campaign_trail':'NFIOptCampaignTrail','size_only':'NFIOptSizeOnly',
          'overheat_no_adds':'NFIOptOverheatNoAdds','trend_runner':'NFIOptTrendRunner',
          'weighted_no_adds':'NFIOptWeightedNoAdds'}


def run(name,fee=.0005,suffix=''):
    out=ROOT/'results/nfi/return_search'/(name+suffix);out.mkdir(parents=True,exist_ok=True)
    if list(out.glob('*.zip')):raise ValueError(f'Existing result preserved: {out}')
    runtime=ROOT/'data/nfi_ytd2026/runtime';runtime.mkdir(parents=True,exist_ok=True)
    config=ROOT/'research/nfi/ytd2026/config.backtest.json'
    strategy='NFI24Hour' if name=='baseline' else VARIANTS[name]
    strategy_dir=ROOT/'research/nfi'/('study' if name=='baseline' else 'return_search')
    u=json.loads((ROOT/'research/nfi/ytd2026/universe.json').read_text())
    window=f"{millis(u['evaluation_start'])//1000}-{millis(u['end_exclusive'])//1000}"
    cmd=[str(ROOT/'.venv/bin/freqtrade'),'backtesting','--userdir',tempfile.mkdtemp(prefix=name,dir=runtime),
         '--config',str(config),'--strategy-path',str(strategy_dir),'--strategy',strategy,
         '--datadir',str(ROOT/'data/nfi_ytd2026/freqtrade'),'--data-format-ohlcv','jsongz','--timerange',window,
         '--fee',str(fee),'--cache','none','--export','trades','--breakdown','month','--backtest-directory',str(out)]
    source=strategy_dir/('NFI24Hour.py' if name=='baseline' else 'NFIOptimize.py')
    record={'started_at':datetime.now(timezone.utc).isoformat(),'status':'running','command':cmd,
            'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'config_sha256':hashlib.sha256(config.read_bytes()).hexdigest()}
    record['strategy_sources_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in sorted(source.parent.glob('NFI*.py'))}
    (out/'execution.json').write_text(json.dumps(record,indent=2)+'\n');print('START',name,flush=True)
    with (out/'run.log').open('w') as stream:proc=subprocess.run(cmd,cwd=ROOT,stdout=stream,stderr=subprocess.STDOUT)
    record.update(status='success' if not proc.returncode else 'failed',returncode=proc.returncode,finished_at=datetime.now(timezone.utc).isoformat())
    (out/'execution.json').write_text(json.dumps(record,indent=2)+'\n');print('END',name,record['status'],flush=True)
    return proc.returncode


def main():
    p=argparse.ArgumentParser();p.add_argument('variants',nargs='*',choices=list(VARIANTS)+['baseline']);p.add_argument('--workers',type=int,choices=[1,2],default=2)
    p.add_argument('--fee',type=float,default=.0005);p.add_argument('--suffix',default='')
    a=p.parse_args()
    with ThreadPoolExecutor(max_workers=a.workers) as executor:codes=list(executor.map(lambda name:run(name,a.fee,a.suffix),a.variants or list(VARIANTS)))
    if any(codes):raise SystemExit(1)


if __name__=='__main__':main()
