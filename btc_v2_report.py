"""Robustness checks and reproducible report, without selecting new parameters."""
import json
from dataclasses import asdict,replace
from datetime import datetime,timezone
from btc_v2 import OUT,DATA,Config,load,prepare,universe,run,write_json,ts


def main():
    rows=load(DATA);h4=prepare(rows);c=Config()
    specs=universe();s=next(s for s in specs if s.name=='trend_both_pause')
    table=json.loads((OUT/'static_results.json').read_text())
    rolling=json.loads((OUT/'rolling_metrics.json').read_text())
    byname={s.name:s for s in specs}
    schedule={x['month']:byname.get(x['choice']) for x in json.loads((OUT/'rolling_decisions.json').read_text())}
    cost={}
    for label,fee,slip in [('normal',.0005,.0002),('double',.001,.0004),('triple',.0015,.0006)]:
        cost[label]={}
        cfg=replace(c,fee=fee,slippage=slip)
        for period,start in [('full',None),('2025_plus',ts('2025-01-01'))]:
            cost[label][period]=run(rows,h4,s,cfg,start=start)[0]
    neighbors={}
    # Stability probes only; keep original 3/3 ATR parameters irrespective of outcomes.
    for stop,trail in [(2.5,3),(3.5,3),(3,2.5),(3,3.5)]:
        neighbor=replace(s,stop_atr=stop,trail_atr=trail)
        neighbors[f'stop{stop}_trail{trail}']=run(rows,h4,neighbor,c)[0]
    benchmark={}
    for label,begin in [('full',rows[0]['t']),('2025_plus',ts('2025-01-01'))]:
        subset=[b for b in rows if b['t']>=begin]
        entry=subset[0]['open']*(1+c.slippage);qty=c.equity/(entry*(1+c.fee))
        peak=c.equity;dd=0
        for b in subset:
            value=qty*b['close']*(1-c.slippage)*(1-c.fee)
            peak=max(peak,value);dd=max(dd,1-value/peak)
        benchmark[label]=dict(return_pct=100*(value/c.equity-1),max_drawdown_pct=100*dd)
    trades=json.loads((OUT/f'{s.name}_trades.json').read_text())
    gains=sum(t['net_pnl'] for t in trades if t['net_pnl']>0)
    best=sorted((t['net_pnl'] for t in trades),reverse=True)
    fragility=dict(top_5_profit_share=sum(best[:5])/gains,
                   full_pnl_without_5_best=sum(t['net_pnl'] for t in trades)-sum(best[:5]))
    check=dict(cost=cost,neighbors=neighbors,buy_hold=benchmark,profit_concentration=fragility)
    write_json(OUT/'robustness.json',check)
    write_json(OUT/'candidate.json',dict(strategy=asdict(s),risk=asdict(c),
        status='BTC research candidate; previously examined data only',live_trading_enabled=False,
        execution_command='python btc_v2.py --mode single --strategy trend_both_pause'))
    lines=['# BTC V2 改进结果与运行说明','',
      '本轮只研究 BTC-USDT-SWAP。ETH 下载已按用户要求停止，没有用于策略研究。',
      '', '**结论：趋势持仓与移动止损改善了 BTC 历史表现；候选已实现并跑通。数据此前都已查看，本报告不能作为新样本外证明。**',
      '', '数据区间：2024-01-01 UTC 至 2026-10-27 18:30 UTC，98,954根15m；已收盘4h与日线从同源数据聚合。初始10,000 USDT；单笔计划风险1%，最多1个仓位，名义金额不超过权益，无杠杆。',
      '', '## 已落地的改进','',
      '1. 趋势仓位取消固定3R止盈，改为每根4h收盘后更新3×ATR移动止损，保留大趋势收益；初始止损为3×4h ATR14。',
      '2. EMA25/99与收盘相对EMA99确定方向；持仓时EMA方向反转，下一根15m开盘退出。最长持仓90天。',
      '3. 每次平仓后冷却24小时；连续3笔净亏损后暂停至少7天。连续亏损次数的统计不会因为暂停而消失。',
      '4. 实现18个固定对照：趋势、20日突破、RSI2均值回归 × 多头/双向 × 基础/日线过滤/连亏暂停。没有搜索海量指标权重。',
      '5. 新增按过去365天表现逐月选型：至少8笔、净盈利、PF≥1.1、回撤≤20%；选择收益/回撤比最高者，否则空仓。',
      '6. 策略切换时退出旧仓，不允许旧策略信号被新策略执行。入场当根也检查止损，跳空采用更差开盘成交，移动止损仅在后续K线生效。',
      '', '这些是新的趋势持仓策略，并不继续要求原策略的前高/前低固定目标与入场净RR≥1.5。它们通过止损限制亏损、通过移动退出获取趋势收益；原策略保留不变。',
      '', '## 全区间连续回测','',
      '| 方案 | 收益率 | 胜率 | 最大回撤 | PF | 交易数 |',
      '|---|---:|---:|---:|---:|---:|']
    names=[('trend_long_base','趋势多头基础'),('trend_long_pause','趋势多头+暂停'),('trend_both_base','趋势双向基础'),
           ('trend_both_pause','趋势双向+暂停候选'),('reversion_long_base','均值回归多头')]
    for name,label in names:
        m=table[name]['full']
        lines.append(f'| {label} | {m["return_pct"]:.2f}% | {m["win_rate"]*100:.2f}% | {m["max_drawdown_pct"]:.2f}% | {m["profit_factor"]:.3f} | {m["trades"]} |')
    lines+=['', '此前原始结构基线全区间收益-49.04%、胜率20.18%、最大回撤52.48%；上一轮固定目标4h候选收益+9.31%、胜率30.00%、回撤12.09%。V2改进有明确历史效果，但均值回归约70%胜率仍亏损，说明胜率不能替代期望收益。',
      '', '## 双向趋势+暂停候选，分年重置账户','',
      '| 年份 | 收益率 | 胜率 | 回撤 | 交易数 |','|---|---:|---:|---:|---:|']
    for year in ('2024','2025','2026'):
        m=table[s.name][year]
        lines.append(f'| {year} | {m["return_pct"]:.2f}% | {m["win_rate"]*100:.2f}% | {m["max_drawdown_pct"]:.2f}% | {m["trades"]} |')
    lines+=['', '## 滚动选型回放（2025年初至今，连续账户）','',
      f'净收益 **{rolling["return_pct"]:.2f}%**，最大回撤 **{rolling["max_drawdown_pct"]:.2f}%**，胜率 {rolling["win_rate"]*100:.2f}%，{rolling["trades"]}笔，PF {rolling["profit_factor"]:.3f}。',
      '', '每个月的排名只使用当月开始之前已结束的行情和交易，训练窗口末尾按市价强平后计算排名；实际组合平仓后仍保持冷却规则。选型日程在rolling_decisions.json中逐月记录。此回放避免使用当月未来数据，但策略族本身是在已知历史后设计，仍有研究者选型偏差。',
      '', '## 成本压力测试：双向趋势+暂停','',
      '| 场景 | 单边手续费 | 单边滑点 | 全区间收益 | 2025年至今收益 |',
      '|---|---:|---:|---:|---:|']
    for label,fee,slip in [('normal',.05,.02),('double',.1,.04),('triple',.15,.06)]:
        lines.append(f'| {label} | {fee:.2f}% | {slip:.2f}% | {cost[label]["full"]["return_pct"]:.2f}% | {cost[label]["2025_plus"]["return_pct"]:.2f}% |')
    lines+=['', '## 相邻参数稳定性（只诊断，不根据结果重新选参数）','',
      '| 参数 | 全区间收益 | 最大回撤 |','|---|---:|---:|']
    for label,m in neighbors.items():lines.append(f'| {label} | {m["return_pct"]:.2f}% | {m["max_drawdown_pct"]:.2f}% |')
    lines+=['', '## 基准与局限','',
      f'同区间买入持有BTC，含同样交易成本：全区间收益{benchmark["full"]["return_pct"]:.2f}%，回撤{benchmark["full"]["max_drawdown_pct"]:.2f}%；2025年至今收益{benchmark["2025_plus"]["return_pct"]:.2f}%，回撤{benchmark["2025_plus"]["max_drawdown_pct"]:.2f}%。候选不一定超过买入持有的绝对收益，应同时比较风险与资金占用。',
      f'候选最大5笔盈利占总盈利的{fragility["top_5_profit_share"]*100:.1f}%；移除这5笔后总净收益为{fragility["full_pnl_without_5_best"]:.2f} USDT。这是盈利集中度诊断，不是新的回测策略。',
      '', '资金费按用户要求关闭。真实资金费、历史合约规则、订单簿冲击、标记价格及部分成交未建模。回撤按15m收盘盯市计算，并非真实盘中最大回撤。止损遇到跳空可能超过单笔1%计划风险。',
      '', '16项自动测试通过，新增了入场当根止损、费用与权益核对、完整/截断行情因果性及空仓选型测试。',
      '', '## 运行','', '```powershell','python btc_v2.py',
      'python btc_v2.py --mode single --strategy trend_both_pause',
      'python btc_v2.py --mode single --strategy trend_both_pause --start 2025-01-01',
      'python btc_v2_report.py','python -m unittest discover -s tests -v','```','',
      'static_results.json保存全部18个方案；rolling_metrics.json/rolling_equity.csv保存滚动组合；robustness.json保存压力测试、相邻参数与买入持有；candidate.json保存候选参数；逐笔交易另存。所有脚本只做本地研究，不发送订单。',
      '', '## 下一步执行方向','',
      '保留趋势移动止损和暂停机制作为BTC V2主候选；均值回归与低频突破暂不升级。滚动选型作为可复现的对照，后续使用新增BTC数据做持续前向验证。不要根据已知2026年再次宣称独立留出盈利。',
      '', '研究参考：[Time Series Momentum](https://www.aqr.com/Insights/Research/Journal-Article/Time-Series-Momentum)、[Risks and Returns of Cryptocurrency](https://www.nber.org/papers/w24877)。这些研究支持把趋势作为候选假设，不证明本策略可获利。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(check,indent=2))


if __name__=='__main__':main()
