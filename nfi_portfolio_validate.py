"""Additional cost / fresh-wallet portfolio checks; completed folders are preserved."""
from concurrent.futures import ThreadPoolExecutor
from nfi_portfolio import run

JOBS=[('side_cap',.001,'_fee10',None),('shock',.001,'_fee10',None),
      ('half_all',.0005,'_july','2026-07-01T00:00:00Z'),('half_long',.0005,'_july','2026-07-01T00:00:00Z'),
      ('portfolio',.0005,'_july','2026-07-01T00:00:00Z'),('side_cap',.0005,'_july','2026-07-01T00:00:00Z'),('shock',.0005,'_july','2026-07-01T00:00:00Z')]

if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(lambda args:run(*args),JOBS))
    if any(codes):raise SystemExit(1)
