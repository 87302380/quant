"""Audit matched fixed-allocation ATR short experiments, preserving failed hypotheses."""
import json,gzip,hashlib
from pathlib import Path
import pandas as pd
from nfi_analyze import load_result,groups,filled_orders
from nfi_rebound_report import collect
ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results/nfi/atr_short'

def match(a,b):
    def key(t):return (t['pair'],t['open_date'],t['is_short'])
    x={key(t):t for t in a['trades']};y={key(t):t for t in b['trades']};common=x.keys()&y.keys()
    return {'matched_close_times':sum(x[k]['close_date']==y[k]['close_date'] for k in common),'matched_exit_reasons':sum(x[k]['exit_reason']==y[k]['exit_reason'] for k in common),'matched_entries':len(common),'only_left':len(x.keys()-y.keys()),'only_right':len(y.keys()-x.keys()),'matched_actual_profit_difference_usdt':sum(y[k]['profit_abs']-x[k]['profit_abs'] for k in common),'warning':'Actual compounded sizes differ; not isolated causal dollar alpha'}

def recovery(s):
    cache={};out=[]
    for t in s['trades']:
        if not t['is_short'] or t['exit_reason'] not in ['trailing_stop_loss','stop_loss','research_short_stop_gap']:continue
        pair=t['pair']
        if pair not in cache:
            name=pair.replace('/','_').replace(':','_')+'-5m-futures.json.gz'
            with gzip.open(ROOT/'data/nfi_ytd2026/freqtrade/futures'/name,'rt') as f:rows=json.load(f)
            frame=pd.DataFrame(rows,columns=['ts','open','high','low','close','volume']);frame['time']=pd.to_datetime(frame.ts,unit='ms',utc=True)+pd.Timedelta(minutes=5);cache[pair]=frame
        frame=cache[pair];start=pd.Timestamp(t['close_date']);end=pd.Timestamp(t['open_date'])+pd.Timedelta(hours=24)
        future=frame[(frame.time>start)&(frame.time<=end)]
        # Diagnostic only, no claim of executable hindsight-minimum exit.
        breakeven=t['open_rate']*(1-t['fee_open'])/(1+t['fee_close'])
        out.append({'pair':pair,'open_date':t['open_date'],'close_date':t['close_date'],'profit_usdt':t['profit_abs'],'later_closed_price_breakeven_before_24h':bool((future.close<=breakeven).any()),'observed_future_bars':len(future)})
    return {'stopped_shorts':len(out),'later_breakeven_count':sum(t['later_closed_price_breakeven_before_24h'] for t in out),'trades':out,'warning':'Post-exit hypothetical original-price recovery only, excludes released-capital opportunity and intervening risk; does not prove holding is preferable'}

def trough_holdings(result,engine):
    time=pd.Timestamp(result['equity_audit']['drawdown_trough_time']);records=[]
    for t in engine['trades']:
        if not (pd.Timestamp(t['open_date'])<=time<pd.Timestamp(t['close_date'])):continue
        stem=t['pair'].replace('/','_').replace(':','_')
        with gzip.open(ROOT/'data/nfi_ytd2026/freqtrade/futures'/f'{stem}-5m-futures.json.gz','rt') as f:rows=json.load(f)
        price=next(row[4] for row in reversed(rows) if row[0]+300000<=time.value//1000000)
        cash=qty=0.
        for order in filled_orders(t):
            if order['order_filled_timestamp']>time.value//1000000:continue
            sign=1 if order['ft_order_side']=='buy' else -1
            amount=order['amount'];rate=order['safe_price']
            cash-=sign*amount*rate+amount*rate*t['fee_open' if order['ft_is_entry'] else 'fee_close']
            qty+=sign*amount
        records.append({'pair':t['pair'],'side':'short' if t['is_short'] else 'long','tag':t['enter_tag'],'open_date':t['open_date'],'open_rate':t['open_rate'],'closed_mark_price':price,'campaign_mtm_pnl_usdt':cash+qty*price})
    return {'time_utc':str(time),'time_shanghai':str(time.tz_convert('Asia/Shanghai')),'holdings':records,'warning':'Open-campaign current PnL, not attribution of entire peak-to-trough equity change'}

def main():
    results={};raw={}
    for folder in sorted(OUT.iterdir()):
        if folder.is_dir() and list(folder.glob('*.zip')):
            r=collect(folder);s=load_result(next(folder.glob('*.zip')))
            assert r['campaigns_with_adds']==0
            assert all(t['leverage']==3 for t in s['trades'])
            assert s['starting_balance']==10000 and len(s['pairlist'])==57
            r['exit_groups']=groups(s['trades'],lambda t:t['exit_reason']);r['short_exit_groups']=groups([t for t in s['trades'] if t['is_short']],lambda t:t['exit_reason'])
            r['short_profit_factor']=sum(max(t['profit_abs'],0) for t in s['trades'] if t['is_short'])/max(1e-12,-sum(min(t['profit_abs'],0) for t in s['trades'] if t['is_short']))
            r['direction_quality']={}
            for side in ['long','short']:
                trades=[t for t in s['trades'] if t['is_short']==(side=='short')]
                wins=[t['profit_ratio'] for t in trades if t['profit_abs']>0];losses=[t['profit_ratio'] for t in trades if t['profit_abs']<0]
                gp=sum(max(t['profit_abs'],0) for t in trades);gl=-sum(min(t['profit_abs'],0) for t in trades)
                r['direction_quality'][side]={'trades':len(trades),'profit_factor':gp/max(gl,1e-12),'average_winning_margin_return_pct':100*sum(wins)/max(len(wins),1),'average_losing_margin_return_pct':100*sum(losses)/max(len(losses),1),'average_payoff_ratio':(sum(wins)/max(len(wins),1))/max(1e-12,-sum(losses)/max(len(losses),1))}
            results[folder.name]=r;raw[folder.name]=s
    pairs=[('native','budget'),('budget','stop'),('stop','target'),('target','gated'),('gated','weak'),('base_risk','target'),('gated','gated_stop'),('weak','weak_stop'),('gated_stop','weak_stop')]
    attribution={a+'__'+b:match(raw[a],raw[b]) for a,b in pairs if a in raw and b in raw}
    troughs={n:trough_holdings(results[n],raw[n]) for n in ['control','gated','weak','gated_stop','weak_stop'] if n in raw}
    (OUT/'drawdown_holdings.json').write_text(json.dumps(troughs,indent=2)+'\n')
    recover={n:recovery(raw[n]) for n in ['stop','target','gated','weak','gated_stop','weak_stop'] if n in raw}
    (OUT/'comparison.json').write_text(json.dumps(results,indent=2)+'\n');(OUT/'entry_matching.json').write_text(json.dumps(attribution,indent=2)+'\n');(OUT/'stop_recovery.json').write_text(json.dumps(recover,indent=2)+'\n')
    lines=['# 固定仓位：空头ATR退出、熊态门控与相对强弱','', '历史窗口为北京时间2026-01-01 08:00至2026-10-29 11:10；_july从北京时间7月1日08:00同本金重启。固定57币、10000 USDT初始钱包、3倍、6仓、首次成交24h退出；不增加原始NFI初始仓位，所有组禁止正向补仓。费用单边5bps，fee10为10bps真实重跑；资金费排除。4ULP同价舍入修正沿用既有协议。','', '用户诊断源码未提供，本轮为独立重建，不能称精确复现。control统一禁止补仓，因此不是旧版允许补仓的baseline_24h；不能把两者收益差直接归因于空头。原始多头信号和原生退出保留；long初始stake采用原版，无历史1.5/1.25加权。原始四空头与新增九空头按同样规则管理。熊态要求闭合BTC4h低于EMA200且EMA200较6根前下降；weak再要求个币闭合4h的24h收益低于BTC。只在入场过滤，不强制状态切换退出。','', '空头ATR14来自已收盘1h；固定初始距离max(2ATR,1%价格)，计划止损成本含双边费，初始保证金不超过原生额度且计划风险不超过当时可交易已实现钱包1%。非保证损失上限：跳空、滑点可突破预算。2R目标按5m回调当前价格触发，非盘中最高/最低价保证成交；止损由引擎执行。','', '|方案|交易|收益|含浮亏回撤|平仓回撤|组合PF|空头PF|7—10月区段收益|平均保证金/权益|','|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in results.items():lines.append(f"|{n}|{r['campaigns']}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{r['closed_trade_drawdown_pct']:.2f}%|{r['profit_factor']:.2f}|{r['short_profit_factor']:.2f}|{r['segment_return_pct']['Jul-Oct']:.2f}%|{r['average_margin_equity_pct']:.2f}%|")
    lines+=['','## 关键对照判断','']
    if all(n in results for n in ['native','budget','stop']):
        a,b,c=[results[n] for n in ['native','budget','stop']]
        lines.append(f"原生扩展{a['return_pct']:.2f}%→仅加ATR仓位上限{b['return_pct']:.2f}%→再启用真实ATR止损{c['return_pct']:.2f}%。native/budget的入场匹配见entry_matching；预算调整本身已改变保证金、复利和最终收益，不能把native到stop全部差额归因于止损。budget到stop的含浮亏回撤{b['equity_audit']['mtm_drawdown_pct']:.2f}%→{c['equity_audit']['mtm_drawdown_pct']:.2f}%，此处实际启用止损并未摧毁收益。")
    if all(n in results for n in ['target','gated','weak']):
        a,b,c=[results[n] for n in ['target','gated','weak']]
        lines.append(f"2R框架下空头自身PF：无门控{a['short_profit_factor']:.2f}→熊态{b['short_profit_factor']:.2f}→相对弱势{c['short_profit_factor']:.2f}；弱势过滤提升质量但降低总收益，不能仅凭组合PF判定空头alpha大小。")
        lines.append(f"门控/弱势的平仓回撤{b['closed_trade_drawdown_pct']:.2f}%/{c['closed_trade_drawdown_pct']:.2f}%，含浮亏回撤{b['equity_audit']['mtm_drawdown_pct']:.2f}%/{c['equity_audit']['mtm_drawdown_pct']:.2f}%。不得把前者称为组合真实最大风险。")
    if all(n in results for n in ['control_july','target_july','gated_july','weak_july']):
        a,b,c,d=[results[n] for n in ['control_july','target_july','gated_july','weak_july']]
        lines.append(f"7月同本金重启：control {a['return_pct']:.2f}%、无门控2R {b['return_pct']:.2f}%、门控2R {c['return_pct']:.2f}%、相对弱势 {d['return_pct']:.2f}%。门控避免了多数无门控拖累，但两候选均没有显示相对原始核心明确的反弹收益优势；弱势相对control仅差{d['return_pct']-a['return_pct']:.2f}个百分点，不称稳健胜出。")
    if all(n in results for n in ['gated_fee10','weak_fee10']):
        lines.append(f"双倍手续费全年：门控{results['gated_fee10']['return_pct']:.2f}%、弱势{results['weak_fee10']['return_pct']:.2f}%；这是真实重跑，仍未包括资金费或真实订单队列。")
    lines.append('原始初始仓位没有放大，但新增短交易增加组合实际暴露，平均保证金/权益单列；这并非严格同组合风险匹配。个币ATR计划预算也不限制六仓同时开仓后的总计划损失。')
    lines+=['','control原生4空头；native增加9空头但仍原生退出；budget仅应用同样ATR推算仓位上限，不启用ATR止损；stop在budget上启用ATR止损并保留原生利润退出；target再替换空头利润退出为2R；gated再加熊态；weak再加相对弱势；base_risk是原生4空头采用同样ATR/2R预算；gated_stop/weak_stop保留原生利润退出而非2R，以复核退出和过滤的交互。','', '## 入口匹配与止损后恢复','', 'entry_matching.json逐组按币种/入场时间/方向匹配，列出共同与新增/消失交易。预算、释放资金和复利会改变成交路径；收益百分点差不能当alpha贡献百分比。stop_recovery.json列出止损空单在首次入场24h内，后续闭合价格是否曾回到计费保本价；这是事后路径诊断，不代表该价格会被规则实际捕捉，也没有扣除持有期间风险和资金机会。','']
    for n,r in recover.items():lines.append(f"- {n}：止损空单{r['stopped_shorts']}，此后原持仓期限内曾回到保本价{r['later_breakeven_count']}。")
    lines+=['','## 最大回撤时持仓','', 'drawdown_holdings.json记录各方案最大回撤时实际未平仓、方向、闭合标价和整轮当前损益。它解释风险集中，不把未平仓损益等同整个峰谷回撤。','']
    for n,v in troughs.items():lines.append(f"- {n}：{v['time_shanghai']}，多头{sum(t['side']=='long' for t in v['holdings'])}仓、空头{sum(t['side']=='short' for t in v['holdings'])}仓。")
    lines+=['','## 多空质量分开比较','','|方案|方向|交易|PF|平均盈利保证金收益|平均亏损保证金收益|平均盈亏比|','|---|---|---:|---:|---:|---:|---:|']
    for n,r in results.items():
        for side,q in r['direction_quality'].items():lines.append(f"|{n}|{side}|{q['trades']}|{q['profit_factor']:.2f}|{q['average_winning_margin_return_pct']:.2f}%|{q['average_losing_margin_return_pct']:.2f}%|{q['average_payoff_ratio']:.2f}|")
    lines+=['','PF按实际USDT盈利/亏损加总，受仓位及复利影响；平均盈亏比按逐笔保证金收益率的盈利均值/亏损均值计算，二者并不相同。baseline含空头，不称纯多头。','']
    lines+=['','## 证据边界','', '回撤主要用5m闭合价格重建全部持仓权益，另保留真实小时标记价回撤；非盘中最坏回撤。平仓余额回撤单列，不替代含浮亏回撤。所有历史已查看，含事后静态选币及研究选择偏差，不称独立样本外。禁止由更高历史收益推断未来胜率；不启动实盘。','', '复现：`.venv/bin/python nfi_atr_short.py control native budget stop target gated weak base_risk gated_stop weak_stop --workers 2`，随后`.venv/bin/python nfi_atr_report.py`。各成功目录拒绝覆盖；费用和7月独立本金测试使用--fee、--start、--suffix。']
    lines+=['','后续冻结与风险研究见[FORWARD.md](../../../research/nfi/atr_short/FORWARD.md)。','']
    lines+=['','![权益与回撤](comparison.png)','']
    (OUT/'REPORT.md').write_text('\n'.join(lines).rstrip()+'\n')
    plot(results)
    for n,r in results.items():print(n,r['campaigns'],round(r['return_pct'],3),round(r['equity_audit']['mtm_drawdown_pct'],3),round(r['profit_factor'],3),flush=True)
def plot(results):
    import os
    os.environ.setdefault('MPLCONFIGDIR','/tmp/nfi-mpl');os.environ.setdefault('XDG_CACHE_HOME','/tmp/nfi-cache')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True)
    for n in ['control','native','stop','target','gated','weak','gated_stop','weak_stop']:
        if n not in results:continue
        eq=pd.read_csv(OUT/n/'equity.csv',parse_dates=['time']).set_index('time').equity.resample('1h').last()
        axes[0].plot(eq.index,100*(eq/10000-1),label=n,lw=1.3)
        axes[1].plot(eq.index,100*(eq/eq.cummax()-1),label=n,lw=1.1)
    axes[0].set_ylabel('Net return %');axes[1].set_ylabel('Sampled equity drawdown %')
    axes[0].legend(ncol=4);axes[0].set_title('Fixed native allocation: ATR short exit ablation (funding excluded)')
    for ax in axes:ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(OUT/'comparison.png',dpi=160);plt.close(fig)

if __name__=='__main__':main()
