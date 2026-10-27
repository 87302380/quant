"""Verify downloaded 5m data aggregates exactly to the existing OKX 15m file."""
import csv
import json
import hashlib
from decimal import Decimal
from pathlib import Path
from btc_5m import DATA,OUT
from research import DATA as OLD_DATA


def main():
    with DATA.open(encoding='utf-8',newline='') as f:five=list(csv.DictReader(f))
    with OLD_DATA.open(encoding='utf-8',newline='') as f:old=list(csv.DictReader(f))
    assert len(five)==3*len(old)
    mismatch={k:0 for k in ('open','high','low','close','volume','volume_base','volume_quote')}
    for i,b in enumerate(old):
        g=five[3*i:3*i+3]
        assert g[0]['timestamp']==b['timestamp']
        values=dict(open=Decimal(g[0]['open']),high=max(Decimal(x['high']) for x in g),
            low=min(Decimal(x['low']) for x in g),close=Decimal(g[-1]['close']))
        for k in ('volume','volume_base','volume_quote'):values[k]=sum(Decimal(x[k]) for x in g)
        for k,v in values.items():mismatch[k]+=v!=Decimal(b[k])
    meta=json.loads(DATA.with_suffix('.manifest.json').read_text())
    assert hashlib.sha256(DATA.read_bytes()).hexdigest()==meta['sha256']
    result=dict(candles_5m=len(five),candles_15m=len(old),mismatch_counts=mismatch,sha256=meta['sha256'])
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/'data_validation.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    assert not any(mismatch.values()),'OKX historical revision or aggregation discrepancy; investigate before research'


if __name__=='__main__':main()
