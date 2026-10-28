# NFI X8：OKX USDT 永续多币种研究

本专项由用户于 2026-10-28 明确授权。原 BTC 研究全部保留；这里先准备策略与数据基础，不把下载完成等同于发现盈利策略。

## 固定版本与学习入口

- 上游：[iterativv/NostalgiaForInfinity](https://github.com/iterativv/NostalgiaForInfinity)。固定提交 `05b95e189ac5d301da2169ddec3118368f1b5c8b`，X8 `v18.0.167`。
- 原样保存 `upstream/NostalgiaForInfinityX8.py`，GPL-3.0 许可证与原说明一并保留；`source_manifest.json` 记录逐文件 Git blob SHA。没有自动跟随 main 更新。
- 引擎：Freqtrade；独立研究依赖 `requirements.txt` 固定 `freqtrade==2026.9`，建议 Python 3.12。下载、恢复和完整性检查仅需标准库。
- 官方架构文档在 `upstream/docs/technical-architecture/architecture-overview.md`，实际源码优先于概念说明。

## X8 赚什么钱、不能忽略什么

X8 是一个多信号、跨周期、带仓位管理的组合系统。源码的基础周期为 5m，每个币种另需 15m、1h、4h、1d；BTC/USDT:USDT 的 4h 提供额外市场背景。各信号并不共享同一套“RSI 低于某值就买”的简单规则。应按 `enter_tag` 追踪不同模式，结合趋势、动量、成交量和波动环境分析实际收益来源。

学习时按顺序阅读：`informative_pairs` → `populate_indicators` → `populate_entry_trend` → `custom_stake_amount` → `adjust_trade_position` → `custom_exit`。指标包含不同窗口的 RSI、EMA、布林带、CMF、ROC、StochRSI、Aroon 等；不能据指标数量推断有效性。仓位函数还包含 rebuy、grinding、derisk，不是每次买卖独立结算的单笔止盈系统。

执行 `python nfi_inspect.py` 可在不执行策略源码的情况下生成 `strategy_inventory.json`，列出这些函数的准确行号、默认参数和各模式标签。标签定义不代表全部启用，应继续核对配置与入场函数。

固定版本的全局 `stoploss=-0.99`，`use_custom_stoploss=False`；实际退出依赖定制管理。这个极宽的兜底值不能被解释为低风险。永续模式源码含默认杠杆，`config.backtest.json` 沿用原策略逻辑，没有通过改变杠杆或禁用亏损仓位来美化基线。

后续基线须同时报告：扣手续费后的已实现与未实现收益、期末强制平仓、最大权益回撤、最长持仓、补仓次数和资金占用、币种集中度、long/short 与 entry tag 分组。不能只汇报平仓胜率。先用同一个初始钱包跑 40 币组合，禁止把 40 份各有完整本金的单币收益直接相加。

## 本次数据范围

市场是 **OKX 线性 USDT 永续合约**，不是现货。固定 40 币：见 `pairs.json` 和 `universe.json`。选择条件为：固定上游 OKX futures 静态回测白名单、扣除该版本黑名单、2025-03-07 前上市、下载时仍 live，再按当前 `volCcy24h × last` 的成交额近似值排序取前 40。该数值是排序代理，非精确历史成交额。BTC 包含在内。

这并非 NFI 的唯一币种池，也不是全部可交易币种。上游还提供动态成交量池；本轮 40 币是可复现的首批基线，落在 README 建议的 40–80 币范围内。上市限制为首个研究日保留至少约 480 根日线，避免新币预热不足。所有筛选依据和交易所公开元数据均已保存，不含账户信息。

| 数据 | 下载起点 | 用途 |
|---|---|---|
| 原生 5m | 2026-06-24 | 2026-07-01 起首轮研究及入场预热 |
| 原生 15m | 2026-06-01 | 辅助指标预热 |
| 原生 1h | 2026-05-01 | 中周期指标预热 |
| 原生 4h | 2026-04-01 | 高周期与 BTC 背景预热 |
| 原生 UTC 日线 | 2024-01-01，或上市后首个完整日 | 日线长期指标预热 |
| 原生 1h 标记价格 | 2026-06-24 | 永续回测所需价格辅助数据 |

统一截止 **2026-10-28 00:00 UTC，不含该时刻**。所有 K 线均已收盘。日线使用 OKX `1Dutc`，避免把 UTC+8 日线混进 Freqtrade。没有下载 2024 年之前数据。

按用户要求**没有下载资金费率**。回测配置将缺失费率的回退值显式设为 `0.0`，这只是研究假设，绝不代表交易所实际费率为零。手续费、滑点、实际成交与补仓限制还需要后续单独核验；不要把未含资金费的永续结果称为实盘净利润。

## 本地或 Codex Cloud 恢复

仓库中 `datasets/nfi/` 的 40 个 ZIP 各装一个币种的原生 gzip 文件，使用无重复压缩的确定性封装；无需 LFS、令牌或访问 OKX 即可恢复历史数据。逐文件及 ZIP SHA256 都有清单。

在仓库根目录执行：

```sh
python -m unittest discover -s tests -q
python nfi_verify.py
```

校验将恢复 `data/nfi/freqtrade/futures/` 下 200 个交易行情文件和 40 个标记价格文件，并写入 `results/nfi/data_verification.json`。恢复文件使用 Freqtrade `jsongz` 格式；线性合约交易量采用 OKX `volCcy`（基础币数量），保留的原始归档另含合约张数和计价币成交量。没有以合约张数冒充基础币成交量。

所有重叠且完整的高周期 K 线会对照 5m 聚合检查 OHLC 和成交量。原数据存在缺口或哈希异常时拒绝发布成功记录，不补造价格。不会覆盖被用户修改过的恢复文件。

ETHW 等币种出现过原生零成交 5m K 线，OKX 会沿用前一成交价；它不代表该时段成交过这个价格。原归档保留这些行，跨周期 OHLC 校验只使用有成交的子 K 线（整组无成交时保留沿用价），避免将沿用价当成高周期真实开盘或极值。重新请求 API 已确认这一现象，并非缺口补造。

## 在云端接着研究

GitHub Actions 的 **NFI X8 dataset verification** 会执行标准库测试、数据恢复、周期交叉检查，再安装固定 Freqtrade 检查策略与数据能否读取；完整性记录可从 Artifacts 下载。此流程不会启动交易。

若要运行 X8，使用单独虚拟环境（不要把旧机器人配置复制进来）：

```sh
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# PowerShell: .venv/Scripts/Activate.ps1
python -m pip install -r research/nfi/requirements.txt
python nfi_verify.py
freqtrade create-userdir --userdir research/nfi/user_data
freqtrade list-strategies --userdir research/nfi/user_data --strategy-path research/nfi/upstream
freqtrade list-data --userdir research/nfi/user_data --datadir data/nfi/freqtrade --data-format-ohlcv jsongz --trading-mode futures --show-timerange
freqtrade backtesting --userdir research/nfi/user_data --config research/nfi/config.backtest.json --strategy-path research/nfi/upstream --strategy NostalgiaForInfinityX8 --datadir data/nfi/freqtrade --data-format-ohlcv jsongz --timerange 20260701-20261028 --fee 0.0005 --cache none --export trades --backtest-directory results/nfi/backtests
```

手续费 `0.0005` 是单边 5 bps 的显式研究假设，不是用户账户真实费率。这个命令还需要交易所市场规格等公开网络访问；行情本身已在仓库。对云端区域访问限制应记录错误，不允许静默改用 Binance 或现货数据。仅凭数据校验通过，不能声称完整 X8 回测已通过；应查看对应引擎执行记录。

## 偏差与下一步

当前存续状态、当前成交量与当前黑名单会产生存活者／事后选择偏差，包括上游可能因近期事故新增的黑名单。因此本批历史数据适合学习、找错误和建立可复现基线，不能证明历史实盘可达到同样收益。今后应按历史时点构建币种池，并保留退市币种，再做冻结规则后的前向模拟。

建议云端下一条任务：先阅读本文件、源码和 `source_manifest.json`，执行校验；固定原版 X8 做组合基线，不先 hyperopt；按币种、方向、入场标签、补仓与浮亏来源解释结果，然后一次只改一个机制。资金费未包含和当前币池偏差必须随每份报告披露。

## 重新下载／续传

```sh
python nfi_data.py download
python nfi_mark.py download
python nfi_data.py bundle
python nfi_verify.py
```

下载使用固定 `universe.json` 的窗口，不会自动滚动日期或重新选币；SQLite 检查点仅留本地。创建新窗口或扩大币种池时应新建有版本的研究清单，不能覆盖本轮已冻结的数据。原始大数据与 SQLite 不单独入 Git，上传的是可校验 ZIP 与汇总清单。

来源：
[NFI 固定源码](https://github.com/iterativv/NostalgiaForInfinity/blob/05b95e189ac5d301da2169ddec3118368f1b5c8b/NostalgiaForInfinityX8.py)、
[NFI README](https://github.com/iterativv/NostalgiaForInfinity/blob/05b95e189ac5d301da2169ddec3118368f1b5c8b/README.md)、
[Freqtrade 数据说明](https://www.freqtrade.io/en/stable/data-download/)、
[Freqtrade 回测说明](https://www.freqtrade.io/en/stable/backtesting/)、
[OKX API](https://www.okx.com/docs-v5/en/)。
