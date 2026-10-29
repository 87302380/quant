"""Return/risk and rebound attribution with fresh-July wallet checks separated."""
import json,hashlib
from pathlib import Path
import pandas as pd
from nfi_analyze import analyze,load_result,groups

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'results/nfi/rebound';DATA=ROOT/'data/nfi_ytd2026/freqtrade/futures'
REF={'incumbent':'incumbent_precision','expanded':'expanded_precision','slow_gate':'gated_precision'}


def collect(folder):
    archives=list(folder.glob('*.zip'))
    if len(archives)!=1:raise ValueError(f'Expected one result: {folder}')
    record=json.loads((folder/'execution.json').read_text());assert record['status']=='success'
    if (folder/'run.log').exists():
        log=(folder/'run.log').read_text();assert 'Traceback' not in log and ' - ERROR - ' not in log
    saved=folder/'analysis.json'
    r=json.loads(saved.read_text()) if saved.exists() and (folder/'equity.csv').exists() else None
    if r is None or r.get('archive_sha256')!=hashlib.sha256(archives[0].read_bytes()).hexdigest():r=analyze(archives[0],DATA)
    assert r['deadline_audit']['overdue_campaigns']==r['deadline_audit']['late_adds']==0
    eq=pd.read_csv(folder/'equity.csv',parse_dates=['time']).set_index('time')
    assert abs(eq.equity.iloc[-1]-(10000+r['profit_usdt']))<.01,'Cached equity CSV is incomplete or stale'
    if (eq.index<pd.Timestamp('2026-07-01',tz='UTC')).any():
        split=eq.equity[eq.index<pd.Timestamp('2026-07-01',tz='UTC')].iloc[-1]
        r['segment_return_pct']={'Jan-Jun':100*(split/10000-1),'Jul-Oct':100*(eq.equity.iloc[-1]/split-1)}
    else:r['segment_return_pct']={'Jul-Oct':r['return_pct']}
    s=load_result(archives[0]);r['short_by_open_half']=groups([t for t in s['trades'] if t['is_short']],lambda t:'Jan-Jun' if t['open_date']<'2026-07' else 'Jul-Oct')
    r['profit_factor']=s['profit_factor']
    r['average_margin_equity_pct']=float(100*(eq.margin_basis/eq.equity).mean())
    r['average_gross_equity_ratio']=float((eq.gross_notional/eq.equity).mean())
    r['monthly_mtm']=r['equity_audit']['monthly_mtm']
    return r


def main():
    results={name:collect(ROOT/'results/nfi/short_search'/ref) for name,ref in REF.items()}
    for name in ['fast','soft','long_bias','local','cover_loss','cooldown','allocation_only','style_gate','core_allocation']:results[name]=collect(OUT/name)
    extra={}
    for folder in sorted(OUT.iterdir()):
        if folder.is_dir() and (folder.name.endswith('_july') or folder.name.endswith('_fee10')) and list(folder.glob('*.zip')):
            extra[folder.name]=collect(folder)
    (OUT/'comparison.json').write_text(json.dumps(results,indent=2)+'\n')
    (OUT/'validation_replays.json').write_text(json.dumps(extra,indent=2)+'\n')
    lines=['# NFI反弹状态优化','',
           '研究窗口2026-01-01 00:00 UTC至2026-10-29 03:10 UTC，57固定币、同一10,000 USDT初始钱包、3倍杠杆、6仓、首次入场起24小时上限，禁止补仓。单边手续费5bps，资金费排除。沿用已披露的4ULP机器舍入成交边界修正，所有参照同口径。', '',
           '目标是改善反弹区间收益，交易规则只读已闭合BTC/个币状态，不以7月等日历日期切换。7—10月用于事后描述和候选选择，已被反复查看，不是新样本外。','',
           '|方案|年初至今收益|连续钱包7—10月收益|含浮亏回撤|7—10月空头净利润USDT|平均保证金/权益|',
           '|---|---:|---:|---:|---:|---:|']
    for name,r in results.items():
        short=r['short_by_open_half'].get('Jul-Oct',{}).get('profit_usdt',0)
        lines.append(f"|{name}|{r['return_pct']:.2f}%|{r['segment_return_pct']['Jul-Oct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{short:.2f}|{r['average_margin_equity_pct']:.2f}%|")
    lines+=['','空头净利润按入场所属区段归因；连续区间收益按日历权益切割，跨月仓位的归属会有差异。','']
    lines+=['','## 机制','',
            '- incumbent：此前加权且禁止补仓核心。expanded：额外启用9个原生空头。slow_gate：新增9个空头只在闭合BTC4h低于EMA200且均线24小时下行时启用。',
            '- fast：闭合BTC4h价格高于EMA50且EMA12>EMA50为反弹/上涨，禁开所有空头；两条件均反向为偏空，允许全部13个空头；混合状态只保留原生4个。既有仓位不因状态变化强制退出。',
            '- soft：信号保留，偏空/混合/上涨状态将初始空头仓位分别乘1/0.5/0.25。减少仓位不会释放占用的持仓槽位。',
            '- long_bias：fast基础上，上涨状态多头初始仓位额外乘1.25并受钱包上限限制。它增加资金暴露，不能把全部增益视为信号质量提高。',
            '- local：不用BTC禁止全部空头，改为只允许个币闭合4h EMA12<EMA50且RSI14<50时做空，测试反弹中只空弱币。','',
            '- cover_loss：保留原生扩展入场；空单持有至少1小时、闭合BTC状态转强且整轮净损益为负时退出，原有退出及24h期限保留。',
            '- cooldown：只对额外9个空头模式按已平仓记录准入；同主标签最近5笔净收益率合计为负，距最新平仓不足72h时暂停新入场。到期后允许重新尝试，既有持仓及原生4个空头不因此改变。仅使用当前时刻已平仓记录；此机制在看到首批开关失效后追加，存在适应性研究偏差。','',
            '- allocation_only：拆分long_bias的两个机制，保留全部扩展信号，仅在上涨状态将多头初始仓位乘1.25。该对照用于判断资金配置增益，不把增加暴露当成新的信号alpha。','',
            '- style_gate：非偏空状态保留原生4个空头与543超买衰竭、545失败突破、546布林上轨拒绝；其余新增趋势/回落延续模式仅在偏空状态允许。分类依据固定源码语义，仍保留此前亏损的545，没有按本段盈亏删标签。','',
            '- core_allocation：同一1.25上涨期多头资金因子直接应用旧核心（仅原生4个空头），用于分离扩展空头拖累和资金使用效果；没有扫描因子，不称为同风险alpha。','',
            '## 月度含浮亏收益','',
            '|月份|'+'|'.join(results)+'|','|---|'+'|'.join(['---:']*len(results))+'|']
    for month in results['incumbent']['monthly_mtm']:
        lines.append('|'+month[:7]+'|'+'|'.join(f"{r['monthly_mtm'][month]['return_pct']:.2f}%" for r in results.values())+'|')
    lines+=['','## 独立初始化与成本压力','',
            '_july从7月1日以10,000 USDT重新启动真实引擎，之前数据仅作指标预热；这检验复利/资金路径影响，仍不是未查看历史。_fee10将手续费提高到单边10bps重新运行订单与资金路径，不是简单扣费。','',
            '|重跑|窗口收益|含浮亏回撤|交易数|','|---|---:|---:|---:|']
    for name,r in extra.items():lines.append(f"|{name}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{r['campaigns']}|")
    lines+=['','## 本轮判断','',
            '更快或更强的禁空并不自动改善反弹收益：fast/soft/local及存量亏损空头提前退出都未稳健超过旧核心。冷却的连续钱包近期收益42.50%看似略高，但7月重启仅35.60%，低于旧核心41.33%；依赖前半年资金与已平仓状态，不能据此选为通用反弹增强。','']
    if 'core_allocation_july' in extra and 'incumbent_july' in extra:
        a=extra['core_allocation_july'];b=extra['incumbent_july']
        lines += [f"更干净的增益来自旧核心资金配置：7月同本金收益{b['return_pct']:.2f}%→{a['return_pct']:.2f}%，5m回撤{b['equity_audit']['mtm_drawdown_pct']:.2f}%→{a['equity_audit']['mtm_drawdown_pct']:.2f}%。平均保证金/权益{b['average_margin_equity_pct']:.2f}%→{a['average_margin_equity_pct']:.2f}%。这保留原生4空头，信号不扩充；上涨状态多头初始仓位乘1.25，杠杆仍3倍，实际资金暴露增加。",'']
    if 'core_allocation_july_fee10' in extra and 'incumbent_july_fee10' in extra:
        a=extra['core_allocation_july_fee10'];b=extra['incumbent_july_fee10']
        lines += [f"双倍手续费同口径近期收益{b['return_pct']:.2f}%→{a['return_pct']:.2f}%。该改善在这一历史成本压力下保留，但仍未模拟真实盘口队列、滑点及用户排除的资金费。原生退出依赖扣费后损益，改费率会改变退出时间和后续资金路径；本段双费结果略高不代表提高成本普遍有益。",'']
    lines += ['候选是资金分配改善，不是证明新增指标或空头预测更准确；样本最大回撤相近不代表未来风险不变。继续冻结规则做前向模拟，配置保持停止，历史选择结果不直接作为实盘授权。','']
    lines+=['','## 解释边界与复现','',
            '完整结果及信号族、方向、币种、成本、到期退出、订单现金流对账见comparison.json和各归档。5m权益回撤是离散闭合价格采样，不是盘中极值；整点真实标记价格回撤也保留。当前静态币池、已查看历史与自适应候选选择存在事后偏差。没有启动实盘或前向模拟。','',
            '运行`.venv/bin/python nfi_rebound.py fast soft long_bias local cover_loss cooldown allocation_only style_gate core_allocation --workers 2`，再运行`.venv/bin/python nfi_rebound_report.py`。近期同钱包对照使用`--start 2026-07-01T00:00:00Z --suffix _july`，双倍费用使用`--fee .001 --suffix _fee10`。成功目录拒绝覆盖。','',
            '![权益和回撤](comparison.png)','',
            '![7月同本金权益与回撤](recent_compare.png)','']
    (OUT/'REPORT.md').write_text('\n'.join(lines))
    import os
    os.environ.setdefault('MPLCONFIGDIR','/tmp/nfi-mpl')
    os.environ.setdefault('XDG_CACHE_HOME','/tmp/nfi-cache')
    Path(os.environ['MPLCONFIGDIR']).mkdir(parents=True,exist_ok=True)
    Path(os.environ['XDG_CACHE_HOME']).mkdir(parents=True,exist_ok=True)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True)
    top=sorted([n for n in results if n not in REF],key=lambda n:results[n]['segment_return_pct']['Jul-Oct'],reverse=True)[:3]
    for name in list(REF)+top:
        folder=ROOT/'results/nfi/short_search'/REF[name] if name in REF else OUT/name
        eq=pd.read_csv(folder/'equity.csv',parse_dates=['time']).set_index('time').equity
        axes[0].plot(eq.index,100*(eq/10000-1),label=name,linewidth=1)
        axes[1].plot(eq.index,100*(eq/eq.cummax().clip(lower=10000)-1),linewidth=1)
    axes[0].set(title='NFI rebound regimes: 57 pairs, 3x, max 24h',ylabel='Wallet return (%)');axes[0].legend(ncol=4)
    axes[1].set(ylabel='Sampled drawdown (%)')
    for ax in axes:ax.grid(alpha=.25)
    fig.text(.07,.015,'Retrospective static universe; 5 bps per fill; funding excluded; closed-price equity.',fontsize=9)
    fig.tight_layout(rect=(0,.035,1,1));fig.savefig(OUT/'comparison.png',dpi=170);plt.close(fig)
    recent=[n for n in ['incumbent_july','core_allocation_july','cooldown_july','allocation_only_july','style_gate_july'] if n in extra]
    if recent:
        fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True)
        for name in recent:
            eq=pd.read_csv(OUT/name/'equity.csv',parse_dates=['time']).set_index('time').equity
            axes[0].plot(eq.index,100*(eq/10000-1),label=name,linewidth=1)
            axes[1].plot(eq.index,100*(eq/eq.cummax().clip(lower=10000)-1),linewidth=1)
        axes[0].set(title='Fresh July start: same 10,000 USDT, 57 pairs, 3x, max 24h',ylabel='Wallet return (%)');axes[0].legend(ncol=2)
        axes[1].set(ylabel='Sampled drawdown (%)')
        for ax in axes:ax.grid(alpha=.25)
        fig.text(.07,.015,'Seen-history comparison, not OOS; 5 bps per fill; funding excluded; discrete closed-price equity.',fontsize=9)
        fig.tight_layout(rect=(0,.035,1,1));fig.savefig(OUT/'recent_compare.png',dpi=170);plt.close(fig)
    print('\n'.join(lines[:15]))


if __name__=='__main__':main()
