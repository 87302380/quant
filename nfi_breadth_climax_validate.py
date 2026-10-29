"""At most one adaptive climax candidate gets further cost and wallet checks."""
import json
from concurrent.futures import ThreadPoolExecutor
from nfi_breadth import run,ROOT
from nfi_rebound_report import collect
from nfi_portfolio_report import tail_metrics

def main():
    out=ROOT/'results/nfi/breadth';names=['climax','climax_after'];rs={}
    b=collect(out/'control');b['tail_metrics']=tail_metrics(out/'control')
    for n in names:r=collect(out/n);r['tail_metrics']=tail_metrics(out/n);rs[n]=r
    candidates=[]
    for n,r in rs.items():
        dominate=r['return_pct']>=b['return_pct'] and r['equity_audit']['mtm_drawdown_pct']<=b['equity_audit']['mtm_drawdown_pct']+1e-6
        risk=r['return_pct']>=.75*b['return_pct'] and r['equity_audit']['mtm_drawdown_pct']<=.8*b['equity_audit']['mtm_drawdown_pct'] and r['tail_metrics']['ulcer_index_pct']<=b['tail_metrics']['ulcer_index_pct'] and r['tail_metrics']['daily_es95_pct']>=b['tail_metrics']['daily_es95_pct']
        if dominate or risk:candidates.append(n)
    selected=max(candidates,key=lambda n:rs[n]['return_pct']) if candidates else None
    record={'selected':selected,'eligible':candidates,'adaptive_posthoc':True,'independent_oos':False}
    (out/'climax_validation_selection.json').write_text(json.dumps(record,indent=2)+'\n');print(record,flush=True)
    if selected:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(run,selected,.001,'_fee10'),pool.submit(run,selected,.0005,'_july','2026-07-01T00:00:00Z')]
            codes=[j.result() for j in jobs]
            if any(codes):raise SystemExit(1)
if __name__=='__main__':main()
