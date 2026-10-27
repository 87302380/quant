"""Reproducible small hypothesis comparison with an untouched 2026 holdout.

python research.py --stage develop
python research.py --stage final
"""
import argparse
import bisect
import csv
import hashlib
import json
import math
import random
import statistics
from collections import Counter, deque
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from pullback import Config, load, features, candidates, run, report

DATA=Path('data/okx/BTC-USDT-SWAP_15m_1704067200000_1793125800000.csv')
OUT=Path('results/research')


def ts(s): return int(datetime.fromisoformat(s).replace(tzinfo=timezone.utc).timestamp())
PERIODS={'train':(ts('2024-01-01'),ts('2025-01-01')),
         'validation':(ts('2025-01-01'),ts('2026-01-01')),
         'holdout':(ts('2026-01-01'),1793125800)}


def dump(path,obj):
    path.write_text(json.dumps(obj,indent=2,allow_nan=False),encoding='utf-8')


def hypotheses():
    base=Config()
    result={}
    for name,rsi,vol in [('baseline',False,False),('rsi',True,False),('volume',False,True),('rsi_volume',True,True)]:
        result[name]=('structure',replace(base,require_rsi=rsi,require_volume=vol))
    # Bounded, declared in advance; no indicator weight or threshold sweep.
    for side in ('both','long'):
        c=replace(base,enable_short=side=='both')
        for name,changes in [
            ('aligned',dict(require_1h_trend=True,min_adx=20)),
            ('wider',dict(stop_atr=.5,min_stop_atr=1.5,max_entry_atr=2.5)),
            ('capped',dict(stop_atr=.5,min_stop_atr=1.5,max_entry_atr=2.5,target_rr_cap=2)),
            ('rsi_wider',dict(require_rsi=True,stop_atr=.5,min_stop_atr=1.5,max_entry_atr=2.5))]:
            result[f'{name}_{side}']=('structure',replace(c,**changes))
    for mode in ('ema_pullback','donchian'):
        for side in ('both','long'):
            for target in (2,3):
                result[f'{mode}_{side}_{target}R']=(mode,replace(base,enable_short=side=='both',
                     max_entry_atr=100,max_hold_bars=480,target_rr_cap=0,min_stop_atr=0))
    for mode in ('slow_break20','slow_break55','slow_pullback'):
        for side in ('both','long'):
            for target in (3,6):
                result[f'{mode}_{side}_{target}R']=(mode,replace(base,enable_short=side=='both',
                     max_entry_atr=100,max_hold_bars=2880))
    return result


def alternative_events(bars,c,mode,target_r):
    # 1h decisions occur only on the last 15m subbar; next 15m open executes.
    slow=mode.startswith('slow_')
    history=deque(maxlen=330 if mode=='slow_break55' else 120 if slow else 48)
    for i,b in enumerate(bars):
        if (b['t']+900)%(14400 if slow else 3600): continue
        f=b['h4']; h=f if slow else b['h1']
        prior=list(history)
        history.append(h)
        if len(prior)<history.maxlen or not f.get('ema99') or not h.get('atr') or not h.get('ema99'): continue
        for d in (1,-1):
            if d==-1 and not c.enable_short: continue
            if d*(f['ema25']-f['ema99'])<=0 or d*(f['close']-f['ema99'])<=0: continue
            if mode in ('ema_pullback','slow_pullback'):
                trigger=(d*(h['ema25']-h['ema99'])>0 and
                    (h['low']<=h['ema25'] if d==1 else h['high']>=h['ema25']) and
                    d*(h['close']-h['ema25'])>0 and d*(h['close']-prior[-1]['high' if d==1 else 'low'])>0)
            else:
                level=max(x['high'] for x in prior) if d==1 else min(x['low'] for x in prior)
                trigger=d*(h['close']-level)>0
            if not trigger: continue
            dist=2*h['atr']
            stop=h['close']-d*dist
            yield dict(index=i,side='long' if d==1 else 'short',direction=d,stop=stop,
                target=h['close']+d*target_r*dist,structure=stop,atr=b['atr'],rsi=b['rsi'],
                rsi_1h=h['rsi'],volume_ratio=b['volume_ratio'],adx=f['adx'],plus_di=f['plus_di'],
                minus_di=f['minus_di'],ema_distance_atr=(f['close']-f['ema25'])/f['atr'],
                score=0,rsi_ok=True,volume_ok=True,strategy=mode)


def simulate(bars,name,mode,c,start):
    events=candidates(bars,c) if mode=='structure' else alternative_events(bars,c,mode,int(name[-2]))
    return run([],c,prepared_bars=bars,event_source=events,start_time=start)


def metrics(trades,bars,c,start):
    # Mark-to-market equity at every 15m close, charging entry fee immediately.
    realized=c.equity; j=0; peak=c.equity; drawdown=0; active=0; daily={}; curve=[]
    worst_intrabar=0
    for b in bars:
        if b['t']<start: continue
        end=b['t']+900
        while j<len(trades) and trades[j]['exit_time']<=end:
            realized+=trades[j]['net_pnl']; j+=1
        value=realized; worst=realized
        if j<len(trades) and trades[j]['entry_time']<end:
            t=trades[j]; active+=1
            value+=t['quantity']*(t['direction']*(b['close']-t['entry'])-c.fee*(t['entry']+b['close']))
            adverse=b['low'] if t['direction']==1 else b['high']
            adverse=max(adverse,t['stop']) if t['direction']==1 else min(adverse,t['stop'])
            worst+=t['quantity']*(t['direction']*(adverse-t['entry'])-c.fee*(t['entry']+adverse))
        peak=max(peak,value)
        drawdown=max(drawdown,1-value/peak)
        worst_intrabar=max(worst_intrabar,1-worst/peak)
        daily[(end-1)//86400]=value
        curve.append((end,value))
    values=[c.equity]+list(daily.values())
    returns=[b/a-1 for a,b in zip(values,values[1:])]
    days=(bars[-1]['t']+900-start)/86400
    net=sum(t['net_pnl'] for t in trades)
    std=statistics.stdev(returns) if len(returns)>1 else 0
    result=dict(report(trades)['all'],return_pct=100*net/c.equity,end_equity=c.equity+net,
        max_drawdown_pct=100*drawdown,adverse_mark_drawdown_pct=100*worst_intrabar,
        sharpe_daily=statistics.mean(returns)/std*math.sqrt(365) if std else None,
        annualized_return_pct=100*((1+net/c.equity)**(365/days)-1),
        exposure_pct=100*active/len(curve) if curve else 0,
        fees=sum(t['quantity']*(t['entry']+t['exit'])*c.fee for t in trades),
        monthly={},sides={side:report([t for t in trades if t['side']==side])['all'] for side in ('long','short')})
    previous=c.equity
    for day,value in daily.items():
        month=datetime.fromtimestamp(day*86400,timezone.utc).strftime('%Y-%m')
        result['monthly'].setdefault(month,{'start':previous})
        result['monthly'][month]['end']=value
        previous=value
    result['monthly']={m:100*(v['end']/v['start']-1) for m,v in result['monthly'].items()}
    return result,curve,returns


def bootstrap(returns):
    rng=random.Random(20261028); means=[]; n=len(returns)
    for _ in range(1000):
        sample=[]
        while len(sample)<n:
            begin=rng.randrange(n)
            sample.extend(returns[(begin+j)%n] for j in range(14))
        means.append(statistics.mean(sample[:n]))
    means.sort()
    return dict(method='circular 14-day block bootstrap, 1000 draws; not selection-adjusted',
                daily_mean_return_95pct=[means[24],means[974]])


def main():
    p=argparse.ArgumentParser(); p.add_argument('--stage',choices=['develop','final'],required=True); args=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    configs=hypotheses(); rows=load(DATA)
    if args.stage=='develop':
        # Holdout is not featured or simulated in development.
        rows=[b for b in rows if b['t']<PERIODS['validation'][1]]
        freeze=dict(split=PERIODS,hypotheses={n:dict(mode=m,config=asdict(c)) for n,(m,c) in configs.items()},
                    selection='train and validation each >=20 trades and positive net return; maximize minimum return/drawdown ratio; otherwise cash',
                    data_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest(),
                    engine_sha256=hashlib.sha256(Path('pullback.py').read_bytes()).hexdigest(),
                    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
        dump(OUT/'experiment_plan.json',freeze)
        full=features(rows,Config()); times=[b['t'] for b in full]; table={}
        for name,(mode,c) in configs.items():
            table[name]={}
            for period in ('train','validation'):
                start,end=PERIODS[period]; bars=full[:bisect.bisect_left(times,end)]
                trades,audit=simulate(bars,name,mode,c,start)
                metric,_,_=metrics(trades,bars,c,start)
                metric['rejections']=dict(Counter(e['status'] for e in audit))
                table[name][period]=metric
                dump(OUT/f'{name}_{period}_trades.json',trades)
            print(name,[(k,round(v['return_pct'],2),round(v['max_drawdown_pct'],2),v['trades']) for k,v in table[name].items()],flush=True)
        eligible=[n for n,v in table.items() if all(v[p]['trades']>=20 and v[p]['return_pct']>0 for p in ('train','validation'))]
        rank=lambda n:min(table[n][p]['return_pct']/max(.1,table[n][p]['max_drawdown_pct']) for p in ('train','validation'))
        selected=max(eligible,key=rank) if eligible else None
        dump(OUT/'development.json',table)
        dump(OUT/'selection.json',dict(selected=selected,eligible=sorted(eligible,key=rank,reverse=True),
              diagnostic_best_validation=max((n for n in table if all(table[n][p]['trades']>=20 for p in ('train','validation'))),key=lambda n:table[n]['validation']['return_pct']),
              plan_sha256=hashlib.sha256((OUT/'experiment_plan.json').read_bytes()).hexdigest()))
        print('SELECTION',selected)
    else:
        selection=json.loads((OUT/'selection.json').read_text())
        plan=json.loads((OUT/'experiment_plan.json').read_text())
        assert selection['plan_sha256']==hashlib.sha256((OUT/'experiment_plan.json').read_bytes()).hexdigest()
        assert plan['data_sha256']==hashlib.sha256(DATA.read_bytes()).hexdigest()
        assert plan['engine_sha256']==hashlib.sha256(Path('pullback.py').read_bytes()).hexdigest()
        # A diagnostic candidate is evaluated even when the deployment choice is cash.
        chosen=selection['selected'] or selection['diagnostic_best_validation']
        mode=plan['hypotheses'][chosen]['mode']; c=Config(**plan['hypotheses'][chosen]['config'])
        dump(OUT/'candidate_config.json',dict(name=chosen,mode=mode,config=asdict(c)))
        start,end=PERIODS['holdout']; full=features(rows,Config()); output={}
        for name in dict.fromkeys(['baseline','rsi','volume','rsi_volume',chosen]):
            spec=plan['hypotheses'][name]; cfg=Config(**spec['config'])
            trades,audit=simulate(full,name,spec['mode'],cfg,start)
            m,curve,returns=metrics(trades,full,cfg,start); m['uncertainty']=bootstrap(returns)
            output[name]=m
            dump(OUT/f'{name}_holdout_trades.json',trades)
            dump(OUT/f'{name}_holdout_signals.json',audit)
            with (OUT/f'{name}_holdout_equity.csv').open('w',newline='') as f:
                w=csv.writer(f); w.writerow(['close_time_utc_seconds','equity']); w.writerows(curve)
        stresses={}
        for label,fee,slip in [('normal',c.fee,c.slippage),('moderate',c.fee*1.5,c.slippage*2),('severe',c.fee*2,c.slippage*3)]:
            cfg=replace(c,fee=fee,slippage=slip)
            trades,_=simulate(full,chosen,mode,cfg,start)
            stresses[label]=metrics(trades,full,cfg,start)[0]
        b=[b for b in rows if b['t']>=start]; initial=b[0]['open']*(1+c.slippage)
        qty=c.equity/(initial*(1+c.fee)); exit=b[-1]['close']*(1-c.slippage)
        bh_return=100*(qty*exit*(1-c.fee)/c.equity-1)
        peak=c.equity; dd=0
        for x in b:
            value=qty*x['close']*(1-c.fee); peak=max(peak,value); dd=max(dd,1-value/peak)
        dump(OUT/'holdout.json',dict(selection=selection,candidate=chosen,results=output,stress=stresses,
            buy_hold=dict(return_pct=bh_return,max_drawdown_pct=100*dd),
            funding_disabled=True,holdout_used_once=True))
        print(json.dumps({n:{k:v for k,v in r.items() if k in ('trades','return_pct','max_drawdown_pct','win_rate','profit_factor','sharpe_daily')} for n,r in output.items()},indent=2))
        print('BUY HOLD',bh_return,'STRESS',[(n,m['return_pct']) for n,m in stresses.items()])


if __name__=='__main__':main()
