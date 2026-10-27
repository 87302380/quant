"""BTC V4: study the source of profit; 4h regime and 1h entry experiments."""
import hashlib
import json
import math
from collections import deque
from dataclasses import asdict,replace
from pathlib import Path
from btc_v2 import Strategy,Config,DATA,load,prepare,run,write_json,ts
from pullback import aggregate,indicators
from btc_v3 import concentration,monthly_concentration

OUT=Path('results/btc_v4')


def entry_features(rows):
    regime=prepare(rows)
    hourly=indicators(aggregate(rows,3600),Config())
    j=-1;width_history=deque(maxlen=120)
    for i,h in enumerate(hourly):
        while j+1<len(regime) and regime[j+1]['t']+14400<=h['t']+3600:j+=1
        r=regime[j] if j>=0 else {}
        h['regime']=r;h['daily']=r.get('daily',{});h['signals']={}
        window=hourly[max(0,i-19):i+1]
        mean=sum(x['close'] for x in window)/len(window)
        width=4*math.sqrt(sum((x['close']-mean)**2 for x in window)/len(window))/mean
        threshold=sorted(width_history)[int((len(width_history)-1)*.2)] if len(width_history)==120 else 0
        h['bb_width']=width;h['compressed']=width<=threshold
        width_history.append(width)
        if not r.get('ema99') or not h.get('ema99') or i<20 or not h.get('atr'):continue
        d=1 if r['ema25']>r['ema99'] and r['close']>r['ema99'] else -1 if r['ema25']<r['ema99'] and r['close']<r['ema99'] else 0
        if not d:continue
        previous=hourly[i-1];recent=hourly[i-8:i+1]
        recovery=d*(h['close']-previous['high' if d==1 else 'low'])>0
        touched=any(d*(x['low' if d==1 else 'high']-x['ema25'])<=0 for x in recent if x.get('ema25'))
        not_late=0<d*(h['close']-h['ema25'])<=1.5*h['atr']
        momentum=d*(h['rsi']-previous['rsi'])>0
        if recovery and touched and not_late and momentum:h['signals']['resume']=d
        extreme=min(x['rsi'] for x in recent)<=40 if d==1 else max(x['rsi'] for x in recent)>=60
        if recovery and extreme and momentum:h['signals']['dip']=d
        compressed=any(x.get('compressed',False) for x in hourly[i-6:i])
        boundary=max(x['high'] for x in hourly[i-12:i]) if d==1 else min(x['low'] for x in hourly[i-12:i])
        if compressed and d*(h['close']-boundary)>0:h['signals']['squeeze']=d
    return hourly,regime


def universe():
    result=[]
    for family in ('resume','dip','squeeze'):
        for stop in (2,3):
            for vol in (0,1.2):
                result.append(Strategy(f'{family}_stop{stop}_vol{vol}',family,short=True,
                    stop_atr=stop,trail_atr=3,pause_losses=3,signal_seconds=3600,
                    trail_on_regime=True,min_volume_ratio=vol))
        result.append(Strategy(f'{family}_long',family,short=False,stop_atr=2,trail_atr=3,
            pause_losses=3,signal_seconds=3600,trail_on_regime=True))
    result.append(Strategy('resume_local_trail','resume',short=True,stop_atr=2,trail_atr=3,
        pause_losses=3,signal_seconds=3600,trail_on_regime=False))
    return result


def attribution(trades):
    import statistics
    result={}
    for side in ('long','short'):
        group=[t for t in trades if t['side']==side]
        winners=[t['net_pnl']/t['planned_risk'] for t in group if t['net_pnl']>0]
        losers=[t['net_pnl']/t['planned_risk'] for t in group if t['net_pnl']<=0]
        result[side]=dict(trades=len(group),net_pnl=sum(t['net_pnl'] for t in group),
            win_rate=len(winners)/len(group) if group else None,
            mean_win_r=statistics.mean(winners) if winners else None,
            mean_loss_r=statistics.mean(losers) if losers else None,
            mean_hold_hours=statistics.mean((t['exit_time']-t['entry_time'])/3600 for t in group) if group else None)
    return result


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    rows=load(DATA);hourly,regime=entry_features(rows);c=Config();specs=universe()
    write_json(OUT/'plan.json',dict(known_data=True,funding=0,
        rationale='Earn directional persistence after temporary retracement or compression; reduce entry stop distance, retain 4h management.',
        hypotheses=[asdict(s) for s in specs],source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        engine_sha256=hashlib.sha256(Path('btc_v2.py').read_bytes()).hexdigest(),
        data_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest()))
    end=rows[-1]['t']+900
    periods={'2024':(rows[0]['t'],ts('2025-01-01')),'2025':(ts('2025-01-01'),ts('2026-01-01')),
             '2026':(ts('2026-01-01'),end),'full':(rows[0]['t'],end)}
    all_specs=[Strategy('v2_control','trend',short=True,pause_losses=3)]+specs
    results={};stress={}
    for s in all_specs:
        bars=regime if s.signal_seconds==14400 else hourly
        results[s.name]={}
        for label,(start,stop) in periods.items():
            m,trades,curve=run(rows,bars,s,c,start,stop)
            m.update(concentration(trades));m.update(monthly_concentration(curve,c.equity));m['sides']=attribution(trades)
            results[s.name][label]=m
            if label=='full':write_json(OUT/f'{s.name}_trades.json',trades)
        stress[s.name]=run(rows,bars,s,replace(c,fee=.001,slippage=.0004))[0]
        print(s.name,[(p,round(v['return_pct'],2),round(v['max_drawdown_pct'],2),v['trades']) for p,v in results[s.name].items()],flush=True)
    old=json.loads(Path('results/btc_v2/static_results.json').read_text())['trend_both_pause']['full']
    assert abs(results['v2_control']['full']['return_pct']-old['return_pct'])<1e-8
    write_json(OUT/'results.json',results);write_json(OUT/'double_cost.json',stress)
    lines=['# BTC V4：策略赚什么钱，以及怎样改善入场','',
      '本轮仅BTC，研究已查看的2024—2026年历史；不是新的独立留出。单笔计划风险1%，无杠杆、名义金额不超过权益；资金费关闭，手续费和滑点保持前述口径。',
      '', '## 收益来源','',
      'V2赚趋势持续的钱：容忍小亏，依靠趋势中的盈利仓位覆盖亏损。利润主要来自多单，空单在该区间贡献有限。下表的R是净利润/最初计划风险，不等于BTC价格涨跌幅。','',
      '| 方向 | 交易数 | 净利润USDT | 胜率 | 平均盈利R | 平均亏损R | 平均持仓小时 |','|---|---:|---:|---:|---:|---:|---:|']
    for side,m in results['v2_control']['full']['sides'].items():
        lines.append(f'| {side} | {m["trades"]} | {m["net_pnl"]:.2f} | {m["win_rate"]*100:.2f}% | {m["mean_win_r"]:.2f} | {m["mean_loss_r"]:.2f} | {m["mean_hold_hours"]:.1f} |')
    lines+=['','## 本轮交易假设','',
      '- resume：4h EMA25/99方向一致，1h最近8根内曾回踩EMA25，当前收回EMA25并突破前一根高/低，RSI14恢复；距离EMA25不超过1.5倍1h ATR。',
      '- dip：4h趋势中，1h最近8根曾RSI≤40/≥60，随后RSI恢复且价格突破前一根高/低。',
      '- squeeze：1h布林宽度低于此前120根的20%分位，压缩发生于此前6根内，随后突破此前12根高/低，同时符合4h方向。',
      '- 指标用途分别是方向、回调/动量恢复、波动压缩、成交活跃度；每个家族对照不限制量与量比≥1.2。不是把所有指标同时看多当成独立证据。',
      '- 初始止损对照2或3倍1h ATR；随后主要按4h ATR移动退出，信号和止损更新只使用已收盘数据；另有1h局部移动退出对照。止损更近不保证实际亏损更少。',
      '', '## 同成本、同风险预算的结果','',
      '| 方案 | 总收益 | 胜率 | 回撤 | 2025 | 2026 | 双倍成本收益 | 交易数 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,r in results.items():
        m=r['full']
        lines.append(f'| {name} | {m["return_pct"]:.2f}% | {m["win_rate"]*100:.2f}% | {m["max_drawdown_pct"]:.2f}% | {r["2025"]["return_pct"]:.2f}% | {r["2026"]["return_pct"]:.2f}% | {stress[name]["return_pct"]:.2f}% | {m["trades"]} |')
    lines+=['','16个新方案及1个V2对照。所有方案保留，不把本轮最佳历史表现当作预先选中的策略。分年各重置10,000，全区间连续复利。',
       '', '完整参数、代码和数据哈希、逐笔交易、多空贡献、最佳月份/交易集中度均在同目录JSON中。',
       '', '研究参考：[Liu与Tsyvinski，Risks and Returns of Cryptocurrency](https://www.nber.org/papers/w24877)发现其研究样本中存在时间序列动量；该结论只支持研究趋势持续性，不证明本轮入场模式有效。',
       '', '复现：`python btc_v4.py`。这是本地研究脚本，不发送交易所订单。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('COMPLETE',OUT/'REPORT.md')


if __name__=='__main__':main()
