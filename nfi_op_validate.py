"""Predeclared selection, matched allocation check, cost/restart and order stress."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from nfi_opportunities import run,ROOT
from nfi_analyze import load_result
from nfi_op_audit import collect_op
OUT=ROOT/'results/nfi/opportunities';NAMES=['control','pullback','breakout','native','retest','combined','compression','context']
def batch(jobs):
    def one(args):
        name,fee,suffix,start,reverse=args;folder=OUT/(name+suffix)
        if list(folder.glob('*.zip')):
            record=json.loads((folder/'execution.json').read_text());assert record['status']=='success';return 0
        return run(name,fee,suffix,start,reverse)
    with ThreadPoolExecutor(max_workers=2) as pool:
        codes=list(pool.map(one,jobs))
    if any(codes):raise SystemExit(1)
def main():
    baseline=load_result(next((OUT/'control').glob('*.zip')));rs={n:collect_op(OUT/n,baseline) for n in NAMES};b=rs['control']
    def risk_ok(r):return r['equity_audit']['mtm_drawdown_pct']<=13.3163266626+1e-6 and r['tail_metrics']['ulcer_index_pct']<=3.51914292982+1e-8 and r['tail_metrics']['daily_es95_pct']>=-2.63561957572-1e-8
    eligible=[n for n in NAMES[1:] if rs[n]['return_pct']>b['return_pct'] and rs[n]['extra']['profit_usdt']>0 and risk_ok(rs[n])]
    chosen=max(eligible,key=lambda n:rs[n]['return_pct']) if eligible else 'compression';fixed=chosen+'_fixed'
    record={'raw_eligible':eligible,'raw_selected':chosen,'fixed_candidate':fixed,'fixed_qualified':False,'stress_qualified':False,'reverse_tested':False,'warning':'Qualification thresholds retained; compression selected posthoc per adaptive_plan.json. All history examined, no OOS. Fixed pair checks ordinary proposal cap; it does not remove wallet/path effects.'}
    def save():(OUT/'selection.json').write_text(json.dumps(record,indent=2)+'\n')
    save();print(record,flush=True)
    batch([('control_fixed',.0005,'',None,False),(fixed,.0005,'',None,False)])
    fixedbase=load_result(next((OUT/'control_fixed').glob('*.zip')))
    a=collect_op(OUT/'control_fixed',fixedbase);v=collect_op(OUT/fixed,fixedbase)
    record['fixed_qualified']=v['return_pct']>a['return_pct'] and v['extra']['profit_usdt']>0 and risk_ok(v);save();print('FIXED',record,flush=True)
    if not record['fixed_qualified']:return
    batch([('control_fixed',.001,'_fee10',None,False),(fixed,.001,'_fee10',None,False)])
    batch([('control_fixed',.0005,'_july','2026-07-01T00:00:00Z',False),(fixed,.0005,'_july','2026-07-01T00:00:00Z',False)])
    values={}
    for suffix in ['_fee10','_july']:
        values[suffix]={n:load_result(next((OUT/(n+suffix)).glob('*.zip')))['profit_total'] for n in ['control_fixed',fixed]}
    record['stress_qualified']=all(r[fixed]>r['control_fixed'] for r in values.values());save();print('STRESS',record,flush=True)
    if record['stress_qualified']:
        batch([('control_fixed',.0005,'_reverse',None,True),(fixed,.0005,'_reverse',None,True)])
        record['reverse_tested']=True;save()
if __name__=='__main__':main()
