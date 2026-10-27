"""5m execution audit and bounded BTC scalp hypotheses. No live orders."""
import csv
import hashlib
import json
import math
from dataclasses import asdict,replace
from pathlib import Path
from btc_scalp import Mode,prepare as prepare15,simulate
from pullback import Config,load,indicators,smooth
from research import ts

DATA=Path('data/okx/BTC-USDT-SWAP_5m_1704067200000_1793125800000.csv')
OUT=Path('results/btc_5m')


def resample(rows,seconds,source_seconds=300):
    groups={}
    for b in rows:groups.setdefault(b['t']//seconds*seconds,[]).append(b)
    return [dict(t=t,open=g[0]['open'],high=max(x['high'] for x in g),low=min(x['low'] for x in g),
        close=g[-1]['close'],volume=sum(x['volume'] for x in g))
        for t,g in groups.items() if len(g)==seconds//source_seconds and g[0]['t']==t]


def prepare(rows):
    ctx=prepare15(resample(rows,900));bars=indicators(rows,Config());j=-1
    gains=[0]+[max(b['close']-a['close'],0) for a,b in zip(bars,bars[1:])]
    losses=[0]+[max(a['close']-b['close'],0) for a,b in zip(bars,bars[1:])]
    for b,g,l in zip(bars,smooth(gains,2),smooth(losses,2)):
        b['rsi2']=100*g/(g+l) if g is not None and g+l else 50
    projected=[]
    for i,b in enumerate(bars):
        while j+1<len(ctx) and ctx[j+1]['t']+900<=b['t']+300:j+=1
        h=ctx[j] if j>=0 else {}
        b['hour']=h.get('hour',{});b['regime']=h.get('regime',{});b['signals']=h.get('signals',{})
        recent=bars[max(0,i-19):i+1];avg=sum(x['close'] for x in recent)/len(recent)
        b['mean']=avg;b['sd']=math.sqrt(sum((x['close']-avg)**2 for x in recent)/len(recent))
        vw=bars[max(0,i-47):i+1];volume=sum(x['volume'] for x in vw)
        b['vwap']=sum(x['close']*x['volume'] for x in vw)/volume if volume else b['close']
        p=dict(b)
        for key in ('atr','rsi2','mean','sd','volume_ratio'):
            if key in h:p[key]=h[key]
        projected.append(p)
    return bars,projected,ctx


def universe():
    result=[]
    for maker in (False,True):
        for short in (False,True):
            for kind in ('reclaim','vwap_reject'):
                result.append(Mode(f'{kind}_{"maker" if maker else "market"}_{"both" if short else "long"}',
                    maker=maker,short=short,target_atr=.75,stop_atr=.75,entry_kind=kind,max_hours=2))
    for maker in (False,True):
        for target in (.75,1.5):
            result.append(Mode(f'deep2sigma_{"maker" if maker else "market"}_tp{target}',
                maker=maker,short=True,z_entry=2,target_atr=target,stop_atr=1,max_hours=4))
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True);rows=load(DATA,step_seconds=300);bars,projected,ctx=prepare(rows)
    c=Config(risk=.0025);end=rows[-1]['t']+300;specs=universe()
    write=lambda path,obj:path.write_text(json.dumps(obj,indent=2,allow_nan=False),encoding='utf-8')
    write(OUT/'plan.json',dict(known_underlying_history=True,
        note='Finer unseen resolution, but underlying 2024-2026 BTC history has been examined; not independent future data.',
        specs=[asdict(s) for s in specs],risk=.0025,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        data_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest(),
        selection='2024 and 2025 each >=100 trades, return>0, PF>=1.05; maximize minimum return/drawdown; else none'))
    audit={}
    # Keep original signal cadence fixed, change only intrabar execution resolution.
    control=Mode('old_market',maker=False)
    for label,source,step,decision in [('15m_original',ctx,900,900),('15m_signal_5m_fill',projected,300,900)]:
        m,t,_=simulate(source,control,c,bar_seconds=step,decision_seconds=decision)
        audit[label]=m;write(OUT/f'{label}_trades.json',t)
    for label,source,step in [('15m_known_open_target',ctx,900),('5m_known_open_target',projected,300)]:
        m,t,_=simulate(source,control,c,bar_seconds=step,decision_seconds=900,market_entry_target=True)
        audit[label]=m;write(OUT/f'{label}_trades.json',t)
    write(OUT/'execution_audit.json',audit)
    periods={'2024':(rows[0]['t'],ts('2025-01-01')),'2025':(ts('2025-01-01'),ts('2026-01-01'))}
    table={}
    for s in specs:
        table[s.name]={}
        for period,(start,stop) in periods.items():
            m,t,_=simulate(bars,s,c,start=start,end=stop,bar_seconds=300,market_entry_target=True)
            table[s.name][period]=m
        print('DEVELOP',s.name,[(p,round(m['return_pct'],2),round((m['win_rate'] or 0)*100,1),m['trades']) for p,m in table[s.name].items()],flush=True)
    eligible=[s for s in specs if all(table[s.name][p]['trades']>=100 and table[s.name][p]['return_pct']>0 and (table[s.name][p]['profit_factor'] or 0)>=1.05 for p in periods)]
    rank=lambda s:min(table[s.name][p]['return_pct']/max(.1,table[s.name][p]['max_drawdown_pct']) for p in periods)
    selected=max(eligible,key=rank) if eligible else None
    write(OUT/'selection_before_2026_resolution.json',dict(selected=asdict(selected) if selected else None,eligible=[s.name for s in eligible]))
    # Freeze selection before evaluating 2026 finer resolution. All results disclosed.
    stress={}
    for s in specs:
        for period,start in [('2026',ts('2026-01-01')),('full',rows[0]['t'])]:
            m,t,curve=simulate(bars,s,c,start=start,end=end,bar_seconds=300,market_entry_target=True);table[s.name][period]=m
            if period=='full':
                write(OUT/f'{s.name}_trades.json',t)
                with (OUT/f'{s.name}_equity.csv').open('w',newline='') as f:
                    w=csv.writer(f);w.writerow(['timestamp','equity']);w.writerows(curve)
        stress[s.name]=simulate(bars,s,c,maker_fee=.0005,bar_seconds=300,market_entry_target=True)[0]
        print('CONFIRM',s.name,table[s.name]['full']['return_pct'],flush=True)
    write(OUT/'results.json',table);write(OUT/'fee_stress.json',stress)
    lines=['# BTC 5分钟执行复核与短线策略研究','',
        '仅BTC，资金费关闭。账户10,000，单笔计划风险0.25%，不加杠杆。maker费率0.02%仅为假设，taker0.05%、市价滑点0.02%；限价穿越1 tick才计成交，入场当根不计止盈，跳空止损按更差开盘。',
        '', '## 先复核旧策略，只改变成交粒度','',
        '| 口径 | 收益率 | 胜率 | 交易数 | 回撤 |','|---|---:|---:|---:|---:|']
    for n,m in audit.items():lines.append(f'| {n} | {m["return_pct"]:.2f}% | {m["win_rate"]*100:.2f}% | {m["trades"]} | {m["max_drawdown_pct"]:.2f}% |')
    lines+=['','市价开盘入场的先后顺序是已知的，因此新增known_open_target口径：当根未触止损、只触止盈时允许成交；同根止损止盈仍按止损。限价入场先后不明，继续不计入场当根止盈。修正与粒度变化分别列示，新方案使用修正口径。',
        '', '## 新5m入场','',
        'reclaim：上一根刺穿2σ布林带，当前收回且价格转向；vwap_reject：偏离4小时滚动VWAP至少1倍1h ATR，当前突破上一根高/低；deep2sigma：2σ偏离与RSI2极值。均只在1h ADX<25入场，测试市价/限价及多头/双向。VWAP由K线收盘与成交量近似，不是逐笔真实VWAP。',
        '', '前两类止损/目标均为0.75倍1h ATR，最长2小时；第三类止损1倍ATR、目标0.75/1.5倍，最长4小时。毛目标至少覆盖预估成本3倍。所有窗口仅用已收盘数据。',
        '', '| 方案 | 总收益 | 胜率 | 笔数 | 回撤 | 2024 | 2025 | 2026 | maker按taker费收益 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in table.items():
        m=r['full'];lines.append(f'| {n} | {m["return_pct"]:.2f}% | {(m["win_rate"] or 0)*100:.2f}% | {m["trades"]} | {m["max_drawdown_pct"]:.2f}% | {r["2024"]["return_pct"]:.2f}% | {r["2025"]["return_pct"]:.2f}% | {r["2026"]["return_pct"]:.2f}% | {stress[n]["return_pct"]:.2f}% |')
    lines+=['',f'在读取2026年新粒度结果前选中的候选：{selected.name if selected else "无合格候选"}。',
        '', '已有2024—2026年标的历史均被研究过，本轮只是新粒度确认，不是全新的独立留出。分年重置账户，全区间连续复利。5m仍不提供盘口队列和逐笔成交顺序，不能据此保证真实剥头皮成交。',
        '', '复现：`python btc_5m.py`。完整方案、哈希、逐笔交易、权益与费用压力测试在同目录。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('COMPLETE',OUT/'REPORT.md')


if __name__=='__main__':main()
