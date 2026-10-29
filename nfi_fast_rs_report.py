"""Actual-engine fast relative-strength comparisons and original-path diagnostics."""
import json,gzip,hashlib
from pathlib import Path
import numpy as np
import pandas as pd
from nfi_analyze import load_result,groups
from nfi_rebound_report import collect
ROOT=Path(__file__).resolve().parent;OUT=ROOT/'results/nfi/fast_rs'


def quality(trades):
    win=[t for t in trades if t['profit_abs']>0];loss=[t for t in trades if t['profit_abs']<0]
    gp=sum(t['profit_abs'] for t in win);gl=-sum(t['profit_abs'] for t in loss)
    avg_win=sum(t['profit_ratio'] for t in win)/max(len(win),1);avg_loss=sum(t['profit_ratio'] for t in loss)/max(len(loss),1)
    return {'trades':len(trades),'profit_usdt':sum(t['profit_abs'] for t in trades),'win_rate_pct':100*len(win)/max(len(trades),1),'profit_factor':gp/gl if gl else None,'average_payoff_ratio':avg_win/-avg_loss if avg_loss else None}


def diagnose(engine):
    import sys
    sys.path.insert(0,str(ROOT/'research/nfi/fast_rs'))
    from NFIShortFastRS import strength_features
    data=ROOT/'data/nfi_ytd2026/freqtrade/futures'
    def read(pair):
        stem=pair.replace('/','_').replace(':','_')
        with gzip.open(data/f'{stem}-5m-futures.json.gz','rt') as f:rows=json.load(f)
        frame=pd.DataFrame(rows,columns=['time','open','high','low','close','volume']);frame['date']=pd.to_datetime(frame.time,unit='ms',utc=True)
        return frame
    btc=read('BTC/USDT:USDT');cache={};records=[]
    for t in engine['trades']:
        pair=t['pair']
        if pair not in cache:
            coin=read(pair);features=strength_features(coin,btc);features['available']=coin.date+pd.Timedelta(minutes=5)
            cache[pair]=features.set_index('available')
        frame=cache[pair];time=pd.Timestamp(t['open_date'])
        if time not in frame.index:raise ValueError('No synchronous closed entry feature '+repr((pair,time)))
        row=frame.loc[time]
        item={k:t[k] for k in ['pair','enter_tag','is_short','open_date','profit_abs','profit_ratio','trade_duration']}
        item.update({k:float(row[k]) if np.isfinite(row[k]) else None for k in ['rs_15','rs_60','rs_240','beta_60','beta_estimate','own_60']})
        records.append(item)
    grouped={}
    for minutes in [15,60,240]:
        grouped[str(minutes)]={}
        for side in ['long','short']:
            trades=[t for t in records if t['is_short']==(side=='short') and t['pair']!='BTC/USDT:USDT']
            allowed=lambda t:t[f'rs_{minutes}'] is not None and ((t[f'rs_{minutes}']< -1e-12) if side=='short' else (t[f'rs_{minutes}']>1e-12))
            kept=[t for t in trades if allowed(t)];blocked=[t for t in trades if not allowed(t)]
            grouped[str(minutes)][side]={'allowed_original_path':quality(kept),'blocked_original_path':quality(blocked),'original_winners_blocked':sum(t['profit_abs']>0 for t in blocked),'original_losers_blocked':sum(t['profit_abs']<0 for t in blocked),'blocked_by_tag':groups(blocked,lambda t:t['enter_tag'].strip())}
    return {'warning':'Entry-time features are causal, but labels are eventual original-path profits. Removing these records is NOT a strategy backtest; capital, exits and later entries change. BTC benchmark excluded from diagnostic signs, consistently exempt in engine candidates.','groups':grouped,'trades':records}


def plot(results):
    import os
    os.environ.setdefault('MPLCONFIGDIR','/tmp/nfi-mpl');os.environ.setdefault('XDG_CACHE_HOME','/tmp/nfi-cache')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(2,1,figsize=(12,8),sharex=True)
    for name in ['control','short15','short60','short240','improving_long']:
        if name not in results:continue
        raw_equity=pd.read_csv(OUT/name/'equity.csv',parse_dates=['time']).set_index('time').equity
        e=raw_equity.resample('1h').last()
        axes[0].plot(e.index,100*(e/10000-1),label=name)
        dd=(100*(raw_equity/raw_equity.cummax()-1)).resample('1h').min()
        axes[1].plot(dd.index,dd,label=name)
    axes[0].set_title('Fast BTC relative strength: fixed initial stake ceilings, funding excluded')
    axes[0].set_ylabel('Net return %');axes[1].set_ylabel('Sampled equity drawdown %');axes[0].legend(ncol=5)
    for ax in axes:ax.grid(alpha=.2)
    fig.tight_layout();fig.savefig(OUT/'comparison.png',dpi=160);plt.close(fig)


def main():
    results={};raw={}
    for folder in sorted(OUT.iterdir()):
        if not folder.is_dir() or not list(folder.glob('*.zip')):continue
        if json.loads((folder/'execution.json').read_text())['status']!='success':continue
        r=collect(folder);s=load_result(next(folder.glob('*.zip')))
        assert r['campaigns_with_adds']==0 and len(s['pairlist'])==57 and s['starting_balance']==10000
        assert all(t['leverage']==3 for t in s['trades'])
        r['quality']={side:quality([t for t in s['trades'] if t['is_short']==(side=='short')]) for side in ['long','short']}
        results[folder.name]=r;raw[folder.name]=s
    refs={n:collect(ROOT/'results/nfi/atr_short'/n) for n in ['gated','gated_july','gated_fee10']}
    if 'control' in results:
        assert abs(results['control']['return_pct']-refs['gated']['return_pct'])<1e-7
        baseline=load_result(next((ROOT/'results/nfi/atr_short/gated').glob('*.zip')))
        def identity(s):return [(t['pair'],t['open_date'],t['close_date'],t['profit_abs'],t['enter_tag']) for t in s['trades']]
        assert identity(raw['control'])==identity(baseline),'Feature pipeline altered control trades'
        cache=OUT/'entry_diagnosis.json';feature_sha=hashlib.sha256((ROOT/'research/nfi/fast_rs/NFIShortFastRS.py').read_bytes()).hexdigest()
        diag=json.loads(cache.read_text()) if cache.exists() else {}
        if diag.get('control_archive_sha256')!=results['control']['archive_sha256'] or diag.get('feature_sha256')!=feature_sha:
            diag=diagnose(raw['control']);diag.update(control_archive_sha256=results['control']['archive_sha256'],feature_sha256=feature_sha)
            cache.write_text(json.dumps(diag,indent=2)+'\n')
    if all(n in results for n in ['short240_july','short240_fee10']):
        decision={'core_logic_replaced':False,'recent_forward_research_candidate':'NFIShortFastShort240','primary_limit':'All full-period filters return less than original control; 4h short-only improves inspected rebound interval but sacrifices annual return.','fresh_july_gain_pp':results['short240_july']['return_pct']-refs['gated_july']['return_pct'],'funding_excluded':True,'independent_oos':False,'services_started':False}
        (OUT/'decision.json').write_text(json.dumps(decision,indent=2)+'\n')
    (OUT/'comparison.json').write_text(json.dumps(results,indent=2)+'\n');(OUT/'references.json').write_text(json.dumps(refs,indent=2)+'\n')
    lines=['# 小周期BTC相对强弱：多空选择实验','',
    '固定历史窗口：北京时间2026-01-01 08:00至10月29日11:10。57静态币、10000 USDT、3倍、6仓、禁补仓、首次入场24h；原始初始stake上限，空头2x闭合1hATR14（价格距离至少1%）/2R与计费计划风险1%上限，多头原生退出。所有空头仍受闭合BTC4h熊态门控；相对强弱不替代大周期方向。单边5bps，fee10为10bps真实重跑，资金费排除。保留4ULP同价浮点边界协议。','',
    'RS_h=log(C_t/C_{t-h})-log(BTC_t/BTC_{t-h})，以同一已收盘5m时间戳计算15m/1h/4h窗口，每5m更新。遇到窗口缺口拒绝使用，不拿旧BTC价格前向补齐。Beta版本用测量1小时前已知的最近7天同步5m收益协方差/方差估计beta，再计算1h个币收益-beta*BTC收益；没有扣除回归截距，不将其称为已证明alpha。BTC自身统一豁免相对过滤。','',
    '原始NFI信号成立后才过滤：long要求正RS，short要求负RS；不凭指标独立开单、不加大仓位、不按已知交易盈亏删币。both15/both60/both240过滤两边；short15/short60/short240仅过滤空头，后两个补充时间窗是在识别多头混淆后追加的探索；long60只过滤多头；confirm要求1h和4h方向一致；beta60用Beta调整1h分数；momentum60还要求个币绝对1h收益方向与交易一致；improving_long是查看首批结果后追加的探索对照，仅要求多头最近15m的相对收益高于前一个不重叠15m窗口，空头保持原框架。','',
    '|全年方案|交易|组合收益|含浮亏回撤|多头PF|空头PF|连续钱包7—10月收益|平均保证金/权益|','|---|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in results.items():
        if n.endswith(('_fee10','_july')):continue
        l=r['quality']['long']['profit_factor'];s=r['quality']['short']['profit_factor']
        lines.append(f"|{n}|{r['campaigns']}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{'—' if l is None else round(l,2)}|{'—' if s is None else round(s,2)}|{r['segment_return_pct']['Jul-Oct']:.2f}%|{r['average_margin_equity_pct']:.2f}%|")
    lines+=['','## 预定的独立本金与费用压力','',
    '_july在北京时间7月1日08:00以10000 USDT重新启动；更早数据只供指标预热。fee10覆盖全年。三个预定候选是both60/short60/confirm；short240是在全区间结果显示近期改善后追加的适应性复核，记录于phase4.json。所有历史已看过，这不是独立样本外。下表参照沿用旧ATR门控组，前提是新control逐笔交易及损益与旧gated完全一致。','',
    '|方案|区间收益|含浮亏回撤|交易|','|---|---:|---:|---:|']
    for n in ['gated_july','gated_fee10']:
        r=refs[n];lines.append(f"|reference_{n}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{r['campaigns']}|")
    for n,r in results.items():
        if n.endswith(('_fee10','_july')):lines.append(f"|{n}|{r['return_pct']:.2f}%|{r['equity_audit']['mtm_drawdown_pct']:.2f}%|{r['campaigns']}|")
    lines+=['','## 本轮判断','']
    if all(n in results for n in ['control','both60','long60','short60']):
        c=results['control'];b=results['both60'];l=results['long60'];s=results['short60']
        lines.append(f"1h同时过滤收益{b['return_pct']:.2f}%，只过滤多头{l['return_pct']:.2f}%，只过滤空头{s['return_pct']:.2f}%，对照{c['return_pct']:.2f}%。分方向证据显示，直接要求回调型多头短期正RS会删除主要盈利来源；只空短期弱币提高空头PF或降低暴露，不代表提高组合总收益。")
    if 'improving_long' in results:lines.append(f"追加相对改善多头收益{results['improving_long']['return_pct']:.2f}%，仍需相对control比较；该假设是在首批诊断后提出，不能称预先独立验证。")
    if all(n in results for n in ['short15','short60','short240','control']):
        names=['short15','short60','short240']
        lines.append('只过滤空头的三个时间窗：'+', '.join(f"{n} {results[n]['return_pct']:.2f}%" for n in names)+f"；对照{results['control']['return_pct']:.2f}%。")
        main={n:r for n,r in results.items() if not n.endswith(('_fee10','_july')) and n!='control'}
        if max(r['return_pct'] for r in main.values())<=results['control']['return_pct']:
            lines.append('所有本轮完整区间过滤变体收益均未超过对照。本轮不替换当前入场逻辑，不将更高PF、更低暴露或更小回撤单独称为收益优化成功；观察工具与实盘策略采用分开。')
    if all(n in results for n in ['short240_july','short240_fee10']):
        r=results['short240_july'];c=refs['gated_july'];fee=results['short240_fee10']
        lines.append(f"4h只空弱币的追加复核：7月同本金收益{r['return_pct']:.2f}% vs参照{c['return_pct']:.2f}%，差{r['return_pct']-c['return_pct']:.2f}个百分点；全年双倍手续费收益{fee['return_pct']:.2f}% vs参照{refs['gated_fee10']['return_pct']:.2f}%。它体现近期表现和全年收益的取舍，非全周期胜出；在看到近期结果后选择复核，不是新的独立样本外。")
    lines.append('原始同窗口RS跨币排序与USDT涨跌排序相同，因为每个币减去同一个BTC收益；Beta调整改变不同个币的市场敏感度比较，但没有自动产生可盈利信号。指标适合观察市场背景，是否过滤入场必须服从具体策略及真实回放证据。')
    if all(n in results for n in ['both60_july','short60_july','confirm_july']):
        lines.append('7月同本金重启：'+', '.join(f"{n} {results[n]['return_pct']:.2f}%" for n in ['both60_july','short60_july','confirm_july'])+f"；参照{refs['gated_july']['return_pct']:.2f}%。")
    lines+=['','## 原始信号路径诊断','',
    'entry_diagnosis.json记录基线每次入场前最后闭合5m的分数、原始信号族与最终损益，分方向统计会被过滤的原始赢家和输家。它解释过滤器偏好；事后删掉这些交易并相加，不等同于真实过滤策略收益。实际效果以上述引擎重跑为准。','']
    if 'control' in results:
        for h,g in diag['groups'].items():
            for side,q in g.items():lines.append(f"- {h}分钟/{side}：原赢家被挡{q['original_winners_blocked']}笔，原输家被挡{q['original_losers_blocked']}笔；被挡原路径净损益{q['blocked_original_path']['profit_usdt']:.2f} USDT。")
    lines+=['','## 解释限制与复现','',
    '本轮是正负强弱作为入场过滤的对照，尚未测试在同一时点已成立的NFI候选之间重新排序、分配有限持仓槽位；不能从过滤失败推断排序没有帮助。冻结观察表只提供描述性排序，不会更改策略优先级。全部沿用已经查看的历史和事后静态币池，有存活者及研究选择偏差。短周期强弱可能只是高beta、噪声或短期超涨超跌，不能据更新更快推断预测更好。NFI回调/均值回归多头可能在短期RS为负时入场，强行只买短期强币会删除这类有效信号；分方向重跑用于检验而非预设结论。','',
    '收益表为组合；PF按方向实际USDT盈利/亏损计算，受复利与资金路径影响。初始单笔上限不变，但筛选会改变交易次数、槽位占用、平均暴露和后续多头机会；不是严格同组合风险匹配。权益回撤按闭合5m价格采样，另保留真实小时标价回撤，不含盘中极值。1%计划风险不能保证跳空或限价未成交后的真实损失；没有启动实盘。','',
    '复现：`.venv/bin/python nfi_fast_rs.py control both60 short60 long60 both15 both240 confirm beta60 momentum60 --workers 2`；费用压力对both60/short60/confirm加`--fee .001 --suffix _fee10`，同本金近期对照加`--start 2026-07-01T00:00:00Z --suffix _july`。报告`.venv/bin/python nfi_fast_rs_report.py`。成功目录拒绝覆盖。','',
    '观察表见[冻结历史强弱表](latest_snapshot.md)，指标解释见[INDICATOR.md](../../../research/nfi/fast_rs/INDICATOR.md)，后续约束见[FORWARD.md](../../../research/nfi/fast_rs/FORWARD.md)。','',
    '![权益与回撤](comparison.png)','']
    (OUT/'REPORT.md').write_text('\n'.join(lines).rstrip()+'\n');plot(results)
    for n,r in results.items():print(n,r['campaigns'],round(r['return_pct'],3),round(r['equity_audit']['mtm_drawdown_pct'],3),round(r['segment_return_pct']['Jul-Oct'],3),flush=True)
if __name__=='__main__':main()
