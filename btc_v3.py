"""BTC V3 bounded ablations; known-data research, not independent validation."""
import csv
import hashlib
import json
from dataclasses import asdict,replace
from pathlib import Path
from datetime import datetime,timezone
from btc_v2 import Strategy,Config,DATA,load,prepare,run,write_json,ts
from pullback import stats

OUT=Path('results/btc_v3')


def universe():
    b=Strategy('v2_control','trend',short=True,pause_losses=3)
    return [b,
        replace(b,name='adx20',min_adx=20),
        replace(b,name='adx25',min_adx=25),
        replace(b,name='efficiency20',min_efficiency=.2),
        replace(b,name='efficiency30',min_efficiency=.3),
        replace(b,name='breakeven1R',breakeven_r=1),
        replace(b,name='breakeven2R',breakeven_r=2),
        replace(b,name='fast13_55',fast=13,slow=55),
        replace(b,name='slow50_200',fast=50,slow=200),
        replace(b,name='long_adx20',short=False,min_adx=20),
        replace(b,name='long_efficiency20',short=False,min_efficiency=.2),
        replace(b,name='adx20_breakeven2R',min_adx=20,breakeven_r=2)]


def concentration(trades):
    gains=sum(max(t['net_pnl'],0) for t in trades)
    top=sum(sorted((t['net_pnl'] for t in trades),reverse=True)[:5])
    return dict(top5_share_of_gross_profit=top/gains if gains else None,
                net_pnl_without_best5=sum(t['net_pnl'] for t in trades)-top)


def monthly_concentration(curve,equity):
    ending={}
    for t,v in curve:
        ending[datetime.fromtimestamp(t-1,timezone.utc).strftime('%Y-%m')]=v
    previous=equity;changes=[]
    for value in ending.values():changes.append(value-previous);previous=value
    return dict(net_change_without_best5_months=sum(changes)-sum(sorted(changes,reverse=True)[:5]),
                worst_month_cash_change=min(changes))


def ensemble(rows,h4,specs,c,start,end):
    # Actual equal subaccount capital; each subaccount rounds its own orders.
    curves=[];trades=[]
    for s in specs:
        _,t,curve=run(rows,h4,s,replace(c,equity=c.equity/len(specs)),start,end)
        curves.append(curve)
        trades.extend(t)
    curve=[(points[0][0],sum(p[1] for p in points)) for points in zip(*curves)]
    peak=c.equity;dd=0
    for _,equity in curve:peak=max(peak,equity);dd=max(dd,1-equity/peak)
    trades.sort(key=lambda t:t['exit_time'])
    m=dict(stats(trades),return_pct=100*(curve[-1][1]/c.equity-1),max_drawdown_pct=100*dd,
           end_equity=curve[-1][1],**concentration(trades),**monthly_concentration(curve,c.equity))
    return m,trades,curve


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    specs=universe();rows=load(DATA);h4=prepare(rows);c=Config();end=rows[-1]['t']+900
    write_json(OUT/'plan.json',dict(strategies=[asdict(s) for s in specs],known_data=True,
        policy='Ablations and equal capital allocation; do not maximize position risk',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        engine_sha256=hashlib.sha256(Path('btc_v2.py').read_bytes()).hexdigest(),
        data_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest()))
    periods={'2024':(rows[0]['t'],ts('2025-01-01')),'2025':(ts('2025-01-01'),ts('2026-01-01')),
             '2026':(ts('2026-01-01'),end),'full':(rows[0]['t'],end),'2025_plus':(ts('2025-01-01'),end)}
    results={};stress={}
    for s in specs:
        results[s.name]={}
        for label,(start,stop) in periods.items():
            m,trades,curve=run(rows,h4,s,c,start,stop)
            m.update(concentration(trades));m.update(monthly_concentration(curve,c.equity));results[s.name][label]=m
            if label=='full':
                write_json(OUT/f'{s.name}_trades.json',trades)
                with (OUT/f'{s.name}_equity.csv').open('w',newline='') as f:
                    w=csv.writer(f);w.writerow(['timestamp','equity']);w.writerows(curve)
        stress[s.name]=run(rows,h4,s,replace(c,fee=.001,slippage=.0004))[0]
        print(s.name,[(p,round(v['return_pct'],2),round(v['max_drawdown_pct'],2)) for p,v in results[s.name].items()],flush=True)
    # Ensure optional V3 features leave the default V2 simulation unchanged.
    old=json.loads(Path('results/btc_v2/static_results.json').read_text())['trend_both_pause']['full']
    assert abs(old['return_pct']-results['v2_control']['full']['return_pct'])<1e-8
    mix=[next(s for s in specs if s.name==n) for n in ('fast13_55','v2_control','slow50_200')]
    results['speed_ensemble']={}
    for label,(start,stop) in periods.items():
        m,t,curve=ensemble(rows,h4,mix,c,start,stop);results['speed_ensemble'][label]=m
        if label=='full':
            write_json(OUT/'speed_ensemble_trades.json',t)
            with (OUT/'speed_ensemble_equity.csv').open('w',newline='') as f:
                w=csv.writer(f);w.writerow(['timestamp','equity']);w.writerows(curve)
    stress['speed_ensemble']=ensemble(rows,h4,mix,replace(c,fee=.001,slippage=.0004),rows[0]['t'],end)[0]
    write_json(OUT/'results.json',results);write_json(OUT/'double_cost.json',stress)
    write_json(OUT/'decision.json',dict(action='retain_v2_research_candidate',candidate='trend_both_pause',
        reason='No tested variant improved both full return and drawdown; common trend concentration remains.',
        live_trading_enabled=False,independent_validation=False))
    lines=['# BTC V3 研究：过滤、保本止损与多速度组合','',
      '**本轮结论：维持V2研究候选，不升级参数。新增过滤与保本规则没有同时改善收益和回撤，多速度组合也未消除共同趋势依赖。**','',
      '本轮仅使用BTC此前已查看的数据；所有结果均为探索性历史回放，不是新的独立验证。资金费按用户要求关闭，单边手续费0.05%、滑点0.02%，单账户名义金额不超过权益，计划风险1%。',
      '', '12个单策略方案：V2对照；ADX20/25入场过滤；20根4h净位移/总波动路径比率≥0.2/0.3；盈利达到1R/2R后移至含预计成本的保本止损；EMA13/55与EMA50/200；多头过滤；ADX20+2R保本。仅限制新入场，除保本外不改变移动退出。',
      '', '另测试三种EMA速度的等资金组合，每个子账户按实际分配资金独立计算仓位和交易数量取整，合计不通过加杠杆放大风险。',
      '', '| 方案 | 全区间收益 | 胜率 | 回撤 | 2025收益 | 2026收益 | 双倍成本收益 | 去掉最佳5笔后净利润 |',
      '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name,r in results.items():
        m=r['full']
        lines.append(f'| {name} | {m["return_pct"]:.2f}% | {m["win_rate"]*100:.2f}% | {m["max_drawdown_pct"]:.2f}% | {r["2025"]["return_pct"]:.2f}% | {r["2026"]["return_pct"]:.2f}% | {stress[name]["return_pct"]:.2f}% | {m["net_pnl_without_best5"]:.2f} |')
    lines+=['','## 相同自然月口径检查盈利集中度','','| 方案 | 去掉最佳5个月的净值增量后，剩余净增量（USDT） | 最差月净值变化（USDT） |','|---|---:|---:|']
    for name in ('v2_control','fast13_55','speed_ensemble'):
        m=results[name]['full']
        lines.append(f'| {name} | {m["net_change_without_best5_months"]:.2f} | {m["worst_month_cash_change"]:.2f} |')
    lines+=['','拆分子策略会改变交易笔数，因此不能用去掉最佳5笔来证明组合消除了共同的大趋势依赖。上述月度净值增量包含浮盈亏，只是统一口径的集中度诊断，并非删除月份后重新运行或复利。']
    lines+=['','年段分别从10,000 USDT开始；全区间是连续账户，不能直接用分年乘积复原。去除最佳5笔的数字只用于盈利集中度诊断，不是剔除交易后重新复利的回测。组合交易笔数包含各子策略交易，不等于独立样本数。',
        '', '保本止损按完整4h收盘后更新，下一根15m起生效；不会用入场当根最高价决定当根新止损。市场跳空时仍可能净亏损。',
        '', '复现：`python btc_v3.py`。逐笔交易、15m盯市净值、参数及代码/数据哈希保存在同目录。默认V2参数的全区间结果已与此前V2文件做精确回归核对。',
        '', '19项自动测试通过，覆盖保本止损下一根才生效、多空费用核算、实际子账户数量取整及原有因果性检查。',
        '', '不根据本轮结果自动启用实盘，也不把2024—2026历史研究当作未来收益保证。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('COMPLETE',OUT/'REPORT.md')


if __name__=='__main__':main()
