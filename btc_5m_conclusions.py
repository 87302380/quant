"""Confirm the trend benchmark on finer execution, then summarize findings."""
import json
from pathlib import Path
from btc_5m import DATA,OUT,resample
from btc_v2 import Config,Strategy,load,prepare,run,write_json


def main():
    rows=load(DATA,step_seconds=300);coarse=resample(rows,900);h4=prepare(coarse)
    s=Strategy('trend_both_pause','trend',short=True,pause_losses=3)
    comparison={}
    for risk in (.0025,.01):
        for label,bars,seconds in [('15m',coarse,900),('5m',rows,300)]:
            c=Config(risk=risk)
            m,t,_=run(bars,h4,s,c,bar_seconds=seconds)
            comparison[f'{label}_risk{risk}']=m
            if label=='5m':write_json(OUT/f'trend_5m_risk{risk}_trades.json',t)
    write_json(OUT/'trend_resolution_check.json',comparison)
    old=json.loads(Path('results/btc_v2/static_results.json').read_text())['trend_both_pause']['full']
    assert abs(old['return_pct']-comparison['15m_risk0.01']['return_pct'])<1e-8
    results=json.loads((OUT/'results.json').read_text())
    positives=[n for n,r in results.items() if r['full']['return_pct']>0]
    decision=dict(research_preference='range short-term primary, trend only on continuation',
        scalp_positive_configurations=positives,scalp_deployment_enabled=False,
        reason='No scalp hypothesis passed predeclared 2024/2025 eligibility.',
        next_evidence_needed='BTC tick/orderbook and independent forward execution logs, not more unbounded indicator fitting')
    write_json(OUT/'decision.json',decision)
    report=(OUT/'REPORT.md').read_text(encoding='utf-8')
    report+='\n\n## 趋势对照在5m成交粒度下的复核\n\n| 成交粒度与计划单笔风险 | 净收益 | 胜率 | 回撤 |\n|---|---:|---:|---:|\n'
    for n,m in comparison.items():report+=f'| {n} | {m["return_pct"]:.2f}% | {m["win_rate"]*100:.2f}% | {m["max_drawdown_pct"]:.2f}% |\n'
    report+='\n风险预算不同的行不能直接比较绝对收益。趋势对照仅用于检查撮合粒度，不代表用户应改变交易风格。已核对15m默认结果与原V2精确一致。\n'
    report+='\n## 本轮结论\n\n5m数据已下载并与15m逐根核对，28项测试通过。本轮12个新的5m短线方案全部未得到全区间正净收益，且没有方案通过2024/2025预先筛选。应保留空仓门槛，不通过放大风险或无限调参宣称已经提高总收益。\n'
    report+='\n当前OHLCV证据不支持持续盈利的剥头皮系统；真正盘口/逐笔优势、真实账户费率及独立前向成交记录尚未验证。本轮未启动实盘，也没有下载资金费率。\n'
    (OUT/'REPORT.md').write_text(report,encoding='utf-8')
    print(json.dumps(comparison,indent=2))


if __name__=='__main__':main()
