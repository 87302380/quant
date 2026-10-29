"""Reconcile frozen YTD runs and attribute campaign P&L without relabeling OOS."""
import gzip,json,re
from pathlib import Path
import numpy as np
import pandas as pd
import talib
from nfi_analyze import analyze,load_result,groups

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results/nfi/ytd_research'
DATA=ROOT/'data/nfi_ytd2026/freqtrade/futures'


def main():
    rows=json.loads(gzip.decompress((DATA/'BTC_USDT_USDT-4h-futures.json.gz').read_bytes()))
    dates=np.array([r[0]+14400000 for r in rows]);closes=np.array([r[4] for r in rows],dtype=float)
    ema=talib.EMA(closes,200)
    def regime(t):
        i=np.searchsorted(dates,t['open_timestamp'],side='right')-1
        if i<6 or not np.isfinite(ema[i-6]):return 'unavailable'
        if closes[i]<ema[i] and ema[i]<ema[i-6]:return 'BTC_below_falling_4h_EMA200'
        if closes[i]>ema[i] and ema[i]>ema[i-6]:return 'BTC_above_rising_4h_EMA200'
        return 'BTC_mixed'
    results={}
    for variant in ['baseline','overheat','budget','direction']:
        folder=OUT/variant
        paths=list(folder.glob('*.zip'))
        if len(paths)!=1:raise ValueError(f'Expected exactly one successful archive: {folder}')
        s=load_result(paths[0]);r=analyze(paths[0],DATA);ts=s['trades']
        wins=[t['profit_abs'] for t in ts if t['profit_abs']>0]
        losses=[t['profit_abs'] for t in ts if t['profit_abs']<0]
        r['payoff']={'average_win_usdt':float(np.mean(wins)) if wins else 0,
                     'average_loss_usdt':float(np.mean(losses)) if losses else 0,
                     'average_win_over_average_loss':float(-np.mean(wins)/np.mean(losses)) if losses and wins else None,
                     'profit_factor':s['profit_factor'],'expectancy_usdt':s['expectancy'],
                     'gross_profit_usdt':sum(wins),'gross_loss_usdt':sum(losses)}
        r['by_BTC_entry_regime']=groups(ts,regime)
        r['by_half']=groups(ts,lambda t:'Jan-Jun' if t['open_date']<'2026-07' else 'Jul-Oct')
        if variant in ['budget','direction']:
            audits=[json.loads(item) for item in re.findall(r'RISK_AUDIT\s+(\{.*?\})',(folder/'run.log').read_text(),re.S)]
            if not audits:raise ValueError('Missing risk audit events')
            excess=[a for a in audits if a['planned_stop_loss']>a['budget']+.02]
            r['risk_audit']={'fill_events':len(audits),'events_above_budget_plus_2c':len(excess),
                            'max_planned_loss_over_budget':max(a['planned_stop_loss']/a['budget'] for a in audits if a['budget']>0),
                            'excess_events':excess}
            first={}
            for a in audits:first.setdefault(a['trade_id'],a)
            budgets={(a['pair'],int(pd.Timestamp(a['time']).timestamp()*1000)):a['budget'] for a in first.values()}
            realized=[]
            for t in ts:
                b=budgets.get((t['pair'],t['open_timestamp']))
                if b is None:raise ValueError(f"Missing first-fill audit for {t['pair']} {t['open_date']}")
                realized.append({'pair':t['pair'],'open_date':t['open_date'],'profit_usdt':t['profit_abs'],
                                 'budget_usdt':b,'loss_over_budget':max(0,-t['profit_abs'])/b,'exit_reason':t['exit_reason']})
            r['risk_audit']['max_realized_loss_over_budget']=max(a['loss_over_budget'] for a in realized)
            r['risk_audit']['realized_losses_exceeding_budget_plus_2c']=[a for a in realized if -a['profit_usdt']>a['budget_usdt']+.02]
            (folder/'risk_audit_events.json').write_text(json.dumps(audits,indent=2)+'\n')
        (folder/'analysis.json').write_text(json.dumps(r,indent=2)+'\n')
        results[variant]=r
    base=load_result(next((OUT/'baseline').glob('*.zip')))
    key=lambda t:(t['pair'],t['open_timestamp'],t['is_short'])
    bm={key(t):t for t in base['trades']}
    for variant in ['overheat','budget','direction']:
        s=load_result(next((OUT/variant).glob('*.zip')));vm={key(t):t for t in s['trades']}
        common=bm.keys()&vm.keys()
        changed=[{'pair':bm[k]['pair'],'open_date':bm[k]['open_date'],'baseline_profit':bm[k]['profit_abs'],
                  'variant_profit':vm[k]['profit_abs'],'variant_exit':vm[k]['exit_reason']}
                 for k in sorted(common) if (bm[k]['profit_abs']>0)!=(vm[k]['profit_abs']>0)]
        results[variant]['matched_to_baseline']={'matched':len(common),'baseline_only':len(bm.keys()-vm.keys()),
            'variant_only':len(vm.keys()-bm.keys()),'win_to_loss':sum(bm[k]['profit_abs']>0>vm[k]['profit_abs'] for k in common),
            'loss_to_win':sum(bm[k]['profit_abs']<0<vm[k]['profit_abs'] for k in common),'sign_changes':changed}
    (OUT/'comparison.json').write_text(json.dumps(results,indent=2)+'\n')
    lines=['# NFI X8：2026年初至今的四组受控实验','',
           '窗口：2026-01-01 00:00 至 2026-10-29 03:10 UTC（北京时间10月29日11:10）。57个固定币种、初始10,000 USDT、同一钱包、最多6仓、原版3倍杠杆。单次持仓从首次成交计时不超过24小时。', '',
           '单边手续费5bps已计入；资金费未计入。滑点表是成交路径不变的附加扣费压力，不是订单簿重放。当前57币倒推历史存在选择及存活者偏差，所有实验均是回顾研究，非独立样本外。','',
           '|版本|交易|收益|5m权益回撤|胜率|平均盈亏比|利润因子|',
           '|---|---:|---:|---:|---:|---:|---:|']
    for name,r in results.items():
        lines.append(f"|{name}|{r['campaigns']}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{r['win_rate_pct']:.2f}%|{r['payoff']['average_win_over_average_loss']:.2f}|{r['payoff']['profit_factor']:.2f}|")
    lines+=['','baseline只加24小时强平；overheat在此基础上拒绝闭合4h RSI≥80的多单和≤20的空单。budget独立使用基线信号，以闭合4h ATR14的2倍、至少价格1%的距离冻结止损，按已结算权益0.5%计划风险缩仓，加仓共享预算。direction在新增仓前要求同向冻结预算合计不超过当时可交易已结算权益的1.5%。预算并非跳空或执行损失保证。', '',
            '风险预算与原始仓位上限取较小者；不是每笔必须用满0.5%。预算基数为Freqtrade可交易已结算权益（含已实现部分退出收益，再乘99%可交易比例），不含浮亏；单笔预算约占总已结算权益0.495%。同向上限使用全部同向币种这一保守代理，没有事后拟合相关系数。部分减仓不释放冻结预算，平仓才释放；权益随后下降时不会强制减仓，因此该上限是新增仓准入门槛，并非持续强制再平衡。','',
            '## 月度权益收益','', '|月份|baseline|overheat|budget|direction|','|---|---:|---:|---:|---:|']
    months=results['baseline']['equity_audit']['monthly_mtm']
    for month in months:
        lines.append('|'+month[:7]+'|'+'|'.join(f"{r['equity_audit']['monthly_mtm'][month]['return_pct']:.2f}%" for r in results.values())+'|')
    lines+=['','## 利润来源与风险边界','']
    for name,r in results.items():
        lines.append(f"- {name}：多空归因 {json.dumps(r['by_direction'],ensure_ascii=False)}；限时退出{r['deadline_audit']['deadline_exits']}笔，其中亏损{r['deadline_audit']['deadline_losing_exits']}笔。")
    lines+=['','## 结论与取舍','',
            '1. RSI过滤只删除8月22日OP/XRP两笔；1—6月交易与收益完全不变。虽然全段收益更高，回撤未下降，仍是从已知亏损事件提出的待验证假设，不能当成跨行情确认。',
            '2. budget保留全部152个对应入场，减少仓位并限制补仓后，回撤显著下降，收益也明显缩水。FIL（6月2日）和UNI（2月5日）两笔原本盈利被止损成亏损。平均盈利/平均亏损约0.63，低于基线约1.23，说明止损没有免费改善盈利能力。',
            '3. direction相对budget只降低约0.10个百分点回撤，却少赚约3.56个百分点；当前不把它作为默认升级。保留它作同向冲击压力对照，不能据一次历史样本推断组合上限永远无用。',
            '4. 下一阶段主模拟候选为budget，基线24h和direction保留独立钱包对照；暂不叠加RSI过滤。启动规范见 [前向计划](../../../research/nfi/ytd_research/FORWARD.md)，配置处于停止状态，尚未运行前向样本。',
            '5. budget同时改变止损、仓位和补仓，不能把回撤改善全部归功于ATR止损。若继续历史实验，应先增加同风险规模的纯缩仓对照，区分缩仓贡献与退出贡献，而非继续扫描RSI或ATR参数。','',
            '基线约92%的净利润来自多头，long_top_coins与long_normal为主要来源；46笔short_rebuy只贡献约202 USDT。这更接近多头反弹/波动恢复与持仓管理收益，不能视为天然对冲组合。入场处于BTC低于且下行4h EMA200时仍有盈利，只能说明部分弱势背景中的交易可盈利，不能证明持续无反弹暴跌时安全。','',
            '本轮完成的budget/direction分别审计155/148个仍有剩余持仓的成交事件，均未发现计划止损风险或最终亏损超过冻结预算（容差0.02 USDT）；完全平仓事件不再计算剩余止损风险。真实跳空、限价无法成交及费用变化仍可突破预算。所有版本均未发现24h超期或到期后加仓。', '',
            '完整亏损路径见 [trade_diagnosis.json](trade_diagnosis.json)。某个时点已浮亏并不代表后续必亏；替代退出必须重新回放，不能按最终输赢事后决定谁提前平仓。','']
    lines+=['','逐信号族、BTC入场状态、半年、最差交易、费用与滑点敏感性见 [comparison.json](comparison.json)。BTC状态只使用入场时最后已闭合4h及EMA200过去24小时斜率；它是描述性分组，不能证明整段单边熊市存活。不同版本交易数与资金路径会变化，不能将收益差全部解释为被删除交易的原始盈亏。', '',
            '## 可复现与检查','',
            '运行 `.venv/bin/python nfi_ytd_study.py baseline overheat budget direction`，再运行 `.venv/bin/python nfi_ytd_analysis.py`。每组使用隔离缓存和真实Freqtrade引擎，原版源码不改动。已完成的目录重跑前应另存归档，分析拒绝多份ZIP。', '',
            '订单现金流逐笔对账，并用最后已收盘5m价格重建持仓权益；整点真实标记价格另做敏感性核对。所报回撤是离散采样，不含盘中极值。预算成交审计见各组analysis与risk_audit_events。', '']
    diagnostic=OUT/'trade_diagnosis.json'
    if diagnostic.exists():
        d=json.loads(diagnostic.read_text());x=d['summary']
        lines+=['## 30笔亏损的路径诊断','',
                f"基线亏损共{x['losses']}笔，亏损合计{-x['gross_loss_usdt']:.2f} USDT；四笔最大亏损占{x['largest4_loss_share_pct']:.2f}%。其中{x['losers_ever_net_green_5m']}笔曾出现扣手续费及预计平仓费后的正浮盈，但正浮盈可能很小，不能直接推导可锁定利润。另有{x['losers_never_net_green_5m']}笔在5m采样中未净盈利。",'',
                f"仍持有到对应时点、当时净浮亏、最终却盈利的交易：6小时{x['negative_at_6h_then_won']}笔，12小时{x['negative_at_12h_then_won']}笔，18小时{x['negative_at_18h_then_won']}笔。简单按‘浮亏太久’强退会误杀，必须用真实回放衡量。",'',
                '|最大亏损|最终净损益USDT|6h浮动净损益|12h浮动净损益|持仓内最高净浮盈|','|---|---:|---:|---:|---:|']
        for t in d['campaigns'][:5]:
            lines.append(f"|{t['pair']} {t['side']}|{t['profit_usdt']:.2f}|{t['at6h']['pnl_usdt']:.2f}|{t['at12h']['pnl_usdt']:.2f}|{t['max_sampled_pnl']['pnl_usdt']:.2f}|")
        lines+=['','ALGO这类始终偏弱的交易需要风险预算或失效退出；OP/XRP主要是强势末端入场后反转，闭合4h RSI过热只是可解释特征；空头rebuy则需警惕下跌后的反弹。这些是现有路径的诊断，不是事前必然可辨认的标签。','',
                '![权益与回撤](comparison.png)','']
    (OUT/'REPORT.md').write_text('\n'.join(lines))
    print('\n'.join(lines[:14]))


if __name__=='__main__':main()
