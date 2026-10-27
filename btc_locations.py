"""4h market regime, 4h/1h locations, 5m execution triggers. BTC research only."""
import hashlib
import json
from collections import Counter
from dataclasses import dataclass,asdict,replace
from pathlib import Path
from btc_5m import DATA,resample
from pullback import Config,load,indicators,round_step,stats
from research import ts

OUT=Path('results/btc_locations')


@dataclass(frozen=True)
class Rules:
    name:str
    regime:str='trend'
    short:bool=True
    exit:str='split'
    only4h:bool=False
    align1h:bool=False
    momentum:bool=False
    min_net_rr:float=.5
    stop_floor4h:float=0
    cooldown_hours:int=1
    max_cost_fraction:float=0
    runner_atr4h:float=1.5


def annotate(rows,seconds):
    bars=indicators(resample(rows,seconds),Config())
    lows=[];highs=[]
    for i,b in enumerate(bars):
        p=i-2
        if p>=2:
            window=bars[p-2:i+1]
            if bars[p]['low']==min(x['low'] for x in window):lows.append((bars[p]['low'],b['t']+seconds))
            if bars[p]['high']==max(x['high'] for x in window):highs.append((bars[p]['high'],b['t']+seconds))
        b['lows']=list(lows[-5:]);b['highs']=list(highs[-5:])
        b['previous_rsi']=bars[i-1]['rsi'] if i else None
    return bars


def prepare(rows):
    base=indicators(rows,Config());h1=annotate(rows,3600);h4=annotate(rows,14400)
    days=resample(rows,86400);j=k=l=-1
    for b in base:
        end=b['t']+300
        while j+1<len(h1) and h1[j+1]['t']+3600<=end:j+=1
        while k+1<len(h4) and h4[k+1]['t']+14400<=end:k+=1
        while l+1<len(days) and days[l+1]['t']+86400<=end:l+=1
        b['h1']=h1[j] if j>=0 else {};b['h4']=h4[k] if k>=0 else {}
        b['day']=days[l] if l>=0 else {}
    return base


def directions(b,r):
    h=b['h4']
    if not h.get('ema99') or not h.get('atr'):return []
    d=1 if h['ema25']>h['ema99'] and h['close']>h['ema99'] else -1 if h['ema25']<h['ema99'] and h['close']<h['ema99'] else 0
    adx=h.get('adx') or 0
    if r.regime=='range':allowed=[1,-1] if adx<20 else []
    elif r.regime=='hybrid':
        allowed=[d] if adx>=25 and d else [1,-1] if adx<20 and abs(h['ema25']-h['ema99'])<h['atr'] else []
    else:allowed=[d] if d else []
    return [d for d in allowed if d==1 or r.short]


def levels(b,d,r,opposite=False):
    h=b['h1'];f=b['h4'];day=b['day'];now=b['t']+300
    low=(d==1) != opposite;kind='lows' if low else 'highs'
    result=[(p,'4h_pivot') for p,confirmed in f.get(kind,[]) if now-confirmed<=20*86400]
    if day:result.append((day['low' if low else 'high'],'previous_day'))
    if not r.only4h:result.extend((p,'1h_pivot') for p,confirmed in h.get(kind,[]) if now-confirmed<=5*86400)
    if not opposite:
        result.append((f['ema25'],'4h_ema25'))
        if not r.only4h:result.extend([(h['ema25'],'1h_ema25'),(h['ema99'],'1h_ema99')])
    return [(p,label) for p,label in result if p is not None]


def signals(bars,r):
    setups={1:None,-1:None}
    for i,b in enumerate(bars):
        h=b['h1'];f=b['h4']
        if not h.get('ema99') or not f.get('ema99') or not b.get('atr'):continue
        allowed=directions(b,r)
        for d in (1,-1):
            if d not in allowed:
                setups[d]=None;continue
            if r.align1h and d*(h['ema25']-h['ema99'])<=0:continue
            if r.momentum and (h.get('previous_rsi') is None or d*(h['rsi']-h['previous_rsi'])<=0 or b['volume_ratio']<1):continue
            s=setups[d];tol=.2*h['atr']
            if s and (i-s['start']>12 or (b['low']<s['level']-.75*s['atr1h'] if d==1 else b['high']>s['level']+.75*s['atr1h'])):
                s=setups[d]=None
            if s is None:
                candidates=[(p,label) for p,label in levels(b,d,r) if b['low']<=p+tol and b['high']>=p-tol]
                if not candidates:continue
                # Prefer larger timeframe sources when several locations overlap.
                p,label=min(candidates,key=lambda x:(0 if x[1].startswith('4h') or x[1]=='previous_day' else 1,abs(x[0]-b['close'])))
                s=setups[d]=dict(start=i,level=p,source=label,atr1h=h['atr'],low=b['low'],high=b['high'])
            s['low']=min(s['low'],b['low']);s['high']=max(s['high'],b['high'])
            if i<=s['start']:continue
            # 5m has no independent market-regime or support/resistance role.
            if not (d*(b['close']-s['level'])>0 and d*(b['close']-b['open'])>0 and
                    d*(b['close']-bars[i-1]['high' if d==1 else 'low'])>0):continue
            stop=min(s['level']-.35*s['atr1h'],s['low']-.15*s['atr1h']) if d==1 else max(s['level']+.35*s['atr1h'],s['high']+.15*s['atr1h'])
            stop=min(stop,b['close']-.5*s['atr1h']) if d==1 else max(stop,b['close']+.5*s['atr1h'])
            targets=[(p,label) for p,label in levels(b,d,r,True) if d*(p-b['close'])>.1*h['atr']]
            if targets:
                target,label=min(targets,key=lambda x:abs(x[0]-b['close']))
                yield dict(index=i,direction=d,stop=stop,target=target,level=s['level'],source=s['source'],
                    target_source=label,adx4h=f['adx'],rsi1h=h['rsi'],rsi5m=b['rsi'],volume_ratio=b['volume_ratio'],
                    atr1h=s['atr1h'],regime=r.regime,setup_started=bars[s['start']]['t'])
            setups[d]=None


def simulate(bars,r,c=Config(),start=None,end=None,events=None):
    start=bars[0]['t'] if start is None else start;end=bars[-1]['t']+300 if end is None else end
    last_index=next((i-1 for i,b in enumerate(bars) if b['t']>=end),len(bars)-1)
    equity=c.equity;busy=-1;cool_until=0;trades=[];audit=Counter();curve=[];cursor=0
    for ev in events if events is not None else signals(bars,r):
        i=ev['index']+1;d=ev['direction']
        if i>last_index:continue
        if bars[i]['t']<start:continue
        if i<=busy or bars[i]['t']<cool_until:audit['busy_or_cooldown']+=1;continue
        entry=bars[i]['open']*(1+d*c.slippage)
        f=bars[i-1]['h4']
        management='runner' if r.exit=='runner' or (r.exit=='adaptive' and (f.get('adx') or 0)>=25 and d*((f.get('plus_di') or 0)-(f.get('minus_di') or 0))>0) else 'cap' if r.exit=='adaptive' else r.exit
        stop=round_step(ev['stop'],c.tick_size,up=d==-1)
        if r.stop_floor4h:
            floor=r.stop_floor4h*bars[i-1]['h4']['atr']
            stop=min(stop,entry-floor) if d==1 else max(stop,entry+floor)
            stop=round_step(stop,c.tick_size,up=d==-1)
        target=round_step(ev['target'],c.tick_size,up=d==-1)
        distance=d*(entry-stop)
        if distance<=0 or (not r.stop_floor4h and distance>2*ev['atr1h']):audit['invalid_or_late_stop']+=1;continue
        if management=='cap':target=min(target,entry+distance) if d==1 else max(target,entry-distance)
        target=round_step(target,c.tick_size,up=d==-1)
        sf=stop*(1-d*c.slippage);tf=target*(1-d*c.slippage)
        loss=d*(entry-sf)+c.fee*(entry+sf);reward=d*(tf-entry)-c.fee*(entry+tf)
        cost=entry*c.slippage+stop*c.slippage+c.fee*(entry+sf)
        if r.max_cost_fraction and cost/loss>r.max_cost_fraction:audit['cost_fraction']+=1;continue
        if reward/loss<r.min_net_rr:audit['net_rr']+=1;continue
        qty=round_step(min(equity*c.risk/loss,equity/(entry*(1+c.fee))),c.contract_value*c.lot_size)
        if qty<c.contract_value*c.min_contracts:audit['size']+=1;continue
        before=equity;cash=equity-qty*entry*c.fee;remaining=qty;fees=qty*entry*c.fee
        take=min(target,entry+distance) if d==1 else max(target,entry-distance)
        take=round_step(take,c.tick_size,up=d==-1)
        partial=False;parts=[];pending_exit=False;best=entry;last_h=None
        while cursor<i:
            if bars[cursor]['t']>=start:curve.append((bars[cursor]['t']+300,equity))
            cursor+=1
        last=min(last_index,i+(288 if r.regime=='range' else 4032)-1)
        for j in range(i,last+1):
            b=bars[j];raw=None;why=None
            stop_hit=b['low']<=stop if d==1 else b['high']>=stop
            if pending_exit:raw=b['open'];why='higher_timeframe_exit'
            elif stop_hit:raw=min(stop,b['open']) if d==1 else max(stop,b['open']);why='stop'
            elif management not in ('split','runner') and (b['high']>=target if d==1 else b['low']<=target):raw=target;why='higher_target'
            if raw is None and management=='split' and not partial and (b['high']>=take if d==1 else b['low']<=take):
                amount=round_step(qty/2,c.contract_value*c.lot_size)
                if amount>=c.contract_value*c.min_contracts and remaining-amount>=c.contract_value*c.min_contracts:
                    fill=take*(1-d*c.slippage);fee=amount*fill*c.fee
                    cash+=amount*d*(fill-entry)-fee;fees+=fee;remaining-=amount;partial=True
                    parts.append(dict(time=b['t']+300,price=fill,quantity=amount,reason='partial_1R'))
                else:raw=target;why='target_small_size'
            if raw is None and j==last:raw=b['close'];why='time_or_end'
            if raw is not None:
                fill=raw*(1-d*c.slippage);fee=remaining*fill*c.fee
                cash+=remaining*d*(fill-entry)-fee;fees+=fee
                parts.append(dict(time=b['t']+300,price=fill,quantity=remaining,reason=why))
                equity=cash;curve.append((b['t']+300,equity));cursor=j+1
                trade=dict(ev,side='long' if d==1 else 'short',entry=entry,entry_time=bars[i]['t'],exit_time=b['t']+300,
                    quantity=qty,initial_stop=ev['stop'],target=ev['target'],planned_risk=qty*loss,
                    net_pnl=equity-before,fees=fees,parts=parts,exit_reason=why,equity=equity,management=management)
                trades.append(trade);busy=j;cool_until=b['t']+300+r.cooldown_hours*3600;audit['filled']+=1
                break
            h=b['h1'];f=b['h4']
            if management in ('split','runner') and h['t']!=last_h:
                last_h=h['t'];best=max(best,h['close']) if d==1 else min(best,h['close'])
                trail=round_step(best-d*(r.runner_atr4h*f['atr'] if management=='runner' else 2*h['atr']),c.tick_size,up=d==-1)
                if d*(b['close']-trail)>0:stop=max(stop,trail) if d==1 else min(stop,trail)
            if partial:
                be=entry*(d+c.fee)/(d-c.fee)/(1-d*c.slippage)
                lock=round_step(be,c.tick_size,up=d==1)
                if d*(b['close']-lock)>0:stop=max(stop,lock) if d==1 else min(stop,lock)
            pending_exit=d*(f['ema25']-f['ema99'])<=0 if r.regime!='range' else (f['adx'] or 0)>=25
            value=cash+remaining*(d*(b['close']-entry)-c.fee*b['close'])
            curve.append((b['t']+300,value));cursor=j+1
    while cursor<=last_index:
        if bars[cursor]['t']>=start:curve.append((bars[cursor]['t']+300,equity))
        cursor+=1
    peak=c.equity;dd=0
    for _,v in curve:peak=max(peak,v);dd=max(dd,1-v/peak)
    m=dict(stats(trades),return_pct=100*(equity/c.equity-1),max_drawdown_pct=100*dd,
        fees=sum(t['fees'] for t in trades),end_equity=equity,rejections=dict(audit))
    return m,trades,curve


def universe():
    result=[]
    for regime,shorts in [('trend',(False,True)),('range',(True,)),('hybrid',(True,))]:
        for short in shorts:
            for exit in ('level','cap','split'):
                result.append(Rules(f'{regime}_{"both" if short else "long"}_{exit}',regime,short,exit))
    result.extend([Rules('trend_both_split_4honly',only4h=True),Rules('trend_both_split_align1h',align1h=True),
                   Rules('trend_both_split_momentum',momentum=True)])
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True);rows=load(DATA,step_seconds=300);bars=prepare(rows);specs=universe();c=Config()
    write=lambda p,o:p.write_text(json.dumps(o,indent=2,allow_nan=False),encoding='utf-8')
    write(OUT/'plan.json',dict(known_history=True,rules=[asdict(r) for r in specs],risk=asdict(c),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),data_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest(),
        eligibility='2024 and 2025 each >=20 completed trades, positive return and PF>=1.1; maximize minimum return/drawdown'))
    table={};cache={}
    for r in specs:
        key=(r.regime,r.short,r.only4h,r.align1h,r.momentum)
        if key not in cache:cache[key]=list(signals(bars,r))
        events=cache[key];table[r.name]={}
        for period,start,end in [('2024',rows[0]['t'],ts('2025-01-01')),('2025',ts('2025-01-01'),ts('2026-01-01'))]:
            m,t,_=simulate(bars,r,c,start,end,events);table[r.name][period]=m
        print('DEVELOP',r.name,[(p,round(m['return_pct'],2),round((m['win_rate'] or 0)*100,1),m['trades']) for p,m in table[r.name].items()],flush=True)
    eligible=[r for r in specs if all(table[r.name][p]['trades']>=20 and table[r.name][p]['return_pct']>0 and (table[r.name][p]['profit_factor'] or 0)>=1.1 for p in ('2024','2025'))]
    rank=lambda r:min(table[r.name][p]['return_pct']/max(.1,table[r.name][p]['max_drawdown_pct']) for p in ('2024','2025'))
    chosen=max(eligible,key=rank) if eligible else None
    write(OUT/'selection.json',dict(selected=asdict(chosen) if chosen else None,eligible=[r.name for r in eligible]))
    stress={}
    for r in specs:
        events=cache[(r.regime,r.short,r.only4h,r.align1h,r.momentum)]
        for label,start in [('2026',ts('2026-01-01')),('full',rows[0]['t'])]:
            m,t,curve=simulate(bars,r,c,start=start,events=events);table[r.name][label]=m
            if label=='full':write(OUT/f'{r.name}_trades.json',t)
        stress[r.name]=simulate(bars,r,replace(c,fee=.001,slippage=.0004),events=events)[0]
        print('CONFIRM',r.name,round(table[r.name]['full']['return_pct'],2),flush=True)
    write(OUT/'results.json',table);write(OUT/'double_cost.json',stress)
    lines=['# 高周期支撑压力、5m入场研究','',
        '本轮按用户要求：市场方向仅由已收盘4h判断，位置仅取4h/1h已确认摆动点、前一日高低、4h EMA25、1h EMA25/99；5m只确认触及区域后收回并突破前一根高/低。',
        '', '摆动点左右各2根，右侧收盘后才可用；4h区域优先于1h。观察区域半径0.2倍1h ATR，设置最多60分钟；结构破坏或4h方向失效则取消。初始止损依高周期区域及触发极值，至少0.5倍1h ATR；入场距离止损超过2倍1h ATR拒绝。',
        '', '三种高周期市场模式：趋势方向、4h ADX<20的区间、ADX≥25趋势/ADX<20且EMA差小于ATR的混合。不是让5m自行判断趋势。',
        '', '退出：level到最近高周期对侧目标；cap至多1R全平；split在1R或更近高周期目标兑现一半，剩余按1h ATR移动退出与4h趋势失效退出。分批退出合并一笔完整交易统计。',
        '', '每笔计划风险最多1%，不加杠杆，名义金额不超过权益；单边手续费0.05%、滑点0.02%，资金费关闭。初始目标净RR至少0.5（用户短线偏好，未沿用原先1.5硬条件）。同根先止损；移动止损下根才生效。',
        '', '| 方案 | 总收益 | 胜率 | 回撤 | 笔数 | 2024 | 2025 | 2026 | 双倍成本 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for name,r in table.items():
        m=r['full'];lines.append(f'| {name} | {m["return_pct"]:.2f}% | {(m["win_rate"] or 0)*100:.2f}% | {m["max_drawdown_pct"]:.2f}% | {m["trades"]} | {r["2024"]["return_pct"]:.2f}% | {r["2025"]["return_pct"]:.2f}% | {r["2026"]["return_pct"]:.2f}% | {stress[name]["return_pct"]:.2f}% |')
    lines+=['',f'查看本轮2026结果前选中的候选：{chosen.name if chosen else "无合格方案"}。所有原始标的历史此前均已研究，不能称为全新独立留出。',
        '', '4h/1h更有效属于待验证假设，并非普遍定理。参考：[纽约联储关于支撑压力与订单的外汇研究](https://www.newyorkfed.org/research/staff_reports/sr125.html)，它支持研究反弹与突破两种情形，不证明BTC高周期一定有效。',
        '', '复现：`python btc_locations.py`。所有15个方案、分批成交、指标与高周期位置记录均保存在同目录。脚本不发送订单。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('COMPLETE',OUT/'REPORT.md')


if __name__=='__main__':main()
