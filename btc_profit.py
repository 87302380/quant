"""BTC return-first study: capital use via protected pyramiding and trend exits."""
import argparse
import csv
import hashlib
import json
from dataclasses import asdict,replace
from pathlib import Path
from btc_5m import DATA,resample
from btc_v2 import Config,Strategy,load,prepare,run,write_json
from research import ts

OUT=Path('results/btc_profit')


def universe():
    result=[]
    for short in (False,True):
        for stop in (1.5,2,3):
            for trail in (3,4.5):
                for adds in (0,2):
                    name=f'{"both" if short else "long"}_stop{stop}_trail{trail}_adds{adds}'
                    result.append(Strategy(name,'trend',short=short,stop_atr=stop,trail_atr=trail,
                        pause_losses=3,max_adds=adds))
    return result


def main():
    p=argparse.ArgumentParser();p.add_argument('--strategy',choices=[s.name for s in universe()]);args=p.parse_args()
    OUT.mkdir(parents=True,exist_ok=True);rows=load(DATA,step_seconds=300);h=prepare(resample(rows,900));c=Config()
    specs=universe();end=rows[-1]['t']+300
    if args.strategy:
        s=next(s for s in specs if s.name==args.strategy)
        m,t,curve=run(rows,h,s,c,bar_seconds=300)
        write_json(OUT/f'{s.name}_replay_metrics.json',m);write_json(OUT/f'{s.name}_replay_trades.json',t)
        print(json.dumps(m,indent=2));return
    write_json(OUT/'plan.json',dict(known_data=True,universe=[asdict(s) for s in specs],risk=asdict(c),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        engine_sha256=hashlib.sha256(Path('btc_v2.py').read_bytes()).hexdigest(),
        data_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest(),
        risk_definition='At shared stop, net campaign loss incl fees <=1% current marked equity. Profit giveback from mark may exceed 1%. Gross notional <= marked equity at each add.',
        selection='2024/2025 each >=20 trades, positive return, PF>=1.05, DD<=20%; maximize minimum annual return, else no candidate'))
    table={}
    for s in specs:
        table[s.name]={}
        for period,start,stop in [('2024',rows[0]['t'],ts('2025-01-01')),('2025',ts('2025-01-01'),ts('2026-01-01'))]:
            m,t,_=run(rows,h,s,c,start,stop,bar_seconds=300);table[s.name][period]=m
        print('DEVELOP',s.name,[(p,round(m['return_pct'],2),round(m['max_drawdown_pct'],2)) for p,m in table[s.name].items()],flush=True)
    eligible=[s for s in specs if all(table[s.name][p]['trades']>=20 and table[s.name][p]['return_pct']>0 and (table[s.name][p]['profit_factor'] or 0)>=1.05 and table[s.name][p]['max_drawdown_pct']<=20 for p in ('2024','2025'))]
    selected=max(eligible,key=lambda s:min(table[s.name][p]['return_pct'] for p in ('2024','2025'))) if eligible else None
    write_json(OUT/'selection_before_2026.json',dict(selected=asdict(selected) if selected else None,eligible=[s.name for s in eligible]))
    stress={}
    for s in specs:
        for period,start in [('2026',ts('2026-01-01')),('full',rows[0]['t'])]:
            m,t,curve=run(rows,h,s,c,start=start,bar_seconds=300);table[s.name][period]=m
            if period=='full':
                write_json(OUT/f'{s.name}_trades.json',t)
                if selected and s.name==selected.name:
                    with (OUT/'candidate_equity.csv').open('w',newline='') as f:
                        w=csv.writer(f);w.writerow(['timestamp','equity']);w.writerows(curve)
        stress[s.name]=run(rows,h,s,replace(c,fee=.001,slippage=.0004),bar_seconds=300)[0]
        print('CONFIRM',s.name,round(table[s.name]['full']['return_pct'],2),round(table[s.name]['full']['max_drawdown_pct'],2),flush=True)
    write_json(OUT/'results.json',table);write_json(OUT/'double_cost.json',stress)
    old=json.loads(Path('results/btc_5m/trend_resolution_check.json').read_text())['5m_risk0.01']
    assert abs(old['return_pct']-table['both_stop3_trail3_adds0']['full']['return_pct'])<1e-8
    lines=['# BTC 收益优先：趋势仓与盈利后加仓','',
        '只研究BTC。4h收盘EMA决定趋势，5m检查成交与止损；本轮优先总净收益，不把高胜率作为硬目标。共24个预先列出的方案。底层2024—2026历史此前均已查看，非全新独立样本外验证。',
        '', '## 仓位与风险定义','',
        '初始仓按净值1%与止损距离定仓，名义金额不超过净值。可选最多2次加仓：价格比首笔入场有利移动达到1R/2R，并在4h收盘突破前一根4h高/低，且方向仍一致。下根5m开盘重新计算可用资金及风险后成交。',
        '', '所有单位共用只收紧的止损；每次加仓校验总仓在共同止损处的净损失（相对本轮持仓初始资本、包含费用）不超过当前盯市净值1%，总名义金额不超过盯市净值。已保护盈利允许抵消新增单位风险。这不是“从当前浮盈净值回撤最多1%”：浮盈回吐和跳空可使实际回撤更大。',
        '', '分批入场合并成一轮完整持仓统计胜负，未靠拆单虚增胜率。没有杠杆、摊平亏损或亏损后加倍仓位。费用单边0.05%、滑点0.02%，资金费按用户要求关闭。',
        '', '| 方案 | 全区间收益 | 胜率 | 回撤 | 2024 | 2025 | 2026 | 双倍成本收益 |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in table.items():
        m=r['full'];lines.append(f'| {n} | {m["return_pct"]:.2f}% | {m["win_rate"]*100:.2f}% | {m["max_drawdown_pct"]:.2f}% | {r["2024"]["return_pct"]:.2f}% | {r["2025"]["return_pct"]:.2f}% | {r["2026"]["return_pct"]:.2f}% | {stress[n]["return_pct"]:.2f}% |')
    lines+=['',f'按2024/2025固定规则、在计算本轮2026新配置结果前选中：{selected.name if selected else "无合格候选"}。全区间事后收益最高者不一定是这个候选。分年重置账户，全区间连续复利。',
        '', '## 实际使用边界','',
        '本轮仍未验证历史规则变化、真实资金费、标记价格、滑点尾部、订单簿冲击和部分成交。5m不能完全恢复逐笔成交。稳健性需要成本压力、相邻参数和独立新增BTC行情共同支持。',
        '', '复现：`python btc_profit.py`；指定回放：`python btc_profit.py --strategy 策略名称`。脚本不发送订单。',
        '', '参考：[AQR Trends Everywhere](https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-Trends-Everywhere_JOIM.pdf?sc_lang=en)讨论趋势与波动率仓位；本轮盈利后加仓规则是研究假设，并非该论文对BTC的保证。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    if selected:write_json(OUT/'candidate.json',dict(strategy=asdict(selected),risk=asdict(c),live_trading_enabled=False,known_data=True))
    print('COMPLETE',OUT/'REPORT.md')


if __name__=='__main__':main()
