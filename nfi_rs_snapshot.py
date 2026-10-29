"""Rank BTC-relative strength at a closed timestamp in the frozen dataset, not live."""
import argparse,gzip,json,sys
from pathlib import Path
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'research/nfi/fast_rs'))
from NFIShortFastRS import strength_features


def closed_rows(rows,at):
    cutoff=int(pd.Timestamp(at).timestamp()*1000)
    return [r for r in rows if cutoff-9*86400000<=r[0] and r[0]+300000<=cutoff]


def snapshot(at):
    at=pd.Timestamp(at)
    if at.tzinfo is None:raise ValueError('Provide an explicit timezone offset')
    at=at.tz_convert('UTC').floor('5min')
    u=json.loads((ROOT/'research/nfi/ytd2026/universe.json').read_text())
    maximum=pd.Timestamp(u['end_exclusive'])-pd.Timedelta(minutes=5)
    if at>maximum or at<pd.Timestamp(u['evaluation_start']):raise ValueError('Outside frozen evaluation history')
    pairs=json.loads((ROOT/'research/nfi/ytd2026/config.backtest.json').read_text())['exchange']['pair_whitelist']
    def load(pair):
        stem=pair.replace('/','_').replace(':','_')
        with gzip.open(ROOT/'data/nfi_ytd2026/freqtrade/futures'/f'{stem}-5m-futures.json.gz','rt') as f:rows=closed_rows(json.load(f),at)
        df=pd.DataFrame(rows,columns=['time','open','high','low','close','volume']);df['date']=pd.to_datetime(df.time,unit='ms',utc=True)
        return df
    btc=load('BTC/USDT:USDT');records=[];unavailable=[]
    for pair in pairs:
        coin=load(pair)
        if coin.empty or coin.date.iloc[-1]+pd.Timedelta(minutes=5)!=at:
            unavailable.append(pair);continue
        row=strength_features(coin,btc).iloc[-1]
        def number(x):return float(x) if np.isfinite(x) else None
        records.append({'pair':pair,'coin_1h_return_pct':number(100*np.expm1(row.own_60)),
            **{f'btc_ratio_{minutes}m_return_pct':number(100*np.expm1(row[f'rs_{minutes}'])) for minutes in [15,60,240]},
            'beta_estimate':number(row.beta_estimate),'beta_adjusted_1h_log_return_pct':number(100*row.beta_60)})
    ranked=sorted([r for r in records if r['pair']!='BTC/USDT:USDT' and r['btc_ratio_60m_return_pct'] is not None],key=lambda r:r['btc_ratio_60m_return_pct'],reverse=True)
    for rank,r in enumerate(ranked,1):r['relative_1h_rank']=rank
    out=ROOT/'results/nfi/fast_rs';out.mkdir(parents=True,exist_ok=True)
    result={'asof_shanghai':str(at.tz_convert('Asia/Shanghai')),'asof_utc':str(at),'frozen_history_not_live':True,'warning':'Historical observation only; strength alone does not trigger an NFI order. Raw same-window relative ranking equals coin USDT return ranking; beta-adjusted values can rank differently.','unavailable':unavailable,'ranked_ex_btc':ranked,'benchmark':next((r for r in records if r['pair']=='BTC/USDT:USDT'),None)}
    # Refuse to overwrite the canonical end-snapshot with an earlier query.
    stem='latest_snapshot' if at==maximum else 'snapshot_'+at.strftime('%Y%m%dT%H%MZ')
    (out/f'{stem}.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# 冻结历史：BTC相对强弱观察表','',f"数据时点：{result['asof_shanghai']}（北京时间）。这是冻结历史快照，不是当前实时行情，也不是买卖建议。",'',
    '相对收益为个币/BTC价格比的区间涨跌；Beta调整列为对数收益百分数，不减回归截距。原始1h相对排序与同窗口USDT涨跌排序相同，BTC提供强弱基准。', '',
    '|1h排名|币种|个币1h涨跌%|相对15m%|相对1h%|相对4h%|7日Beta|Beta调整1h%|','|---:|---|---:|---:|---:|---:|---:|---:|']
    fmt=lambda n:'—' if n is None else f'{n:.3f}'
    for r in ranked:lines.append('|'+str(r['relative_1h_rank'])+'|'+r['pair']+'|'+'|'.join(fmt(r[k]) for k in ['coin_1h_return_pct','btc_ratio_15m_return_pct','btc_ratio_60m_return_pct','btc_ratio_240m_return_pct','beta_estimate','beta_adjusted_1h_log_return_pct'])+'|')
    (out/f'{stem}.md').write_text('\n'.join(lines)+'\n')
    print(result['asof_shanghai'],len(ranked),'ranked coins; frozen historical snapshot, not live')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--at');a=p.parse_args()
    u=json.loads((ROOT/'research/nfi/ytd2026/universe.json').read_text())
    snapshot(a.at or pd.Timestamp(u['end_exclusive'])-pd.Timedelta(minutes=5))
