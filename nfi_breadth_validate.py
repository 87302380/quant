"""Prespecified return and risk-tradeoff selections, then actual cost/wallet replays."""
import json
from concurrent.futures import ThreadPoolExecutor
from nfi_breadth import run,ROOT
from nfi_rebound_report import collect
from nfi_portfolio_report import tail_metrics
NAMES=['control','gate','exit','both','btc_exit','long_cap']
def main():
    out=ROOT/'results/nfi/breadth';results={}
    for n in NAMES:
        r=collect(out/n);r['tail_metrics']=tail_metrics(out/n);results[n]=r
    b=results['control'];eligible=[n for n in NAMES[1:-1] if results[n]['return_pct']>=b['return_pct'] and results[n]['equity_audit']['mtm_drawdown_pct']<=b['equity_audit']['mtm_drawdown_pct']+1e-6]
    primary=max(eligible,key=lambda n:results[n]['return_pct']) if eligible else 'both'
    risk=[]
    for n in NAMES[1:]:
        r=results[n]
        if r['return_pct']>=.75*b['return_pct'] and r['equity_audit']['mtm_drawdown_pct']<=.8*b['equity_audit']['mtm_drawdown_pct'] and r['tail_metrics']['ulcer_index_pct']<=b['tail_metrics']['ulcer_index_pct'] and r['tail_metrics']['daily_es95_pct']>=b['tail_metrics']['daily_es95_pct']:risk.append(n)
    secondary=max(risk,key=lambda n:results[n]['return_pct']/results[n]['equity_audit']['mtm_drawdown_pct']) if risk else None
    selected=[primary]+([secondary] if secondary and secondary!=primary else [])
    record={'primary':primary,'return_eligible':eligible,'risk_eligible':risk,'secondary':secondary,'selected':selected,'warning':'Rules recorded in plan.json and risk_validation_plan.json; same inspected history, not OOS.'}
    (out/'validation_selection.json').write_text(json.dumps(record,indent=2)+'\n');print(record,flush=True)
    for n in selected:
        with ThreadPoolExecutor(max_workers=2) as pool:
            jobs=[pool.submit(run,n,.001,'_fee10'),pool.submit(run,n,.0005,'_july','2026-07-01T00:00:00Z')]
            codes=[job.result() for job in jobs]
            if any(codes):raise SystemExit(1)
if __name__=='__main__':main()
