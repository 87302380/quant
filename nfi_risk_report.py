"""Report all61 campaign diagnostics and retain successful/failed risk controls."""
import json
import os
from pathlib import Path

os.environ.setdefault('MPLCONFIGDIR','/tmp/nfi-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import pandas as pd

from nfi_analyze import load_result

ROOT=Path(__file__).resolve().parent


def main():
    out=ROOT/'results/nfi/risk_study'
    diagnosis=json.loads((out/'trade_diagnosis.json').read_text())
    comparison=json.loads((ROOT/'results/nfi/study/comparison.json').read_text())
    labels={'official_24h':'原版57币＋24小时','risk_stop3':'首单逆向价格3%硬止损',
            'risk_stop6':'首单逆向价格6%硬止损','risk_stale12':'12小时后整笔亏损即退出',
            'risk_trendgate':'闭合4h趋势准入','risk_profitprotect':'闭合5m有利2%后保护首单成本',
            'official_1x_24h':'相同24小时版本降到1倍', 'risk_overheat80':'闭合4h RSI80/20过热过滤（事后假设）'}
    def latest(key):
        return load_result(sorted((ROOT/'results/nfi/study'/key).glob('*.zip'))[-1])
    base=latest('official_24h')
    original={(t['pair'],t['open_timestamp']):t for t in base['trades']}
    matched={}
    for key in labels:
        current={(t['pair'],t['open_timestamp']):t for t in latest(key)['trades']}
        common=original.keys()&current.keys()
        matched[key]={'same_entry_matches':len(common),
                      'old_win_now_loss':sum(original[k]['profit_abs']>0 and current[k]['profit_abs']<0 for k in common),
                      'old_loss_now_win':sum(original[k]['profit_abs']<0 and current[k]['profit_abs']>0 for k in common),
                      'missing_old_entries':[{'pair':original[k]['pair'],'open_date':original[k]['open_date'],
                                             'profit_usdt':original[k]['profit_abs']} for k in original.keys()-current.keys()],
                      'new_entries':len(current.keys()-original.keys())}
    (out/'matched_campaigns.json').write_text(json.dumps(matched,indent=2)+'\n')
    losses=[t for t in diagnosis['campaigns'] if t['profit_usdt']<0]
    gross_loss=-sum(t['profit_usdt'] for t in losses)
    top4=-sum(t['profit_usdt'] for t in losses[:4])
    text=f'''# 57币61笔交易：亏损原因与优化实测

## 结论

研究对象为2026年7月1日至10月27日的57币、3倍杠杆、统一10000 USDT钱包、6槽位、24小时硬期限版本。61笔完整持仓中47赢、14亏，净赚3010.07 USDT。14笔均因24小时期限退出；总亏损{gross_loss:.2f}，其中ALGO、OP、XRP、AR四笔亏{top4:.2f}，占{100*top4/gross_loss:.2f}%。已分析所有盈利仓，以检查止损对恢复性盈利的误伤，未按币种或标签事后删除亏损。

**简单收紧止损没有改善本批组合；避免极端过热入场是一个有正向样本内结果的候选，但收益改善来自已知的两笔亏损，不能视作独立验证。** 持续单边下跌存活性仍未验证。降低杠杆能降低绝对风险，不提高信号本身的预测能力。

全部新实验都使用真实Freqtrade2026.9重跑完整组合和资金路径，原版源码不改，独立空userdir，保留5bps逐次手续费与24h限制。没有实盘。资金费仍未计入，静态币池、固定策略版本和所有已见历史存在选择偏差。

## 逐笔亏损证据

时间为北京时间（Asia/Shanghai）；浮盈/浮亏按已闭合5m收盘重估，包含已发生的加减仓、手续费和剩余仓位预估平仓费，不是保证可成交的逐tick价格。MAE价格为首次入场以来的最大逆向价格变动（使用5m高低价）；它不是账户亏损比例。14笔均持有24小时。

| 币种/方向/标签 | 入场北京时间 | 最终净盈亏USDT | 6h净盈亏 | 12h净盈亏 | 曾有最高净盈亏 | 最大逆向价格 | 入场4h RSI14 | 入场次数 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
'''
    for t in losses:
        date=pd.Timestamp(t['open_date']).tz_convert('Asia/Shanghai').strftime('%m-%d %H:%M')
        text+=f"| {t['pair'].split('/')[0]} / {t['side']} / {t['tag']} | {date} | {t['profit_usdt']:.2f} | {t['at6h']['pnl_usdt']:.2f} | {t['at12h']['pnl_usdt']:.2f} | {t['max_sampled_pnl']['pnl_usdt']:.2f} | {t['max_adverse_price_pct']:.2f}% | {t['own4h_at_entry']['RSI14']:.1f} | {t['entries']} |\n"
    text+='''
### 观察到的失败类型

- **ALGO143：入场后一直缺乏恢复。** 闭合5m采样从未净盈利，6小时已经亏191.64，12小时亏200.03；到期亏262.47。它入场时4h RSI64.6、EMA12高于EMA200，普通上行趋势过滤照样放行。需要约束单笔/组合风险，不能只靠等趋势判定翻空或等24小时。
- **OP144和XRP144：同一时段强势行情后的回撤。** 两笔北京时间8月22日15:50/16:05入场，4h RSI83.6/88.9，价格分别高于4h EMA200约28%/44%，随后逆向最大约6.4%。不是缺少上升趋势，而是趋势已拉伸后入场仍可能失败；同方向相关性导致损失集中。不能由此推出所有高RSI交易必亏。
- **AR64：趋势回调演变为深回撤，并发生加仓。** 入场4h RSI78.5，价格高于EMA200约80.5%，仍满足趋势确认；最大逆向价格15.11%，两次入场，6/12小时均亏。说明长期均线具有滞后，名义上的趋势回调不能替代资金损失约束。
- **FIL等：浮盈回吐。** FIL曾有约109.27净浮盈，最终亏41.05；OP和XRP也曾有正浮盈。利润保护有理由实验，但将每次小浮盈迅速锁住也会损害大盈利；必须看完整组合结果。
- **小亏的short rebuy：等待下跌恢复与交易摩擦。** JTO最大逆向价格5.84%；其余一些空头最终只小亏或接近持平。对HBAR这类-0.14 USDT结果，不宜为了消除每一笔亏损制造复杂规则。提前12小时平BCH还可能比等24小时更差：原路径12小时亏58.21，最终只亏2.84。

这些是价格、仓位和指标层面的可观察失败路径；没有新闻/订单簿证据来断言外部事件原因。

## 提前退出会误伤谁

原47笔盈利持仓中14笔曾逆向超过3%，4笔超过6%；12小时仍处于亏损但最终盈利的持仓有7笔，最终贡献约851.69 USDT。不能因为14笔坏单最后亏损，就事后要求它们都在最优时点退出。

真实3%止损实验将14笔原盈利持仓变成亏损。例如ICP由+348.79变为-146.96、ARB由+292.20变为-145.15、SUI由+206.28变为-145.27。AR的大亏确实减少了，但不能抵消对其他恢复性交易的损害。新交易和复利也发生改变，不能只加总“救回原亏损”的金额。

## 真实组合重跑

每个改动单独对照原24h版本，没有将效果叠加拼成未经运行的候选。3%/6%是标的价格止损，3倍杠杆下约相当于单次初始保证金9%/18%的损失尺度，绝非账户仅亏3%/6%。实际仍受仓位、加减仓、费用、跳空影响。

| 方案 | 净收益 | 含浮亏最大回撤 | 胜率 | 完整持仓数 | 最长小时 |
|---|---:|---:|---:|---:|---:|
'''
    for key,label in labels.items():
        r=comparison[key]
        text+=f"| {label} | {r['return_pct']:+.2f}% | {r['equity_audit']['mtm_drawdown_pct']:.2f}% | {r['win_rate_pct']:.2f}% | {r['campaigns']} | {r['max_holding_hours']:.2f} |\n"
    text+='''
- 12h规则是“从第12小时起，整笔累计净利润为负就退出”，不是只在12小时检查一次；包含此前部分退出盈亏。实际有9笔原盈利交易变为亏损。只看12小时那个截面会低估误伤。
- 严格趋势门槛使用该币已闭合4h EMA12/EMA200和4h收盘价；它过滤了5笔原盈利交易，却没有去掉原14笔亏损。仅加强趋势确认未解决这批失败原因。
- 利润保护为闭合5m有利价格变动达到2%后，把保护价设在首次入场成本有利0.15%一侧。没有初始硬止损；保护价受首单而非加仓后整笔净利润定义，不能保证整笔保本。它将2笔原亏损变盈利，仍因减少其他盈利而降低总收益。
- 1倍24h版本是资金风险对照，收益和回撤都降低；不能拿它与3倍只比较绝对收益，也不能称它改善了策略信号。

### 过热过滤的正向结果及偏差

最后一项是在发现OP/XRP高RSI后提出的事后假设：4h RSI14>=80不新开多，<=20不新开空，使用已闭合指标；其他行为不变。它避免了原来的OP、XRP两笔亏损。本批原盈利多头没有4h RSI>=80，因此此次漂亮的改善高度依赖同一个已知时段，样本只有两笔，存在明显的样本内选择偏差。

这可作为**冻结后前向模拟的候选**，不能宣称已得到可靠优化，更不应继续围绕这两笔扫描79/81等阈值。本轮仍没有证明可以同时提高收益并降低含浮亏最大回撤的稳健改动；不能用更好看的已平仓回撤代替浮动权益回撤。

## 优化优先级

1. 保留24小时硬期限；接受合理亏损，不以恢复100%胜率为目标。
2. 把“过热准入”保留为独立候选，冻结80/20，不与其他改动随意叠加；用后续新行情检验是否仍减少坏单。
3. 下一项最值得设计的是**按净值预算整笔风险，包含加仓，并限制相关币同方向总暴露**。原版按槽位分资金不是按止损损失定仓，OP/XRP的同步亏损正说明了这个区别。该组合风险预算本轮未实现，不能声称有效。
4. 若希望先控制绝对损失，1倍24h对照已经有证据；若继续3倍，不能将时间止损或某个价格阈值理解为账户最大亏损保证。
5. 对单边下跌另做真实片段独立启动与各截止点浮亏结算。当前61笔只有四个月，所有历史都已看过，没有独立OOS；未计真实资金费与执行细节仍是限制。

例如净值10000、单笔预算50 USDT、标的价格止损3%、3倍杠杆，忽略费用时应约分配555.56 USDT保证金，而不是直接按6槽位分出1650；加仓也必须共享同一个50 USDT预算。此处只是风险计算示例，不是新回测或对用户风险预算的擅自设定。

## 证据与复现

`trade_diagnosis.json`保存全部61笔的6/12/18小时净利润、最大不利价格、采样浮盈浮亏和入场闭合4h指标；每笔路径期末与引擎净利润核对。`matched_campaigns.json`记录同币同入场时刻的转亏、转盈和新增/缺失交易，金额变化也受复利仓位影响。各方案`analysis.json`包含权益对账、完整归因、逐成交滑点压力与24h期限核对；原始引擎压缩结果和日志均保留。

```sh
.venv/bin/python nfi_loss_diagnosis.py
.venv/bin/python nfi_study.py risk_stop3 risk_stop6 risk_stale12 risk_trendgate risk_profitprotect official_1x_24h risk_overheat80
.venv/bin/python nfi_analyze.py
.venv/bin/python nfi_risk_report.py
.venv/bin/python -m unittest discover -s research/nfi/risk_study -p 'test_*.py' -v
```

实验预先规则和事后追加假设分别记录在`research/nfi/risk_study/plan.json`，不得将事后假设伪装成事前验证。源码上游保持原样。所有数据与操作仅用于研究，没有启用实盘、推送或发布。
'''
    (out/'REPORT.md').write_text(text)
    fig,axes=plt.subplots(2,1,figsize=(12,9),gridspec_kw={'height_ratios':[1,1.3]})
    x=range(len(losses))
    axes[0].bar(x,[t['profit_usdt'] for t in losses],label='Final net P&L',color='#ce4d4d')
    axes[0].scatter(x,[t['max_sampled_pnl']['pnl_usdt'] for t in losses],label='Best sampled net P&L',color='#229966',zorder=3)
    axes[0].set_xticks(list(x),[t['pair'].split('/')[0] for t in losses],rotation=35)
    axes[0].axhline(0,color='black',lw=.5);axes[0].set_ylabel('USDT per campaign');axes[0].legend(fontsize=8)
    for key,label in [('official_24h','24h baseline,3x'),('risk_stop3','3% price stop'),
                       ('risk_stale12','Negative after12h'),('risk_profitprotect','Profit protection'),
                       ('risk_overheat80','RSI80/20,in-sample hypothesis'),('official_1x_24h','24h baseline,1x')]:
        frame=pd.read_csv(ROOT/f'results/nfi/study/{key}/equity.csv',parse_dates=['time'])
        axes[1].plot(frame.time,(frame.equity/10000-1)*100,label=label,lw=1)
    axes[1].set_ylabel('Net portfolio return(%)');axes[1].legend(fontsize=8)
    for axis in axes:axis.grid(alpha=.2)
    fig.suptitle('NFI X8 /57 static pairs /2026-07 to10 /Exploratory risk controls\nFees included; no funding; all history already observed')
    fig.tight_layout();fig.savefig(out/'risk_comparison.png',dpi=170);plt.close(fig)
    print('Saved risk report, campaign matching and chart')


if __name__ == '__main__':main()
