"""Recorded adaptive risk-rule combinations, including cost and fresh-wallet checks."""
from concurrent.futures import ThreadPoolExecutor
from nfi_portfolio import run

JOBS=[('shock_corr',.0005,'',None),('atr_corr',.0005,'',None),
      ('shock_corr',.001,'_fee10',None),('atr_corr',.001,'_fee10',None),
      ('shock_corr',.0005,'_july','2026-07-01T00:00:00Z'),('atr_corr',.0005,'_july','2026-07-01T00:00:00Z')]
if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=2) as pool:codes=list(pool.map(lambda args:run(*args),JOBS))
    if any(codes):raise SystemExit(1)
