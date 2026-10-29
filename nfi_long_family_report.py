"""Actual-engine disjoint signal-family research and frozen-rule comparison."""
import hashlib,json
from pathlib import Path
from nfi_analyze import load_result,filled_orders
from nfi_rebound_report import collect
from nfi_portfolio_report import tail_metrics
from nfi_atr_report import trough_holdings
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/long_family'
NAMES=['control','trend_gate','trend_exit','trend_both','dip_recovery','dip_limit']
def identity(s):return [(t['pair'],t['open_date'],t['close_date'],t['profit_abs'],t['enter_tag']) for t in s['trades']]
def main():
    source=ROOT/'research/nfi/long_family/NFIShortLongFamily.py';digest=hashlib.sha256(source.read_bytes()).hexdigest();results={};holdings={};engines={}
    for folder in sorted(OUT.iterdir()):
        if not folder.is_dir() or not list(folder.glob('*.zip')):continue
        record=json.loads((folder/'execution.json').read_text());assert record['source_sha256']==digest
        r=collect(folder);s=load_result(next(folder.glob('*.zip')));engines[folder.name]=s
        assert r['campaigns_with_adds']==0 and r['max_holding_hours']<=24
        r['tail_metrics']=tail_metrics(folder)
        ls=[t for t in s['trades'] if not t['is_short']];gp=sum(max(t['profit_abs'],0) for t in ls);gl=-sum(min(t['profit_abs'],0) for t in ls)
        r['long_summary']={'trades':len(ls),'wins':sum(t['profit_abs']>0 for t in ls),'losses':sum(t['profit_abs']<0 for t in ls),'net_usdt':gp-gl,'profit_factor':gp/gl if gl else None,'trend_failure_exits':sum(t['exit_reason']=='research_long_trend_failure' for t in ls)}
        results[folder.name]=r
    assert set(NAMES)<=set(results)
    prior=load_result(next((ROOT/'results/nfi/long_entry/control').glob('*.zip')));assert identity(prior)==identity(engines['control'])
    results={n:results[n] for n in NAMES+sorted(set(results)-set(NAMES))}
    for n in NAMES:holdings[n]=trough_holdings(results[n],engines[n])
    (OUT/'drawdown_holdings.json').write_text(json.dumps(holdings,indent=2)+'\n')
    (OUT/'comparison.json').write_text(json.dumps(results,indent=2)+'\n')
    reference={n:collect(ROOT/'results/nfi/atr_short'/n) for n in ['gated_fee10','gated_july']}
    reference['prior_global_recovery']=collect(ROOT/'results/nfi/fast_rs/improving_long')
    reference['prior_half_long']=collect(ROOT/'results/nfi/portfolio_risk/half_long')
    (OUT/'references.json').write_text(json.dumps(reference,indent=2)+'\n')
    baseline=results['control'];pareto=[n for n in NAMES[1:] if results[n]['return_pct']>=baseline['return_pct'] and results[n]['equity_audit']['mtm_drawdown_pct']<=baseline['equity_audit']['mtm_drawdown_pct']+1e-6]
    decision={'promoted':None,'full_year_return_drawdown_candidates':pareto,'reason':'Historical exploration only; cost/restart evidence and future verification required. No core replacement or live service.','funding_excluded':True,'independent_oos':False}
    (OUT/'decision.json').write_text(json.dumps(decision,indent=2)+'\n')
    diag=json.loads((OUT/'source_and_baseline_diagnosis.json').read_text())
    lines=['# NFI按多头信号原理分组研究','',
      '北京时间2026-01-01 08:00至2026-10-29 11:10，固定57币、10000USDT、3倍/最多6仓、禁补仓、首次入场24小时。手续费单边5bps；fee10为10bps真实重跑，july为7月1日同本金重启。全部历史已经查看、静态币池存在事后偏差；不是独立样本外，资金费排除。', '',
      '## 分组依据','',
      '按固定上游原始触发条件分组：21为强均线背景下回调；47为短均线金叉转强；64为上涨中的超卖回调；65为布林上轨突破；161为均线金叉且高于1h/4h EMA200。其余27个启用标签主要是急跌、均线负乖离、超卖及修复。此为研究分类，不是官方策略命名；源码最后触发条件之外仍有大量原生保护条件。混合或未知标签保持原逻辑。', '',
      '|基线信号组|交易|赢/亏|净利润USDT|PF|','|---|---:|---:|---:|---:|']
    for n,r in diag['groups'].items():lines.append(f"|{n}|{r['trades']}|{r['wins']}/{r['losses']}|{r['profit_usdt']:.2f}|{r['profit_factor'] if r['profit_factor'] is not None else '—'}|")
    lines+=['','原生仓位模式不同，且共享复利钱包；上表不是各组独立配置同本金后的收益，也不是因果alpha分解。完整触发条件、行号及逐笔归属见source_and_baseline_diagnosis.json。', '',
      '## 冻结实验','',
      '- control：原信号、仓位和退出不变，逐笔对齐前轮基线。','- trend_gate：仅顺势/转强/突破组要求最新已闭合1h收盘高于EMA50，EMA50高于6小时前。',
      '- trend_exit：仅该组，持有至少2h后连续两根已闭合1h收盘低于各自EMA50则退出；原生盈利退出和24h上限保留。trend_both合并两项，作为机制消融。',
      '- dip_recovery：仅纯急跌修复组，最近15m对BTC相对对数收益高于前一个不重叠15m窗口；BTC自身豁免。不是要求已强于BTC，空头不受过滤。',
      '- dip_limit：仅纯急跌修复组，委托买价在原拟入场价下方0.5倍已闭合1hATR，距离最多1.9%。保持原仓位上限、原3分钟未成交超时；回测以5m处理订单，不模拟真实盘口队列。未成交后错过反弹属于结果，不能仅比较成交价格更低的交易。',
      '- 限价组有额外执行限制：原3分钟超时短于5m主周期，现有K线无法确认触价发生在超时前。5m引擎按整根K线触价成交，可能乐观；即使收益改善，也需更细成交数据验证，不能据此晋级。',
      '- 全部组空头信号、ATR退出及风险预算原样保留；共享钱包和持仓槽位仍可能使实际空头交易与配置金额变化。','',
      '|方案|交易|多头赢/亏|组合收益|含浮亏回撤|Ulcer|日ES95|平均保证金/权益|','|---|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in results.items():
        l=r['long_summary'];t=r['tail_metrics'];lines.append(f"|{n}|{r['campaigns']}|{l['wins']}/{l['losses']}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{t['ulcer_index_pct']:.2f}%|{t['daily_es95_pct']:.2f}%|{r['average_margin_equity_pct']:.2f}%|")
    lines+=['','Ulcer为5m权益回撤百分比均方根；日ES95为完整北京时间日收益最差5%均值。回撤包含持仓浮亏，是离散闭合5m采样，不是盘中极值。最大回撤时实际持仓见drawdown_holdings.json；不能将该时点持仓浮亏直接解释为整个峰谷回撤贡献。', '',
      '## 费用、同本金及旧规则参照','', '|原框架参照|收益|持仓权益回撤|','|---|---:|---:|']
    for n,r in reference.items():lines.append(f"|{n}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|")
    lines+=['','各组comparison.json还保留2/5/10bps固定成交路径滑点压力，它不是新订单路径重跑；费用重跑与固定路径扣费分开解释。','',
      '## 研究结论','', '分组后的相对恢复组194.86%、回撤11.26%，比旧全多头统一相对恢复过滤179.44%、11.26%保留更多收益；但原框架239.26%、13.32%仍有更高收益。它改善了旧过滤方案，尚未证明改善核心。限价组133.44%、10.52%还不如此前简单多头减半152.50%、9.61%的收益与回撤，且有额外成交假设限制。', '', '原时点匹配审计：趋势确认没有消除原趋势组5笔亏损，缺失的2个原入场时点均属原盈利；反弹相对恢复过滤未重复42个原盈利时点和4个原亏损时点，并产生14个新多头时点；低价限价未重复51个原盈利和6个原亏损时点，并产生12个新多头时点。时点缺失可来自过滤、未成交、持仓与槽位变化，不等于直接因果；见entry_cohort_audit.json。原坏单全部消失也不保证改进。', '', '趋势退出组6笔触发退出，匹配原始入场后3笔原亏损减亏、1笔原亏损扩大，2笔原盈利转亏；趋势确认加退出组5笔触发退出，3笔减亏、1笔原亏损扩大、1笔原盈利转亏。见matched_exit_diagnosis.json。减少某几笔亏损不代表组合净增益。', '', '全年收益和最大回撤同时达到基线的规则：'+(', '.join(pareto) if pareto else '无')+'。这一筛选不代表通过稳健性验证，必须结合尾部损失、费用、近期同本金和暴露变化判断。核心保持原样，不晋级实盘。', '',
      '初始实现因Pandas3原生时间戳精度不同，在指标合并时失败，未进入交易模拟；原始代码及执行记录保存在implementation_failure。统一UTC纳秒精度后重跑，金融规则未变，新增真实时间戳单位测试。未扫描阈值，保留全部金融变体。', '',
      '复现：`.venv/bin/python nfi_long_family.py control trend_gate trend_exit trend_both dip_recovery dip_limit --workers 2`；完成目录拒绝覆盖。然后运行`nfi_long_family_diagnose.py`、`nfi_long_family_report.py`与`nfi_long_family_plot.py`。','', '![权益及回撤](comparison.png)']
    (OUT/'REPORT.md').write_text('\n'.join(lines).rstrip()+'\n')
    print(json.dumps({n:{'return_pct':r['return_pct'],'dd':r['equity_audit']['mtm_drawdown_pct']} for n,r in results.items()},indent=2))
if __name__=='__main__':main()
