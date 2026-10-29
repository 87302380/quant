"""Matched native entry cohorts; descriptive labels, never deletion-based returns."""
import json,sys
from pathlib import Path
from nfi_analyze import load_result,filled_orders
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/long_family'
sys.path.insert(0,str(ROOT/'research/nfi/long_family'))
from NFIShortLongFamily import signal_family

def main():
    base=load_result(next((OUT/'control').glob('*.zip')))
    original={(t['pair'],t['open_date']):t for t in base['trades'] if not t['is_short']};summary={}
    for name in ['trend_gate','trend_exit','trend_both','dip_recovery','dip_limit']:
        raw=load_result(next((OUT/name).glob('*.zip')));new={(t['pair'],t['open_date']):t for t in raw['trades'] if not t['is_short']}
        target='dip' if name.startswith('dip_') else 'trend';old={k:t for k,t in original.items() if signal_family(t['enter_tag'])==target}
        matched=set(old)&set(new);missing=set(old)-set(new);rows=[]
        for k in sorted(matched):
            a=next(o for o in filled_orders(old[k]) if o['ft_is_entry']);b=next(o for o in filled_orders(new[k]) if o['ft_is_entry'])
            rows.append({'pair':k[0],'open_date':k[1],'original_winner':old[k]['profit_abs']>0,'new_winner':new[k]['profit_abs']>0,'entry_price_change_bps':10000*(b['safe_price']/a['safe_price']-1),'original_margin_return_pct':old[k]['profit_ratio']*100,'new_margin_return_pct':new[k]['profit_ratio']*100})
        summary[name]={'target_family':target,'original_target_entries':len(old),'matched_target_entry_times':len(matched),'original_winning_entry_times_not_repeated':sum(old[k]['profit_abs']>0 for k in missing),'original_losing_entry_times_not_repeated':sum(old[k]['profit_abs']<0 for k in missing),'new_long_entry_times_without_any_baseline_match':len(set(new)-set(original)),'mean_matched_entry_price_change_bps':sum(r['entry_price_change_bps'] for r in rows)/len(rows) if rows else None,'records':rows}
    result={'warning':'Entry-time cohort comparisons only. Missing original entry times may reflect filters, unfilled orders, different holding periods or shared-wallet slot changes; not direct causal attribution. Eventual profit labels are diagnostic only. No revised profits computed by deleting original trades.','variants':summary}
    (OUT/'entry_cohort_audit.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:{x:y for x,y in v.items() if x!='records'} for k,v in summary.items()},indent=2))
if __name__=='__main__':main()
