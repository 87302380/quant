"""Actual new/missing campaign cohorts; no hindsight-deletion return estimates."""
import json
from pathlib import Path
from nfi_analyze import load_result,filled_orders
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/breadth'
def main():
    old=load_result(next((OUT/'control').glob('*.zip')));orig={(t['pair'],t['open_date']):t for t in old['trades'] if not t['is_short']};records={}
    def short_identity(s):return [(t['pair'],t['open_date'],t['close_date'],t['profit_ratio']) for t in s['trades'] if t['is_short']]
    for name in ['climax','climax_after']:
        raw=load_result(next((OUT/name).glob('*.zip')));new={(t['pair'],t['open_date']):t for t in raw['trades'] if not t['is_short']}
        missing=set(orig)-set(new);added=set(new)-set(orig);matched=set(new)&set(orig)
        prices=[]
        for k in matched:
            a=next(o for o in filled_orders(orig[k]) if o['ft_is_entry']);b=next(o for o in filled_orders(new[k]) if o['ft_is_entry']);prices.append(10000*(b['safe_price']/a['safe_price']-1))
        rows=[{'pair':new[k]['pair'],'open_date':new[k]['open_date'],'tag':new[k]['enter_tag'],'profit_usdt':new[k]['profit_abs'],'margin_return_pct':100*new[k]['profit_ratio'],'hours':new[k]['trade_duration']/60} for k in sorted(added)]
        records[name]={'matched_original_long_entry_times':len(matched),'original_winning_times_not_repeated':sum(orig[k]['profit_abs']>0 for k in missing),'original_losing_times_not_repeated':sum(orig[k]['profit_abs']<0 for k in missing),'new_long_entry_times':len(added),'new_longs_wins':sum(new[k]['profit_abs']>0 for k in added),'new_longs_losses':sum(new[k]['profit_abs']<0 for k in added),'new_long_net_usdt_descriptive':sum(new[k]['profit_abs'] for k in added),'max_abs_matched_entry_price_delta_bps':max(map(abs,prices),default=0),'short_entry_exit_and_normalized_profit_identical':short_identity(old)==short_identity(raw),'new_campaigns':rows}
    (OUT/'climax_cohort_audit.json').write_text(json.dumps({'warning':'Actual original and new paths. Missing/added campaigns reflect filtering and shared capital/slots, not isolated causal alpha. New-campaign profits under their own compounded wallet cannot be added to an original wallet as a new backtest. These hypotheses were chosen after seeing baseline labels.','variants':records},indent=2)+'\n')
    print(json.dumps(records,indent=2))
if __name__=='__main__':main()
