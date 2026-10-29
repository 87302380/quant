"""Audit all original 24h campaigns before interpreting any risk-control result."""
import bisect
import gzip
import json
from pathlib import Path
import numpy as np
import talib
from nfi_analyze import load_result, filled_orders, family

ROOT = Path(__file__).resolve().parent
CACHE = {}


def candles(pair, tf):
    key = pair, tf
    if key not in CACHE:
        name = pair.replace('/', '_').replace(':', '_') + f'-{tf}-futures.json.gz'
        rows = json.loads(gzip.decompress((ROOT/'data/nfi/freqtrade/futures'/name).read_bytes()))
        CACHE[key] = rows
    return CACHE[key]


def features(pair, stamp):
    rows = candles(pair, '4h')
    index = bisect.bisect_right([r[0]+14400000 for r in rows], stamp)-1
    close = np.array([r[4] for r in rows], dtype=float)
    high = np.array([r[2] for r in rows], dtype=float)
    low = np.array([r[3] for r in rows], dtype=float)
    if index < 0:
        return {'available':False}
    vals = {'close':close[index], 'EMA12':talib.EMA(close,12)[index],
            'EMA50':talib.EMA(close,50)[index], 'EMA200':talib.EMA(close,200)[index],
            'RSI14':talib.RSI(close,14)[index], 'ADX14':talib.ADX(high,low,close,14)[index],
            'ATR14_pct':talib.ATR(high,low,close,14)[index]/close[index]*100}
    return {k:float(v) if np.isfinite(v) else None for k,v in vals.items()}


def diagnose(t):
    orders = sorted(filled_orders(t),key=lambda o:o['order_filled_timestamp'])
    first = next(o for o in orders if o['ft_is_entry'])
    initial_margin = first['amount']*first['safe_price']/t['leverage']
    cash, qty, pos = 0., 0., 0
    points = []
    for row in candles(t['pair'], '5m'):
        at = row[0]+300000
        if at < t['open_timestamp'] or at > t['close_timestamp']:
            continue
        while pos < len(orders) and orders[pos]['order_filled_timestamp'] <= at:
            o = orders[pos];pos += 1
            sign = 1 if o['ft_order_side']=='buy' else -1
            cash -= sign*o['amount']*o['safe_price']
            cash -= o['amount']*o['safe_price']*t['fee_open' if o['ft_is_entry'] else 'fee_close']
            qty += sign*o['amount']
        pnl = cash+qty*row[4]-abs(qty)*row[4]*t['fee_close']
        points.append({'timestamp':at,'pnl_usdt':pnl,'pnl_initial_margin_pct':100*pnl/initial_margin,
                       'hours':(at-t['open_timestamp'])/3600000})
    minimum = min(points,key=lambda p:p['pnl_usdt'])
    maximum = max(points,key=lambda p:p['pnl_usdt'])
    if abs(points[-1]['pnl_usdt']-t['profit_abs']) > .01:
        raise ValueError(f'Campaign path does not reconcile: {t["pair"]} {t["open_date"]}')
    def snapshot(hour):
        eligible = [p for p in points if p['hours']<=hour]
        return eligible[-1] if eligible else None
    hi = max((r[2] for r in candles(t['pair'],'5m') if t['open_timestamp']<=r[0]<t['close_timestamp']), default=first['safe_price'])
    lo = min((r[3] for r in candles(t['pair'],'5m') if t['open_timestamp']<=r[0]<t['close_timestamp']), default=first['safe_price'])
    adverse = (hi/first['safe_price']-1) if t['is_short'] else (1-lo/first['safe_price'])
    return {'pair':t['pair'],'side':'short' if t['is_short'] else 'long','tag':t['enter_tag'].strip(),
            'family':family(t['enter_tag']), 'open_date':t['open_date'],'open_timestamp':t['open_timestamp'],
            'close_date':t['close_date'],'profit_usdt':t['profit_abs'], 'profit_ratio_pct':100*t['profit_ratio'],
            'entries':sum(o['ft_is_entry'] for o in orders),'initial_margin':initial_margin,
            'max_adverse_price_pct':100*adverse,'min_sampled_pnl':minimum,'max_sampled_pnl':maximum,
            'at6h':snapshot(6),'at12h':snapshot(12),'at18h':snapshot(18),
            'own4h_at_entry':features(t['pair'],t['open_timestamp']),
            'btc4h_at_entry':features('BTC/USDT:USDT',t['open_timestamp'])}


def main():
    source = sorted((ROOT/'results/nfi/study/official_24h').glob('*.zip'))[-1]
    ts = load_result(source)['trades']
    details = sorted([diagnose(t) for t in ts],key=lambda t:t['profit_usdt'])
    summary = {}
    for pct in (3,6):
        summary[f'ever_adverse_{pct}pct'] = {
            'eventually_winning':sum(t['profit_usdt']>0 and t['max_adverse_price_pct']>=pct for t in details),
            'eventually_losing':sum(t['profit_usdt']<0 and t['max_adverse_price_pct']>=pct for t in details)}
    result = {'source':str(source.relative_to(ROOT)),
              'scope':'All61 original-path campaigns, not a replacement backtest; closed5m marks and cumulative order cashflows incl. partial exits, actual fees and estimated fee to close remaining position. Price excursion uses intrabar extremes; P&L samples do not. Features use lastfullyclosed4h, talib warmup NaN explicit.',
              'summary':summary,'campaigns':details}
    out = ROOT/'results/nfi/risk_study/trade_diagnosis.json'
    out.write_text(json.dumps(result,indent=2)+'\n')
    for t in details:
        if t['profit_usdt']<0:
            print(t['pair'],t['side'],t['tag'],round(t['profit_usdt'],2),
                  'MAE price',round(t['max_adverse_price_pct'],2),
                  '6h',round(t['at6h']['pnl_usdt'],2),'12h',round(t['at12h']['pnl_usdt'],2),
                  'maxpnl',round(t['max_sampled_pnl']['pnl_usdt'],2))
    print(summary)


if __name__ == '__main__':main()
