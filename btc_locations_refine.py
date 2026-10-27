"""Cost-space and higher-timeframe location refinements, all trials disclosed."""
import json
from dataclasses import asdict,replace
from btc_locations import DATA,OUT,Config,Rules,load,prepare,signals,simulate,ts


def main():
    bars=prepare(load(DATA,step_seconds=300));c=Config()
    specs=[]
    for short in (False,True):
        for exit in ('level','cap','split'):
            specs.append(Rules(f'4h_{"both" if short else "long"}_{exit}',short=short,exit=exit,only4h=True,
                stop_floor4h=.75,cooldown_hours=12,max_cost_fraction=.15,min_net_rr=.75))
    specs.extend([replace(specs[2],name='4h_long_split_align1h',align1h=True),
                  replace(specs[5],name='4h_both_split_momentum',momentum=True)])
    table={};cost={}
    for r in specs:
        events=list(signals(bars,r));table[r.name]={}
        for label,start,end in [('2024',bars[0]['t'],ts('2025-01-01')),('2025',ts('2025-01-01'),ts('2026-01-01')),
            ('2026',ts('2026-01-01'),None),('full',bars[0]['t'],None)]:
            m,t,_=simulate(bars,r,c,start,end,events);table[r.name][label]=m
            if label=='full':(OUT/f'{r.name}_refined_trades.json').write_text(json.dumps(t,indent=2),encoding='utf-8')
        cost[r.name]=simulate(bars,r,replace(c,fee=.001,slippage=.0004),events=events)[0]
        print(r.name,[(p,round(m['return_pct'],2),round((m['win_rate'] or 0)*100,1),m['trades']) for p,m in table[r.name].items()],flush=True)
    (OUT/'refined_plan.json').write_text(json.dumps([asdict(r) for r in specs],indent=2),encoding='utf-8')
    (OUT/'refined_results.json').write_text(json.dumps(table,indent=2),encoding='utf-8')
    (OUT/'refined_double_cost.json').write_text(json.dumps(cost,indent=2),encoding='utf-8')
    lines=['# 高周期位置：成本空间与交易节奏收紧','',
        '本轮沿用4h市场方向、4h及前一日位置、5m确认。仅4h位置；初始止损至少0.75倍4h ATR；预计往返成本最多占计划止损损失15%；净RR至少0.75；交易后冷却12小时。所有底层价格历史已研究，本轮不是独立留出。',
        '', '收紧基于首轮发现的成本/止损空间比例和过度交易问题。没有提高杠杆与单笔风险；所有8个方案均披露。分批退出仍合并一笔统计。',
        '', '| 方案 | 总收益 | 胜率 | 回撤 | 交易数 | 2024 | 2025 | 2026 | 双倍成本 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in table.items():
        m=r['full'];lines.append(f'| {n} | {m["return_pct"]:.2f}% | {(m["win_rate"] or 0)*100:.2f}% | {m["max_drawdown_pct"]:.2f}% | {m["trades"]} | {r["2024"]["return_pct"]:.2f}% | {r["2025"]["return_pct"]:.2f}% | {r["2026"]["return_pct"]:.2f}% | {cost[n]["return_pct"]:.2f}% |')
    lines+=['', '双倍成本时会重新按同一成本比例规则筛选，交易数量可能减少；同时考察基础成本分年结果，不能把少交易带来的较小亏损当成盈利证明。',
        '', '复现：`python btc_locations_refine.py`。风险、费用和数据沿用首轮。']
    (OUT/'REFINED.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':main()
