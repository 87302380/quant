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

后续基线须同时报告：扣手续费后的已实现与未实现收益、期末强制平仓、最大权益回撤、最长持仓、补仓次数和资金占用、币种集中度、long/short 与 entry tag 分组。不能只汇报平仓胜率。用同一个初始钱包做多币组合，不得把各自分配完整本金的单币收益直接相加。数据池扩为 100 币，最大同时持仓仍为 6，没有因此放大仓位。

## 本次数据范围

市场是 **OKX 线性 USDT 永续合约**，不是现货。2026-10-29 用户要求扩充至热度与交易量前 100 个币种，当前固定 100 币：见 `pairs.json`、`universe.json` 和 `expansion100/selection.json`。

便于阅读的完整排序表见 [100币名单及成交额](expansion100/PAIRS.md)，可执行 `python nfi_expand.py summary` 重新生成；执行 `python nfi_expand.py verify` 离线复算候选完整性及前100排序。

本次使用 OKX 原生最近 24 根已收盘 1h K 线的 `volCcyQuote` 合计，按**真实 USDT 成交额**降序取 100，而非上一批的 `volCcy24h × last` 近似值。具体排名时点和 24h 起止时刻已冻结在选择清单。热度指成交活跃度，没有混入无法核验的社交热度分数。

候选条件：仍为 live、线性 USDT 结算、`instCategory=1`（加密币），上市至少 60 天，扣除固定 NFI 版本的黑名单。排除股票、金属、商品、外汇和债券合约。202 个候选均成功获取排名证据，再取前 100；未因 API 失败静默跳过任何候选。100 币中 57 个出现在官方静态列表，43 个不在；静态名单并不等于当下成交量排名。

已核对官方 `pairlist-volume-okx-futures.json`：110 个成交量候选，`AgeFilter=60` 天，`RangeStabilityFilter` 最近 3 天振幅 0.03–0.95，另有依赖持仓状态的 `FullTradesFilter`。本批是**100 币研究数据池**，不是宣称完全复刻某一时刻的官方实盘池。记录最近 3 天振幅和过滤通过标签（当时 95/100 通过），不据此删除历史数据；实际回测应根据当时已收盘数据重建过滤，不能把今天的振幅标签倒灌到历史。README 建议 40–80 币属运行建议，本次按用户要求扩大数据覆盖，未同步增加持仓数。

原 40 币全部复用，新增 60 币。原始配置、清单、哈希与币池保存在 `snapshots/40-pair/`，同一份行情归档不重复存储；原 40 币配置仍可配合当前数据做对照。原研究的选择偏差与结论不因扩池而消失。

`expansion100/coverage.json` 给出每币上市后的数据起点、7 月 1 日前日线数量及 200/480 根日线最早就绪日期。CAP、IRYS、GRVT、CHIP、VVV、MEGA、BILL、GRAM 在截止时不足 200 根日线；上市后才有数据的币种从首个完整周期下载，绝不补造上市前价格。实际指标有各自就绪条件，不能假设 100 币在 7 月 1 日同时可交易。

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

仓库中 `datasets/nfi/` 的 100 个 ZIP 各装一个币种的原生 gzip 文件，使用无重复压缩的确定性封装；无需 LFS、令牌或访问 OKX 即可恢复历史数据。逐文件及 ZIP SHA256 都有清单。

在仓库根目录执行：

```sh
python -m unittest discover -s tests -q
python nfi_verify.py
```

校验将恢复 `data/nfi/freqtrade/futures/` 下 500 个交易行情文件和 100 个标记价格文件，并写入 `results/nfi/data_verification.json`。恢复文件使用 Freqtrade `jsongz` 格式；线性合约交易量采用 OKX `volCcy`（基础币数量），保留的原始归档另含合约张数和计价币成交量。没有以合约张数冒充基础币成交量。

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

当前存续状态、当前成交量与当前黑名单会产生存活者／事后选择偏差，包括上游可能因近期事故新增的黑名单。排名时点晚于许多历史 K 线，原数据统一截止时间特意保留以便复用；绝不能把这种当前选币倒推历史的研究称为历史时点交易池或独立样本外验证。今后应按历史时点构建币种池，并保留退市币种，再做冻结规则后的前向模拟。

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

## 固定风险空头实验（2026-10-29）

按用户最新要求取消增加仓位方向，研究ATR退出、BTC熊态门控及个币相对弱势。方案见[atr_short/plan.json](atr_short/plan.json)，报告见[固定风险空头实验](../../results/nfi/atr_short/REPORT.md)，入口`python nfi_atr_short.py`。所有变体沿用24h期限和实际引擎，未启动实盘。

## 小周期相对BTC强弱（2026-10-29）

使用已收盘5m滚动计算15m/1h/4h强弱，测试多空分方向过滤和Beta残差，不增加初始仓位。方案见[fast_rs/plan.json](fast_rs/plan.json)，报告见[fast_rs研究](../../results/nfi/fast_rs/REPORT.md)，入口`python nfi_fast_rs.py`。

## 组合稳健性与风险管理（2026-10-29）

比较ATR多头风控、组合计划风险、BTC冲击/波动及相关性上限，并保留简单减仓/限仓对照。入口`python nfi_portfolio.py`，规则见[portfolio_risk/plan.json](portfolio_risk/plan.json)，报告见[组合风险研究](../../results/nfi/portfolio_risk/REPORT.md)。无实盘服务。

## 多头入场与交易失效（2026-10-30）

新增[long_entry研究边界](long_entry/FORWARD.md)及[结果报告](../../results/nfi/long_entry/REPORT.md)。原信号即时止跌/突破确认、30分钟延迟确认、6h后结构失效均在真实引擎比较，空头规则及原仓位上限保留。逐笔对照包含被误杀的原盈利单，不以删除亏损交易计算收益。

## 按多头触发原理分组（2026-10-30）

新增[long_family研究边界](long_family/FORWARD.md)及[结果报告](../../results/nfi/long_family/REPORT.md)，对顺势回调/转强/突破与急跌修复分别验证过滤、退出、相对卖压及限价执行，原生混合标签保留。记录固定规则、执行失败、原入场时点匹配及钱包机会成本，不按旧亏损是否消失选型。

## 市场广度与同步冲击（2026-10-30）

新增[breadth研究边界](breadth/FORWARD.md)及[结果报告](../../results/nfi/breadth/REPORT.md)。分别测试冲击门控、已有多头退出、BTC对照及最多2多头；随后依据已看到的原路径诊断，追加将近期冲击作为纯反弹组机会条件的明确事后探索。原阈值不变，费用、重启与固定反向币种排序均保留成对证据，不自动晋级核心。
