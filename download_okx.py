"""Download public OKX 1m/5m/15m/1H/4H history with transactional checkpoints."""
import argparse
import csv
import hashlib
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from urllib.parse import urlencode, urlparse
from urllib.error import HTTPError, URLError
from pullback import load

STEP = 900000
BARS = {'1m': 60000, '5m': 300000, '15m': STEP, '1H': 3600000, '4H': 14400000}


def timestamp(value, step=STEP):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('dates require timezone, e.g. 2025-01-01T00:00:00Z')
    result = int(dt.timestamp()*1000)
    if result % step:
        raise ValueError('dates must align to the selected bar interval')
    return result


def iso(ts):
    return datetime.fromtimestamp(ts/1000, timezone.utc).isoformat()


class Client:
    def __init__(self, base='https://www.okx.com', proxy=None):
        parts = urlparse(base)
        if parts.scheme != 'https' or parts.path not in ('', '/') or parts.query or parts.fragment:
            raise ValueError('base URL must be an HTTPS origin')
        self.base = base.rstrip('/')
        self.opener = build_opener(ProxyHandler({'https':proxy, 'http':proxy})) if proxy else build_opener()

    def get(self, path, params):
        url = self.base+path+'?'+urlencode(params)
        for attempt in range(5):
            try:
                req = Request(url, headers={'User-Agent':'PullbackResearch/1.0', 'Accept':'application/json'})
                with self.opener.open(req, timeout=20) as response:
                    data = json.load(response)
                if data.get('code') == '50011':
                    raise URLError('OKX rate limit')
                if data.get('code') != '0' or not isinstance(data.get('data'),list):
                    raise RuntimeError(f'OKX error: {data.get("code")} {data.get("msg")}')
                return data
            except HTTPError as exc:
                if exc.code not in (429,500,502,503,504):
                    raise RuntimeError(f'HTTP {exc.code}: check regional API domain / network access; no data exported') from exc
                if attempt == 4: raise
            except (URLError, TimeoutError):
                if attempt == 4: raise
            time.sleep(min(2**attempt, 8))


def open_db(path):
    db = sqlite3.connect(path,timeout=30)
    db.executescript('''
        CREATE TABLE IF NOT EXISTS candles(inst TEXT, ts INTEGER, raw TEXT, PRIMARY KEY(inst,ts));
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, cursor INTEGER, done INTEGER);
        CREATE TABLE IF NOT EXISTS pages(job TEXT, cursor INTEGER, response TEXT,
          fetched TEXT, PRIMARY KEY(job,cursor));
    ''')
    return db


def download(client, db, inst, start, end, pause=.25, bar='15m'):
    # Range and source are part of checkpoint identity; other jobs cannot hide gaps.
    job = hashlib.sha256(json.dumps([client.base,inst,start,end,bar]).encode()).hexdigest()
    state = db.execute('SELECT cursor,done FROM jobs WHERE id=?',(job,)).fetchone()
    cursor, done = state if state else (end,0)
    while not done:
        response = client.get('/api/v5/market/history-candles',dict(instId=inst,bar=bar,after=str(cursor),limit='300'))
        rows = response['data']
        if not rows:
            # Do not checkpoint as success; a later retry can recover availability.
            raise RuntimeError('history ended before requested start; verify listing date / availability')
        if any(len(r)!=9 for r in rows): raise ValueError('unexpected candle format')
        oldest = min(int(r[0]) for r in rows)
        if oldest >= cursor: raise RuntimeError('pagination did not advance')
        with db:
            db.execute('INSERT OR REPLACE INTO pages VALUES(?,?,?,?)',
                       (job,cursor,json.dumps(response),datetime.now(timezone.utc).isoformat()))
            for r in rows:
                ts = int(r[0])
                if start <= ts < end and r[8]=='1':
                    db.execute('INSERT OR REPLACE INTO candles VALUES(?,?,?)',(inst,ts,json.dumps(r)))
            done = oldest <= start
            db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?)',(job,oldest,int(done)))
        cursor = oldest
        print(f'{inst}: reached {iso(cursor)}',flush=True)
        if not done: time.sleep(pause)
    return job


def parallel_download(base,proxy,path,inst,start,end,bar,workers):
    step=BARS[bar];count=(end-start)//step
    def worker(n):
        left=start+(count*n//workers)*step
        right=start+(count*(n+1)//workers)*step
        db=open_db(path)
        try:return download(Client(base,proxy),db,inst,left,right,pause=.4,bar=bar)
        finally:db.close()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(worker,range(workers)))


def export(db, inst, start, end, path, bar='15m'):
    rows = db.execute('SELECT ts,raw FROM candles WHERE inst=? AND ts>=? AND ts<? ORDER BY ts',(inst,start,end)).fetchall()
    step = BARS[bar]
    expected = (end-start)//step
    present = {ts for ts,_ in rows}
    missing = [ts for ts in range(start,end,step) if ts not in present]
    if missing:
        raise RuntimeError(f'incomplete: expected {expected}, got {len(rows)}; first missing {iso(missing[0])}. No final CSV exported.')
    temp = path.with_suffix('.csv.tmp')
    with temp.open('w',newline='',encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp','open','high','low','close','volume','volume_base','volume_quote'])
        for ts,raw in rows:
            r = json.loads(raw)
            writer.writerow([iso(ts),*r[1:8]])
    load(temp, step_seconds=step//1000)
    temp.replace(path)
    return len(rows)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inst',default='BTC-USDT-SWAP')
    p.add_argument('--bar',choices=BARS,default='15m')
    p.add_argument('--workers',type=int,choices=(1,2,3),default=1)
    p.add_argument('--start',required=True,help='inclusive UTC candle open')
    p.add_argument('--end',required=True,help='exclusive UTC candle open')
    p.add_argument('--out',default='data/okx')
    p.add_argument('--base-url',default='https://www.okx.com')
    p.add_argument('--proxy',help='HTTP(S) proxy URL; never disable TLS verification')
    args = p.parse_args()
    if not args.inst.endswith('-USDT-SWAP') or not all(x.isalnum() or x=='-' for x in args.inst):
        p.error('only USDT perpetual instruments supported')
    step = BARS[args.bar]
    start,end = timestamp(args.start,step),timestamp(args.end,step)
    if start % step or end % step:
        p.error('start and end must align to the selected timeframe')
    if start >= end or end > int(time.time()*1000)//step*step:
        p.error('range must be nonempty and contain only fully closed candles')
    out = Path(args.out); out.mkdir(parents=True,exist_ok=True)
    client = Client(args.base_url,args.proxy)
    # Snapshot is observation-time metadata, never historical trading-rule evidence.
    instrument = client.get('/api/v5/public/instruments',dict(instType='SWAP',instId=args.inst))
    if len(instrument['data']) != 1:
        raise RuntimeError('instrument not found')
    meta = instrument['data'][0]
    if meta.get('ctType') != 'linear' or meta.get('settleCcy') != 'USDT':
        raise RuntimeError('not a linear USDT settled contract')
    # Separate databases prevent overlapping candle-open timestamps across bars.
    db_path=out/('cache.sqlite' if args.bar == '15m' else f'cache_{args.bar}.sqlite')
    db = open_db(db_path)
    try:
        job = download(client,db,args.inst,start,end,bar=args.bar) if args.workers==1 else parallel_download(args.base_url,args.proxy,db_path,args.inst,start,end,args.bar,args.workers)
        path = out/f'{args.inst}_{args.bar}_{start}_{end}.csv'
        count = export(db,args.inst,start,end,path,bar=args.bar)
        manifest = dict(instrument=args.inst,source=client.base,bar=args.bar,start=iso(start),end_exclusive=iso(end),
                        candles=count,sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        retrieved_at=datetime.now(timezone.utc).isoformat(),job=job,
                        volume_unit='contracts',instrument_snapshot=instrument,
                        funding='not downloaded; disabled in current default backtest config')
        path.with_suffix('.manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
        print(f'Validated {count} candles: {path}')
    finally:
        db.close()


if __name__ == '__main__': main()
