"""Compare OKX native higher timeframe bars against complete 15m groups."""
import csv
import json
from decimal import Decimal
from pathlib import Path
from pullback import load
from download_okx import timestamp


def read(path):
    with path.open(encoding='utf-8',newline='') as f:
        return list(csv.DictReader(f))


def verify(directory):
    directory=Path(directory)
    # Select the largest available dataset of each timeframe.
    files={bar:max(directory.glob(f'BTC-USDT-SWAP_{bar}_*.csv'),key=lambda p:p.stat().st_size)
           for bar in ('15m','1H','4H')}
    base=read(files['15m'])
    result={}
    for bar,step in [('1H',3600000),('4H',14400000)]:
        native=read(files[bar])
        load(files[bar],step_seconds=step//1000)
        groups={}
        for b in base:
            t=timestamp(b['timestamp'])
            groups.setdefault(t//step*step,[]).append(b)
        mismatch={k:0 for k in ('open','high','low','close','volume','volume_base','volume_quote')}
        max_diff={k:Decimal(0) for k in mismatch}
        missing=[]
        for b in native:
            t=timestamp(b['timestamp']); g=groups.get(t,[])
            if len(g)!=step//900000:
                missing.append(t); continue
            values=dict(open=Decimal(g[0]['open']),close=Decimal(g[-1]['close']),
                        high=max(Decimal(x['high']) for x in g),low=min(Decimal(x['low']) for x in g))
            for k in ('volume','volume_base','volume_quote'):
                values[k]=sum(Decimal(x[k]) for x in g)
            for k,v in values.items():
                diff=abs(Decimal(b[k])-v)
                mismatch[k]+=int(diff!=0)
                max_diff[k]=max(max_diff[k],diff)
        result[bar]=dict(file=str(files[bar]),candles=len(native),missing_15m_groups=len(missing),
                         exact_mismatch_counts=mismatch,max_absolute_difference={k:str(v) for k,v in max_diff.items()})
    path=directory/'timeframe_validation.json'
    path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    return result


if __name__=='__main__': verify('data/okx')
