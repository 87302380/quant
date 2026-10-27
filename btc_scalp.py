"""BTC scalp/range + breakout trend research with explicit maker fill assumptions."""
import json
import math
import hashlib
from dataclasses import dataclass,asdict,replace
from pathlib import Path
from btc_v4 import DATA,Config,load,entry_features,run as trend_run,Strategy,ts,write_json
from btc_v4_extension import micro_features
from pullback import smooth,round_step,stats

OUT=Path('results/btc_scalp')


@dataclass(frozen=True)
class Mode:
    name:str
    maker:bool=True
    short:bool=True
    target_atr:float=.75
    recovery:bool=False
    hybrid:bool=False
    max_hours:int=8
    adx_ceiling:float=25
    trend_align:bool=False
    entry_kind:str='rsi'
    stop_atr:float=1.5
    z_entry:float=1


def prepare(rows):
    hourly,_=entry_features(rows);bars=micro_features(rows,hourly)
    gains=[0]+[max(b['close']-a['close'],0) for a,b in zip(bars,bars[1:])]
    losses=[0]+[max(a['close']-b['close'],0) for a,b in zip(bars,bars[1:])]
    for b,g,l in zip(bars,smooth(gains,2),smooth(losses,2)):
        b['rsi2']=100*g/(g+l) if g is not None and g+l else 50
    j=-1
    for i,b in enumerate(bars):
        while j+1<len(hourly) and hourly[j+1]['t']+3600<=b['t']+900:j+=1
        h=hourly[j] if j>=0 else {}
        b['hour']=h
        recent=bars[max(0,i-19):i+1];avg=sum(x['close'] for x in recent)/len(recent)
        b['mean']=avg;b['sd']=math.sqrt(sum((x['close']-avg)**2 for x in recent)/len(recent))
    return bars


def simulate(bars,s,c=Config(risk=.0025),maker_fee=.0002,start=None,end=None,bar_seconds=900,decision_seconds=None,market_entry_target=False):
    decision_seconds=decision_seconds or bar_seconds
    start=bars[0]['t'] if start is None else start;end=bars[-1]['t']+bar_seconds if end is None else end
    cash=c.equity;position=None;order=None;pending_exit=False;trades=[];curve=[];fees=0;peak=cash;dd=0
    orders=filled=expired=0
    def close(b,raw,reason,fee_rate,slip):
        nonlocal cash,position,fees,pending_exit
        p=position;d=p['direction'];fill=raw*(1-d*slip);fee=p['qty']*fill*fee_rate
        pnl=p['qty']*d*(fill-p['entry'])-fee-p['entry_fee'];cash+=pnl+p['entry_fee'];fees+=fee
        trades.append(dict(p,exit=fill,exit_time=b['t']+bar_seconds,net_pnl=pnl,exit_reason=reason,equity=cash))
        position=None;pending_exit=False
    for i,b in enumerate(bars):
        if b['t']>=end:break
        if b['t']<start:continue
        h=b['hour'];old_position=position is not None;exited=False
        if position:
            p=position;d=p['direction'];stop=p['stop']
            stop_hit=b['low']<=stop if d==1 else b['high']>=stop
            tp_hit=p['target'] is not None and (b['high']>p['target']+c.tick_size if d==1 else b['low']<p['target']-c.tick_size)
            if pending_exit:
                close(b,b['open'],'regime_exit',c.fee,c.slippage)
            elif stop_hit:
                close(b,min(stop,b['open']) if d==1 else max(stop,b['open']),'stop',c.fee,c.slippage)
            elif tp_hit:
                close(b,p['target'],'target',maker_fee if s.maker else c.fee,0 if s.maker else c.slippage)
            elif b['t']-p['entry_time']>=(s.max_hours if p['mode']=='scalp' else 90*24)*3600:
                close(b,b['open'],'timeout',c.fee,c.slippage)
            exited=position is None
        if not position and order and not exited:
            d=order['direction'];price=order['price']
            crossed=b['low']<price-c.tick_size if d==1 else b['high']>price+c.tick_size
            if not order['passive'] or crossed:
                passive=order['passive'];entry=price if passive else b['open']*(1+d*c.slippage)
                ef=maker_fee if passive else c.fee
                stop=round_step(entry-d*order['stop_dist'],c.tick_size,up=d==-1)
                target=round_step(entry+d*order['target_dist'],c.tick_size,up=d==-1) if order['target_dist'] else None
                sf=stop*(1-d*c.slippage);loss=d*(entry-sf)+ef*entry+c.fee*sf
                qty=round_step(min(cash*c.risk/loss,cash/(entry*(1+ef))),.0001)
                if qty>=.0001 and cash>0:
                    fee=qty*entry*ef;cash-=fee;fees+=fee;filled+=1
                    position=dict(direction=d,side='long' if d==1 else 'short',mode=order['mode'],entry=entry,
                        entry_time=b['t'],qty=qty,entry_fee=fee,stop=stop,target=target,planned_risk=qty*loss,
                        best_close=entry)
                    # Limit fills have unknown high/low order. Never credit entry-bar TP.
                    if b['low']<=stop if d==1 else b['high']>=stop:
                        close(b,stop,'entry_bar_stop',c.fee,c.slippage)
                    elif market_entry_target and not passive and target and (b['high']>target+c.tick_size if d==1 else b['low']<target-c.tick_size):
                        close(b,target,'entry_bar_target',c.fee,c.slippage)
                order=None
            elif i-order['created']>=max(1,3600//bar_seconds):
                order=None;expired+=1
        if position and b['t']+bar_seconds>=end:
            close(b,b['close'],'end',c.fee,c.slippage)
        if position:
            p=position;d=p['direction']
            if p['mode']=='trend' and h.get('atr'):
                p['best_close']=max(p['best_close'],b['close']) if d==1 else min(p['best_close'],b['close'])
                trail=round_step(p['best_close']-d*3*h['atr'],c.tick_size,up=d==-1)
                if d*(b['close']-trail)>0:p['stop']=max(p['stop'],trail) if d==1 else min(p['stop'],trail)
                if d*(h['ema25']-h['ema99'])<=0:pending_exit=True
            elif p['mode']=='scalp' and (h.get('adx') or 0)>=30:
                pending_exit=True
        if not position and not order and not exited and h.get('atr') and h.get('ema99') and (b['t']+bar_seconds)%decision_seconds==0:
            trend_d=b['signals'].get('micro',0)
            if s.hybrid and (h.get('adx') or 0)>=25 and trend_d and (trend_d==1 or s.short) and b['volume_ratio']>=1.2:
                order=dict(direction=trend_d,price=b['close'],passive=False,stop_dist=2*h['atr'],
                    target_dist=0,created=i,mode='trend');orders+=1
            elif (h.get('adx') or 0)<s.adx_ceiling and h['atr']>0:
                d=1 if b['rsi2']<10 and b['close']<b['mean']-s.z_entry*b['sd'] else -1 if b['rsi2']>90 and b['close']>b['mean']+s.z_entry*b['sd'] else 0
                if s.recovery and i>0:
                    d=1 if bars[i-1]['rsi2']<10 and b['rsi2']>bars[i-1]['rsi2'] and b['close']<b['mean'] else -1 if bars[i-1]['rsi2']>90 and b['rsi2']<bars[i-1]['rsi2'] and b['close']>b['mean'] else 0
                if s.entry_kind=='reclaim' and i>0:
                    p=bars[i-1]
                    d=1 if p['low']<p['mean']-2*p['sd'] and b['close']>b['mean']-2*b['sd'] and b['close']>p['close'] else -1 if p['high']>p['mean']+2*p['sd'] and b['close']<b['mean']+2*b['sd'] and b['close']<p['close'] else 0
                if s.entry_kind=='vwap_reject' and i>0:
                    p=bars[i-1]
                    d=1 if b['vwap']-b['close']>=h['atr'] and b['close']>p['high'] else -1 if b['close']-b['vwap']>=h['atr'] and b['close']<p['low'] else 0
                if d and s.trend_align:
                    r=b['regime']
                    if not r.get('ema99') or d*(r['ema25']-r['ema99'])<=0 or d*(r['close']-r['ema99'])<=0:d=0
                if d and (d==1 or s.short):
                    target_dist=s.target_atr*h['atr']
                    cost=b['close']*(2*maker_fee if s.maker else 2*c.fee+2*c.slippage)
                    if target_dist>=3*cost:
                        price=round_step(b['close']-d*.25*b['atr'],c.tick_size,up=d==-1) if s.maker else b['close']
                        order=dict(direction=d,price=price,passive=s.maker,stop_dist=s.stop_atr*h['atr'],
                            target_dist=target_dist,created=i,mode='scalp');orders+=1
        value=cash
        if position:
            p=position;value+=p['qty']*(p['direction']*(b['close']-p['entry'])-c.fee*b['close'])
        peak=max(peak,value);dd=max(dd,1-value/peak);curve.append((b['t']+bar_seconds,value))
    m=dict(stats(trades),return_pct=100*(curve[-1][1]/c.equity-1),max_drawdown_pct=100*dd,fees=fees,
        orders=orders,filled=filled,expired=expired,end_equity=curve[-1][1],
        scalp_planned_gross_rr=s.target_atr/s.stop_atr)
    return m,trades,curve


def main():
    OUT.mkdir(parents=True,exist_ok=True);bars=prepare(load(DATA));end=bars[-1]['t']+900
    specs=[]
    for hybrid in (False,True):
        for maker in (False,True):
            for recovery in (False,True):
                specs.append(Mode(f'{"hybrid" if hybrid else "scalp"}_{"maker" if maker else "market"}_{"recover" if recovery else "extreme"}',maker=maker,recovery=recovery,hybrid=hybrid))
    for short in (False,True):
        for hours in (2,8):
            for target in (.75,1.5):
                specs.append(Mode(f'aligned_{"both" if short else "long"}_{hours}h_tp{target}',
                    short=short,max_hours=hours,target_atr=target,trend_align=True))
            specs.append(Mode(f'range15_{"both" if short else "long"}_{hours}h',short=short,max_hours=hours,adx_ceiling=15))
    write_json(OUT/'plan.json',dict(specs=[asdict(s) for s in specs],known_data=True,
        maker_fee_assumption=.0002,taker_fee=.0005,slippage=.0002,risk_per_trade=.0025,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        data_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest(),
        limitation='15m bars; no queue or orderbook simulation; maker fill strictly crosses by tick; no entry-bar profit'))
    table={};stress={}
    for s in specs:
        table[s.name]={}
        for label,start,stop in [('2024',bars[0]['t'],ts('2025-01-01')),('2025',ts('2025-01-01'),ts('2026-01-01')),
            ('2026',ts('2026-01-01'),end),('full',bars[0]['t'],end)]:
            m,t,curve=simulate(bars,s,start=start,end=stop);table[s.name][label]=m
            if label=='full':write_json(OUT/f'{s.name}_trades.json',t)
        # Re-run even passive entries at taker-level fees; do not assume VIP tier.
        stress[s.name]=simulate(bars,s,maker_fee=.0005)[0]
        print(s.name,[(p,round(v['return_pct'],2),round((v['win_rate'] or 0)*100,1),v['trades']) for p,v in table[s.name].items()],flush=True)
    write_json(OUT/'results.json',table);write_json(OUT/'fee_stress.json',stress)
    lines=['# BTC震荡剥头皮＋突破趋势模式研究','',
        '按用户偏好，平时研究小利润多次兑现，突破时切到趋势。这里只使用BTC，资金费关闭，所有历史已参与研究。',
        '', '震荡条件为已收盘1h ADX<25。15m RSI2极值配合布林中轴偏离，或RSI极值后恢复触发。止损1.5倍1h ATR，止盈0.75倍1h ATR，最多持仓8小时，毛目标必须至少覆盖预计往返成本3倍。单笔计划风险0.25%，名义金额不超过权益。',
        '', '剥头皮允许毛盈亏比0.5，已不强制趋势仓净RR≥1.5；必须通过胜率、平均净盈亏与成本共同判断。ADX升至30则下根开盘退出震荡仓。混合模式在1h ADX≥25且15m中继突破、量比≥1.2时转为趋势仓；趋势仓2倍1h ATR止损、3倍1h ATR移动退出。',
        '', 'maker版本假设费率0.02%，不是已核实账户费率。限价挂单下一根起有效，必须穿过价格至少1 tick才记成交，4根未成交撤单，入场当根不计止盈、先计止损。无队列/盘口信息，仍不能证明真实可成交；另把maker费用提高到0.05%做压力测试。market版本为单边手续费0.05%和滑点0.02%。',
        '', '| 模式 | 总收益 | 胜率 | 回撤 | 交易数 | 2025收益 | 2026收益 | maker按taker费压力收益 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in table.items():
        m=r['full'];lines.append(f'| {n} | {m["return_pct"]:.2f}% | {(m["win_rate"] or 0)*100:.2f}% | {m["max_drawdown_pct"]:.2f}% | {m["trades"]} | {r["2025"]["return_pct"]:.2f}% | {r["2026"]["return_pct"]:.2f}% | {stress[n]["return_pct"]:.2f}% |')
    lines+=['','前8个方案为第一轮；随后12个方案对照只顺4h方向、ADX<15的更弱趋势环境、2/8小时退出、0.75/1.5倍ATR止盈。两轮都使用已查看历史，不能作为独立验证。',
        '', '当前20个方案均未得到正的全区间净收益，不采用这些参数发送订单。研究方向保留为震荡短线主模式、突破时转趋势；V2仅作为趋势对照。',
        '', '24项自动测试通过，包含限价仅触及不成交、入场当根不计止盈、同根先计止损、计划风险和费用对账。',
        '', '15m OHLCV不足以验证秒级/逐笔剥头皮；这里只能测试15m信号、小时级持仓的短线近似。高胜率并不自动覆盖大亏和成本。',
        '', '复现：`python btc_scalp.py`。结果和逐笔记录保存在同目录，脚本不发送订单。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':main()
