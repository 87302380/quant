"""Opportunity quality, original-campaign crowding and independent new-risk audit."""
import gzip,json,re,sys
from pathlib import Path
import numpy as np
import pandas as pd
import talib
from nfi_analyze import load_result,filled_orders
from nfi_rebound_report import collect
from nfi_portfolio_report import tail_metrics
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/opportunities'
PREFIX='research_op_long_'
def extra(t):return (t['enter_tag'] or '').startswith(PREFIX)
def summarize(ts):
    wins=[t for t in ts if t['profit_abs']>0];loss=[t for t in ts if t['profit_abs']<0]
    gp=sum(t['profit_abs'] for t in wins);gl=-sum(t['profit_abs'] for t in loss)
    dates=[pd.Timestamp(t['open_date']).tz_convert('Asia/Shanghai') for t in ts]
    return {'trades':len(ts),'wins':len(wins),'losses':len(loss),'profit_usdt':gp-gl,'profit_factor':gp/gl if gl else None,
            'active_days':len(set(d.date() for d in dates)),'unique_pair_dates':len(set((t['pair'],d.date()) for t,d in zip(ts,dates))),
            'median_holding_hours':float(np.median([t['trade_duration']/60 for t in ts])) if ts else None}
def risk_audit(folder,s):
    raw=(folder/'run.log').read_text();logs=[]
    for m in re.finditer(r'OP_RISK_AUDIT\s+(\{[^}]+\})',raw,re.S):logs.append(json.loads(''.join(line.strip() for line in m.group(1).splitlines())))
    new=[t for t in s['trades'] if extra(t)];assert len(logs)==len(new)
    lookup={(t['pair'],t['open_timestamp']):t for t in new};cache={};records=[]
    for row in logs:
        stamp=int(pd.Timestamp(row['time']).timestamp()*1000);t=lookup[(row['pair'],stamp)];assert not t['is_short']
        entries=[o for o in filled_orders(t) if o['ft_is_entry']];assert len(entries)==1;o=entries[0];price=o['safe_price'];q=o['amount']
        pair=t['pair']
        if pair not in cache:
            stem=pair.replace('/','_').replace(':','_')
            with gzip.open(ROOT/'data/nfi_ytd2026/freqtrade/futures'/f'{stem}-1h-futures.json.gz','rt') as f:h=np.array(json.load(f),dtype=float)
            cache[pair]=(h[:,0]+3600000,talib.ATR(h[:,2],h[:,3],h[:,4],14))
        at,atr=cache[pair];i=np.searchsorted(at,stamp,side='right')-1;assert i>=0
        d=min(max(2*atr[i],price*.01),price*.99);stop=price-d;target=price+2*d
        risk=q*(d+t['fee_open']*price+t['fee_close']*stop);margin=q*price/t['leverage']
        assert abs(stop-row['stop'])<max(1e-8,price*1e-8) and abs(target-row['target'])<max(1e-8,price*1e-8)
        assert abs(risk-row['risk'])<.02 and abs(margin-row['margin'])<.02
        assert risk<=.005*row['equity']+.02 and margin<=row['ceiling']+.02
        if '_fixed' in folder.name:assert row['ceiling']<=row['equity']/24+.02
        assert t['trade_duration']<=1440
        records.append({'pair':pair,'entry_timestamp':stamp,'independent_risk':risk,'risk_fraction_pct':100*risk/row['equity'],'margin':margin,'ordinary_quarter_ceiling':row['ceiling'],'stop':stop,'target':target,'actual_profit_usdt':t['profit_abs'],'actual_net_R':t['profit_abs']/risk,'actual_loss_fraction_pct':max(0,-100*t['profit_abs']/row['equity'])})
    overlap=max((sum(x['open_timestamp']<=t['open_timestamp']<x['close_timestamp'] for x in new) for t in new),default=0);assert overlap<=2
    return {'qualified':True,'entries_audited':len(records),'max_observed_extra_overlap':overlap,'max_entry_risk_pct':max((r['risk_fraction_pct'] for r in records),default=0),'max_actual_loss_pct':max((r['actual_loss_fraction_pct'] for r in records),default=0),'worst_actual_net_R':min((r['actual_net_R'] for r in records),default=0),'records':records,
            'warning':'Entry planned stop loss including fees, not maxDD/loss guarantee; simultaneous exits counted before entries for overlap. Pending reservation enforced by live Trade-count callback and unit test.'}
def collect_op(folder,baseline):
    r=collect(folder);s=load_result(next(folder.glob('*.zip')));r['tail_metrics']=tail_metrics(folder)
    new=[t for t in s['trades'] if extra(t)];legacy=[t for t in s['trades'] if not extra(t)]
    r['extra']=summarize(new);r['legacy']=summarize(legacy)
    r['extra_by_tag']={tag:summarize([t for t in new if t['enter_tag']==tag]) for tag in sorted(set(t['enter_tag'] for t in new))}
    old={(t['pair'],t['is_short'],t['open_date']):t for t in baseline['trades']};actual={(t['pair'],t['is_short'],t['open_date']):t for t in legacy};missing=set(old)-set(actual)
    r['original_entry_times_not_repeated']={'total':len(missing),'original_winners':sum(old[k]['profit_abs']>0 for k in missing),'original_losers':sum(old[k]['profit_abs']<0 for k in missing)}
    r['actual_path_accounting']={'extra_pnl_usdt':r['extra']['profit_usdt'],'legacy_pnl_usdt':r['legacy']['profit_usdt'],'baseline_total_pnl_usdt':baseline['profit_total_abs'],'legacy_difference_usdt':r['legacy']['profit_usdt']-baseline['profit_total_abs'],'portfolio_difference_usdt':r['profit_usdt']-baseline['profit_total_abs'],'warning':'Arithmetic actual-path identity, not causal alpha/opportunity-cost decomposition; legacy differences include wallet compounding, sizes and entry/exit changes.'}
    assert abs(r['extra']['profit_usdt']+r['legacy']['profit_usdt']-r['profit_usdt'])<.01
    r['risk_audit']=risk_audit(folder,s)
    return r
if __name__=='__main__':
    baseline=load_result(next((OUT/'control').glob('*.zip')))
    for f in sorted(OUT.iterdir()):
        if f.is_dir() and list(f.glob('*.zip')):
            r=collect_op(f,baseline);print(f.name,r['return_pct'],r['extra'],flush=True)
