# 云端运行与迁移记录

## 新增 NFI X8 多币种专项

用户已授权研究 OKX USDT 永续的 NFI X8，并于 2026-10-29 扩充到当前成交额前 100 币。先阅读 `research/nfi/README.md`，执行 `python nfi_verify.py`，从仓库归档恢复 5m/15m/1h/4h/1d 行情及 1h 标记价格。没有资金费数据。8 个新币不足 200 根日线，阅读 `research/nfi/expansion100/coverage.json`，不要假设全部同日具备交易条件。原 40 币配置保存在 `research/nfi/snapshots/40-pair/`。NFI 使用独立的 Freqtrade 依赖与静态配置；原 BTC 入口不变。GitHub Actions 的 `NFI X8 dataset verification` 提供云端数据与引擎读取检查。

仓库只包含独立研究项目，旧 `D:/quant/freqtrade` 不属于此仓库。

## 开始

从仓库根目录执行，使用 Python 3.10 或更新版本；本地已在 Python 3.14.4 测试。

```sh
python --version
python cloud_data.py
python -m unittest discover -s tests -q
python btc_bear.py
```

或者一条命令执行全部检查与回测：`python cloud_verify.py --backtest`。

## 直接在GitHub云端运行

在仓库页面打开 **Actions → BTC cloud tests and backtest → Run workflow**。推送main分支也会触发相同流程：Ubuntu云端检出仓库、安装Python 3.14、恢复校验数据、运行测试和当前熊市专项回测。无需保持本地电脑开机。

任务完成后在该次运行的 **Artifacts** 下载 `btc-research-运行编号`，其中包含执行记录、报告、汇总和逐笔结果，保留14天。`cloud_execution.json`记录运行时间、Python版本、数据清单哈希和各阶段状态；失败时也会保存已完成阶段，避免把旧报告误认为新运行结果。

当前脚本均只使用Python标准库，不必安装交易框架。`cloud_data.py` 从仓库内压缩归档恢复4份BTC行情（5m、15m、1H、4H）并核对SHA256，因此回测无需重新访问OKX。行情更新才需要网络。

## 研究上下文

优先阅读 `RESEARCH_SCOPE.md`、`README.md` 和 `results/btc_bear/REPORT.md`。当前约定：仅BTC、不使用2024年前数据、近期熊市场景优先；4h/1h判断方向和支撑压力，5m确认入场；资金费关闭，手续费和滑点保留；不把反复查看过的历史称为新独立留出。

当前没有通过预设筛选、适合实盘的近期熊市候选。跨2024—2026的高收益研究版本只保留作对照，不能代表当前有效性。

## 文件保存策略

- 代码、测试、关键报告、参数、汇总JSON和原始行情manifest入库。
- BTC CSV以确定性gzip归档放在 `datasets/`，恢复到 `data/okx/`。
- SQLite缓存、虚拟环境、日志、临时文件、完整逐笔JSON和权益CSV不入库；本地原件保留，云端可运行对应脚本重新生成。
- 不包含旧机器人配置、交易所凭据或实盘交易数据库。仓库脚本不会自动下单。

示例：`python btc_locations_refine.py` 生成位置策略逐笔结果；`python btc_profit.py` 生成盈利加仓对照；`python btc_v2.py` 生成V2研究记录。

修改代码前先运行测试。云端需延续研究时，应先确认当前研究范围，再选择入口；不要仅挑选全区间收益最高的参数。
