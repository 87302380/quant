"""Separate tactical recovery from 15m trend continuation entry, BTC only."""
import json
import hashlib
from dataclasses import asdict,replace
from btc_v4 import OUT,DATA,Config,load,entry_features,run,write_json,ts,Strategy,attribution
from pullback import indicators


def micro_features(rows,hourly):
    bars=indicators(rows,Config());j=-1
    for i,b in enumerate(bars):
        while j+1<len(hourly) and hourly[j+1]['t']+3600<=b['t']+900:j+=1
        h=hourly[j] if j>=0 else {};r=h.get('regime',{})
        b['daily']=h.get('daily',{});b['regime']=r;b['signals']={}
        if not h.get('ema99') or not r.get('ema99') or not b.get('atr') or i<4:continue
        b['management_atr']=h['atr']
        d=1 if r['ema25']>r['ema99'] and r['close']>r['ema99'] else -1 if r['ema25']<r['ema99'] and r['close']<r['ema99'] else 0
        if not d or d*(h['ema25']-h['ema99'])<=0:continue
        window=bars[i-4:i]
        high=max(x['high'] for x in window);low=min(x['low'] for x in window)
        # Small local consolidation, not a mandatory pullback to a large EMA.
        compact=high-low<=2.5*bars[i-1]['atr']
        breakout=d*(b['close']-(high if d==1 else low))>0
        bar_range=b['high']-b['low']
        controlled=bar_range<=2*b['atr'] and d*(b['close']-b['open'])>=.5*bar_range
        if compact and breakout and controlled:b['signals']['micro']=d
    return bars


def universe():
    result=[]
    for family in ('resume','dip'):
        for short in (False,True):
            for target in (2,3):
                result.append(Strategy(f'tactical_{family}_{"both" if short else "long"}_{target}R',family,
                    short=short,stop_atr=2,trail_atr=3,pause_losses=3,signal_seconds=3600,
                    trail_on_regime=True,target_r=target))
    for short in (False,True):
        for mode in ('trend','target2R','volume'):
            result.append(Strategy(f'micro_{"both" if short else "long"}_{mode}','micro',short=short,
                stop_atr=3,trail_atr=3,pause_losses=3,signal_seconds=900,trail_on_regime=True,
                target_r=2 if mode=='target2R' else 0,min_volume_ratio=1.2 if mode=='volume' else 0))
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=load(DATA);hourly,regime=entry_features(rows);micro=micro_features(rows,hourly)
    c=Config();specs=universe();end=rows[-1]['t']+900
    write_json(OUT/'extension_plan.json',dict(known_data=True,strategies=[asdict(s) for s in specs],
        rationale='Tactical recovery with finite target vs local continuation without large timeframe pullback',
        engine_sha256=hashlib.sha256(__import__('pathlib').Path('btc_v2.py').read_bytes()).hexdigest()))
    periods={'2024':(rows[0]['t'],ts('2025-01-01')),'2025':(ts('2025-01-01'),ts('2026-01-01')),
        '2026':(ts('2026-01-01'),end),'full':(rows[0]['t'],end)}
    results={};stress={}
    for s in specs:
        bars=micro if s.family=='micro' else hourly
        results[s.name]={}
        for label,(start,stop) in periods.items():
            m,t,curve=run(rows,bars,s,c,start,stop);m['sides']=attribution(t);results[s.name][label]=m
            if label=='full':write_json(OUT/f'{s.name}_trades.json',t)
        stress[s.name]=run(rows,bars,s,replace(c,fee=.001,slippage=.0004))[0]
        print(s.name,[(p,round(m['return_pct'],2),round(m['max_drawdown_pct'],2),m['trades']) for p,m in results[s.name].items()],flush=True)
    write_json(OUT/'extension_results.json',results);write_json(OUT/'extension_double_cost.json',stress)
    lines=['# BTC V4补充：回调交易与持续趋势中继','',
      'BTC已知历史研究；资金费关闭，单边手续费0.05%、滑点0.02%，风险预算和数量取整沿用V2。',
      '', '回调战术仓：沿用1h恢复信号，采用固定2R/3R止盈，预计净RR低于1.5拒绝入场。',
      '', '15m中继仓：4h方向、1h EMA25/99同向；此前4根15m高低跨度≤2.5倍前一根ATR；当前收盘突破该小区间，实体方向一致且至少占本根振幅50%，本根振幅不超过2倍ATR。无需回到4h/1h均线。',
      '', '中继仓初始止损3倍15m ATR；移动退出用已收盘1h ATR，方向失效用4h EMA。对照趋势持有、固定2R止盈和量比≥1.2；平仓冷却24小时、连亏暂停保持不变。',
      '', '| 方案 | 总收益 | 胜率 | 回撤 | 2025收益 | 2026收益 | 双倍成本收益 | 交易数 |',
      '|---|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in results.items():
        m=r['full'];lines.append(f'| {n} | {m["return_pct"]:.2f}% | {(m["win_rate"] or 0)*100:.2f}% | {m["max_drawdown_pct"]:.2f}% | {r["2025"]["return_pct"]:.2f}% | {r["2026"]["return_pct"]:.2f}% | {stress[n]["return_pct"]:.2f}% | {m["trades"]} |')
    lines+=['', '本轮增加8个战术退出版本与6个中继版本，全部保留。不得将事后最佳参数宣传为样本外选择。',
        '', '复现：`python btc_v4_extension.py`。新信号、移动止损、量比都只读取已收盘K线。']
    (OUT/'EXTENSION.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('COMPLETE',OUT/'EXTENSION.md')


if __name__=='__main__':main()
