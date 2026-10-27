"""Known-data contrast: take profit normally, run only in aligned strong 4h trend."""
import json
from dataclasses import asdict,replace
from btc_locations import DATA,OUT,Config,Rules,load,prepare,signals,simulate,ts


def main():
    bars=prepare(load(DATA,step_seconds=300));c=Config()
    b=Rules('adaptive_long_1.5','trend',False,'adaptive',only4h=True,stop_floor4h=.75,
        cooldown_hours=12,max_cost_fraction=.15,min_net_rr=.75,runner_atr4h=1.5)
    specs=[b,replace(b,name='adaptive_long_2',runner_atr4h=2),replace(b,name='adaptive_both_1.5',short=True),
           replace(b,name='always_runner_long_1.5',exit='runner')]
    write=lambda p,o:p.write_text(json.dumps(o,indent=2),encoding='utf-8')
    write(OUT/'adaptive_plan.json',[asdict(r) for r in specs]);table={};stress={}
    for r in specs:
        events=list(signals(bars,r));table[r.name]={}
        for label,start,end in [('2024',bars[0]['t'],ts('2025-01-01')),('2025',ts('2025-01-01'),ts('2026-01-01')),
            ('2026',ts('2026-01-01'),None),('full',bars[0]['t'],None)]:
            m,t,_=simulate(bars,r,c,start,end,events);table[r.name][label]=m
            if label=='full':write(OUT/f'{r.name}_trades.json',t)
        stress[r.name]=simulate(bars,r,replace(c,fee=.001,slippage=.0004),events=events)[0]
        print(r.name,[(p,round(m['return_pct'],2),round((m['win_rate'] or 0)*100,1),m['trades']) for p,m in table[r.name].items()],flush=True)
    write(OUT/'adaptive_results.json',table);write(OUT/'adaptive_double_cost.json',stress)
    lines=['# 高周期位置与强弱趋势退出对照','',
        '4h/1h决定方向位置，5m确认入场。沿用4h位置、0.75倍4h ATR止损下限、12小时冷却和成本空间筛选。普通环境至多1R兑现；4h ADX≥25且DI与方向一致，才切为移动退出仓。全部使用信号收盘时已知的4h状态，入场后不根据未来结果挑选退出模式。',
        '', '移动退出距离对照1.5/2倍4h ATR；另有双向与始终移动退出对照。全部历史此前已研究，属于探索性测试。',
        '', '| 方案 | 总收益 | 胜率 | 回撤 | 笔数 | 2024 | 2025 | 2026 | 双倍成本 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in table.items():
        m=r['full'];lines.append(f'| {n} | {m["return_pct"]:.2f}% | {(m["win_rate"] or 0)*100:.2f}% | {m["max_drawdown_pct"]:.2f}% | {m["trades"]} | {r["2024"]["return_pct"]:.2f}% | {r["2025"]["return_pct"]:.2f}% | {r["2026"]["return_pct"]:.2f}% | {stress[n]["return_pct"]:.2f}% |')
    lines+=['','风控和费用不变，不通过提高杠杆增加收益。初始目标仅用于进入前的空间校验，runner仓以移动退出替代固定目标。',
        '', '复现：`python btc_locations_adaptive.py`。']
    (OUT/'ADAPTIVE.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')


if __name__=='__main__':main()
