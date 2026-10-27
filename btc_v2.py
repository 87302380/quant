"""BTC-only research: causal dynamic exits and monthly past-only selection.

Run: python btc_v2.py
This is research replay on previously examined data, not a new holdout.
"""
import bisect
import argparse
import csv
import hashlib
import json
import math
from collections import deque
from dataclasses import dataclass, asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from pullback import Config, load, aggregate, indicators, smooth, round_step, stats
from research import DATA, ts

OUT=Path('results/btc_v2')


@dataclass(frozen=True)
class Strategy:
    name: str
    family: str
    short: bool = False
    stop_atr: float = 3
    trail_atr: float = 3
    daily_filter: bool = False
    cooldown_hours: int = 24
    pause_losses: int = 0
    fast: int = 25
    slow: int = 99
    min_adx: float = 0
    min_efficiency: float = 0
    breakeven_r: float = 0
    signal_seconds: int = 14400
    trail_on_regime: bool = False
    min_volume_ratio: float = 0
    target_r: float = 0
    max_adds: int = 0
    add_step_r: float = 1
    long: bool = True


def universe():
    result=[]
    for family in ('trend','breakout','reversion'):
        for short in (False,True):
            for variant in ('base','daily','pause'):
                name=f'{family}_{"both" if short else "long"}_{variant}'
                result.append(Strategy(name,family,short,stop_atr=2.5 if family=='reversion' else 3,
                    trail_atr=3,daily_filter=variant=='daily',pause_losses=3 if variant=='pause' else 0))
    return result


def prepare(rows):
    h4=indicators(aggregate(rows,14400),Config())
    daily=indicators(aggregate(rows,86400),Config())
    for group in (h4,daily):
        closes=[b['close'] for b in group]
        gains=[0]+[max(b-a,0) for a,b in zip(closes,closes[1:])]
        losses=[0]+[max(a-b,0) for a,b in zip(closes,closes[1:])]
        for b,g,l in zip(group,smooth(gains,2),smooth(losses,2)):
            b['rsi2']=100*g/(g+l) if g is not None and g+l else 50
        for b,v in zip(group,smooth(closes,50,2/51)): b['ema50']=v
        for n in (13,55,200):
            for b,v in zip(group,smooth(closes,n,2/(n+1))): b[f'ema{n}']=v
        for i,b in enumerate(group):
            travel=sum(abs(closes[j]-closes[j-1]) for j in range(max(1,i-19),i+1))
            b['efficiency']=abs(closes[i]-closes[i-20])/travel if i>=20 and travel else 0
    history=deque(maxlen=120)
    j=-1
    for b in h4:
        while j+1<len(daily) and daily[j+1]['t']+86400<=b['t']+14400:j+=1
        b['daily']=daily[j] if j>=0 else {}
        b['channel_high']=max(x['high'] for x in history) if len(history)==120 else None
        b['channel_low']=min(x['low'] for x in history) if len(history)==120 else None
        b['previous_high']=history[-1]['high'] if history else None
        b['previous_low']=history[-1]['low'] if history else None
        history.append(b)
    return h4


def direction(h,s):
    fast,slow=h.get(f'ema{s.fast}'),h.get(f'ema{s.slow}')
    if not slow or not fast or not h.get('atr'): return 0
    daily=h['daily']
    trend=1 if fast>slow and h['close']>slow else -1 if fast<slow and h['close']<slow else 0
    if s.family in ('resume','squeeze','dip','micro'):
        trend=h.get('signals',{}).get(s.family,0)
    if s.family=='breakout':
        trend=1 if h['channel_high'] and h['close']>h['channel_high'] else -1 if h['channel_low'] and h['close']<h['channel_low'] else 0
    if s.family=='reversion':
        trend=1 if h['rsi2']<10 and h['close']>h['ema99'] else -1 if h['rsi2']>90 and h['close']<h['ema99'] else 0
    if s.daily_filter and trend:
        if not daily.get('ema50') or trend*(daily['close']-daily['ema50'])<=0:return 0
    if s.min_adx and (h.get('adx') or 0)<s.min_adx:return 0
    if s.min_efficiency and h.get('efficiency',0)<s.min_efficiency:return 0
    if s.min_volume_ratio and h.get('volume_ratio',0)<s.min_volume_ratio:return 0
    return trend if (trend==1 and s.long) or (trend==-1 and s.short) else 0


def run(rows,h4,s,c=Config(),start=None,end=None,schedule=None,bar_seconds=900):
    """Stops checked before close-derived trail changes; signals execute next open."""
    start=rows[0]['t'] if start is None else start
    end=rows[-1]['t']+bar_seconds if end is None else end
    cash=c.equity; position=None; pending=None; pending_add=False; last_h=None
    trades=[]; curve=[]; j=-1; cooldown=0; losses=0; peak=c.equity
    dd=0; day_equity={}; fees=0; active=0
    def close_position(b,raw,reason):
        nonlocal position,pending,cash,fees,losses,cooldown
        p=position;fill=raw*(1-p['direction']*c.slippage)
        exit_fee=p['quantity']*fill*c.fee
        pnl=p['quantity']*p['direction']*(fill-p['entry'])-exit_fee-p['entry_fee']
        cash+=pnl+p['entry_fee'];fees+=exit_fee
        trades.append(dict(p,exit=fill,exit_time=b['t']+bar_seconds,net_pnl=pnl,exit_reason=reason,equity=cash))
        losses=losses+1 if pnl<0 else 0
        cooldown=b['t']+p['cooldown_hours']*3600
        if p['pause_losses'] and losses>=p['pause_losses']:
            cooldown=max(cooldown,b['t']+7*86400);losses=0
        position=None;pending=None
    for b in rows:
        if b['t']>=end:break
        while j+1<len(h4) and h4[j+1]['t']+s.signal_seconds<=b['t']:j+=1
        h=h4[j] if j>=0 else None
        if b['t']<start:continue
        current=schedule.get(datetime.fromtimestamp(b['t'],timezone.utc).strftime('%Y-%m')) if schedule is not None else s
        switched=position is not None and (current is None or current.name!=position['strategy'])
        if position and pending_add and pending!='exit' and not switched:
            p=position;d=p['direction'];fill=b['open']*(1+d*c.slippage)
            sf=p['stop']*(1-d*c.slippage)
            marked=cash+p['quantity']*(d*(b['open']-p['entry'])-c.fee*b['open'])
            # All units share one stop. Risk is measured against campaign entry equity.
            existing_risk=p['quantity']*(d*(p['entry']-sf)+c.fee*sf)+p['entry_fee']
            unit_loss=d*(fill-sf)+c.fee*(fill+sf)
            room=(marked-p['quantity']*fill)/(fill*(1+c.fee))
            risk_room=marked*c.risk-existing_risk
            amount=round_step(max(0,min(room,risk_room/max(unit_loss,1e-12))),c.contract_value*c.lot_size)
            if amount>=c.contract_value*c.min_contracts and d*(fill-p['stop'])>0:
                fee=amount*fill*c.fee;cash-=fee;fees+=fee
                old_qty=p['quantity'];p['quantity']+=amount
                p['entry']=(old_qty*p['entry']+amount*fill)/p['quantity']
                p['entry_fee']+=fee;p['adds']+=1
                after_risk=p['quantity']*(d*(p['entry']-sf)+c.fee*sf)+p['entry_fee']
                p['units'].append(dict(time=b['t'],price=fill,quantity=amount,fee=fee,
                    planned_campaign_loss=after_risk,risk_budget=marked*c.risk,
                    gross_notional=p['quantity']*fill,marked_equity_before_fee=marked))
        pending_add=False
        exit_reason=None; raw_exit=None
        if position and (switched or pending=='exit'):
            raw_exit=b['open'];exit_reason='rotation' if switched else 'signal'
        if position and raw_exit is None:
            d=position['direction'];stop=position['stop']
            if (b['low']<=stop if d==1 else b['high']>=stop):
                raw_exit=min(stop,b['open']) if d==1 else max(stop,b['open']);exit_reason='stop'
            elif position.get('target') and (b['high']>=position['target'] if d==1 else b['low']<=position['target']):
                raw_exit=position['target'];exit_reason='target'
        if position and raw_exit is None and (b['t']+bar_seconds>=end or b['t']-position['entry_time']>=90*86400):
            raw_exit=b['close'];exit_reason='end' if b['t']+bar_seconds>=end else 'time'
        if position and raw_exit is not None:
            close_position(b,raw_exit,exit_reason)
        # At most one new order per 4h signal; avoid same-bar exit/reentry.
        if not position and pending not in (None,'exit') and raw_exit is None and current is not None and b['t']>=cooldown and pending[3]==current.name:
            d,dist,target,_=pending
            entry=b['open']*(1+d*c.slippage)
            stop=round_step(entry-d*dist,c.tick_size,up=d==-1)
            stop_fill=stop*(1-d*c.slippage)
            loss=d*(entry-stop_fill)+c.fee*(entry+stop_fill)
            rr_ok=True
            fixed_target=entry+d*current.target_r*dist if current.target_r else None
            if fixed_target:
                fixed_target=round_step(fixed_target,c.tick_size,up=d==-1)
                target_fill=fixed_target*(1-d*c.slippage)
                reward=d*(target_fill-entry)-c.fee*(entry+target_fill)
                if reward/max(loss,1e-12)<c.min_rr:
                    rr_ok=False
            qty=round_step(min(cash*c.risk/max(loss,1e-12),cash/(entry*(1+c.fee))),c.contract_value*c.lot_size)
            if cash>0 and qty>=c.contract_value*c.min_contracts and d*(entry-stop)>0 and rr_ok:
                fee=qty*entry*c.fee;cash-=fee;fees+=fee
                position=dict(strategy=current.name,direction=d,side='long' if d==1 else 'short',score=0,
                    entry=entry,entry_time=b['t'],quantity=qty,entry_fee=fee,stop=stop,initial_stop=stop,
                    target=fixed_target if fixed_target else entry+d*3*dist if target else None,planned_risk=qty*loss,
                    best_close=entry,cooldown_hours=current.cooldown_hours,pause_losses=current.pause_losses,
                    first_entry=entry,first_stop_distance=abs(entry-stop),adds=0,
                    units=[dict(time=b['t'],price=entry,quantity=qty,fee=fee)])
                # New positions are exposed to this entry candle's entire range.
                if b['low']<=stop if d==1 else b['high']>=stop:
                    close_position(b,stop,'stop')
                elif position['target'] and (b['high']>=position['target'] if d==1 else b['low']<=position['target']):
                    close_position(b,position['target'],'target')
                elif b['t']+bar_seconds>=end:
                    close_position(b,b['close'],'end')
        pending=None
        # Update only after the 4h candle is fully closed; applies from next bar.
        while j+1<len(h4) and h4[j+1]['t']+s.signal_seconds<=b['t']+bar_seconds:j+=1
        h=h4[j] if j>=0 else None
        fresh=h is not None and h['t']!=last_h
        if fresh:
            last_h=h['t']
            if current:
                d=direction(h,current)
                if position:
                    p=position;pd=p['direction']
                    if current.family=='reversion':
                        if (h['rsi2']>60 if pd==1 else h['rsi2']<40):pending='exit'
                    elif current.family in ('trend','resume','squeeze','dip','micro'):
                        management=h.get('regime',h)
                        if pd*(management[f'ema{current.fast}']-management[f'ema{current.slow}'])<=0:pending='exit'
                    if current.family!='reversion':
                        p['best_close']=max(p['best_close'],h['close']) if pd==1 else min(p['best_close'],h['close'])
                        trail_atr=h.get('management_atr',h.get('regime',h)['atr']) if current.trail_on_regime else h['atr']
                        trail=p['best_close']-pd*current.trail_atr*trail_atr
                        trail=round_step(trail,c.tick_size,up=pd==-1)
                        # Trailing stop can lock gains but cannot be beyond the current close.
                        if pd*(h['close']-trail)>0:
                            p['stop']=max(p['stop'],trail) if pd==1 else min(p['stop'],trail)
                        if current.breakeven_r and pd*(h['close']-p['entry'])>=current.breakeven_r*abs(p['entry']-p['initial_stop']):
                            raw=p['entry']*(pd+c.fee)/(pd-c.fee)/(1-pd*c.slippage)
                            lock=round_step(raw,c.tick_size,up=pd==1)
                            if pd*(h['close']-lock)>0:
                                p['stop']=max(p['stop'],lock) if pd==1 else min(p['stop'],lock)
                    if current.max_adds and p['adds']<current.max_adds and pending!='exit':
                        progress=pd*(h['close']-p['first_entry'])
                        boundary=h.get('previous_high' if pd==1 else 'previous_low')
                        if (d==pd and boundary is not None and pd*(h['close']-boundary)>0 and
                                progress>=(p['adds']+1)*current.add_step_r*p['first_stop_distance']):
                            pending_add=True
                elif d and b['t']+bar_seconds>=cooldown:
                    pending=(d,current.stop_atr*h['atr'],current.family=='reversion',current.name)
        value=cash
        if position:
            active+=1;p=position
            value+=p['quantity']*(p['direction']*(b['close']-p['entry'])-c.fee*b['close'])
        peak=max(peak,value);dd=max(dd,1-value/peak)
        curve.append((b['t']+bar_seconds,value));day_equity[(b['t']+bar_seconds-1)//86400]=value
    if not curve:raise ValueError('empty evaluation period')
    returns=[];prev=c.equity
    for value in day_equity.values():returns.append(value/prev-1);prev=value
    import statistics
    std=statistics.stdev(returns) if len(returns)>1 else 0
    m=dict(stats(trades),return_pct=100*(curve[-1][1]/c.equity-1),max_drawdown_pct=100*dd,
           fees=fees,sharpe_daily=statistics.mean(returns)/std*math.sqrt(365) if std else None,
           exposure_pct=100*active/len(curve),end_equity=curve[-1][1])
    return m,trades,curve


def write_json(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False),encoding='utf-8')


def months(start,end):
    d=datetime.fromtimestamp(start,timezone.utc)
    d=d.replace(day=1,hour=0,minute=0,second=0)
    while d.timestamp()<end:
        nxt=d.replace(year=d.year+(d.month==12),month=d.month%12+1)
        yield d.strftime('%Y-%m'),int(d.timestamp()),min(end,int(nxt.timestamp()))
        d=nxt


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['research','single'],default='research')
    parser.add_argument('--strategy',default='trend_both_pause',choices=[s.name for s in universe()])
    parser.add_argument('--start',help='UTC date, inclusive e.g. 2025-01-01')
    parser.add_argument('--end',help='UTC date, exclusive')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    rows=load(DATA);h4=prepare(rows);specs=universe();c=Config()
    if args.mode=='single':
        s=next(s for s in specs if s.name==args.strategy)
        m,trades,curve=run(rows,h4,s,c,start=ts(args.start) if args.start else None,end=ts(args.end) if args.end else None)
        write_json(OUT/f'{s.name}_single_metrics.json',m)
        write_json(OUT/f'{s.name}_single_trades.json',trades)
        print(json.dumps(m,indent=2));return
    plan=dict(universe=[asdict(s) for s in specs],data_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        known_data=True,funding=0,selection='monthly: trailing 365 days, >=8 trades, positive return, PF>=1.1, drawdown<=20%; maximize return/max(drawdown,1); else cash',
        caveat='All BTC 2024-2026 dates were examined previously; rolling replay is not independent validation.')
    write_json(OUT/'plan.json',plan)
    table={}
    periods={'2024':(ts('2024-01-01'),ts('2025-01-01')),'2025':(ts('2025-01-01'),ts('2026-01-01')),
             '2026':(ts('2026-01-01'),rows[-1]['t']+900),'full':(rows[0]['t'],rows[-1]['t']+900)}
    for s in specs:
        table[s.name]={}
        for label,(begin,end) in periods.items():
            m,t,curve=run(rows,h4,s,c,begin,end)
            table[s.name][label]=m
            if label=='full':write_json(OUT/f'{s.name}_trades.json',t)
        print(s.name,[(p,round(m['return_pct'],2),round(m['max_drawdown_pct'],2),m['trades']) for p,m in table[s.name].items()],flush=True)
    write_json(OUT/'static_results.json',table)
    # Walk forward is a replay of a fixed policy: ranking uses only data before each month.
    schedule={};decisions=[]
    for month,begin,end in months(ts('2025-01-01'),rows[-1]['t']+900):
        ranked=[]
        for s in specs:
            m,_,_=run(rows,h4,s,c,begin-365*86400,begin)
            if m['trades']>=8 and m['return_pct']>0 and (m['profit_factor'] or 0)>=1.1 and m['max_drawdown_pct']<=20:
                ranked.append((m['return_pct']/max(1,m['max_drawdown_pct']),s,m))
        winner=max(ranked,key=lambda x:x[0]) if ranked else None
        schedule[month]=winner[1] if winner else None
        decisions.append(dict(month=month,training_end_exclusive=begin,choice=winner[1].name if winner else 'cash',
                              training_metrics=winner[2] if winner else None))
        print('rolling',month,decisions[-1]['choice'],flush=True)
    m,trades,curve=run(rows,h4,specs[0],c,ts('2025-01-01'),rows[-1]['t']+900,schedule)
    write_json(OUT/'rolling_decisions.json',decisions)
    write_json(OUT/'rolling_trades.json',trades)
    write_json(OUT/'rolling_metrics.json',m)
    with (OUT/'rolling_equity.csv').open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['timestamp','equity']);w.writerows(curve)
    stress={}
    for label,fee,slip in [('normal',.0005,.0002),('double',.001,.0004)]:
        stress[label]=run(rows,h4,specs[0],replace(c,fee=fee,slippage=slip),ts('2025-01-01'),rows[-1]['t']+900,schedule)[0]
    write_json(OUT/'rolling_stress.json',stress)
    print('ROLLING',json.dumps(m),flush=True)


if __name__=='__main__':main()
