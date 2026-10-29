# 57币、24小时版本的逐笔亏损研究

报告：[亏损诊断与真实组合对照](../../../results/nfi/risk_study/REPORT.md)。

基线固定为61笔完整持仓、47赢14亏；不是恢复无期限原版。`plan.json`区分初始四项对照、诊断后利润保护假设、风险缩放对照及诊断后80/20过热假设。所有已见历史都是探索性样本，不能称独立验证。24h上限、手续费和统一钱包贯穿所有对照，上游源码不改。

`NFIRiskControls.py`里的每一类单独测试一个机制；没有自动将研究候选替换为实盘或默认配置。

```sh
.venv/bin/python nfi_loss_diagnosis.py
.venv/bin/python nfi_study.py risk_stop3 risk_stop6 risk_stale12 risk_trendgate risk_profitprotect official_1x_24h risk_overheat80
.venv/bin/python nfi_analyze.py
.venv/bin/python nfi_risk_report.py
.venv/bin/python -m unittest discover -s research/nfi/risk_study -p 'test_*.py' -v
```

价格止损使用首次成交价格，加仓不能使止损变远；止损不保证跳空时精确成交。趋势/RSI门槛只使用已闭合高周期。利润保护从已闭合5m信号激活，不假定同根先高后低；新激活保护价遇跳空穿越时用当前价退出。保护首单成本不等于加减仓后的整个campaign保证保本。

最有希望的80/20候选是看过OP/XRP亏损后提出的；其样本内收益增加，浮动回撤未下降，且只排除了同一天两笔亏损。需要冻结后使用新到来行情检验，不能继续围绕这两笔扫描阈值来制造“最优参数”。
