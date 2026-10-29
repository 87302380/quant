"""Rebuild the closed-bar breadth ledger and explain baseline drawdown timing."""
import gzip,json,sys
from pathlib import Path
import pandas as pd
from nfi_analyze import load_result
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/breadth'
sys.path.insert(0,str(ROOT/'research/nfi/breadth'))
from breadth import market_features
sys.path.insert(0,str(ROOT/'research/nfi/long_family'))
from NFIShortLongFamily import signal_family

def main():
    u=json.loads((ROOT/'research/nfi/ytd2026/universe.json').read_text());frames={}
    for item in u['pairs']:
        pair=item['pair'];stem=pair.replace('/','_').replace(':','_')
        with gzip.open(ROOT/'data/nfi_ytd2026/freqtrade/futures'/f'{stem}-5m-futures.json.gz','rt') as stream:rows=json.load(stream)
        f=pd.DataFrame(rows,columns=['time','open','high','low','close','volume'])
        frames[pair]=pd.DataFrame({'date':pd.to_datetime(f.time,unit='ms',utc=True),'close':f.close})
    features=market_features(frames);features.to_csv(OUT/'market_features.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    close=pd.DatetimeIndex(features.date)+pd.Timedelta(minutes=5)
    base=load_result(next((ROOT/'results/nfi/long_family/control').glob('*.zip')))
    audit=json.loads((ROOT/'results/nfi/long_family/control/analysis.json').read_text());trough=pd.Timestamp(audit['equity_audit']['drawdown_trough_time'])
    active=[t for t in base['trades'] if pd.Timestamp(t['open_date'])<=trough<pd.Timestamp(t['close_date'])]
    records=[]
    for t in active:
        opened=pd.Timestamp(t['open_date']);entry=features.loc[close<=opened].iloc[-1]
        after=features.loc[(close>opened)&(close<=trough)&features.bre_raw]
        first=(pd.Timestamp(after.date.iloc[0])+pd.Timedelta(minutes=5)).tz_convert('Asia/Shanghai') if len(after) else None
        records.append({'pair':t['pair'],'is_short':t['is_short'],'entry_time_shanghai':str(opened.tz_convert('Asia/Shanghai')),'entry_signal_closed_at_shanghai':str((pd.Timestamp(entry.date)+pd.Timedelta(minutes=5)).tz_convert('Asia/Shanghai')),
          'entry_breadth_known':bool(entry.bre_known),'entry_recent_shock':bool(entry.bre_recent),'entry_decliners_pct':float(entry.bre_down_fraction*100),'entry_median_z':float(entry.bre_median_z),
          'first_post_entry_raw_shock_before_trough_shanghai':str(first) if first is not None else None,'original_campaign_profit_usdt':t['profit_abs']})
    flags=[]
    for t in base['trades']:
        if t['is_short']:continue
        opened=pd.Timestamp(t['open_date']);ended=pd.Timestamp(t['close_date']);entry=features.loc[close<=opened].iloc[-1]
        after=features.loc[(close>opened)&(close<ended)&features.bre_raw]
        flags.append({'pair':t['pair'],'open_date':t['open_date'],'original_winner':t['profit_abs']>0,'original_profit_usdt':t['profit_abs'],'signal_family':signal_family(t['enter_tag']),'entry_gate_blocks':not bool(entry.bre_known) or bool(entry.bre_recent),'post_entry_shock_before_original_exit':bool(len(after)),'first_shock_hours':(pd.Timestamp(after.date.iloc[0])+pd.Timedelta(minutes=5)-opened).total_seconds()/3600 if len(after) else None})
    cohorts={}
    for x in flags:
        key=x['signal_family']+'_'+str(x['entry_gate_blocks']);g=cohorts.setdefault(key,{'wins':0,'losses':0,'profit_usdt':0})
        g['wins']+=x['original_winner'];g['losses']+=not x['original_winner'];g['profit_usdt']+=x['original_profit_usdt']
    (OUT/'baseline_cohorts.json').write_text(json.dumps({'warning':'Original-path descriptive PnL, shared sizing and wallet; not causal alpha. These labels motivated the explicitly adaptive climax experiments.','groups':cohorts},indent=2)+'\n')
    (OUT/'baseline_entry_exit_flags.json').write_text(json.dumps({'warning':'Original path flags and eventual labels only; not a revised strategy PnL or causal profit attribution.','entry_blocks_original_winners':sum(x['entry_gate_blocks'] and x['original_winner'] for x in flags),'entry_blocks_original_losers':sum(x['entry_gate_blocks'] and not x['original_winner'] for x in flags),'post_entry_shocks_original_winners':sum(x['post_entry_shock_before_original_exit'] and x['original_winner'] for x in flags),'post_entry_shocks_original_losers':sum(x['post_entry_shock_before_original_exit'] and not x['original_winner'] for x in flags),'records':flags},indent=2)+'\n')
    evaluation=features.loc[(close>=pd.Timestamp(u['evaluation_start']))&(close<=pd.to_datetime(base['backtest_end_ts'],unit='ms',utc=True))]
    starts=evaluation.bre_raw&~evaluation.bre_raw.shift(fill_value=False)
    report={'warning':'Original worst-drawdown holdings selected ex post for explanation; feature decisions use only closed bars. UTC CSV date is bar OPEN, available5minuteslater. Baseline entry flags are not a new strategy return.','pairs':len(frames),'evaluation_rows':len(evaluation),'raw_shock_bars':int(evaluation.bre_raw.sum()),'raw_shock_episodes':int(starts.sum()),'entry_gate_bars':int(evaluation.bre_recent.sum()),'unknown_bars':int((~evaluation.bre_known).sum()),'trough_time_shanghai':str(trough.tz_convert('Asia/Shanghai')),'baseline_trough_campaigns':records}
    (OUT/'baseline_event_diagnosis.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='baseline_trough_campaigns'},indent=2))
if __name__=='__main__':main()
