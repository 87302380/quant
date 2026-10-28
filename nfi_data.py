"""Reproducible OKX USDT perpetual data for a pinned NFI X8 study (stdlib only)."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import threading
import time
import zipfile

from download_okx import Client

ROOT = Path(__file__).resolve().parent
STUDY = ROOT / 'research/nfi'
ARCHIVE = ROOT / 'datasets/nfi'
LOCAL = ROOT / 'data/nfi'
UPSTREAM = '05b95e189ac5d301da2169ddec3118368f1b5c8b'
# Native exchange bars; 1Dutc matches Freqtrade's UTC day, not OKX's UTC+8 1D.
BARS = {'5m': ('5m', 300000, '2026-06-24'),
        '15m': ('15m', 900000, '2026-06-01'),
        '1h': ('1H', 3600000, '2026-05-01'),
        '4h': ('4H', 14400000, '2026-04-01'),
        '1d': ('1Dutc', 86400000, '2024-01-01')}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.tmp')
    # Stable LF bytes on Windows and Linux; this file's hash may be in a manifest.
    tmp.write_bytes(json.dumps(data, indent=2, ensure_ascii=False).encode('utf-8'))
    tmp.replace(path)


def millis(day):
    return int(datetime.fromisoformat(day.replace('Z', '+00:00')).replace(tzinfo=timezone.utc).timestamp()*1000)


def iso(ts):
    return datetime.fromtimestamp(ts/1000, timezone.utc).isoformat()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def jsonc(path):
    # Upstream configs use whole-line comments; preserve regex strings verbatim.
    return json.loads(re.sub(r'(?m)^\s*//.*$', '', path.read_text(encoding='utf-8')))


def prepare(count=40):
    if (STUDY/'universe.json').exists():
        raise ValueError('universe already frozen; preserve it or explicitly create a separate study')
    instruments = {x['instId']: x for x in read(STUDY/'instruments.json')['data']
                   if x.get('settleCcy') == 'USDT' and x.get('ctType') == 'linear' and x['state'] == 'live'}
    whitelist = jsonc(STUDY/'upstream/configs/pairlist-backtest-static-okx-futures-usdt.json')['exchange']['pair_whitelist']
    blacklist = jsonc(STUDY/'upstream/configs/blacklist-okx.json')['exchange']['pair_blacklist']
    rows = []
    cutoff = millis('2025-03-07')  # >=480 daily observations before July evaluation
    for ticker in read(STUDY/'tickers.json')['data']:
        inst = instruments.get(ticker['instId'])
        if not inst:
            continue
        pair = inst['instId'].removesuffix('-SWAP').replace('-', '/') + ':USDT'
        if pair not in whitelist or any(re.fullmatch(p, pair) for p in blacklist):
            continue
        if not inst.get('listTime') or int(inst['listTime']) > cutoff:
            continue
        # OKX linear swaps: volCcy24h = base units, NOT quote turnover.
        turnover = Decimal(ticker['volCcy24h']) * Decimal(ticker['last'])
        rows.append(dict(instrument=inst['instId'], pair=pair, quote_turnover_proxy=str(turnover),
                         list_time=inst['listTime'], contract_value=inst['ctVal'],
                         contract_value_currency=inst['ctValCcy'], metadata=inst))
    rows.sort(key=lambda x: Decimal(x['quote_turnover_proxy']), reverse=True)
    chosen = rows[:count]
    if len(chosen) != count or not any(x['instrument'] == 'BTC-USDT-SWAP' for x in chosen):
        raise ValueError('insufficient eligible pairs or missing BTC context')
    server = int(read(STUDY/'server_time.json')['data'][0]['ts'])
    # Fixed UTC midnight end means every timeframe covers the same fully closed days.
    end = server // 86400000 * 86400000
    universe = dict(format_version=1, upstream_commit=UPSTREAM, exchange='okx', market='linear USDT perpetual',
                    frozen_at=iso(server), end_exclusive=iso(end), evaluation_start='2026-07-01T00:00:00+00:00',
                    selection='Top 40 current turnover proxies in pinned upstream static whitelist, excluding pinned blacklist, listed by 2025-03-07',
                    bias='Current survivors, current volume and current blacklist: retrospective exploration only; not historical point-in-time universe.',
                    funding='NOT downloaded; missing cost, never assume observed zero funding', pairs=chosen,
                    bars={tf: dict(okx_bar=b, step_ms=step, requested_start=start) for tf,(b,step,start) in BARS.items()})
    write(STUDY/'universe.json', universe)
    write(STUDY/'pairs.json', [x['pair'] for x in chosen])
    print(f'Frozen {len(chosen)} pairs, end {iso(end)}', flush=True)


class Limiter:
    """Global spacing across all workers and retries; below OKX 20 requests/2s."""
    def __init__(self, rate=6):
        self.lock = threading.Lock()
        self.next = 0.
        self.delay = 1/rate

    def wait(self):
        with self.lock:
            now = time.monotonic()
            due = max(now, self.next)
            self.next = due+self.delay
        time.sleep(max(0, due-now))


def validate(rows, start, end, step):
    expected = (end-start)//step
    if len(rows) != expected:
        raise ValueError(f'incomplete history: expected {expected}, got {len(rows)}')
    for n, row in enumerate(rows):
        if len(row) != 9 or int(row[0]) != start+n*step or row[8] != '1':
            raise ValueError(f'gap, duplicate, invalid format or unclosed candle at index {n}')
        o,h,l,c,v,b,q = map(Decimal, row[1:8])
        if not all(x.is_finite() for x in (o,h,l,c,v,b,q)) or min(o,l,c) <= 0 or l > min(o,c) or h < max(o,c) or min(v,b,q) < 0:
            raise ValueError(f'invalid OHLCV at {row[0]}')


def compressed(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.tmp')
    with tmp.open('wb') as f:
        with gzip.GzipFile(filename='', mode='wb', fileobj=f, mtime=0) as g:
            g.write(payload)
    tmp.replace(path)


def archive_bytes(name):
    """Read a native gzip locally, or from a deterministic per-instrument bundle."""
    if Path(name).name != name or '/' in name or '\\' in name:
        raise ValueError('invalid archive name')
    direct = ARCHIVE/name
    if direct.exists():
        return direct.read_bytes()
    inst = name.split('_',1)[0]
    with zipfile.ZipFile(ARCHIVE/(inst+'.zip')) as bundle:
        return bundle.read(name)


def bundle():
    """One moderately sized Git object per instrument; no LFS dependency."""
    manifest = read(ARCHIVE/'manifest.json')
    mark = read(ARCHIVE/'mark_manifest.json')
    files = manifest['files']+mark['files']
    items = []
    for pair in read(STUDY/'universe.json')['pairs']:
        inst = pair['instrument']
        target = ARCHIVE/(inst+'.zip')
        with zipfile.ZipFile(target.with_suffix('.zip.tmp'),'w',compression=zipfile.ZIP_STORED) as z:
            for item in sorted((x for x in files if x['instrument']==inst),key=lambda x:x['archive']):
                blob = archive_bytes(item['archive'])
                if sha(blob)!=item['archive_sha256']:raise ValueError('bundle source hash mismatch')
                info=zipfile.ZipInfo(item['archive'],date_time=(1980,1,1,0,0,0))
                info.create_system=0  # fixed across Windows/Linux ZIP writers
                info.compress_type=zipfile.ZIP_STORED;info.external_attr=0o644<<16
                z.writestr(info,blob)
        target.with_suffix('.zip.tmp').replace(target)
        items.append(dict(instrument=inst,file=target.name,bytes=target.stat().st_size,sha256=sha(target.read_bytes())))
    write(ARCHIVE/'bundles.json',dict(format_version=1,files=items))
    print(f'Packed {len(items)} bundles: {sum(x["bytes"] for x in items)} bytes',flush=True)


def fetch_job(pair, tf, universe, limiter):
    bar,step,day = BARS[tf]
    start = max(millis(day), math.ceil(int(pair['list_time'])/step)*step)
    end = millis(universe['end_exclusive'])
    inst = pair['instrument']
    name = f'{inst}_{tf}_{start}_{end}.json.gz'
    archive = ARCHIVE/name
    sidecar = ARCHIVE/(name+'.manifest.json')
    if sidecar.exists() and archive.exists():
        item = read(sidecar)
        if sha(archive.read_bytes()) != item['archive_sha256']:
            raise ValueError('existing archive hash mismatch')
        return item
    LOCAL.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(LOCAL/(inst+'.sqlite'), timeout=30)
    client = Client()
    db.executescript('CREATE TABLE IF NOT EXISTS bars(tf TEXT, ts INTEGER, raw TEXT, PRIMARY KEY(tf,ts));'
                     'CREATE TABLE IF NOT EXISTS jobs(job TEXT PRIMARY KEY, cursor INTEGER, done INTEGER);')
    job = f'{tf}:{start}:{end}'
    state = db.execute('SELECT cursor,done FROM jobs WHERE job=?', (job,)).fetchone()
    cursor, done = state if state else (end,0)
    page_count = 0
    try:
        while not done:
            limiter.wait()
            response = client.get('/api/v5/market/history-candles',
                                  dict(instId=inst, bar=bar, after=str(cursor), limit='300'))
            data = response['data']
            if not data or any(len(r) != 9 for r in data):
                raise ValueError(f'{inst}/{tf}: history ended before requested start {iso(start)}')
            oldest = min(int(r[0]) for r in data)
            if oldest >= cursor:
                raise ValueError('pagination did not advance')
            with db:
                db.executemany('INSERT OR REPLACE INTO bars VALUES(?,?,?)',
                               [(tf,int(r[0]),json.dumps(r,separators=(',',':'))) for r in data
                                if start <= int(r[0]) < end and r[8] == '1'])
                done = oldest <= start
                db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?)', (job,oldest,int(done)))
            cursor = oldest
            page_count += 1
            if page_count % 40 == 0:
                print(f'{inst} {tf}: {iso(cursor)}', flush=True)
        rows = [json.loads(r[0]) for r in db.execute('SELECT raw FROM bars WHERE tf=? AND ts>=? AND ts<? ORDER BY ts',(tf,start,end))]
        validate(rows,start,end,step)
        payload = json.dumps(rows,separators=(',',':')).encode('utf-8')
        compressed(archive,payload)
        item = dict(instrument=inst,pair=pair['pair'],timeframe=tf,okx_bar=bar,start=iso(start),
                    end_exclusive=iso(end),rows=len(rows),archive=name,archive_bytes=archive.stat().st_size,
                    archive_sha256=sha(archive.read_bytes()),raw_bytes=len(payload),raw_sha256=sha(payload),
                    source='https://www.okx.com/api/v5/market/history-candles',
                    retrieved_at=datetime.now(timezone.utc).isoformat(),schema='OKX native 9 strings',
                    volume='contracts, base currency, quote currency preserved',closed_only=True)
        write(sidecar,item)
        print(f'COMPLETE {inst} {tf}: {len(rows)} closed bars',flush=True)
        return item
    finally:
        db.close()


def download(workers=16):
    universe = read(STUDY/'universe.json')
    limiter = Limiter()
    # One worker owns an instrument SQLite file, preventing concurrent same-DB writes.
    def work(pair):
        return [fetch_job(pair,tf,universe,limiter) for tf in BARS]
    items, errors = [], []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(work,p): p['instrument'] for p in universe['pairs']}
        for future in as_completed(futures):
            inst = futures[future]
            try:
                items.extend(future.result())
            except Exception as exc:
                errors.append(dict(instrument=inst,error=str(exc)))
                print(f'FAILED {inst}: {exc}',flush=True)
            write(STUDY/'download_status.json',dict(completed_files=len(items),expected_files=len(universe['pairs'])*len(BARS),errors=errors))
    if errors:
        raise RuntimeError(f'{len(errors)} instruments incomplete; rerun to resume; no complete manifest published')
    manifest = dict(format_version=1,universe_sha256=sha((STUDY/'universe.json').read_bytes()),
                    funding='not downloaded',files=sorted(items,key=lambda x:(x['instrument'],x['timeframe'])))
    write(ARCHIVE/'manifest.json',manifest)
    print(f'ALL COMPLETE: {len(items)} files, {sum(x["rows"] for x in items)} candles',flush=True)


def restore(out=None):
    """Verify raw archives and export Freqtrade JSON gzip, base-currency volume."""
    manifest = read(ARCHIVE/'manifest.json')
    universe = read(STUDY/'universe.json')
    if manifest['universe_sha256'] != sha((STUDY/'universe.json').read_bytes()):
        raise ValueError('universe hash mismatch')
    required = {(p['instrument'],tf) for p in universe['pairs'] for tf in BARS}
    found = [(x['instrument'],x['timeframe']) for x in manifest['files']]
    if len(found) != len(required) or set(found) != required:
        raise ValueError('incomplete or duplicate dataset matrix')
    target = Path(out) if out else LOCAL/'freqtrade'
    for item in manifest['files']:
        name = item['archive']
        if Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('invalid archive name')
        blob = archive_bytes(name)
        if sha(blob) != item['archive_sha256']:
            raise ValueError(f'archive hash mismatch: {name}')
        payload = gzip.decompress(blob)
        if sha(payload) != item['raw_sha256'] or len(payload) != item['raw_bytes']:
            raise ValueError(f'raw hash mismatch: {name}')
        rows = json.loads(payload)
        validate(rows,millis(item['start']),millis(item['end_exclusive']),BARS[item['timeframe']][1])
        # ccxt/Freqtrade linear swap volume is base currency: OKX volCcy (r[6]).
        ft = [[int(r[0]),*map(float,r[1:5]),float(r[6])] for r in rows]
        pair_name = item['pair'].replace('/','_').replace(':','_')
        dest = target/'futures'/f'{pair_name}-{item["timeframe"]}-futures.json.gz'
        result = json.dumps(ft,separators=(',',':'),allow_nan=False).encode('utf-8')
        if not dest.exists() or gzip.decompress(dest.read_bytes()) != result:
            if dest.exists():
                raise ValueError(f'preserving modified local export: {dest}')
            compressed(dest,result)
    print(f'Verified and exported {len(found)} datasets to {target}',flush=True)
    return target


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','download','restore','bundle'])
    parser.add_argument('--count',type=int,default=40)
    parser.add_argument('--workers',type=int,choices=range(1,17),default=16)
    parser.add_argument('--out')
    args = parser.parse_args()
    if args.action == 'prepare': prepare(args.count)
    elif args.action == 'download': download(args.workers)
    elif args.action == 'bundle': bundle()
    else: restore(args.out)
