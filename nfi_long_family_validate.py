"""Apply predeclared one-candidate selection, then cost and fresh-wallet checks."""
import json
from concurrent.futures import ThreadPoolExecutor
from nfi_long_family import run,ROOT
from nfi_rebound_report import collect
NAMES=['control','trend_gate','trend_exit','trend_both','dip_recovery','dip_limit']
def main():
    out=ROOT/'results/nfi/long_family';results={n:collect(out/n) for n in NAMES};base=results['control']
    eligible=[n for n in NAMES[1:] if results[n]['return_pct']>=base['return_pct'] and results[n]['equity_audit']['mtm_drawdown_pct']<=base['equity_audit']['mtm_drawdown_pct']+1e-6]
    selected=max(eligible,key=lambda n:results[n]['return_pct']) if eligible else 'trend_both'
    record={'selected':selected,'full_year_eligible':eligible,'rule':'Highest return among return>=control and DD<=control; fallbacktrend_both. Predeclared in validation_plan.json.','independent_oos':False}
    (out/'validation_selection.json').write_text(json.dumps(record,indent=2)+'\n');print(record,flush=True)
    with ThreadPoolExecutor(max_workers=2) as pool:
        jobs=[pool.submit(run,selected,.001,'_fee10'),pool.submit(run,selected,.0005,'_july','2026-07-01T00:00:00Z')]
        if any(job.result() for job in jobs):raise SystemExit(1)
if __name__=='__main__':main()
