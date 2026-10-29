"""Compare actual engine paths and verify frozen long-entry experiments."""
import hashlib,json,zipfile
from pathlib import Path
from nfi_portfolio_report import tail_metrics
from nfi_rebound_report import collect
from nfi_analyze import load_result
from nfi_atr_report import trough_holdings
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/long_entry'
def identity(s):return [(t['pair'],t['open_date'],t['close_date'],t['profit_abs'],t['enter_tag']) for t in s['trades']]
def main():
    source=ROOT/'research/nfi/long_entry/NFIShortLongEntry.py'
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    results={}
    for folder in sorted(OUT.iterdir()):
        if not folder.is_dir() or not list(folder.glob('*.zip')):continue
        execution=json.loads((folder/'execution.json').read_text())
        selected=source.with_name('NFIShortLongDelayed.py') if folder.name.startswith('delay_') else source
        assert execution['source_sha256']==hashlib.sha256(selected.read_bytes()).hexdigest()
        r=collect(folder);r['tail_metrics']=tail_metrics(folder);s=load_result(next(folder.glob('*.zip')))
        assert r['campaigns_with_adds']==0 and r['max_holding_hours']<=24
        assert abs(r['equity_audit']['final_equity_error_usdt'])<.01 and r['equity_audit']['max_campaign_ledger_error_usdt']<.01
        assert all(t['leverage']==3 for t in s['trades'])
        longs=[t for t in s['trades'] if not t['is_short']]
        r['long_summary']={'trades':len(longs),'wins':sum(t['profit_abs']>0 for t in longs),'losses':sum(t['profit_abs']<0 for t in longs),'pnl_usdt':sum(t['profit_abs'] for t in longs),'failure_exits':sum(t['exit_reason']=='research_long_failure' for t in longs)}
        results[folder.name]=r
    assert {'control','turn','break','failure'}<=set(results)
    original=load_result(next((ROOT/'results/nfi/portfolio_risk/control').glob('*.zip')))
    control=load_result(next((OUT/'control').glob('*.zip')))
    assert identity(original)==identity(control),'Baseline changed'
    results={n:results[n] for n in ['control','turn','break','delay_turn','delay_break','failure','failure_fee10','failure_july'] if n in results}
    holdings={n:trough_holdings(results[n],load_result(next((OUT/n).glob('*.zip')))) for n in ['control','turn','break','failure','delay_turn','delay_break']}
    (OUT/'drawdown_holdings.json').write_text(json.dumps(holdings,indent=2)+'\n')
    (OUT/'comparison.json').write_text(json.dumps(results,indent=2)+'\n')
    lines=['# NFI多头入场及交易失效研究','',
           '固定57币、10000USDT、3倍/6仓、禁补仓、首次入场24小时。北京时间2026-01-01 08:00至10-29 11:10；未更新行情。手续费单边5bps，fee10为10bps真实引擎重跑；资金费排除。全部历史已经查看，不是独立样本外。', '',
           '空头信号、ATR退出及仓位计算代码未变；多头变化仍会影响共享钱包、持仓槽位与随后空头成交，不能要求空头交易路径保持一致。control逐笔与前轮基线完全相同。', '',
           '## 原路径诊断','',
           '94笔多头83赢11亏。11亏损全部24h退出，9笔曾有闭合5m净浮盈；但其中若干浮盈很小，不能推断均能无损保本。盈利单有15笔在6h仍持仓且浮亏、9笔在12h仍浮亏。对应亏损单分别9与10笔，因此按持仓时长直接切亏会误杀盈利单。逐笔含实际减仓、费用的现金流路径见diagnosis.json；不是删除交易后的策略收益。', '',
           '## 冻结规则','',
           '- turn：原入场信号同时要求最近闭合5m收盘上涨、低点不低于前一根。','- break：原信号同时要求闭合5m收盘突破此前3根5m最高价。两组均是信号当下确认，不是持有旧信号等待未来触发。',
           '- failure：原入场不变；首次成交冻结当时最近12根闭合5m低点和已闭合1h ATR14；满6小时且剩余持仓价格低于入场价、跌破该低点减0.5ATR时退出。不是固定亏损6小时即卖出。原盈利退出及24h优先。',
           '- delay_turn/delay_break：原信号及原标签最多保留30分钟和6根K线，在确认出现后入场；遇到空头信号不覆盖空头。该延迟窗口在第一轮指标完成前追加，仍属已查看历史的探索。',
           '- failure状态本轮只存离线回测实例内存，没有实现服务重启恢复，不作为实盘可用实现。','',
           '|方案|交易|多头胜/负|组合收益|含浮亏回撤|多头失效退出|平均保证金/权益|','|---|---:|---:|---:|---:|---:|---:|']
    for name,r in results.items():
        l=r['long_summary'];lines.append(f"|{name}|{r['campaigns']}|{l['wins']}/{l['losses']}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{l['failure_exits']}|{r['average_margin_equity_pct']:.2f}%|")
    lines+=['','结构失效组匹配原入场后：11笔原亏损6笔按净收益率减亏、5笔反而亏得更多；8笔原盈利提前退出，其中7笔转亏。剩余仓价格低于入场价不等于整轮净亏损，SUI部分减仓后的整轮仍盈利。完整逐笔比较见matched_failure_exits.json，不以不同复利钱包的绝对利润差作为因果贡献。', '', '不能仅按胜率或少数坏单是否消失选型。必须同时看被提前退出的潜在盈利单、净收益保留、持仓浮亏及共享钱包机会成本。7月同本金重启仍是已查看历史，只检查资金路径敏感性。5m权益回撤不是盘中极值，限价回测不代表真实盘口成交。','',
            '复现：`.venv/bin/python nfi_long_entry.py control turn break failure --workers 2`；完成目录拒绝覆盖。完整复现还需运行延迟组`delay_turn delay_break`及failure的`--fee .001 --suffix _fee10`和`--start 2026-07-01T00:00:00Z --suffix _july`。之后运行`nfi_long_diagnose.py`、`nfi_long_failure_audit.py`、`nfi_long_entry_report.py`与`nfi_long_entry_plot.py`。没有启动实盘或发布环境。']
    lines+=['','## 结论','', '本轮未找到可替换原核心的多头改进，不晋级任何新规则。即时确认严重损伤收益；30分钟延迟确认的最大回撤均超过22%；6h结构失效退出损伤收益且未降低最大权益回撤。双费及7月同本金检验亦未支持失效退出。', '', '延迟组最差回撤发生在北京时间2月6日08:20，均持有4个多头；原核心和失效退出组则在10月9日01:50持有6个多头。改变入场可能引入原策略没有承受的新风险，不能只检查旧亏损单是否消失。实际持仓见drawdown_holdings.json；持仓浮盈亏不是整个峰谷回撤的因果归因。','']
    (OUT/'decision.json').write_text(json.dumps({'promoted':None,'reason':'No tested modification improves return and overall robustness; core unchanged.','trials':list(results),'independent_oos':False},indent=2)+'\n')
    lines+=['','## 回撤持续性与尾部风险','', '|方案|Ulcer指数|日ES95|最差滚动24h|','|---|---:|---:|---:|']
    for n,r in results.items():
        t=r['tail_metrics'];lines.append(f"|{n}|{t['ulcer_index_pct']:.2f}%|{t['daily_es95_pct']:.2f}%|{t['worst_rolling_24h_pct']:.2f}%|")
    lines+=['','日ES95为已完成北京时间日收益最差5%均值；Ulcer为5m权益回撤百分比均方根。两者定义沿用portfolio_risk。','']
    refs={}
    for n in ['gated_fee10','gated_july']:
        f=ROOT/'results/nfi/atr_short'/n
        if list(f.glob('*.zip')):refs[n]=collect(f)
    (OUT/'references.json').write_text(json.dumps(refs,indent=2)+'\n')
    lines+=['','## 同口径旧基线参照','', '|基线|组合收益|持仓权益回撤|','|---|---:|---:|']
    for n,r in refs.items():lines.append(f"|{n}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|")
    lines+=['','![组合权益及回撤](comparison.png)','']
    (OUT/'REPORT.md').write_text('\n'.join(lines).rstrip()+'\n')
    (OUT/'verification.json').write_text(json.dumps({'status':'passed','replays':len(results),'control_exact':True,'ledger_and_deadline_verified':True,'source_sha256':digest,'funding_excluded':True,'independent_oos':False},indent=2)+'\n')
    print('\n'.join(lines[-(len(results)+5):]))
if __name__=='__main__':main()
