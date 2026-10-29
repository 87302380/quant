# 多周期支撑压力回调策略

原 BTC 回测与数据工具使用 Python 3.10+ 标准库，不发送订单。新增 NFI X8 专项使用独立的 Freqtrade 依赖，见文末研究入口。

## 云端快速开始

```sh
python cloud_verify.py --backtest
```

该命令从仓库内的 `datasets/` 恢复并校验四份BTC行情，运行全部单元测试，再执行当前熊市专项回测。无需本机文件、交易所密钥或额外Python依赖，运行现有历史回测也无需访问OKX。详见 [云端说明](CLOUD_SETUP.md)。

也可在GitHub仓库的 **Actions → BTC cloud tests and backtest → Run workflow** 直接运行，结束后下载该次运行的结果归档。

## 当前优先：近期熊市场景

按最新用户约定，仅BTC、不使用2024年前数据，2024年收益不主导当前策略选型。详见 [研究范围](RESEARCH_SCOPE.md)。`python btc_bear.py` 比较2026年下跌延续、反弹到压力做空、强支撑短暂做多，分为1—6月训练、7—8月验证、9月至今近期确认；全部历史均已被查看，非新独立留出。最新17方案结果见 [熊市专项报告](results/btc_bear/REPORT.md)，目前无合格候选，33项测试通过。

`btc_profit.py` 的盈利后加仓等跨2024—2026研究仅保留作对照，不用其中牛市贡献较大的收益代表当前有效性。

## 最新：高周期位置＋5m触发

本轮按4h/1h判断趋势和位置、5m只做入场触发，完成27个对照和31项测试。见 [本轮总结](results/btc_locations/SUMMARY.md)。盈利位置研究版单独回放：

```powershell
python run_location_candidate.py --style balanced
python run_location_candidate.py --style high_win
```

前者全区间净收益22.79%、胜率49.68%；后者9.94%、58.97%。两者成本翻倍均亏损，尚未同时超过趋势基准的收益与胜率，不能作为稳定盈利证明。

## 5m数据与最新确认

已下载296,862根BTC 5m数据，聚合价格、成交量与现有15m完全一致。运行 `python verify_5m.py` 校验；`python btc_5m.py` 复核旧策略成交并运行12个5m短线方案；`python btc_5m_conclusions.py` 用5m复核趋势对照。详见 [5m研究报告](results/btc_5m/REPORT.md)。本轮没有合格盈利短线候选，28项测试通过。研究方向仍按用户偏好保留震荡短线＋突破趋势，未开启实盘。

## 当前研究偏好：震荡短线为主、突破转趋势

`python btc_scalp.py` 实现震荡短线、被动限价成交近似，以及突破后切换趋势仓的20个对照，详见 [短线模式报告](results/btc_scalp/REPORT.md)。当前版本虽有约60%胜率和较高交易频率，净收益仍为负，不能采用。15m数据不能证明秒级剥头皮可盈利。

此前的1h回调、15m趋势中继与战术止盈实验分别运行 `python btc_v4.py`、`python btc_v4_extension.py`，记录保存在 `results/btc_v4/`。

## BTC V3 对照研究

`python btc_v3.py` 对比ADX/路径效率过滤、保本止损、快慢EMA和等资金组合。结果见 [V3报告](results/btc_v3/REPORT.md)。本轮没有找到同时改善V2收益和回撤的方案，继续保留V2研究候选；组合集中度额外用统一自然月口径核对，避免拆分交易造成的统计误导。

## BTC V2 当前改进

已落地并运行 BTC 专用的趋势移动止损、连亏暂停和过去365天逐月选型。结果及成本压力测试见 [BTC V2 报告](results/btc_v2/REPORT.md)。所有BTC历史均已参与研究，结果是探索性回放；ETH下载已停止，未用于策略选型。

```powershell
python btc_v2.py --mode single --strategy trend_both_pause
python btc_v2.py
python btc_v2_report.py
```

`btc_v2.py` 全量运行18个固定对照及滚动选型，`--mode single` 单独回测指定版本。输出在 `results/btc_v2/`，候选规则与风险配置保存在 `candidate.json`。原15m结构策略及前两轮研究记录保留。

OKX 下载方案与命令见 [OKX_DATA.md](OKX_DATA.md)，工具入口为 `download_okx.py`。

## 真实行情研究结果

已运行真实 OKX 行情回测与两轮共32个最终方案对照。完整结果见 [研究报告](results/research/REPORT.md)。4h低频候选全区间表现改善，但2026年留出亏损，当前没有通过独立验证的可部署方案。

```powershell
python research.py --stage develop
python research.py --stage final
```

`research.py` 实现4h候选等对照方案，`pullback.py` 保留原始15m结构策略。候选参数是研究记录，不能将 `candidate_config.json` 直接传给原始策略CLI。请保留原有实验记录；修改规则后，2026年不再是未使用的留出集。

## 运行

在本目录运行：

```powershell
python -m unittest discover -s tests -v
python pullback.py candles.csv --out results/btc
python pullback.py candles.csv --config config.example.json --out results/custom
```

输入 CSV 必须是连续、完整、已收盘的 15m OHLCV。timestamp 是带时区的开盘时间；UTC 对齐，拒绝乱序、重复、缺失和无效价格。调用方须排除未收盘 K 线。示例表头及格式：

```csv
timestamp,open,high,low,close,volume
2025-01-01T00:00:00Z,93000,93200,92800,93100,120
```

建议至少提供 120 天行情，前 99 根完整 4h 用于预热。没有行情文件时不会伪造历史收益。

## 冻结的第一版定义

- 4h EMA25/99 与收盘位置定义方向；1h EMA25/99、4h EMA25 和 1h/4h 已确认摆动点组成水平区域。相邻区域按 1h ATR 合并，15m ATR 扩展边界。
- 摆动点左右各 2 根，右侧收盘后才可使用。区域第一次触及时冻结；之后需先有距首次极值 0.5 ATR 的恢复收盘，再出现独立二测。二测容忍 0.2 ATR，确认 K 线方向与交易一致。每个设置最长 8 根，失效后重建。
- 二测成立，收盘突破前一根高/低且收回区域下沿/上沿触发。下一根开盘含滑点执行；入场距结构极值超过 1.5 ATR 拒绝。
- 止损为两次测试极值外 0.2 ATR；目标为最近的已确认 1h/4h 对侧摆动点。止损、目标按 tick 取整，再用成交价重算净 RR，至少 1.5。
- RSI14 使用 Wilder 平滑，记录 1h/15m；区域内最近至多 8 根曾 <=35 / >=65 且当前恢复。量比使用当前量 / 此前 20 根平均量。ADX/DI 和距 4h EMA25 的 ATR 倍数只记录。
- 评分：方向20、区域20、二测20、净RR10、区域重合10、RSI10、成交量10。只有通过硬条件的成交才具有净RR分；分数不是胜率。当前硬条件使低分桶可能没有交易。
- 多空阈值可分别配置。CLI 固定执行 baseline、RSI、volume、RSI+volume 四组独立权益回测，不使用评分筛选。

## 成交与风险模型

单品种、最多一笔持仓，因此组合风险由单笔风险与 total_risk 的较小值控制。按净值最多 1% 和包含费用的止损损失算张数，向下按 lot_size 取整。全额抵押、杠杆固定 1，另外限制名义金额及开仓费不超过权益。

费用包含双边手续费与滑点。当前按用户要求关闭资金费，默认 funding_per_8h=0。若手动启用，则按每开始一个 8h 持有区间收取保守成本（两个方向均收费），规划 RR 和仓位预留最大持有期资金费；真实资金费需要历史结算序列。

同根同时触及止损和目标按止损；跳空穿越止损按更差开盘成交。目标按保守目标价减滑点成交。到期按收盘市价退出，数据末尾强制平仓。止损不是保证，跳空可能使实际亏损超过计划 1%。

config.example.json 的合约面值、最小张数、步长、tick 仅为研究假设。真实 OKX 衍生品数量单位为张，必须从当前 instruments 数据取得 ctVal、lotSz、minSz、tickSz 并验证线性 USDT 合约，不能复用陈旧缓存：<https://www.okx.com/docs-v5/en/>。

尚未实现交易所执行适配器、实时行情延迟检查、真实强平计算、订单回执/部分成交、标记价格、跨品种组合与真实资金费。因此本项目不能直接用于实盘，也不接管旧机器人。

## 输出与验证

每组输出 trades.json（每笔指标、区域、止损目标、仓位、费用后收益）与 signals.json（成交及拒绝原因）；summary.json 包含多空和评分桶交易数、胜率、平均净利润、PF、最大连续亏损；config.json 保存参数。PF 无亏损时为 null，需结合交易数解释。

先冻结参数再按时间分训练/验证/最终留出集，保留各段足够预热数据，独立运行四组比较。不要根据最终留出集调阈值或权重。合成数据测试只验证计算与因果性，不证明盈利。
# 新增研究入口

## NFI X8 最新研究与年初至今数据（2026-10-29）

- [空头增强：原生扩展、镜像及状态开关](results/nfi/short_search/REPORT.md)：同口径扩展版收益444.89%/回撤25.64%，状态开关版349.59%/18.86%；近期四个月仍未超过旧核心，保留全部失败方案和执行精度证据。

- [收益优先：11项机制及3次成本重跑](results/nfi/return_search/REPORT.md)：最佳历史收益184.01%、含浮亏回撤16.56%，双倍手续费收益175.92%；保留全部失败方案，未启用实盘。

- [首轮组合研究](results/nfi/study/REPORT.md)：原版、币池、杠杆、成本与仓位管理对照，含浮动权益审计。
- [24小时持仓上限验证](results/nfi/study/DEADLINE_24H.md)：首次入场计时，所有候选均须满足24小时上限。
- [61笔交易的亏损诊断与优化实测](results/nfi/risk_study/REPORT.md)：保留紧止损等失败结果，明确事后80/20过热假设的样本内偏差。
- [57币年初至今四组优化实测](results/nfi/ytd_research/REPORT.md)：基线、过热过滤、单笔风险预算与同向上限，152笔逐笔诊断；含浮亏回撤与停止状态的前向模拟计划。
- [推荐57币年初至今数据完成记录](research/nfi/ytd2026/SUMMARY.md)：独立扩展到2026-10-29北京时间11:15，342份原生数据及引擎读取验证，不覆盖旧窗口。

新数据恢复：`python nfi_ytd_verify.py`，随后用独立虚拟环境执行 `python nfi_ytd_engine_verify.py`。原生ZIP与SHA256清单位于 `datasets/nfi_ytd2026/`；关键真实引擎压缩回测结果连同研究报告保留在 `results/nfi/`。SQLite、临时缓存和大型权益CSV不上传，可由脚本重建。

上述历史均用于探索，包含今天选币倒推历史的偏差，资金费按约定未计入；没有实盘启用，也没有将新增历史称为独立样本外或未来完整全年的实绩。

用户授权的 [NFI X8 多币种永续专项](research/nfi/README.md)：已扩充至真实成交额前 100 个加密币永续合约，保留原 40 币对照；固定源码、原生多周期行情、真实标记价格、离线恢复与云端检查。执行 `python nfi_verify.py` 开始；未下载资金费。原 BTC 研究保留。
