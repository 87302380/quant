"""Download real OKX 1h mark prices for futures backtests; never fetch funding."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import json
import sqlite3

from download_okx import Client
from nfi_data import ARCHIVE, LOCAL, STUDY, Limiter, archive_bytes, compressed, iso, millis, read, sha, validate, write


def validate_mark(rows, start, end):
    if any(len(r) != 6 for r in rows):
        raise ValueError('mark candle must contain timestamp, OHLC and confirm')
    validate([[*r[:5],'0','0','0',r[5]] for r in rows],start,end,3600000)


def mark_start(list_time):
    return max(millis('2026-06-24'),((int(list_time)+3599999)//3600000)*3600000)


def download():
    universe = read(STUDY/'universe.json')
    end = millis(universe['end_exclusive'])
    limiter = Limiter(3)
    def work(pair):
        # Newly listed contracts have no prelisting mark history.
        start=mark_start(pair['list_time'])
        inst = pair['instrument']
        name = f'{inst}_mark1h_{start}_{end}.json.gz'
        archive, sidecar = ARCHIVE/name, ARCHIVE/(name+'.manifest.json')
        if archive.exists() and sidecar.exists():
            item=read(sidecar)
            if sha(archive.read_bytes()) != item['archive_sha256']:raise ValueError('mark archive mismatch')
            return item
        LOCAL.mkdir(parents=True,exist_ok=True)
        db=sqlite3.connect(LOCAL/(inst+'_mark.sqlite'))
        db.executescript('CREATE TABLE IF NOT EXISTS bars(ts INTEGER PRIMARY KEY,raw TEXT);'
                        'CREATE TABLE IF NOT EXISTS jobs(job TEXT PRIMARY KEY,cursor INTEGER,done INTEGER);')
        client=Client();job=f'{start}:{end}'
        state=db.execute('SELECT cursor,done FROM jobs WHERE job=?',(job,)).fetchone()
        cursor,done=state if state else (end,0)
        try:
            while not done:
                limiter.wait()
                response=client.get('/api/v5/market/history-mark-price-candles',
                                    dict(instId=inst,bar='1H',after=str(cursor),limit='100'))
                data=response['data']
                if not data or any(len(r)!=6 for r in data):raise ValueError('invalid/early end mark history')
                oldest=min(int(r[0]) for r in data)
                if oldest>=cursor:raise ValueError('mark pagination did not advance')
                with db:
                    db.executemany('INSERT OR REPLACE INTO bars VALUES(?,?)',
                                   [(int(r[0]),json.dumps(r,separators=(',',':'))) for r in data if start<=int(r[0])<end and r[5]=='1'])
                    done=oldest<=start
                    db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?)',(job,oldest,int(done)))
                cursor=oldest
            rows=[json.loads(r[0]) for r in db.execute('SELECT raw FROM bars WHERE ts>=? AND ts<? ORDER BY ts',(start,end))]
            validate_mark(rows,start,end)
            payload=json.dumps(rows,separators=(',',':')).encode()
            compressed(archive,payload)
            item=dict(instrument=inst,pair=pair['pair'],timeframe='1h',candle_type='mark',start=iso(start),end_exclusive=iso(end),
                      rows=len(rows),archive=name,archive_bytes=archive.stat().st_size,archive_sha256=sha(archive.read_bytes()),
                      raw_bytes=len(payload),raw_sha256=sha(payload),schema='OKX native 6 strings, no volume',
                      source='https://www.okx.com/api/v5/market/history-mark-price-candles',
                      retrieved_at=datetime.now(timezone.utc).isoformat())
            write(sidecar,item);print(f'COMPLETE {inst} mark1h {len(rows)}',flush=True)
            return item
        finally:db.close()
    items=[];errors=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(work,p):p['instrument'] for p in universe['pairs']}
        for f in as_completed(futures):
            try:items.append(f.result())
            except Exception as exc:
                errors.append(dict(instrument=futures[f],error=str(exc)))
                print(f'FAILED {futures[f]} mark: {exc}',flush=True)
    write(STUDY/'mark_download_status.json',dict(completed_files=len(items),errors=errors))
    if errors:raise RuntimeError('incomplete mark dataset; rerun to resume')
    write(ARCHIVE/'mark_manifest.json',dict(universe_sha256=sha((STUDY/'universe.json').read_bytes()),files=sorted(items,key=lambda x:x['instrument'])))


def restore(out=None):
    from pathlib import Path
    manifest=read(ARCHIVE/'mark_manifest.json')
    universe=read(STUDY/'universe.json')
    if manifest['universe_sha256']!=sha((STUDY/'universe.json').read_bytes()):raise ValueError('universe mismatch')
    found=[x['instrument'] for x in manifest['files']]
    if len(found)!=len(universe['pairs']) or set(found)!={x['instrument'] for x in universe['pairs']}:raise ValueError('incomplete mark matrix')
    target=Path(out) if out else LOCAL/'freqtrade'
    for item in manifest['files']:
        name=item['archive']
        if Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('invalid mark archive name')
        blob=archive_bytes(name)
        if sha(blob)!=item['archive_sha256']:raise ValueError('mark archive hash mismatch')
        raw=gzip.decompress(blob)
        if len(raw)!=item['raw_bytes'] or sha(raw)!=item['raw_sha256']:raise ValueError('mark raw hash mismatch')
        rows=json.loads(raw);validate_mark(rows,millis(item['start']),millis(item['end_exclusive']))
        # Mark candles have no traded volume; Freqtrade OHLCV schema needs a zero placeholder.
        ft=[[int(r[0]),*map(float,r[1:5]),0.] for r in rows]
        pair_name=item['pair'].replace('/','_').replace(':','_')
        path=target/'futures'/f'{pair_name}-1h-mark.json.gz'
        payload=json.dumps(ft,separators=(',',':'),allow_nan=False).encode()
        if path.exists():
            if gzip.decompress(path.read_bytes())!=payload:raise ValueError('preserving modified mark export')
        else:compressed(path,payload)
    print(f'Verified and exported {len(found)} real mark-price datasets',flush=True)


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['download','restore']);p.add_argument('--out')
    args=p.parse_args()
    download() if args.action=='download' else restore(args.out)
