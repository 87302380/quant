"""Build a human-readable audit report from frozen research outputs."""
import json
from pathlib import Path
from dataclasses import asdict
from research import OUT,DATA,load,Config,features,metrics,dump


def main():
    dev=json.loads((OUT/'development.json').read_text())
    h=json.loads((OUT/'holdout.json').read_text())
    name=h['candidate']; candidate=json.loads((OUT/'candidate_full_metrics.json').read_text())
    bars=features(load(DATA),Config())
    base_dir=Path('results/okx_full_baseline')
    full={}
    for n in ('baseline','rsi','volume','rsi_volume'):
        trades=json.loads((base_dir/f'{n}_trades.json').read_text())
        full[n]=metrics(trades,bars,Config(),bars[0]['t'])[0]
    full[name]=candidate
    dump(OUT/'full_comparison.json',full)
    lines=['# OKX BTC 多周期策略研究回测报告',
        '', '运行日期：2026-10-28。数据：BTC-USDT-SWAP，2024-01-01 UTC 至 2026-10-27 18:30 UTC，98,954 根 15m K线；原生 1H/4H 已逐根核对。',
        '', '**结论：框架和真实行情回测已跑通；目前没有通过独立留出检验的可部署盈利策略。**',
        '', '较慢的4小时候选在全区间从原始方案的亏损改善为盈利，胜率也提高，但2026年留出仍亏损。全区间结果包含参与选型的数据，不能把它当作未来盈利证据。',
        '', '## 全区间诊断结果（连续复利，不重置账户）',
        '', '| 方案 | 净收益率 | 胜率 | 交易数 | PF | 最大回撤 |',
        '|---|---:|---:|---:|---:|---:|']
    labels={'baseline':'原始结构基线（修正版）','rsi':'基线 + RSI','volume':'基线 + 成交量','rsi_volume':'基线 + RSI + 成交量',name:'4h趋势回调候选'}
    for n,m in full.items():
        lines.append(f'| {labels[n]} | {m["return_pct"]:.2f}% | {m["win_rate"]*100:.2f}% | {m["trades"]} | {m["profit_factor"]:.3f} | {m["max_drawdown_pct"]:.2f}% |')
    lines+=['','初始净值10,000 USDT。4h候选全区间期末净值约10,931.16 USDT，年化约3.20%，最大连续亏损11笔；这不是高收益、高胜率系统。',
        '', '## 时间分割与候选筛选',
        '', '第一轮20个方案没有合格候选；随后增加12个4h低频方案，共32个最终方案。2024年用于训练，2025年在两轮研究中重复使用，已属于开发验证数据；2026年仅在规则冻结后评估，没有根据其结果再调参。',
        '', '筛选规则：训练、验证各至少20笔且均净盈利；在合格者中最大化两期较小的收益/回撤比。唯一入选者为 slow_pullback_both_3R。最终留出失败后应降级为研究候选，不自动启用交易。',
        '', '| 候选分段 | 净收益率 | 胜率 | 交易数 | PF | 最大回撤 |',
        '|---|---:|---:|---:|---:|---:|']
    for label,m in [('2024 训练',dev[name]['train']),('2025 开发验证',dev[name]['validation']),('2026 留出',h['results'][name])]:
        lines.append(f'| {label} | {m["return_pct"]:.2f}% | {m["win_rate"]*100:.2f}% | {m["trades"]} | {m["profit_factor"]:.3f} | {m["max_drawdown_pct"]:.2f}% |')
    lines+=['', '分段回测各从10,000重置，使用此前行情预热，并在分段末尾强制平仓；因此不能直接把分段收益相乘来替代连续回测。',
        '', '## 候选实际规则',
        '', '- 只在完整4h收盘后做决定，下一根15m开盘含滑点执行。',
        '- EMA25/99及4h收盘位置判断多空方向；价格触及EMA25后收回，并突破上一根4h高/低触发。',
        '- 入场规划止损为2倍4h ATR14，目标3R（以信号收盘价规划，实际成交后重算净RR）。最长持仓30天。',
        '- 多空均允许；单笔计划风险最多1%，全额抵押、名义金额不超过权益，不加杠杆。',
        '- 这是一套与最初15m二次测试不同的对照策略，保留原始方案，未把其结果冒充原策略优化。',
        '', '## 2026年独立留出对照',
        '', '| 方案 | 净收益率 | 胜率 | 交易数 | PF | 最大回撤 |',
        '|---|---:|---:|---:|---:|---:|']
    for n,m in h['results'].items():
        lines.append(f'| {labels[n]} | {m["return_pct"]:.2f}% | {m["win_rate"]*100:.2f}% | {m["trades"]} | {m["profit_factor"]:.3f} | {m["max_drawdown_pct"]:.2f}% |')
    ci=h['results'][name]['uncertainty']['daily_mean_return_95pct']
    lines+=['',f'同期含成本买入持有收益约{h["buy_hold"]["return_pct"]:.2f}%。候选日均收益的14天分块重采样95%区间约[{ci[0]*100:.4f}%, {ci[1]*100:.4f}%]，跨越0；该区间未校正多重选型，不能视为显著优势。',
        '', '成交量版本的留出收益虽为正，但此前表现差，留出只有14笔；RSI加成交量仅5笔。看到结果后改选它们会污染留出，必须在未来新数据或未使用品种验证。',
        '', '## 成本压力测试：冻结4h候选，2026年',
        '', '| 场景 | 单边手续费 | 单边滑点 | 净收益率 |',
        '|---|---:|---:|---:|']
    for label,fee,slip in [('normal',.05,.02),('moderate',.075,.04),('severe',.10,.06)]:
        lines.append(f'| {label} | {fee:.3f}% | {slip:.3f}% | {h["stress"][label]["return_pct"]:.2f}% |')
    lines+=['', '资金费率按用户要求完全关闭，长期永续持仓的实际成本可能不同；当前结果不是完整实盘净收益预测。',
        '', '## 诊断与改进方向',
        '', '1. 原始结构基线全区间342笔、PF约0.61，多空都亏，不能仅增加交易频率或放大风险。止损太近时，双边费用占风险的比例增大；本轮放宽止损、止盈封顶、ADX过滤仍未在2025年稳定改善。',
        '2. RSI只在2024年改善，2025/2026转亏；不能作为默认盈利确认。成交量过滤的效果也跨年份不稳定。评分仍是研究标签，不能用分数替代概率。',
        '3. 降低频率改善全区间结果，值得作为下一阶段研究起点，但候选2026多空均亏。暂不因为留出表现删除某一侧，也不据此继续调参数。',
        '4. 下一轮应先补未参与研究的ETH等合约与未来模拟盘，检验是否有跨市场一致性；增加1m数据验证盘中成交次序，逐步补真实交易规则与订单成交模型。',
        '5. 如果继续研究高胜率策略，应单独预注册均值回归假设并同时限制平均亏损、尾部回撤和成本，不能用无限补仓、摊平、取消止损把胜率做高。',
        '', '## 代码修正与核验',
        '', '- 修复二次测试已确认后结构被再次破坏却仍可能触发的情况；修正版基线与初次训练诊断会不同。',
        '- 保留下一根开盘成交、已确认摆动点、已收盘多周期对齐、同根止盈止损按止损、跳空更差止损成交等规则。',
        '- 新增训练/验证/留出隔离、预热、低频对照、逐15m收盘盯市净值、月度收益、成本压力测试、分块重采样。',
        '- 13项测试通过，覆盖因果性、收盘对齐、模拟成交、风险仓位、时间边界、盯市回撤与下载器。',
        '', '最大回撤以15m收盘盯市净值计算，含开仓费用和预计平仓费用，不是逐tick真实盘中回撤。市场冲击、盘口深度、真实资金费、历史规则变化、标记价格、部分成交未建模；合约面值/步长当前仍是研究配置。',
        '', '## 互联网研究如何用于本轮',
        '', '- [Bailey等：The Probability of Backtest Overfitting](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)：反复试配置容易得到历史最优但样本外失效的方案。因此记录两轮研究、保存配置与数据哈希、冻结后才打开2026年。本文没有声称已计算正式PBO或多重比较校正。',
        '- [AQR：A Century of Evidence on Trend-Following Investing](https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-JPM-Fall-2017.pdf)：趋势跟踪研究需要同时考虑成本与多市场证据。本轮据此加入更慢趋势对照；其跨资产长期结果不证明BTC 4h策略有效。',
        '', '## 复现',
        '', '```powershell',
        'python -m unittest discover -s tests -v',
        'python pullback.py data/okx/BTC-USDT-SWAP_15m_1704067200000_1793125800000.csv --config config.example.json --out results/okx_full_baseline',
        'python research.py --stage develop',
        'python research.py --stage final',
        '```',
        '', 'experiment_plan.json保存32套参数和选择规则；selection.json保存冻结选择；holdout.json包含留出结果、压力测试和买入持有；各方案逐笔交易、信号拒绝原因和留出净值曲线均保存在同一目录。重复运行同一冻结方案不等于获得新的独立留出集。',
        '', '**当前建议：不启用实盘。保留4h候选做进一步独立验证，部署风险预算维持0。**']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    spec=json.loads((OUT/'candidate_config.json').read_text())
    spec.update(research_status='rejected_for_deployment_after_2026_holdout',live_trading_enabled=False)
    dump(OUT/'candidate_config.json',spec)
    print(OUT/'REPORT.md')


if __name__=='__main__':main()
