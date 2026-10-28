"""Freeze a top-100 crypto perpetual research universe using native quote turnover."""
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal
import re
import shutil

import nfi_data as data


EXPANSION=data.STUDY/'expansion100'


def eligible(inst,now,blacklist):
    pair=inst['instId'].removesuffix('-SWAP').replace('-','/')+':USDT'
    if inst.get('ctType')!='linear' or inst.get('settleCcy')!='USDT' or inst.get('state')!='live':return 'not_live_linear_usdt'
    if inst.get('instCategory')!='1':return 'not_crypto_category_1'
    if not inst.get('listTime') or int(inst['listTime'])>now-60*86400000:return 'younger_than_60_days'
    if any(re.fullmatch(p,pair) for p in blacklist):return 'upstream_blacklist'
    return None


def rank():
    if (EXPANSION/'selection.json').exists():raise ValueError('selection already frozen; preserve it')
    now=int(data.read(EXPANSION/'server_time.json')['data'][0]['ts'])
    end=now//3600000*3600000;start=end-24*3600000
    daily_end=end//86400000*86400000
    blacklist=data.jsonc(data.STUDY/'upstream/configs/blacklist-okx.json')['exchange']['pair_blacklist']
    static=set(data.jsonc(data.STUDY/'upstream/configs/pairlist-static-okx-futures-usdt.json')['exchange']['pair_whitelist'])
    backtest=set(data.jsonc(data.STUDY/'upstream/configs/pairlist-backtest-static-okx-futures-usdt.json')['exchange']['pair_whitelist'])
    accepted=[];excluded=[]
    for inst in data.read(EXPANSION/'instruments.json')['data']:
        reason=eligible(inst,now,blacklist)
        if reason:excluded.append(dict(instrument=inst['instId'],reason=reason))
        else:accepted.append(inst)
    limiter=data.Limiter(6);cache=data.LOCAL/'ranking100';cache.mkdir(parents=True,exist_ok=True)
    def work(inst):
        path=cache/(inst['instId']+'.json')
        if path.exists():
            record=data.read(path)
            if record['end']==end:return record
        client=data.Client();limiter.wait()
        hours=client.get('/api/v5/market/history-candles',dict(instId=inst['instId'],bar='1H',after=str(end),limit='24'))['data']
        hours=sorted(hours,key=lambda x:int(x[0]));data.validate(hours,start,end,3600000)
        limiter.wait()
        days=client.get('/api/v5/market/history-candles',dict(instId=inst['instId'],bar='1Dutc',after=str(daily_end),limit='3'))['data']
        days=sorted(days,key=lambda x:int(x[0]));data.validate(days,daily_end-3*86400000,daily_end,86400000)
        record=dict(instrument=inst['instId'],end=end,hours=hours,days=days)
        data.write(path,record);return record
    evidence=[];errors=[]
    with ThreadPoolExecutor(max_workers=12) as pool:
        futures={pool.submit(work,i):i['instId'] for i in accepted}
        for f in as_completed(futures):
            try:evidence.append(f.result())
            except Exception as exc:errors.append(dict(instrument=futures[f],error=str(exc)))
            if (len(evidence)+len(errors))%25==0:print(f'RANKING {len(evidence)}/{len(accepted)}, errors {len(errors)}',flush=True)
    if errors:
        data.write(EXPANSION/'ranking_errors.json',errors)
        raise ValueError('ranking incomplete; resume before selecting, never silently skip unavailable candidates')
    insts={x['instId']:x for x in accepted};ranked=[]
    for record in evidence:
        inst=insts[record['instrument']];pair=inst['instId'].removesuffix('-SWAP').replace('-','/')+':USDT'
        quote=sum(Decimal(r[7]) for r in record['hours'])
        high=max(Decimal(r[2]) for r in record['days']);low=min(Decimal(r[3]) for r in record['days'])
        roc=(high-low)/low
        ranked.append(dict(instrument=inst['instId'],pair=pair,quote_turnover_24h_usdt=str(quote),
                           price_change_24h=str(Decimal(record['hours'][-1][4])/Decimal(record['hours'][0][1])-1),
                           range_3d=str(roc),range_stability_pass=Decimal('.03')<=roc<=Decimal('.95'),
                           official_static_member=pair in static,official_backtest_static_member=pair in backtest,
                           list_time=inst['listTime'],contract_value=inst['ctVal'],contract_value_currency=inst['ctValCcy'],metadata=inst))
    ranked.sort(key=lambda x:(-Decimal(x['quote_turnover_24h_usdt']),x['instrument']))
    for n,item in enumerate(ranked,1):item['turnover_rank']=n
    chosen=ranked[:100]
    if len(chosen)!=100 or not any(x['instrument']=='BTC-USDT-SWAP' for x in chosen):raise ValueError('cannot create complete top100 including BTC context')
    data.write(EXPANSION/'ranking_evidence.json',dict(hour_start=data.iso(start),hour_end_exclusive=data.iso(end),
               daily_end_exclusive=data.iso(daily_end),source='OKX history-candles, confirm=1, native volCcyQuote',
               candles=sorted(evidence,key=lambda x:x['instrument'])))
    data.write(EXPANSION/'selection.json',dict(asof=data.iso(now),quote_window_start=data.iso(start),quote_window_end=data.iso(end),
               selected=chosen,all_eligible_ranked=ranked,excluded=excluded,
               policy='Top 100 native quote turnover among live crypto-category-1 linear USDT perpetuals, age>=60d, pinned NFI blacklist excluded.',
               range_filter='3-day RangeStabilityFilter recorded for analysis, not applied to data collection; actual trade universe may be smaller.',
               heat='Trading activity proxy only; no unverified social popularity score. Not exact live NFI pairlist: no portfolio-dependent FullTradesFilter.',
               official_volume_config='configs/pairlist-volume-okx-futures.json: 110 candidates, 60d age, 3d range 0.03..0.95'))
    print('FROZEN TOP100: '+', '.join(x['instrument'] for x in chosen),flush=True)


def activate():
    current=data.read(data.STUDY/'universe.json')
    if len(current['pairs'])!=40:raise ValueError('expected original 40-pair universe; do not overwrite an active expansion')
    snapshot=data.STUDY/'snapshots/40-pair';snapshot.mkdir(parents=True,exist_ok=True)
    for name in ('universe.json','pairs.json','config.backtest.json'):
        dest=snapshot/name
        if dest.exists():raise ValueError('snapshot already exists')
        shutil.copyfile(data.STUDY/name,dest)
    for name in ('manifest.json','mark_manifest.json','bundles.json'):
        shutil.copyfile(data.ARCHIVE/name,snapshot/name)
    selection=data.read(EXPANSION/'selection.json');chosen=selection['selected']
    # Preserve the prior data cutoff and all original raw archives for exact reuse.
    universe=dict(current)
    universe.update(format_version=2,pairs=chosen,frozen_at=selection['asof'],
                    selection=selection['policy'],selection_evidence='expansion100/selection.json',
                    prior_40_universe='snapshots/40-pair/universe.json',
                    bias='Current volume, survivors and pinned blacklist; selection occurs after much of the history. Exploratory, not point-in-time backtesting.')
    coverage=[]
    for p in chosen:
        first_day=((int(p['list_time'])+86400000-1)//86400000)*86400000
        earliest=max(first_day,data.millis('2024-01-01'));evaluation=data.millis(universe['evaluation_start'])
        coverage.append(dict(instrument=p['instrument'],earliest_full_day=data.iso(earliest),
                            daily_bars_before_20260701=max(0,(evaluation-earliest)//86400000),
                            daily_bars_at_data_end=max(0,(data.millis(universe['end_exclusive'])-earliest)//86400000),
                            earliest_200_daily_bars=data.iso(earliest+200*86400000),
                            earliest_480_daily_bars=data.iso(earliest+480*86400000),
                            warning='Actual indicators determine readiness; never fabricate prelisting history or assume all 100 can trade on July 1.'))
    data.write(EXPANSION/'coverage.json',dict(evaluation_start=universe['evaluation_start'],end_exclusive=universe['end_exclusive'],pairs=coverage))
    data.write(data.STUDY/'universe.json',universe);data.write(data.STUDY/'pairs.json',[p['pair'] for p in chosen])
    config=data.read(data.STUDY/'config.backtest.json');config['exchange']['pair_whitelist']=[p['pair'] for p in chosen]
    data.write(data.STUDY/'config.backtest.json',config)
    old={p['instrument'] for p in current['pairs']};new={p['instrument'] for p in chosen}
    print(f'Active100, reused {len(old&new)}, additional {len(new-old)}, preserved excluded old {sorted(old-new)}',flush=True)


def verify_selection():
    """Recompute the ranking from every candidate's preserved native evidence."""
    universe=data.read(data.STUDY/'universe.json')
    if universe.get('format_version',1)<2:return dict(profile='original40')
    selection=data.read(EXPANSION/'selection.json');evidence=data.read(EXPANSION/'ranking_evidence.json')
    now=int(data.read(EXPANSION/'server_time.json')['data'][0]['ts'])
    blacklist=data.jsonc(data.STUDY/'upstream/configs/blacklist-okx.json')['exchange']['pair_blacklist']
    candidates={x['instId']:x for x in data.read(EXPANSION/'instruments.json')['data'] if eligible(x,now,blacklist) is None}
    records=evidence['candles'];ids=[r['instrument'] for r in records]
    if len(ids)!=len(candidates) or set(ids)!=set(candidates):raise ValueError('ranking evidence excludes or duplicates eligible candidates')
    start=data.millis(evidence['hour_start']);end=data.millis(evidence['hour_end_exclusive'])
    if end-start!=24*3600000 or end!=now//3600000*3600000:raise ValueError('ranking hour window differs from snapshot')
    sums={}
    for r in records:
        if r['end']!=end:raise ValueError('mixed ranking snapshots')
        data.validate(r['hours'],start,end,3600000)
        sums[r['instrument']]=sum(Decimal(row[7]) for row in r['hours'])
    ordered=sorted(sums,key=lambda x:(-sums[x],x))
    actual=[p['instrument'] for p in selection['selected']]
    if actual!=ordered[:100] or [p['instrument'] for p in universe['pairs']]!=actual:
        raise ValueError('universe is not the exact top100 native quote-turnover ranking')
    for p in selection['selected']:
        if Decimal(p['quote_turnover_24h_usdt'])!=sums[p['instrument']] or p['metadata']!=candidates[p['instrument']]:
            raise ValueError('selection value or contract metadata differs from preserved evidence')
    return dict(eligible_candidates=len(candidates),selected=len(actual),metric='sum native volCcyQuote over 24 closed hourly bars',
                ranking_start=evidence['hour_start'],ranking_end_exclusive=evidence['hour_end_exclusive'],
                original40_reused=len({p['instrument'] for p in data.read(data.STUDY/'snapshots/40-pair/universe.json')['pairs']}&set(actual)))


def summary():
    selection=data.read(EXPANSION/'selection.json')
    coverage={p['instrument']:p for p in data.read(EXPANSION/'coverage.json')['pairs']}
    lines=['# 成交额前100加密币永续合约', '',
           f"排名窗口：{selection['quote_window_start']} 至 {selection['quote_window_end']}（UTC，不含结束时刻）。", '',
           '指标为 OKX 原生24根已收盘小时线的 USDT 成交额，不是合约张数、币价乘当前成交量或社交热度。', '',
           '这是数据收集池；当前振幅过滤标签不能倒灌历史，新币指标须等实际预热完成。', '',
           '| 排名 | 币对 | 24h成交额（USDT） | 官方静态列表 | 截止日线数 | 当前3日振幅过滤 |',
           '|---:|---|---:|---|---:|---|']
    for p in selection['selected']:
        lines.append(f"| {p['turnover_rank']} | {p['pair']} | {Decimal(p['quote_turnover_24h_usdt']):,.2f} | "
                     f"{'是' if p['official_static_member'] else '否'} | {coverage[p['instrument']]['daily_bars_at_data_end']} | "
                     f"{'通过' if p['range_stability_pass'] else '未通过'} |")
    (EXPANSION/'PAIRS.md').write_bytes(('\n'.join(lines)+'\n').encode('utf-8'))
    print('Saved expansion100/PAIRS.md')


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['rank','activate','verify','summary']);args=p.parse_args()
    if args.action=='rank':rank()
    elif args.action=='activate':activate()
    elif args.action=='verify':print(verify_selection())
    else:summary()
