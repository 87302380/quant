"""Verify, bundle and export the separate native57-pair2026 year-to-date dataset."""
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import json
import time
import zipfile

import nfi_data as old
import nfi_ytd as ytd
from nfi_mark import validate_mark
from nfi_verify import aggregate, verify_sources


def blob(item):
    direct=ytd.ARCHIVE/item['archive']
    if direct.exists():return direct.read_bytes()
    with zipfile.ZipFile(ytd.ARCHIVE/(item['instrument']+'.zip')) as z:
        return z.read(item['archive'])


def restore_and_check():
    started=time.monotonic()
    result={'started_at':datetime.now(timezone.utc).isoformat(),'status':'running',
            'funding':'Not downloaded by user request'}
    target=ytd.STUDY/'verification.json'
    old.write(target,result)
    try:
        universe=old.read(ytd.STUDY/'universe.json')
        manifest=old.read(ytd.ARCHIVE/'manifest.json')
        if manifest['universe_sha256']!=old.sha((ytd.STUDY/'universe.json').read_bytes()):
            raise ValueError('Universe hash mismatch')
        items=manifest['files']
        index={(x['instrument'],'mark1h' if x['candle_type']=='mark' else x['timeframe']):x for x in items}
        required={(p['instrument'],tf) for p in universe['pairs'] for tf in ytd.BARS}
        if len(index)!=len(items) or set(index)!=required:raise ValueError('Incomplete/duplicate342-file matrix')
        result['upstream_source']=verify_sources()
        checked=0
        for pair in universe['pairs']:
            native={}
            for tf in ytd.BARS:
                item=index[pair['instrument'],tf];packed=blob(item)
                if old.sha(packed)!=item['archive_sha256'] or len(packed)!=item['archive_bytes']:
                    raise ValueError('Archive hash/size mismatch')
                raw=gzip.decompress(packed)
                if old.sha(raw)!=item['raw_sha256'] or len(raw)!=item['raw_bytes']:
                    raise ValueError('Raw hash/size mismatch')
                rows=json.loads(raw);step=ytd.BARS[tf][1]
                start=old.millis(item['start']);end=old.millis(item['end_exclusive'])
                if tf=='mark1h':validate_mark(rows,start,end)
                else:old.validate(rows,start,end,step)
                if len(rows)!=item['rows']:raise ValueError('Declared row count differs')
                native[tf]=rows
                if tf=='mark1h':
                    exported=[[int(r[0]),*map(float,r[1:5]),0.] for r in rows]
                    name=pair['pair'].replace('/','_').replace(':','_')+'-1h-mark.json.gz'
                else:
                    exported=[[int(r[0]),*map(float,r[1:5]),float(r[6])] for r in rows]
                    name=pair['pair'].replace('/','_').replace(':','_')+f'-{tf}-futures.json.gz'
                payload=json.dumps(exported,separators=(',',':'),allow_nan=False).encode()
                dest=ytd.LOCAL/'freqtrade/futures'/name
                if dest.exists():
                    if gzip.decompress(dest.read_bytes())!=payload:raise ValueError(f'Preserving modified export:{dest}')
                else:old.compressed(dest,payload)
            low=[(int(r[0]),[Decimal(x) for x in r[1:8]]) for r in native['5m']]
            for tf in ('15m','1h','4h','1d'):
                step=ytd.BARS[tf][1]
                high={int(r[0]):[Decimal(x) for x in r[1:8]] for r in native[tf]}
                pos=0
                while pos<len(low):
                    stamp=low[pos][0]//step*step;end=pos+1
                    while end<len(low) and low[end][0]<stamp+step:end+=1
                    group=low[pos:end];pos=end
                    if group[0][0]!=stamp or len(group)!=step//300000:continue
                    expected=high.get(stamp)
                    if expected is None:raise ValueError(f'Missing native complete{tf} bar')
                    values=aggregate(group)
                    if values[:4]!=expected[:4]:raise ValueError(f'OHLC mismatch:{pair["instrument"]}/{tf}/{stamp}')
                    if any(abs(a-b)>max(Decimal('1e-8'),abs(b)*Decimal('1e-8')) for a,b in zip(values[4:],expected[4:])):
                        raise ValueError('Volume mismatch')
                    checked+=1
            print(f'VERIFIED {pair["instrument"]}6 files, cross-timeframe checks passed',flush=True)
        result.update(status='success',pairs=len(universe['pairs']),files=len(items),
                      ohlcv_rows=sum(x['rows'] for x in items if x['candle_type']=='futures'),
                      mark_rows=sum(x['rows'] for x in items if x['candle_type']=='mark'),
                      checked_higher_bars=checked,evaluation_start=universe['evaluation_start'],
                      end_exclusive=universe['end_exclusive'],
                      universe_sha256=manifest['universe_sha256'],data_manifest_sha256=old.sha((ytd.ARCHIVE/'manifest.json').read_bytes()))
    except Exception as exc:
        result.update(status='failed',error=str(exc));raise
    finally:
        result['elapsed_seconds']=round(time.monotonic()-started,2)
        result['finished_at']=datetime.now(timezone.utc).isoformat()
        old.write(target,result)
    print(json.dumps(result,indent=2),flush=True)


def bundle():
    manifest=old.read(ytd.ARCHIVE/'manifest.json');items=[]
    for pair in old.read(ytd.STUDY/'universe.json')['pairs']:
        inst=pair['instrument'];path=ytd.ARCHIVE/(inst+'.zip')
        with zipfile.ZipFile(path.with_suffix('.zip.tmp'),'w',compression=zipfile.ZIP_STORED) as z:
            for item in sorted((x for x in manifest['files'] if x['instrument']==inst),key=lambda x:x['archive']):
                packed=blob(item)
                if old.sha(packed)!=item['archive_sha256']:raise ValueError('Bundle source hash mismatch')
                info=zipfile.ZipInfo(item['archive'],date_time=(1980,1,1,0,0,0))
                info.create_system=0;info.compress_type=zipfile.ZIP_STORED;info.external_attr=0o644<<16
                z.writestr(info,packed)
        path.with_suffix('.zip.tmp').replace(path)
        items.append({'instrument':inst,'file':path.name,'bytes':path.stat().st_size,'sha256':old.sha(path.read_bytes())})
    old.write(ytd.ARCHIVE/'bundles.json',{'files':items})
    print(f'Bundled{len(items)} instruments',flush=True)


if __name__=='__main__':
    restore_and_check()
    bundle()
