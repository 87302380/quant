"""Report all predeclared return-search results, including failed hypotheses."""
import hashlib,json
from pathlib import Path
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from nfi_analyze import analyze,load_result,filled_orders
from nfi_optimize import VARIANTS

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results/nfi/return_search'
DATA=ROOT/'data/nfi_ytd2026/freqtrade/futures'


def main():
    results={}
    for name in ['baseline','overheat']+list(VARIANTS):
        folder=ROOT/'results/nfi/ytd_research'/name if name in ['baseline','overheat'] else OUT/name
        paths=list(folder.glob('*.zip'))
        if len(paths)!=1:raise ValueError(f'Expected one completed run for {name}')
        s=load_result(paths[0]);ts=s['trades']
        if name in ['baseline','overheat']:
            r=json.loads((folder/'analysis.json').read_text())
        else:
            if json.loads((folder/'execution.json').read_text())['status']!='success':raise ValueError('Incomplete engine run')
            log=(folder/'run.log').read_text()
            if 'Traceback' in log or ' - ERROR - ' in log:raise ValueError(f'Callback errors in {name}')
            saved=folder/'analysis.json'
            r=json.loads(saved.read_text()) if saved.exists() else None
            if r is None or r.get('archive_sha256')!=hashlib.sha256(paths[0].read_bytes()).hexdigest():
                r=analyze(paths[0],DATA)
        wins=[t['profit_abs'] for t in ts if t['profit_abs']>0];loss=[t['profit_abs'] for t in ts if t['profit_abs']<0]
        r['profit_factor']=s['profit_factor']
        r['payoff_ratio']=-np.mean(wins)/np.mean(loss) if loss else None
        r['largest5_winners_usdt']=sum(sorted(wins,reverse=True)[:5])
        r['largest5_share_of_gross_profit_pct']=100*r['largest5_winners_usdt']/sum(wins) if wins else 0
        r['worst_mtm_month_pct']=min(x['return_pct'] for x in r['equity_audit']['monthly_mtm'].values())
        equity=pd.read_csv(folder/'equity.csv',parse_dates=['time']).set_index('time').equity
        split=equity[equity.index<pd.Timestamp('2026-07-01',tz='UTC')].iloc[-1]
        r['calendar_segment_returns_pct']={'Jan-Jun':100*(split/10000-1),'Jul-Oct':100*(equity.iloc[-1]/split-1)}
        results[name]=r
    bm=load_result(next((ROOT/'results/nfi/ytd_research/baseline').glob('*.zip')))
    key=lambda t:(t['pair'],t['is_short'],t['open_timestamp'])
    base={key(t):t for t in bm['trades']}
    for name in VARIANTS:
        ts=load_result(next((OUT/name).glob('*.zip')))['trades'];other={key(t):t for t in ts};common=base.keys()&other.keys()
        results[name]['matching']={'same_entries':len(common),'baseline_only':len(base.keys()-other.keys()),'new_entries':len(other.keys()-base.keys()),
            'win_to_loss':sum(base[k]['profit_abs']>0>other[k]['profit_abs'] for k in common),'loss_to_win':sum(base[k]['profit_abs']<0<other[k]['profit_abs'] for k in common)}
    stress={}
    for name in ['weighted_fee10','baseline_fee10','weighted_no_adds_fee10']:
        paths=list((OUT/name).glob('*.zip'))
        if paths:
            folder=OUT/name
            if json.loads((folder/'execution.json').read_text())['status']!='success':raise ValueError('Incomplete cost replay')
            if 'Traceback' in (folder/'run.log').read_text() or ' - ERROR - ' in (folder/'run.log').read_text():raise ValueError('Cost replay callback failure')
            saved=folder/'analysis.json'
            stress[name]=json.loads(saved.read_text()) if saved.exists() else analyze(paths[0],DATA)
    if stress:(OUT/'cost_replays.json').write_text(json.dumps(stress,indent=2)+'\n')
    (OUT/'comparison.json').write_text(json.dumps(results,indent=2)+'\n')
    ordered=sorted(results,key=lambda name:results[name]['return_pct'],reverse=True)
    lines=['# NFI X8：以收益率为目标的机制实验','',
           '用户授权扩大指标、信号和持仓管理研究。首批预先固定8项机制，第二批在前四项结果出现后增加2项组合/延长盈利持仓假设，第三批组合资金加权和禁止补仓，没有扫描参数网格；全部是适应性回顾研究，保留所有结果。原版源码未改，继承类与分批计划位于research/nfi/return_search。', '',
           '统一窗口：2026-01-01至2026-10-29北京时间11:10。57币、10,000 USDT同一初始钱包、3倍杠杆、最多6仓；首次入场后24h必须平仓，补仓不重置计时。单边5bps手续费已计入，资金费未计入。所有历史均已被查看，静态选币存在事后及存活者偏差，不是独立样本外。','',
           '|方案|交易数|收益|含浮亏回撤|胜率|利润因子|最差月|额外10bps成交成本后收益|',
           '|---|---:|---:|---:|---:|---:|---:|---:|']
    for name in ordered:
        r=results[name];lines.append(f"|{name}|{r['campaigns']}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{r['win_rate_pct']:.2f}%|{r['profit_factor']:.2f}|{r['worst_mtm_month_pct']:.2f}%|{r['fixed_path_slippage_stress']['10']['return_pct']:.2f}%|")
    lines+=['','额外成交成本是原订单路径不变的附加扣费，不是盘口重放。权益回撤按5m最后已收盘价格采样，非盘中极值；整点真实标记价格回撤也单独保留在JSON中。','',
            '## 机制与风险暴露','',
            '- long_only：基线上删除所有空头；no_short_rebuy：只删除含short-rebuy标签的入场；no_adds：禁止增加仓位，保留部分减仓。',
            '- overheat_long：已知RSI80/20过滤叠加纯多头；relative_strength：增加已闭合4h的过去24h相对BTC收益指标，多头要求不弱于BTC，空头要求不强于BTC，BTC自身豁免。',
            '- weighted：RSI过滤上，将long normal/top-coins初始保证金乘1.5、short-rebuy乘0.5。总钱包与杠杆不变，但实际资金暴露可能增加；收益差不能全部当成信号优势。',
            '- campaign_trail：RSI过滤上，整轮净浮盈达到首笔保证金3%后，收盘净浮盈回落到历史峰值60%则退出；保留原有退出，首先执行24h期限。',
            '- size_only：仅使用上一轮ATR初始缩仓，保留原版补仓和退出、取消ATR止损。它检验上一轮改善是否主要来自少下注，不承诺实际风险受冻结预算约束。','',
            '- 第二批overheat_no_adds组合过热过滤和禁止补仓；trend_runner在净盈利且闭合5m价格/EMA20斜率与闭合4h EMA12/EMA50趋势一致时延迟原生exit_profit退出，延迟后趋势破坏即退出，其余退出和24h约束保留。','',
            '- 第三批weighted_no_adds仅将现有资金加权与禁止补仓组合，保持所有权重和阈值不变，并进行正常/双倍手续费两次实际回放。','',
            '## 分段与集中度','',
            '|方案|1—6月收益|7—10月收益|最大5笔盈利占总盈利|最高持仓名义额USDT|平均保证金USDT|',
            '|---|---:|---:|---:|---:|---:|']
    for name in ordered:
        r=results[name];a=r['equity_audit'];h=r['calendar_segment_returns_pct']
        lines.append(f"|{name}|{h['Jan-Jun']:.2f}%|{h['Jul-Oct']:.2f}%|{r['largest5_share_of_gross_profit_pct']:.2f}%|{a['max_gross_notional_usdt']:.2f}|{a['average_margin_basis_usdt']:.2f}|")
    lines+=['','## 结果判断','',
            f"本轮最高历史收益是{ordered[0]}，收益{results[ordered[0]]['return_pct']:.2f}%、含浮亏回撤{results[ordered[0]]['equity_audit']['mtm_drawdown_pct']:.2f}%；基线为113.67%和13.32%。它保持3倍杠杆与同一钱包，但资金加权改变实际保证金和名义持仓，不能将全部增益称为信号优势。", '',
            '相对更少改变资金分配的候选为overheat_no_adds，收益130.51%。它组合禁止补仓和已知过热过滤，仍有同一区间组合选择偏差。纯多头、相对BTC强弱过滤、提前追踪止盈都未提高收益；高胜率本身不是本轮优化目标。','',
            '纯初始缩仓size_only为14.39%收益、1.83%回撤；上一轮带ATR止损和补仓预算的budget为12.43%、1.83%。因此回撤下降主要来自初始缩仓；止损与补仓约束的组合未显示额外优势。这个对照还不能分别分离止损与补仓限制的贡献。','',
            f"建议将{ordered[0]}作为收益优先的研究候选，overheat_no_adds作为不提高初始仓位的对照。保持前向配置停止，不将历史最高收益直接等同于可实盘。下一步检验应冻结规则记录未来信号，而不是继续在本段历史上微调到更高数字。",'']
    if stress:
        lines+=['## 双倍手续费真实重跑','',
                '以下每笔成交单边10bps手续费，重新运行完整引擎、订单和资金路径；不是从原利润中简单扣费。该压力检查仍未模拟真实盘口滑点。','',
                '|方案|收益|5m权益回撤|交易数|','|---|---:|---:|---:|']
        for name,r in stress.items():lines.append(f"|{name}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{r['campaigns']}|")
        lines+=['']
    lines+=['','分段是同一连续资金路径的描述，7月起没有重置钱包；不是新的验证集。逐币、方向、信号族、补仓、时限退出和最差交易详见comparison.json。对照交易匹配见matching字段；交易减少后剩余仓位和未来信号会改变，不能只删掉旧交易再加减利润。','',
            '## 可复现','',
            '`.venv/bin/python nfi_optimize.py long_only no_short_rebuy no_adds overheat_long relative_strength weighted campaign_trail size_only overheat_no_adds trend_runner weighted_no_adds --workers 2`。已有结果目录拒绝覆盖；应另存后再重跑。成本压力用`--fee .001 --suffix _fee10`。完成后执行`.venv/bin/python nfi_optimize_report.py`。', '',
            '两组并行回放使用独立钱包与用户缓存，原始交易ZIP与execution.json保存引擎证据。新增相对强弱指标只在4h完全收盘后可用，已测试尚未收盘的未来大幅变动不会影响当前结果。没有实盘进程或订单。','',
            '![权益与回撤](comparison.png)','']
    (OUT/'REPORT.md').write_text('\n'.join(lines))
    fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True)
    selected=list(dict.fromkeys(['baseline','overheat']+ordered[:3]+['size_only']))
    for name in selected:
        folder=ROOT/'results/nfi/ytd_research'/name if name in ['baseline','overheat'] else OUT/name
        df=pd.read_csv(folder/'equity.csv',parse_dates=['time']).set_index('time');eq=df.equity
        axes[0].plot(eq.index,100*(eq/10000-1),label=name,linewidth=1)
        axes[1].plot(eq.index,100*(eq/eq.cummax().clip(lower=10000)-1),label=name,linewidth=1)
    axes[0].set(title='NFI return search: fixed 3x, 57 pairs, max 24h',ylabel='Wallet return (%)');axes[0].legend(ncol=3)
    axes[1].set(ylabel='Sampled drawdown (%)')
    for ax in axes:ax.grid(alpha=.25)
    fig.text(.07,.015,'Retrospective selected universe; 5 bps per fill; funding excluded; discrete closed-price equity.',fontsize=9)
    fig.tight_layout(rect=(0,.035,1,1));fig.savefig(OUT/'comparison.png',dpi=170);plt.close(fig)
    print('\n'.join(lines[:18]))


if __name__=='__main__':main()
