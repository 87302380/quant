"""Offline verification and Freqtrade export of the pinned NFI data bundle."""
import ast
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import time

import nfi_data as data
import nfi_mark as mark


def verify_sources():
    manifest=data.read(data.STUDY/'source_manifest.json')
    if manifest['commit']!=data.UPSTREAM:raise ValueError('upstream version mismatch')
    for item in manifest['files']:
        raw=(data.STUDY/'upstream'/item['path']).read_bytes()
        blob=hashlib.sha1(f'blob {len(raw)}\0'.encode()+raw).hexdigest()
        if blob!=item['git_blob_sha'] or len(raw)!=item['bytes']:
            raise ValueError(f'upstream file changed: {item["path"]}')
    ast.parse((data.STUDY/'upstream/NostalgiaForInfinityX8.py').read_text(encoding='utf-8'))
    return dict(commit=manifest['commit'],version=manifest['strategy_version'],files=len(manifest['files']))


def aggregate(group):
    # OKX empty 5m bars carry previous close. Those synthetic OHLC values are
    # not trades and must not set a larger native candle's open/high/low.
    traded=[x for x in group if x[1][4]>0]
    prices=traded or group
    return [prices[0][1][0],max(x[1][1] for x in prices),min(x[1][2] for x in prices),prices[-1][1][3],
            *[sum(x[1][j] for x in group) for j in (4,5,6)]]


def crosscheck():
    """Every overlapping complete higher bar is checked against native 5m bars."""
    manifest=data.read(data.ARCHIVE/'manifest.json');checked=0
    index={(x['instrument'],x['timeframe']):x for x in manifest['files']}
    for pair in data.read(data.STUDY/'universe.json')['pairs']:
        inst=pair['instrument']
        item=index[inst,'5m']
        rows=json.loads(gzip.decompress(data.archive_bytes(item['archive'])))
        low=[(int(r[0]),[Decimal(x) for x in r[1:8]]) for r in rows]
        for tf in ('15m','1h','4h','1d'):
            step=data.BARS[tf][1];higher=index[inst,tf]
            high={int(r[0]):[Decimal(x) for x in r[1:8]] for r in json.loads(gzip.decompress(data.archive_bytes(higher['archive'])))}
            pos=0
            while pos<len(low):
                stamp=low[pos][0]//step*step
                end=pos+1
                while end<len(low) and low[end][0]<stamp+step:end+=1
                group=low[pos:end];pos=end
                if group[0][0]!=stamp or len(group)!=step//300000:continue
                values=aggregate(group)
                native=high.get(stamp)
                if native is None:raise ValueError(f'missing native bar {inst}/{tf}/{stamp}')
                if values[:4]!=native[:4]:raise ValueError(f'OHLC aggregation mismatch {inst}/{tf}/{stamp}')
                # Different exchange aggregation precision can affect last volume digits.
                if any(abs(a-b)>max(Decimal('0.00000001'),abs(b)*Decimal('0.00000001')) for a,b in zip(values[4:],native[4:])):
                    raise ValueError(f'volume aggregation mismatch {inst}/{tf}/{stamp}')
                checked+=1
        print(f'CROSSCHECK {inst}: native higher bars agree with 5m aggregation',flush=True)
    return dict(checked_higher_bars=checked,price_tolerance='exact',volume_tolerance='max(1e-8 absolute, 1e-8 relative)',
                empty_bars='Native zero-volume carry candles preserved; exclude their synthetic OHLC from trade aggregation unless entire group has no trades.')


def main():
    begin=time.monotonic()
    result=dict(started_at=datetime.now(timezone.utc).isoformat(),status='running',funding='not downloaded; omitted cost')
    path=data.ROOT/'results/nfi/data_verification.json'
    data.write(path,result)  # Never expose a checked-in success record as this run's result.
    try:
        result['source']=verify_sources()
        if data.read(data.STUDY/'universe.json').get('format_version',1)>=2:
            from nfi_expand import verify_selection
            result['universe_selection']=verify_selection()
        bundles=data.read(data.ARCHIVE/'bundles.json')['files']
        for item in bundles:
            blob=(data.ARCHIVE/item['file']).read_bytes()
            if len(blob)!=item['bytes'] or data.sha(blob)!=item['sha256']:raise ValueError('bundle hash mismatch')
        data.restore();mark.restore()
        result['cross_timeframe']=crosscheck()
        items=data.read(data.ARCHIVE/'manifest.json')['files']
        marks=data.read(data.ARCHIVE/'mark_manifest.json')['files']
        result.update(status='success',pairs=len(bundles),ohlcv_files=len(items),mark_files=len(marks),
                      ohlcv_rows=sum(x['rows'] for x in items),mark_rows=sum(x['rows'] for x in marks),
                      bundle_bytes=sum(x['bytes'] for x in bundles),universe_sha256=data.sha((data.STUDY/'universe.json').read_bytes()))
    except Exception as exc:
        result.update(status='failed',error=str(exc));raise
    finally:
        result['elapsed_seconds']=round(time.monotonic()-begin,2)
        result['finished_at']=datetime.now(timezone.utc).isoformat()
        data.write(path,result)
    print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':main()
