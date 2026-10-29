# 固定 X8 的首轮组合研究

结果：[完整报告](../../../results/nfi/study/REPORT.md)。

用户已确认最长持仓24小时，最新期限验证见[24小时报告](../../../results/nfi/study/DEADLINE_24H.md)。运行 `nfi_study.py official_24h baseline100_24h`、`nfi_analyze.py`、`nfi_deadline_report.py` 可复现；原版基线仍完整保留。限时子类不适用于声称已验证的实盘执行保证。

后续61笔逐笔亏损分析与风险对照见[亏损研究](../../../results/nfi/risk_study/REPORT.md)，其中所有事后假设均明确标注，未自动替换基线。

从仓库根目录用 `.venv/bin/python nfi_study.py official` 运行基线；可用方案见 `nfi_study.py --help`。上游源码保持不变，`NFIHistoricalFilters.py` 是单独的历史年龄/振幅门槛对照，不能代表完整官方动态交易池。

安装 `requirements.txt` 后依次运行 `nfi_analyze.py`、`nfi_plot.py` 可生成审计统计和权益图。会计及闭合日线门槛测试：

```sh
.venv/bin/python -m unittest discover -s research/nfi/study -p test_audit.py -v
```

回放每次创建独立空userdir，避免X8磁盘利润目标缓存污染重复实验。截断诊断保留原始工具失败记录；隔离缓存的有限抽查命令：

```sh
mkdir -p data/nfi/lookahead-base
.venv/bin/python nfi_causality.py --isolate-cache lookahead-analysis \
  --userdir data/nfi/lookahead-base --config research/nfi/study/official.json \
  --strategy-path research/nfi/upstream --strategy NostalgiaForInfinityX8 \
  --datadir data/nfi/freqtrade --data-format-ohlcv jsongz \
  --timerange 20260701-20261028 --fee 0.0005 \
  --minimum-trade-amount 1 --targeted-trade-amount 3 \
  --lookahead-analysis-exportfilename results/nfi/study/lookahead_isolated.csv
```

没有实盘、发布、推送。当前历史选币偏差、未计真实资金费及粗粒度撮合限制见报告。
