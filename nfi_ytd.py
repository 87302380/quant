"""Versioned year-to-date native OKX data, reusing pinned archives without rewriting them."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import gzip
import json
import math
from pathlib import Path
import sqlite3
import zipfile

from download_okx import Client
import nfi_data as old
from nfi_mark import validate_mark

ROOT=Path(__file__).resolve().parent
STUDY=ROOT/'research/nfi/ytd2026'
ARCHIVE=ROOT/'datasets/nfi_ytd2026'
LOCAL=ROOT/'data/nfi_ytd2026'
BARS={'5m':('5m',300000,'2025-12-25'), '15m':('15m',900000,'2025-12-01'),
      '1h':('1H',3600000,'2025-11-01'), '4h':('4H',14400000,'2025-09-01'),
      '1d':('1Dutc',86400000,'2024-01-01'), 'mark1h':('1H',3600000,'2025-12-25')}


def prepare():
    if (STUDY/'universe.json').exists():
        return old.read(STUDY/'universe.json')
    server=Client().get('/api/v5/public/time',{})
    now=int(server['data'][0]['ts']);end=now//300000*300000
    original=old.read(ROOT/'research/nfi/universe.json')
    selected=old.read(ROOT/'research/nfi/study/official.json')['exchange']['pair_whitelist']
    pairs=[p for p in original['pairs'] if p['pair'] in selected]
    if len(pairs)!=57 or len({p['pair'] for p in pairs})!=57:
        raise ValueError('Expected exact existing57-pair research universe')
    universe={'format_version':1,'created_at':old.iso(now),'evaluation_start':'2026-01-01T00:00:00+00:00',
              'end_exclusive':old.iso(end),'upstream_commit':old.UPSTREAM,'pairs':pairs,
              'selection':'Exact existing57-pair official-static intersection; not historical point-in-time selection',
              'funding':'Omitted by user request; never observed zero funding',
              'bars':{tf:{'okx_bar':b,'step_ms':step,'requested_start':start,
                           'end_exclusive':old.iso(end//step*step)} for tf,(b,step,start) in BARS.items()},
              'bias':'Present-day survivors and official lists projected backward. New listings begin only at real listing; indicator readiness varies.'}
    old.write(STUDY/'server_time.json',server)
    old.write(STUDY/'universe.json',universe)
    return universe


def missing_intervals(present,start,end,step):
    """Return exact missing aligned ranges; never substitute synthetic rows."""
    ranges=[];left=None
    for ts in range(start,end,step):
        if ts not in present:
            if left is None:left=ts
        elif left is not None:
            ranges.append((left,ts));left=None
    if left is not None:ranges.append((left,end))
    return ranges


def load_index():
    entries=old.read(ROOT/'datasets/nfi/manifest.json')['files']+old.read(ROOT/'datasets/nfi/mark_manifest.json')['files']
    return {(x['instrument'],'mark1h' if x.get('candle_type')=='mark' else x['timeframe']):x for x in entries}


def fetch_pair(pair,universe,limiter,index):
    LOCAL.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(LOCAL/(pair['instrument']+'.sqlite'),timeout=30)
    db.execute('CREATE TABLE IF NOT EXISTS bars(tf TEXT,ts INTEGER,raw TEXT,PRIMARY KEY(tf,ts))')
    client=Client();items=[]
    try:
        for tf,(bar,step,start_day) in BARS.items():
            start=max(old.millis(start_day),math.ceil(int(pair['list_time'])/step)*step)
            end=old.millis(universe['bars'][tf]['end_exclusive'])
            if start>=end:raise ValueError('No valid interval')
            # Seed native rows only from SHA-verified originals; INSERT OR IGNORE preserves checkpoints.
            prior=index[pair['instrument'],tf]
            seed_key='seed:'+tf
            db.execute('CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY,v TEXT)')
            seeded=db.execute('SELECT v FROM meta WHERE k=?',(seed_key,)).fetchone()
            if not seeded:
                blob=old.archive_bytes(prior['archive'])
                if old.sha(blob)!=prior['archive_sha256']:raise ValueError('Old archive hash mismatch')
                raw=gzip.decompress(blob)
                if old.sha(raw)!=prior['raw_sha256']:raise ValueError('Old raw hash mismatch')
                rows=json.loads(raw)
                with db:
                    db.executemany('INSERT OR IGNORE INTO bars VALUES(?,?,?)',
                                   [(tf,int(r[0]),json.dumps(r,separators=(',',':'))) for r in rows if start<=int(r[0])<end])
                    db.execute('INSERT INTO meta VALUES(?,?)',(seed_key,prior['archive_sha256']))
            present={r[0] for r in db.execute('SELECT ts FROM bars WHERE tf=? AND ts>=? AND ts<?',(tf,start,end))}
            missing=missing_intervals(present,start,end,step)
            print(f'PLAN {pair["instrument"]} {tf}: reused {len(present)}, missing {sum((b-a)//step for a,b in missing)}',flush=True)
            pages=0
            for left,right in missing:
                cursor=right
                while cursor>left:
                    limiter.wait()
                    mark=tf=='mark1h'
                    endpoint='/api/v5/market/history-mark-price-candles' if mark else '/api/v5/market/history-candles'
                    result=client.get(endpoint,dict(instId=pair['instrument'],bar=bar,after=str(cursor),limit='100' if mark else '300'))
                    rows=result['data'];size=6 if mark else 9
                    if not rows or any(len(r)!=size for r in rows):raise ValueError(f'Unexpected/early-end history {tf}')
                    oldest=min(int(r[0]) for r in rows)
                    if oldest>=cursor:raise ValueError('Nonadvancing pagination')
                    with db:
                        db.executemany('INSERT OR IGNORE INTO bars VALUES(?,?,?)',
                            [(tf,int(r[0]),json.dumps(r,separators=(',',':'))) for r in rows
                             if left<=int(r[0])<right and r[-1]=='1'])
                    cursor=oldest;pages+=1
                    if pages%50==0:print(f'PROGRESS {pair["instrument"]} {tf} {old.iso(cursor)} pages={pages}',flush=True)
            rows=[json.loads(r[0]) for r in db.execute('SELECT raw FROM bars WHERE tf=? AND ts>=? AND ts<? ORDER BY ts',(tf,start,end))]
            if tf=='mark1h':validate_mark(rows,start,end)
            else:old.validate(rows,start,end,step)
            payload=json.dumps(rows,separators=(',',':')).encode()
            name=f'{pair["instrument"]}_{tf}_{start}_{end}.json.gz'
            old.compressed(ARCHIVE/name,payload)
            blob=(ARCHIVE/name).read_bytes()
            item={'instrument':pair['instrument'],'pair':pair['pair'],'timeframe':'1h' if tf=='mark1h' else tf,
                  'candle_type':'mark' if tf=='mark1h' else 'futures','start':old.iso(start),'end_exclusive':old.iso(end),
                  'rows':len(rows),'archive':name,'archive_sha256':old.sha(blob),'raw_sha256':old.sha(payload),
                  'archive_bytes':len(blob),'raw_bytes':len(payload),'reused_source_sha256':prior['archive_sha256'],
                  'source':'https://www.okx.com'+('/api/v5/market/history-mark-price-candles' if tf=='mark1h' else '/api/v5/market/history-candles'),
                  'retrieved_at':datetime.now(timezone.utc).isoformat(),'closed_only':True}
            old.write(ARCHIVE/(name+'.manifest.json'),item);items.append(item)
            print(f'COMPLETE {pair["instrument"]} {tf} rows={len(rows)}',flush=True)
        return items
    finally:db.close()


def download(workers=12,rate=8):
    universe=prepare();index=load_index();limiter=old.Limiter(rate)
    items=[];errors=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures={pool.submit(fetch_pair,p,universe,limiter,index):p['instrument'] for p in universe['pairs']}
        for future in as_completed(futures):
            inst=futures[future]
            try:items.extend(future.result())
            except Exception as exc:
                errors.append({'instrument':inst,'error':str(exc)})
                print(f'FAILED {inst}: {exc}',flush=True)
            old.write(STUDY/'download_status.json',{'completed_files':len(items),'expected_files':342,'errors':errors})
    if errors:raise RuntimeError('Incomplete YTD data; resume from retained SQLite checkpoints')
    old.write(ARCHIVE/'manifest.json',{'universe_sha256':old.sha((STUDY/'universe.json').read_bytes()),
                                     'files':sorted(items,key=lambda x:(x['instrument'],x['candle_type'],x['timeframe']))})
    print('ALL COMPLETE342 datasets',flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','download'])
    parser.add_argument('--workers',type=int,default=12)
    parser.add_argument('--rate',type=float,default=8)
    args=parser.parse_args()
    if not 0<args.rate<=8:parser.error('rate must be in (0,8] to remain below OKX20/2s')
    prepare() if args.action=='prepare' else download(args.workers,args.rate)


if __name__=='__main__':main()
