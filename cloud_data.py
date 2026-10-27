"""Pack/restore reproducible BTC datasets without redownloading OKX history."""
import argparse
import gzip
import hashlib
import json
import shutil
from pathlib import Path

ROOT=Path(__file__).resolve().parent
ARCHIVE=ROOT/'datasets'
DATA=ROOT/'data'/'okx'


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def pack():
    ARCHIVE.mkdir(exist_ok=True);items=[]
    for source in sorted(DATA.glob('BTC-USDT-SWAP_*.csv')):
        target=ARCHIVE/(source.name+'.gz')
        with source.open('rb') as f,target.open('wb') as output:
            with gzip.GzipFile(filename='',fileobj=output,mode='wb',mtime=0) as compressed:
                shutil.copyfileobj(f,compressed)
        items.append(dict(file=source.name,archive=target.name,bytes=source.stat().st_size,
                          sha256=sha(source),archive_sha256=sha(target)))
    if not items:raise ValueError('no BTC dataset to pack')
    (ARCHIVE/'manifest.json').write_text(json.dumps(dict(format_version=1,files=items),indent=2),encoding='utf-8')
    print(json.dumps(dict(datasets=len(items),compressed_bytes=sum((ARCHIVE/x['archive']).stat().st_size for x in items))))


def restore():
    manifest=json.loads((ARCHIVE/'manifest.json').read_text(encoding='utf-8'))
    DATA.mkdir(parents=True,exist_ok=True)
    for item in manifest['files']:
        for key in ('file','archive'):
            if Path(item[key]).name!=item[key] or '/' in item[key] or '\\' in item[key]:
                raise ValueError('dataset names must be basenames')
        source=ARCHIVE/item['archive'];target=DATA/item['file']
        if not target.name.endswith('.csv'):raise ValueError('CSV datasets only')
        if target.exists():
            if sha(target)!=item['sha256']:raise ValueError(f'preserving modified local data: {target.name}')
            print(f'verified {target.name}');continue
        if sha(source)!=item['archive_sha256']:raise ValueError(f'archive hash mismatch: {source.name}')
        temp=target.with_suffix('.csv.tmp')
        with gzip.open(source,'rb') as f,temp.open('wb') as output:shutil.copyfileobj(f,output)
        if temp.stat().st_size!=item['bytes'] or sha(temp)!=item['sha256']:
            raise ValueError(f'dataset hash mismatch: {target.name}')
        temp.replace(target);print(f'restored {target.name}')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pack',action='store_true')
    args=p.parse_args();pack() if args.pack else restore()
