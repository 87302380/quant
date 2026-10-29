"""Portfolio robustness, equity-tail metrics and independently rebuilt plan-risk audit."""
import gzip,json,re,hashlib,math
from pathlib import Path
import numpy as np
import pandas as pd
import talib
from nfi_analyze import load_result,filled_orders
from nfi_rebound_report import collect
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/portfolio_risk';DATA=ROOT/'data/nfi_ytd2026/freqtrade/futures'


def tail_metrics(folder):
    frame=pd.read_csv(folder/'equity.csv',parse_dates=['time']).set_index('time');eq=frame.equity
    peak=eq.cummax().clip(lower=10000);dd=100*(peak-eq)/peak
    underwater=dd>1e-8;run=maximum=0
    for active in underwater:
        run=run+1 if active else 0;maximum=max(run,maximum)
    local=eq.tz_convert('Asia/Shanghai');daily=local.resample('D').last()
    # Do not call the last incomplete Beijing day a completed daily observation.
    if local.index[-1]<local.index[-1].normalize()+pd.Timedelta(days=1)-pd.Timedelta(minutes=5):daily=daily.iloc[:-1]
    returns=daily.pct_change(fill_method=None).dropna()*100
    n=max(1,math.ceil(len(returns)*.05));tail=returns.nsmallest(n)
    return {'ulcer_index_pct':float(np.sqrt(np.mean(dd**2))),'underwater_time_pct':float(100*underwater.mean()),'max_observed_underwater_hours':maximum/12,'last_underwater_spell_right_censored':bool(underwater.iloc[-1]),'daily_es95_pct':float(tail.mean()),'daily_es_observations':len(returns),'worst_rolling_24h_pct':float((100*(eq/eq.shift(288)-1)).min()),'gross_exposure_ratio_p95':float((frame.gross_notional/eq).quantile(.95))}


def risk_audit(folder,engine):
    if engine['strategy_name'] not in ['NFIShortPMPortfolio','NFIShortPMCooldown']:return None
    text=(folder/'run.log').read_text();audits=[]
    for match in re.finditer(r'PM_RISK_AUDIT\s+(\{[^}]+\})',text,re.S):
        audits.append(json.loads(''.join(line.strip() for line in match.group(1).splitlines())))
    assert len(audits)==len(engine['trades']),'Missing entry plan-risk audits'
    frames={};trades={};plans={}
    for trade in engine['trades']:
        entries=[o for o in filled_orders(trade) if o['ft_is_entry']];assert len(entries)==1
        first=entries[0];key=(trade['pair'],first['order_filled_timestamp']);assert key not in trades
        trades[key]=trade;pair=trade['pair']
        if pair not in frames:
            stem=pair.replace('/','_').replace(':','_')
            with gzip.open(DATA/f'{stem}-1h-futures.json.gz','rt') as stream:rows=json.load(stream)
            array=np.array(rows,dtype=float)
            frames[pair]=(array[:,0].astype('int64')+3600000,talib.ATR(array[:,2],array[:,3],array[:,4],14))
        dates,atrs=frames[pair];i=np.searchsorted(dates,trade['open_timestamp'],side='right')-1
        assert i>=0 and np.isfinite(atrs[i]);rate=first['safe_price'];distance=max(2*atrs[i],rate*.01)
        if not trade['is_short']:distance=min(distance,rate*.99)
        stop=rate+distance if trade['is_short'] else max(rate-distance,rate*.001)
        cost=abs(stop-rate)+trade['fee_open']*rate+trade['fee_close']*stop
        plans[key]={'quantity':first['amount'],'cost_per_coin':cost,'stop':stop,'trade':trade}
    seen={};records=[]
    for audit in audits:
        timestamp=int(pd.Timestamp(audit['time']).timestamp()*1000);key=(audit['pair'],timestamp)
        assert key in plans;seen[key]=plans[key];lower=0.
        # Same-timestamp exits may execute before or after this entry; subtract
        # all of them for a conservative lower bound, and check current entry
        # separately. Unfilled reservations may increase the logged total.
        for p in seen.values():
            exited=sum(o['amount'] for o in filled_orders(p['trade']) if not o['ft_is_entry'] and o['order_filled_timestamp']<=timestamp)
            lower+=max(0.,p['quantity']-exited)*p['cost_per_coin']
        current=plans[key]['quantity']*plans[key]['cost_per_coin']
        occupied=audit['occupied_planned_loss'];equity=audit['equity_basis'];limit=equity*audit['limit_fraction']
        assert occupied+.02>=max(lower,current),'Logged exposure omits filled risk'
        assert occupied<=limit+.02,f'Entry plan-risk cap exceeded: {occupied} > {limit}'
        assert current<=equity*.01+.02,'Individual planned-risk cap exceeded'
        records.append({**audit,'independently_rebuilt_current_risk':current,'independent_filled_exposure_lower_bound':lower,'occupied_fraction_pct':100*occupied/equity,'entry_fraction_pct':100*current/equity})
    return {'entries_audited':len(records),'max_occupied_fraction_pct':max(r['occupied_fraction_pct'] for r in records),'max_entry_fraction_pct':max(r['entry_fraction_pct'] for r in records),'qualified':True,'notes':'Entry-anchor remaining-quantity planned loss including entry+exit fees, both sides summed without offset. Confirmed Freqtrade Order.close_bt_order recalculates entry amount before order_filled; audit includes new entry. This is not a guaranteed loss/drawdown ceiling.','records':records}


def plot(results):
    import os
    os.environ.setdefault('MPLCONFIGDIR','/tmp/nfi-mpl');os.environ.setdefault('XDG_CACHE_HOME','/tmp/nfi-cache')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True)
    for name in ['control','half_all','portfolio','side_cap','shock_corr','atr_corr']:
        if name not in results:continue
        raw=pd.read_csv(OUT/name/'equity.csv',parse_dates=['time']).set_index('time').equity
        e=raw.resample('1h').last();dd=(100*(raw/raw.cummax()-1)).resample('1h').min()
        axes[0].plot(e.index,100*(e/10000-1),label=name)
        axes[1].plot(dd.index,dd,label=name)
    axes[0].set_title('Portfolio robustness: no allocation boosts, funding excluded');axes[0].set_ylabel('Net return %');axes[1].set_ylabel('5m drawdown %, hourly minima');axes[0].legend(ncol=3)
    for ax in axes:ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(OUT/'comparison.png',dpi=160);plt.close(fig)


def main():
    results={};raw={};audits={}
    for folder in sorted(OUT.iterdir()):
        if not folder.is_dir() or not list(folder.glob('*.zip')):continue
        if json.loads((folder/'execution.json').read_text())['status']!='success':continue
        r=collect(folder);s=load_result(next(folder.glob('*.zip')))
        assert r['campaigns_with_adds']==0 and all(t['leverage']==3 for t in s['trades'])
        r['tail_metrics']=tail_metrics(folder);r['return_drawdown_ratio']=r['return_pct']/r['equity_audit']['mtm_drawdown_pct']
        results[folder.name]=r;raw[folder.name]=s
        audit=risk_audit(folder,s)
        if audit is not None:audits[folder.name]=audit
    refs={n:collect(ROOT/'results/nfi/atr_short'/n) for n in ['gated','gated_july','gated_fee10']}
    if 'control' in raw:
        prior=load_result(next((ROOT/'results/nfi/atr_short/gated').glob('*.zip')))
        identity=lambda s:[(t['pair'],t['open_date'],t['close_date'],t['profit_abs'],t['enter_tag']) for t in s['trades']]
        assert identity(prior)==identity(raw['control']),'Control changed prior economics'
    if len(results)==29:
        decision={'strategy_auto_replaced':False,'services_started':False,'primary_finding':'No tested indicator combination is a universal robustness upgrade; uniform exposure reduction is the clearest broad risk reduction, with large return sacrifice.','fixed_risk_architecture':'Individual1% / aggregate3% are mechanically audited entry-time planned-loss limits, not guaranteed actual loss or drawdown caps.','profiles':['half_all: simplest lower-exposure reference','side_cap: hard same-direction concentration reference','shock: moderate peak-drawdown tradeoff, worse Ulcer; auxiliary risk-state research only','portfolio: explicit planned-stop-budget architecture with significant historical performance cost'],'independent_oos':False,'funding_excluded':True,'next_research':'Explicit gross exposure and cumulative-loss limits, then entry logic compatible with strict stops; do not widen stops or tune thresholds to known loss events.'}
        (OUT/'decision.json').write_text(json.dumps(decision,indent=2)+'\n')
    (OUT/'comparison.json').write_text(json.dumps(results,indent=2)+'\n');(OUT/'risk_budget_audit.json').write_text(json.dumps(audits,indent=2)+'\n');(OUT/'references.json').write_text(json.dumps(refs,indent=2)+'\n')
    lines=['# NFI组合风险与稳健性','',
    '固定历史：北京时间2026-01-01 08:00至2026-10-29 11:10；57静态币、10000 USDT、3倍、最多6仓、禁补仓、首次入场24h。基础是NFIShortATRGated：原生多头退出，扩展空头2x1hATR/2R与1%预算及BTC4h熊态门控。无仓位放大乘数。单边5bps，fee10为10bps真实重跑，资金费排除，沿用4ULP同价浮点修正。','',
    '风险指标：个币闭合1h ATR14；BTC过去15m跌幅相对闭合1hATR的冲击；BTC1h实现波动相对前7天中位值（参考剔除当前1h）；过去7天闭合1h收益相关性。阈值固定，不扫描优化。当前数据均已查看；不是独立样本外。','',
    '|年初至今方案|交易|净收益|含浮亏回撤|收益/回撤|Ulcer指数|日ES95|最差滚动24h|平均保证金/权益|','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in results.items():
        if n.endswith(('_fee10','_july')):continue
        t=r['tail_metrics'];lines.append(f"|{n}|{r['campaigns']}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{r['return_drawdown_ratio']:.2f}|{t['ulcer_index_pct']:.2f}%|{t['daily_es95_pct']:.2f}%|{t['worst_rolling_24h_pct']:.2f}%|{r['average_margin_equity_pct']:.2f}%|")
    lines+=['','收益/回撤是本段累计收益除以样本回撤，不年化，不是预测未来Calmar。Ulcer为5m权益回撤百分比的均方根；日ES95为已完成北京时间日收益最差5%均值（不含首个缺少前日收盘比较日与末个未完成日），越负表示尾部损失越重。5m权益及真实小时标价不是盘中极值。水下时长是组合权益恢复跨度，不是单笔持仓；最大水下时长和占比保留在comparison.json，末期未修复段按已观察时长记并标注右删失。','',
    '## 机制对照','',
    '- half_all：多空两边初始保证金同时减半，其他不变，用作组合限风险的公平缩仓对照。half_long：所有多头初始保证金减半，空头不变。long_budget：按假设2ATR止损限制多头计划风险1%，仍用原生退出，不实际启用该止损，只作仓位对照。long_stop：实际2ATR多头止损，原始初始额度，不额外1%限仓。long_atr：同时启用多头1%限仓和2ATR止损，保留原生盈利退出。距离至少价格1%，冻结首次成交价对应水平。','',
    '- portfolio：long_atr之上，入场前将全部未平仓剩余数量的计划止损损失（含双边费）相加，最多当时可交易已实现钱包3%；不将多空风险相抵。真实未成交Trade保留风险额度，未知风险拒绝新增；减仓释放相应剩余数量额度。已有仓不因钱包下降被强制重设预算，因此这是入场限制，不是持续保证。','',
    '- cooldown：portfolio基础上，同币多头止损后1h内拒绝新多头；过去滚动1h若任意币累计至少2笔多头止损，则在该条件仍成立时拒绝新多头。只用当时已平仓记录，未来平仓不参与。','',
    '- shock：BTC15m对数收益低于负1.5倍闭合1hATR/价格后，过去1h内存在该冲击就拒绝新多头，不强平已有仓。volatility：BTC1h跌且1h实现波动超过剔除当前小时的前7日中位数2倍时，新多头保证金减半；其余不增加额度。','',
    '- shock_corr结合现有shock与correlation；atr_corr结合现有long_atr与correlation。它们来自已知风险事件的互补性诊断，是事后探索，保持原有参数。','',
    '- correlation：新仓若与已有至少2个同向仓的7日小时收益相关性>=0.75，则拒绝；至少120共同观测，不足按1保守处理。这是新仓邻域规则，不是保证传递聚类。side_cap是不看相关性的同向最多2仓对照，名义全局上限仍6。相关序列在指标阶段缓存完整向量，决策时严格切到已闭合小时，避免第一次信号缓存成永久旧历史。','',
    '## 同本金重启与费用压力','',
    '初始计划half_long/long_atr/portfolio/correlation；首批结果显示long_atr在相近回撤下不如简单减仓，于phase2.json记录将该组资格复核改为half_all，保留long_atr完整年初至今诊断。half_long/half_all/portfolio分别做7月同10000本金重启与年初至今10bps；correlation保留已排定的年初至今10bps负面对照，不额外7月资格复核。phase3.json记录追加side_cap与shock的年初至今10bps及7月同本金复核；phase4.json追加已有规则shock_corr/atr_corr组合及同样复核，没有扫描新阈值。较早历史仅作预热，全部仍是已看过历史。原门控参照沿用既有结果，前提是新control逐笔完全一致。','',
    '|方案|区间收益|含浮亏回撤|Ulcer|日ES95|','|---|---:|---:|---:|---:|']
    for n in ['gated_july','gated_fee10']:
        r=refs[n];lines.append(f"|reference_{n}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|—|—|")
    for n,r in results.items():
        if n.endswith(('_fee10','_july')):lines.append(f"|{n}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{r['tail_metrics']['ulcer_index_pct']:.2f}%|{r['tail_metrics']['daily_es95_pct']:.2f}%|")
    lines+=['','## 本轮判断','']
    if all(n in results for n in ['control','half_all','portfolio','correlation']):
        c,h,p,k=[results[n] for n in ['control','half_all','portfolio','correlation']]
        lines.append(f"简单双向减半：收益{h['return_pct']:.2f}%，回撤{h['equity_audit']['mtm_drawdown_pct']:.2f}%，日ES95 {h['tail_metrics']['daily_es95_pct']:.2f}%，Ulcer {h['tail_metrics']['ulcer_index_pct']:.2f}%；原框架分别{c['return_pct']:.2f}%、{c['equity_audit']['mtm_drawdown_pct']:.2f}%、{c['tail_metrics']['daily_es95_pct']:.2f}%、{c['tail_metrics']['ulcer_index_pct']:.2f}%。主要是承担更少风险，不能称信号alpha提高。")
        lines.append(f"3%计划预算框架收益{p['return_pct']:.2f}%、回撤{p['equity_audit']['mtm_drawdown_pct']:.2f}%，在本样本收益/回撤上不如双向减半。预算实现被订单审计验证，但机械风险约束正确不等于收益与稳健性优化成功。普通相关性组收益{k['return_pct']:.2f}%、回撤{k['equity_audit']['mtm_drawdown_pct']:.2f}%，未改善原框架最大回撤。")
    if all(n in results for n in ['shock_corr','atr_corr']):
        for n in ['shock_corr','atr_corr']:
            r=results[n];lines.append(f"组合{n}：收益{r['return_pct']:.2f}%，回撤{r['equity_audit']['mtm_drawdown_pct']:.2f}%，Ulcer {r['tail_metrics']['ulcer_index_pct']:.2f}%；不能因单个风险指标改善就宣称整体更稳。组合是在查看风险事件后追加，参数未改变，仍有适应性选择偏差。")
    lines.append('最大回撤时实际持仓、入场前相关矩阵见drawdown_diagnosis.json；这些持仓是事后选择用来解释风险，不是按结果拟合的新交易规则。后续限制见[FORWARD.md](../../../research/nfi/portfolio_risk/FORWARD.md)。')
    lines+=['','## 组合计划风险审计','',
    'risk_budget_audit.json将实际订单数量、首次成交前已闭合1hATR与手续费独立重建，并核对入场日志。已确认本版引擎Order.close_bt_order在入场回调前重算数量；日志应包含新仓。对同时间戳退出用保守剩余暴露下界，并单独核对新仓风险，避免事件排序伪造精度。未知未成交预留可使日志大于已成交下界。','']
    for n,a in audits.items():lines.append(f"- {n}：核对{a['entries_audited']}笔入场，最高合计计划风险{a['max_occupied_fraction_pct']:.4f}%，最高单笔{a['max_entry_fraction_pct']:.4f}%。")
    lines+=['','1%与3%都是计划损失，不是实际亏损、最大回撤或任何市场状态下的保证上限。跳空、连续多次止损、手续费与流动性变化可使真实损失超预算；所有实验保留真实引擎订单与费用，不事后删超期或亏损交易。','',
    '## 解释边界与复现','',
    '本轮不使用更多指标数量代表有效性。简单减仓或少开仓本来就会降低部分风险，必须对照收益保留、尾部损失和平均暴露，不能把全部回撤降低称作预测能力。当前币池事后选择、已看过历史、样本最大回撤与限价成交模拟都有局限。没有启动实盘或其他交易服务。','',
    '复现：`.venv/bin/python nfi_portfolio.py control half_all half_long long_budget long_stop long_atr portfolio cooldown shock volatility correlation side_cap --workers 2`；再运行`.venv/bin/python nfi_portfolio_report.py`。费用压力加`--fee .001 --suffix _fee10`，7月重启加`--start 2026-07-01T00:00:00Z --suffix _july`。成功目录拒绝覆盖。','',
    '![权益与回撤](comparison.png)','']
    (OUT/'REPORT.md').write_text('\n'.join(lines).rstrip()+'\n');plot(results)
    for n,r in results.items():print(n,r['campaigns'],round(r['return_pct'],3),round(r['equity_audit']['mtm_drawdown_pct'],3),round(r['tail_metrics']['ulcer_index_pct'],3),flush=True)
if __name__=='__main__':main()
