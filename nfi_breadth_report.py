"""Actual-engine breadth risk experiments, opportunity cost and simple controls."""
import hashlib,json
from pathlib import Path
from nfi_analyze import load_result
from nfi_rebound_report import collect
from nfi_portfolio_report import tail_metrics
from nfi_atr_report import trough_holdings
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/breadth'
NAMES=['control','gate','exit','both','btc_exit','long_cap','climax','climax_after']
def identity(s):return [(t['pair'],t['open_date'],t['close_date'],t['profit_abs'],t['enter_tag']) for t in s['trades']]
def main():
    source=ROOT/'research/nfi/breadth/NFIShortBreadth.py';feature=source.with_name('breadth.py');results={};engines={}
    for f in sorted(OUT.iterdir()):
        if not f.is_dir() or not list(f.glob('*.zip')):continue
        source=ROOT/'research/nfi/breadth'/('NFIShortBreadthClimax.py' if f.name.startswith('climax') else 'NFIShortBreadth.py')
        e=json.loads((f/'execution.json').read_text());assert e['source_sha256']==hashlib.sha256(source.read_bytes()).hexdigest() and e['feature_sha256']==hashlib.sha256(feature.read_bytes()).hexdigest()
        r=collect(f);s=load_result(next(f.glob('*.zip')));engines[f.name]=s;r['tail_metrics']=tail_metrics(f)
        assert r['max_holding_hours']<=24 and r['campaigns_with_adds']==0
        ls=[t for t in s['trades'] if not t['is_short']]
        r['long_summary']={'trades':len(ls),'wins':sum(t['profit_abs']>0 for t in ls),'losses':sum(t['profit_abs']<0 for t in ls),'shock_exits':sum(t['exit_reason'] in ['research_breadth_exit','research_btc_shock_exit'] for t in ls)}
        results[f.name]=r
    assert set(NAMES)<=set(results)
    assert identity(engines['control'])==identity(load_result(next((ROOT/'results/nfi/long_family/control').glob('*.zip'))))
    results={n:results[n] for n in NAMES+sorted(set(results)-set(NAMES))};(OUT/'comparison.json').write_text(json.dumps(results,indent=2)+'\n')
    holds={n:trough_holdings(results[n],engines[n]) for n in NAMES};(OUT/'drawdown_holdings.json').write_text(json.dumps(holds,indent=2)+'\n')
    refs={n:collect(ROOT/path) for n,path in {'baseline_fee10':'results/nfi/atr_short/gated_fee10','baseline_july':'results/nfi/atr_short/gated_july','prior_btc_gate':'results/nfi/portfolio_risk/shock','prior_side_cap':'results/nfi/portfolio_risk/side_cap','prior_half_long':'results/nfi/portfolio_risk/half_long'}.items()}
    (OUT/'references.json').write_text(json.dumps(refs,indent=2)+'\n')
    sel=json.loads((OUT/'validation_selection.json').read_text());event=json.loads((OUT/'baseline_event_diagnosis.json').read_text());flags=json.loads((OUT/'baseline_entry_exit_flags.json').read_text())
    extra=json.loads((OUT/'climax_validation_selection.json').read_text())
    order={}
    for label,suffix in [('original',''),('reverse','_reverse')]:
        a=results['control'+suffix];b=results['climax'+suffix]
        order[label]={'control_return_pct':a['return_pct'],'climax_return_pct':b['return_pct'],'return_advantage_pp':b['return_pct']-a['return_pct'],'control_dd_pct':a['equity_audit']['mtm_drawdown_pct'],'climax_dd_pct':b['equity_audit']['mtm_drawdown_pct'],'dd_difference_pp':b['equity_audit']['mtm_drawdown_pct']-a['equity_audit']['mtm_drawdown_pct']}
    (OUT/'order_sensitivity.json').write_text(json.dumps({'warning':'One predetermined reverse-order paired test, not an exhaustive universe/priority robustness proof; no choice of best ordering.','pairs':order},indent=2)+'\n')
    (OUT/'decision.json').write_text(json.dumps({'promoted':None,'selection':sel,'climax_selection':extra,'order_sensitivity':order,'research_return_candidate':extra['selected'],'research_risk_candidate':sel['secondary'],'reason':'Historical inspected-data research; no automatic core replacement, no live service. Funding excluded.'},indent=2)+'\n')
    lines=['# NFI市场广度与共振风险研究','',
      '固定历史北京时间2026-01-01 08:00至10-29 11:10；57静态币、10000USDT、3倍/最多6仓、禁补仓、首次入场24h。单边手续费5bps；fee10为10bps真实重跑；july为7月1日同10000本金重启。资金费排除。全部历史已经查看，不是独立样本外；静态币池有事后及存活者偏差。','',
      '## 指标与实验','',
      '精确同步已闭合5m，不前填缺失报价。每币15m对数收益除以此前288根5m收益标准差乘sqrt(3)，标准差再后移3根，剔除当前15m冲击。至少20个有效币，且覆盖当时已成熟币的80%；成熟需从首次观察经过24h15m，缺失币不会从已成熟分母消失。', '',
      '原始冲击：有效币15m下跌比例>=80%，且横截面标准化跌幅中位数<=-1.5。等权并非等风险，无成交量或市值事后筛选。market_features.csv.gz中的date是UTC开盘时间，5分钟后才可使用。','',
      '- control：原框架，逐笔与上一轮完全一致。','- gate：过去12根5m内有广度冲击则拒绝新多头；未知覆盖也拒绝新多头。','- exit：只有在首次入场之后新闭合的原始广度冲击，才请求退出已有多头；旧冲击不触发入场即退出，未知不强平。','- both：合并gate和exit。','- btc_exit：相同入场后时间限制，BTC15m对数收益<负1.5倍已闭合1hATR/BTC价格则退已有多头。BTC与广度归一化、频率不同，不能称严格同风险匹配。','- climax（事后追加）：纯修复组要求已知广度且过去1h有冲击，保留趋势/混合信号及空头原逻辑；climax_after额外要求当前不满足原始冲击。原阈值不变，基于已看过的原交易诊断启发，不是预先盲测。当前冲击标记消失可能来自波动率分母变化，不等于已经反转。',
      '- *_reverse：原57币排序完整反转，control和climax成对重放；只改变新信号争用6个槽位的先后，不改变币池、指标或其他配置。不搜索哪个排序最好。',
      '- long_cap：最多2个真实已开/待成交多头，空头仍可占全局6仓；不增加原单笔额度。此前side_cap则限制两个方向各最多2仓，须区分。', '',
      '空头信号、ATR退出、风险预算和原始仓位上限不变；钱包和槽位会改变后续实际交易与金额。未扫描阈值。','',
      '|方案|交易|多头赢/亏|组合收益|持仓权益回撤|Ulcer|日ES95|冲击退出|平均保证金/权益|','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in results.items():
        l=r['long_summary'];t=r['tail_metrics'];lines.append(f"|{n}|{r['campaigns']}|{l['wins']}/{l['losses']}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{t['ulcer_index_pct']:.2f}%|{t['daily_es95_pct']:.2f}%|{l['shock_exits']}|{r['average_margin_equity_pct']:.2f}%|")
    lines+=['','适应性追加的依据：原63笔纯反弹组中，有近期广度冲击的51笔49赢2亏、净11252.22USDT；无近期冲击的12笔8赢4亏、净6.24USDT。该原路径统计带标签及资金配置偏差，不是重新分配钱包后的收益；见baseline_cohorts.json与climax_plan.json。', '', 'Ulcer为5m持仓权益回撤百分比均方根；日ES95为完整北京时间日收益最差5%均值。还保留回撤持续时长、最差滚动24h和p95名义敞口。5m收盘和整点标记价格不是盘中极值；冲击时真实滑点和订单队列未被精确模拟。','',
      '## 原始路径及最差事件诊断','',
      f"评价期原始冲击{event['raw_shock_bars']}根、{event['raw_shock_episodes']}段，门控{event['entry_gate_bars']}根，未知覆盖{event['unknown_bars']}根。门控信号并不只出现在极少数崩盘事件。", '',
      f"原94笔多头中，门控在入场时会标记{flags['entry_blocks_original_winners']}笔原盈利和{flags['entry_blocks_original_losers']}笔原亏损；入场后、原退出前出现冲击的有{flags['post_entry_shocks_original_winners']}笔原盈利及{flags['post_entry_shocks_original_losers']}笔原亏损。这只是原路径标签审计，不是删除交易后的收益，不包含新路径的机会成本。", '',
      '原最差回撤在北京时间10月9日01:50，持有6个多头。ALGO/JUP入场时未被门控，首次入场后冲击在10月8日23:05；另外4个在23:25入场时已有冲击。指标在该事件中早于谷值，但6笔原持仓5笔最终盈利，提前识别共同下跌不等于能预测是否会修复。逐笔时间及原路径利润见baseline_event_diagnosis.json。', '',
      '## 简单规则与历史参照','', '|参照|组合收益|持仓权益回撤|','|---|---:|---:|']
    for n,r in refs.items():lines.append(f"|{n}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|")
    lines+=['','先按初始计划筛选收益及回撤同时不劣于control的指标规则，无则对both做负面对照。另行记录的风险取舍标准为保留75%基线收益、回撤至少减少20%、Ulcer及ES不恶化；至多另选一个收益/回撤最高者。附加资格在全部主实验完成前、long_cap完成前记录，属于已看过历史的研究者选择，不是样本外。', '',
      '原规则实际检验选择：'+', '.join(sel['selected'])+'；收益资格：'+str(sel['return_eligible'])+'；风险取舍资格：'+str(sel['risk_eligible'])+'。费用和重启都保留真实引擎资金路径，不简单减手续费；固定路径2/5/10bps滑点压力另存comparison.json，不替代真实冲击成交验证。', '',
      '## 结论与复现','', '追加climax两组后按climax_plan.json单独检验资格，保留原门控/退出失败，不修改初始规则与阈值。该阶段完整选择记录见climax_validation_selection.json。', '',
      'climax相对原框架少了12个原多头入场时点（8个原盈利、4个原亏损），新产生5笔多头且本段全部盈利，描述性净利润1814.47USDT，其中APT/ONDO集中在10月8日同一事件。钱包、后续交易和复利都会变化，不能把这些数字直接相加解释为因果alpha。改善集中于少数新增交易，见climax_cohort_audit.json。', '',
      '当前没有自动晋级或核心替换。指标是否有价值，需同时看收益保留、浮亏回撤、尾部风险、持续性和暴露；不能只挑选是否避开已知一次崩盘。短周期共振也可能是原策略的反弹入场背景，广度风险标记不等于未来方向预测。','',
      '完整复现依次使用`.venv/bin/python`执行：`nfi_breadth.py control gate exit both btc_exit long_cap --workers 2` → `nfi_breadth_features.py` → `nfi_breadth_validate.py` → `nfi_breadth.py climax climax_after --workers 2` → `nfi_breadth_climax_validate.py` → `nfi_breadth.py control climax --reverse-pairs --suffix _reverse --workers 2` → `nfi_breadth_climax_audit.py` → `nfi_breadth_report.py` → `nfi_breadth_plot.py`。已完成目录拒绝覆盖。全部测试命令保留在execution_evidence.zip的tests.log。没有下单、启动服务或发布环境。','', '![权益及回撤](comparison.png)']
    c=results['control'];v=results['climax']
    lines+=['','## 候选的风险与收益','', f"climax收益{v['return_pct']:.2f}%对比原框架{c['return_pct']:.2f}%，持仓权益回撤{v['equity_audit']['mtm_drawdown_pct']:.2f}%对比{c['equity_audit']['mtm_drawdown_pct']:.2f}%；Ulcer {v['tail_metrics']['ulcer_index_pct']:.2f}%对比{c['tail_metrics']['ulcer_index_pct']:.2f}%，日ES95 {v['tail_metrics']['daily_es95_pct']:.2f}%对比{c['tail_metrics']['daily_es95_pct']:.2f}%，平均保证金/权益{v['average_margin_equity_pct']:.2f}%对比{c['average_margin_equity_pct']:.2f}%。原始仓位上限、3倍杠杆、禁止补仓与24h期限保持。", '', f"平仓回撤则为{v['closed_trade_drawdown_pct']:.2f}%，原框架{c['closed_trade_drawdown_pct']:.2f}%，这项指标略有恶化，不能宣称所有风险维度都改善。保留climax为冻结后新增数据检验的研究候选；long_cap是另一个偏低峰值回撤的取舍。没有自动替换核心或授权实盘。", '']
    lines+=['','## 固定币种排序敏感性','', '|排序|原框架收益|climax收益|收益差|原框架回撤|climax回撤|','|---|---:|---:|---:|---:|---:|']
    for n,o in order.items():lines.append(f"|{n}|{o['control_return_pct']:.2f}%|{o['climax_return_pct']:.2f}%|{o['return_advantage_pp']:+.2f}pp|{o['control_dd_pct']:.2f}%|{o['climax_dd_pct']:.2f}%|")
    lines+=['','本检验仍是已看过历史、单一币池和两种固定排序，不证明未来收益，也不能选择更好排序作为新基线。','']
    (OUT/'REPORT.md').write_text('\n'.join(lines).rstrip()+'\n');print(json.dumps({n:{'return':r['return_pct'],'DD':r['equity_audit']['mtm_drawdown_pct']} for n,r in results.items()},indent=2))
if __name__=='__main__':main()
