"""Summarize the real 24h replay and verify the user holding constraint."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    folder = ROOT / 'results/nfi/study'
    rows = json.loads((folder / 'comparison.json').read_text())
    text = '''# 24小时持仓上限真实引擎验证

用户已确认24小时为最长单次持仓。由首次入场计时，加仓、部分减仓不重置期限；到期无论盈亏退出，停止新增仓位并取消到期未成交入场订单。固定上游源码不变，单独子类`NFI24Hour`实现该控制。

与原版使用相同7月至10月27日数据、统一10000 USDT钱包、3倍杠杆、6槽位及单边5bps手续费。真实资金费未计入。当前币池有事后选币偏差，结果为探索性回放；不是新样本外验证。5m撮合中的期限执行通过，不等于实盘订单可保证在截止瞬间成交。

| 配置 | 净收益 | 含浮亏回撤 | 胜率 | 持仓数 | 最长小时 |
|---|---:|---:|---:|---:|---:|
'''
    for key, label in [('official','57币原版'), ('official_24h','57币24小时'),
                       ('baseline100','100币原版'), ('baseline100_24h','100币24小时')]:
        r = rows[key]
        text += f"| {label} | {r['return_pct']:+.2f}% | {r['equity_audit']['mtm_drawdown_pct']:.2f}% | {r['win_rate_pct']:.2f}% | {r['campaigns']} | {r['max_holding_hours']:.2f} |\n"
    for key, label in [('official_24h', '57币'), ('baseline100_24h', '100币')]:
        r = rows[key]
        audit = r['deadline_audit']
        text += f"\n## {label}期限与盈亏核对\n\n"
        text += f"超时持仓{audit['overdue_campaigns']}笔，到期及之后新增入场{audit['late_adds']}笔。期限触发退出{audit['deadline_exits']}笔，其中亏损退出{audit['deadline_losing_exits']}笔；期限退出的完整持仓合计净利润{audit['deadline_profit_usdt']:.2f} USDT（含此前部分减仓盈亏）。这些亏损已计入组合结果，未删除任何超时交易。\n"
        text += '\n| 方向 | 笔数 | 净利润USDT |\n|---|---:|---:|\n'
        for side, v in r['by_direction'].items():
            text += f"| {side} | {v['campaigns']} | {v['profit_usdt']:.2f} |\n"
        text += '\n| 信号族（混合标签独立分组） | 笔数 | 净利润USDT |\n|---|---:|---:|\n'
        for group, v in r['by_family'].items():
            text += f"| {group} | {v['campaigns']} | {v['profit_usdt']:.2f} |\n"
        text += '\n固定成交路径的逐次不利滑点扣减（不是重新撮合；包含加减仓）：'
        text += '；'.join(f"{bps}bps后净收益{r['fixed_path_slippage_stress'][str(bps)]['return_pct']:+.2f}%" for bps in (2,5,10)) + '。\n'
    text += '''
## 如何解读

24小时是交易需求约束，不是通过调参挑选的最优持仓期限。限时退出会确认一些原版后来恢复的小盈利仓的亏损，并改变资金再利用与后续交易路径，所以不能根据旧交易分组推算新收益。本次确实重跑了完整组合。

时间上限不等于损失上限：持仓不足24小时仍可能遭遇快速大跌、暴涨和高相关性冲击。它也不自动解决看多信号面对持续下跌的适应性；单边行情风险预算、累计保证金与加仓上限需要另做冻结规则对照。本结果不能单独作为实盘依据。

复现：

```sh
.venv/bin/python nfi_study.py official_24h baseline100_24h
.venv/bin/python nfi_analyze.py
.venv/bin/python nfi_deadline_report.py
.venv/bin/python -m unittest discover -s research/nfi/study -p 'test_*.py' -v
```

逐方案execution.json记录命令、配置哈希与实际退出状态，压缩引擎结果保存每次订单和信号，analysis.json包含归因、期限审计与权益对账。实际引擎结果的最长持仓和逐订单时间验证是期限是否满足的依据，不能只看子类代码。
'''
    (folder / 'DEADLINE_24H.md').write_text(text)


if __name__ == '__main__':
    main()
