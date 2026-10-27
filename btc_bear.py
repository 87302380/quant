"""BTC current-bear research; no data before 2024, 2026-focused selection."""
import hashlib
import json
from dataclasses import asdict,replace
from pathlib import Path
from datetime import datetime,timezone
from btc_5m import DATA,resample
from btc_v2 import Strategy,Config,load,prepare,run,write_json
from btc_locations import Rules,prepare as location_context,signals,simulate
from research import ts

OUT=Path('results/btc_bear')


def short_universe():
    specs=[]
    for stop in (2,3):
        for trail in (3,4.5):
            for daily in (False,True):
                specs.append(Strategy(f'short_s{stop}_t{trail}_daily{int(daily)}','trend',short=True,long=False,
                    stop_atr=stop,trail_atr=trail,daily_filter=daily,pause_losses=3))
    base=specs[0]
    specs.extend([replace(base,name='short_s2_t3_protected_add',max_adds=2),
                  replace(base,name='short_s2_t3_adx20',min_adx=20)])
    return specs


def main():
    OUT.mkdir(parents=True,exist_ok=True);rows=load(DATA,step_seconds=300)
    h4=prepare(resample(rows,900));loc=location_context(rows);c=Config()
    periods={'train':(ts('2026-01-01'),ts('2026-07-01')),
        'validation':(ts('2026-07-01'),ts('2026-09-01')),
        'recent_confirmation':(ts('2026-09-01'),rows[-1]['t']+300),
        '2026_total':(ts('2026-01-01'),rows[-1]['t']+300)}
    specs=short_universe();table={};kind={};events={};rulemap={}
    for only4h in (False,True):
        for exit in ('level','cap','split'):
            name=f'pressure_{"4h" if only4h else "4h1h"}_{exit}'
            rulemap[name]=Rules(name,short=True,only4h=only4h,exit=exit,stop_floor4h=.75,
                cooldown_hours=12,max_cost_fraction=.15,min_net_rr=.75)
    rulemap['bear_support_bounce']=Rules('bear_support_bounce','range',False,'cap',only4h=True,
        stop_floor4h=.75,cooldown_hours=12,max_cost_fraction=.15,min_net_rr=.75)
    for name,r in rulemap.items():
        e=list(signals(loc,r))
        if name=='bear_support_bounce':
            events[name]=[x for x in e if x['direction']==1 and x['source'] in ('4h_pivot','previous_day') and
                loc[x['index']]['h4']['ema25']<loc[x['index']]['h4']['ema99']]
        else:events[name]=[x for x in e if x['direction']==-1]
    write_json(OUT/'plan.json',dict(periods=periods,short_specs=[asdict(s) for s in specs],locations={n:asdict(r) for n,r in rulemap.items()},
        data_before_2024_used=False,earlier_rows_for_indicator_warmup_only=True,known_history=True,
        selection='train>=8 and validation>=3 trades, both positive, PF>=1.05 and DD<=15%; maximize validation return; otherwise no candidate',
        warning='All calendar dates were already examined at least at aggregate resolution; confirmation is not a new independent holdout.',
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        data_sha256=hashlib.sha256(DATA.read_bytes()).hexdigest()))
    all_names=[s.name for s in specs]+list(rulemap)
    def evaluate(name,start,end,cfg):
        if name in rulemap:return simulate(loc,rulemap[name],cfg,start,end,events[name])
        s=next(s for s in specs if s.name==name)
        return run(rows,h4,s,cfg,start,end,bar_seconds=300)
    for name in all_names:
        table[name]={}
        for period in ('train','validation'):
            start,end=periods[period];m,t,_=evaluate(name,start,end,c);table[name][period]=m
        print('DEVELOP',name,[(p,round(v['return_pct'],2),v['trades']) for p,v in table[name].items()],flush=True)
    eligible=[n for n in all_names if table[n]['train']['trades']>=8 and table[n]['validation']['trades']>=3 and
        all(table[n][p]['return_pct']>0 and (table[n][p]['profit_factor'] or 0)>=1.05 and table[n][p]['max_drawdown_pct']<=15 for p in ('train','validation'))]
    chosen=max(eligible,key=lambda n:table[n]['validation']['return_pct']) if eligible else None
    write_json(OUT/'selection_before_recent_confirmation.json',dict(selected=chosen,eligible=eligible))
    stress={}
    for name in all_names:
        for period in ('recent_confirmation','2026_total'):
            start,end=periods[period];m,t,curve=evaluate(name,start,end,c);table[name][period]=m
            if period=='2026_total':write_json(OUT/f'{name}_trades.json',t)
        start,end=periods['2026_total']
        stress[name]=evaluate(name,start,end,replace(c,fee=.001,slippage=.0004))[0]
        print('RECENT',name,table[name]['recent_confirmation']['return_pct'],'2026',table[name]['2026_total']['return_pct'],flush=True)
    baseline=run(rows,h4,Strategy('baseline','trend',short=True,pause_losses=3),c,*periods['2026_total'],bar_seconds=300)[0]
    write_json(OUT/'results.json',table);write_json(OUT/'double_cost.json',stress);write_json(OUT/'baseline_2026.json',baseline)
    lines=['# BTC近期熊市场景专项研究','',
        '按用户要求，不使用2024年前数据。2024/2025只作指标预热；策略收益筛选只用2026。整体年段不被一概假定为熊市，每笔仍必须满足信号时4h偏空状态。日线过滤版本另要求已收盘日线低于EMA50。',
        '', '训练2026年1—6月，开发验证7—8月，近期确认9月至数据截止，分别重置10,000账户；2026总计另跑连续账户。此前这些历史都已看过，不能作为新独立留出。样本较小，公开全部版本。',
        '', '10个仅做空趋势/过滤对照，6个高周期反弹到压力后5m转弱入场对照，1个熊市弱趋势中强支撑反弹做多对照。不得用牛市做多利润主导本轮选型。',
        '', '风险预算每轮初始计划1%，名义金额不超过净值，单边手续费0.05%、滑点0.02%，资金费关闭；加仓版沿用共同止损成本基础风险定义，浮盈回吐可大于1%。',
        '', '| 方案 | 1—6月收益/笔数 | 7—8月收益/笔数 | 9月至今收益/笔数 | 2026总收益 | 总胜率 | 回撤 | 双倍成本收益 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|']
    for n,r in table.items():
        m=r['2026_total'];a=r['train'];b=r['validation'];q=r['recent_confirmation']
        lines.append(f'| {n} | {a["return_pct"]:.2f}% / {a["trades"]} | {b["return_pct"]:.2f}% / {b["trades"]} | {q["return_pct"]:.2f}% / {q["trades"]} | {m["return_pct"]:.2f}% | {(m["win_rate"] or 0)*100:.2f}% | {m["max_drawdown_pct"]:.2f}% | {stress[n]["return_pct"]:.2f}% |')
    lines+=['',f'按训练/验证预设规则、在本轮近期确认前选中的候选：{chosen or "无合格方案"}。',
        f'同口径原双向趋势2026收益：{baseline["return_pct"]:.2f}%。不能拿它的2024年牛市利润支撑本轮选择。',
        '', '本轮仅标的历史场景研究，不是针对真实最新盘口的预测。市场状态切换和新BTC前向数据仍需要检验；未启动实盘。',
        '', '复现：`python btc_bear.py`。完整计划、数据哈希和逐笔记录在同目录。']
    (OUT/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print('COMPLETE',OUT/'REPORT.md')


if __name__=='__main__':main()
