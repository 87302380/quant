"""Causal 15m pullback research engine. Standard library only; no order routing."""
from __future__ import annotations
import argparse
import csv
import json
import math
from dataclasses import dataclass, asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from decimal import Decimal, ROUND_FLOOR


@dataclass(frozen=True)
class Config:
    equity: float = 10000
    risk: float = .01
    total_risk: float = .02
    fee: float = .0005  # each side
    slippage: float = .0002  # each market fill
    funding_per_8h: float = 0  # disabled for current research; optional cost, both directions
    min_rr: float = 1.5
    zone_atr: float = .3
    stop_atr: float = .2
    max_entry_atr: float = 1.5
    setup_bars: int = 8
    pivot_left: int = 2
    pivot_right: int = 2
    rsi_long: float = 35
    rsi_short: float = 65
    volume_ratio: float = 1.2
    require_rsi: bool = False
    require_volume: bool = False
    enable_long: bool = True
    enable_short: bool = True
    max_hold_bars: int = 96
    min_adx: float = 0
    require_1h_trend: bool = False
    min_stop_atr: float = 0
    target_rr_cap: float = 0  # optional closer target, still subject to net RR hard floor
    # Explicit research assumptions, NOT verified current OKX metadata.
    contract_value: float = .01
    lot_size: float = .01
    min_contracts: float = .01
    tick_size: float = .1
    leverage: float = 1

    def __post_init__(self):
        for k, v in asdict(self).items():
            if isinstance(v, (int, float)) and not math.isfinite(v):
                raise ValueError(f'non-finite config: {k}')
        if not 0 < self.risk <= .01 or not self.risk <= self.total_risk <= 1:
            raise ValueError('risk must be <=1%, total_risk >= risk')
        if self.min_rr < 1.5 or self.leverage != 1:
            raise ValueError('research requires RR >=1.5 and unleveraged collateral')
        for k in ('equity', 'zone_atr', 'max_entry_atr', 'setup_bars', 'pivot_left',
                  'pivot_right', 'max_hold_bars', 'contract_value', 'lot_size', 'min_contracts', 'tick_size'):
            if getattr(self, k) <= 0:
                raise ValueError(f'{k} must be positive')
        if min(self.fee, self.slippage, self.funding_per_8h, self.stop_atr) < 0:
            raise ValueError('costs and buffer must be nonnegative')
        if min(self.min_adx,self.min_stop_atr,self.target_rr_cap) < 0:
            raise ValueError('research filters must be nonnegative')


def load(path, step_seconds=900):
    rows = []
    with open(path, encoding='utf-8-sig', newline='') as f:
        for r in csv.DictReader(f):
            t = datetime.fromisoformat(r['timestamp'].replace('Z', '+00:00'))
            if t.tzinfo is None:
                raise ValueError('timestamp must have timezone')
            b = {k: float(r[k]) for k in ('open', 'high', 'low', 'close', 'volume')}
            b['t'] = int(t.timestamp())
            if (any(not math.isfinite(b[k]) for k in b) or min(b[k] for k in ('open','high','low','close')) <= 0
                    or b['volume'] < 0 or b['low'] > min(b['open'], b['close'])
                    or b['high'] < max(b['open'], b['close']) or b['low'] > b['high']):
                raise ValueError('invalid OHLCV')
            if b['t'] % step_seconds or (rows and b['t'] != rows[-1]['t'] + step_seconds):
                raise ValueError('candles must be ordered, unique, UTC aligned and gap-free')
            rows.append(b)
    if not rows:
        raise ValueError('empty candles')
    return rows


def aggregate(rows, seconds):
    groups = {}
    for b in rows:
        groups.setdefault(b['t'] // seconds * seconds, []).append(b)
    return [dict(t=t, open=g[0]['open'], high=max(b['high'] for b in g),
                 low=min(b['low'] for b in g), close=g[-1]['close'],
                 volume=sum(b['volume'] for b in g))
            for t, g in groups.items() if len(g) == seconds // 900 and g[0]['t'] == t]


def smooth(xs, n, alpha=None):
    out, value, seed = [], None, []
    for x in xs:
        if value is None:
            seed.append(x)
            if len(seed) == n:
                value = sum(seed) / n
        else:
            value += (alpha or 1/n) * (x-value)
        out.append(value)
    return out


def indicators(rows, c):
    rows = [dict(b) for b in rows]
    closes = [b['close'] for b in rows]
    for n in (25, 99):
        for b, v in zip(rows, smooth(closes, n, 2/(n+1))):
            b[f'ema{n}'] = v
    trs, gains, losses, ups, downs = [], [], [], [], []
    for i, b in enumerate(rows):
        prev = rows[max(0, i-1)]
        delta = b['close']-prev['close']
        up, down = b['high']-prev['high'], prev['low']-b['low']
        trs.append(max(b['high']-b['low'], abs(b['high']-prev['close']), abs(b['low']-prev['close'])))
        gains.append(max(delta, 0)); losses.append(max(-delta, 0))
        ups.append(max(up, 0) if up > down else 0)
        downs.append(max(down, 0) if down > up else 0)
    atr, ag, al, pu, pd = [smooth(x, 14) for x in (trs, gains, losses, ups, downs)]
    dx = []
    last_high = last_low = None
    for i, b in enumerate(rows):
        b['atr'] = atr[i]
        b['rsi'] = None if ag[i] is None else (100*ag[i]/(ag[i]+al[i]) if ag[i]+al[i] else 50)
        b['plus_di'] = 100*pu[i]/atr[i] if atr[i] else None
        b['minus_di'] = 100*pd[i]/atr[i] if atr[i] else None
        if pu[i] is not None:
            dx.append(100*abs(pu[i]-pd[i])/(pu[i]+pd[i]) if pu[i]+pd[i] else 0)
        p = i-c.pivot_right
        if p >= c.pivot_left:
            window = rows[p-c.pivot_left:i+1]
            if rows[p]['high'] == max(x['high'] for x in window):
                last_high = rows[p]['high']
            if rows[p]['low'] == min(x['low'] for x in window):
                last_low = rows[p]['low']
        b['swing_high'], b['swing_low'] = last_high, last_low
        b['volume_ratio'] = b['volume']/(sum(x['volume'] for x in rows[i-20:i])/20) if i >= 20 and sum(x['volume'] for x in rows[i-20:i]) else 0
    adx = iter(smooth(dx, 14))
    for b in rows:
        b['adx'] = next(adx) if b['plus_di'] is not None else None
    return rows


def features(rows, c):
    base = indicators(rows, c)
    h1, h4 = indicators(aggregate(rows, 3600), c), indicators(aggregate(rows, 14400), c)
    j = k = -1
    for b in base:
        end = b['t']+900
        while j+1 < len(h1) and h1[j+1]['t']+3600 <= end: j += 1
        while k+1 < len(h4) and h4[k+1]['t']+14400 <= end: k += 1
        b['h1'] = h1[j] if j >= 0 else {}
        b['h4'] = h4[k] if k >= 0 else {}
    return base


def cluster(levels, width):
    groups = []
    for x in sorted(x for x in levels if x is not None):
        if groups and x-groups[-1][0] <= width:
            groups[-1].append(x)
        else:
            groups.append([x])
    return groups


def candidates(bars, c):
    setups = {1: None, -1: None}
    for i, b in enumerate(bars):
        h, f, atr = b['h1'], b['h4'], b['atr']
        if not atr or not f.get('ema99') or not h.get('ema99'): continue
        for d in (1, -1):
            if not (c.enable_long if d == 1 else c.enable_short): continue
            if d*(f['ema25']-f['ema99']) <= 0 or d*(f['close']-f['ema99']) <= 0:
                setups[d] = None
                continue
            s = setups[d]
            if s and i-s['start'] >= c.setup_bars:
                s = setups[d] = None
            if s is None:
                levels = [h['ema25'], h['ema99'], f['ema25'], h['swing_low' if d==1 else 'swing_high'], f['swing_low' if d==1 else 'swing_high']]
                zones = [g for g in cluster(levels, c.zone_atr*h['atr'])
                         if b['low'] <= max(g)+c.zone_atr*atr and b['high'] >= min(g)-c.zone_atr*atr]
                if zones:
                    g = min(zones, key=lambda g: abs(sum(g)/len(g)-b['close']))
                    setups[d] = dict(start=i, low=min(g)-c.zone_atr*atr, high=max(g)+c.zone_atr*atr,
                                     extreme=b['low' if d==1 else 'high'], count=len(g), recovered=False, tested=False)
                continue
            edge = s['low'] if d==1 else s['high']
            extreme = b['low' if d==1 else 'high']
            previous = bars[i-1]
            if s['tested'] and d*(extreme-s['stop_extreme']) < -c.stop_atr*atr:
                setups[d] = None
                continue
            # Distinct tests require an intervening close away from the first touch.
            if s['recovered'] and not s['tested']:
                touch = b['low'] <= s['high'] and b['high'] >= s['low']
                stable = d*(extreme-s['extreme']) >= -.2*atr
                if touch and stable and d*(b['close']-b['open']) > 0:
                    s['tested'] = True
                    s['stop_extreme'] = min(s['extreme'], extreme) if d==1 else max(s['extreme'], extreme)
            if not s['tested'] and d*(extreme-s['extreme']) < -.2*atr:
                setups[d] = None
                continue
            if d*(b['close']-s['extreme']) > .5*atr:
                s['recovered'] = True
            trigger = s['tested'] and d*(b['close']-edge) > 0 and d*(b['close']-previous['high' if d==1 else 'low']) > 0
            if not trigger: continue
            recent = bars[s['start']:i+1]
            rsi_ok = (min(x['rsi'] for x in recent) <= c.rsi_long and b['rsi'] > previous['rsi']) if d==1 else (max(x['rsi'] for x in recent) >= c.rsi_short and b['rsi'] < previous['rsi'])
            vol_ok = b['volume_ratio'] >= c.volume_ratio
            stop = s['stop_extreme']-d*c.stop_atr*atr
            targets = [h['swing_high' if d==1 else 'swing_low'], f['swing_high' if d==1 else 'swing_low']]
            targets = [x for x in targets if x is not None and d*(x-b['close']) > 0]
            event = dict(index=i, side='long' if d==1 else 'short', direction=d, stop=stop,
                         target=min(targets, key=lambda x: abs(x-b['close'])) if targets else None,
                         structure=s['stop_extreme'], atr=atr, rsi=b['rsi'], rsi_1h=h['rsi'],
                         volume_ratio=b['volume_ratio'], adx=f['adx'], plus_di=f['plus_di'], minus_di=f['minus_di'],
                         ema_distance_atr=(f['close']-f['ema25'])/f['atr'], zone_low=s['low'], zone_high=s['high'],
                         score=70+10*(s['count']>=2)+10*rsi_ok+10*vol_ok,
                         rsi_ok=rsi_ok, volume_ok=vol_ok)
            setups[d] = None
            yield event


def round_step(x, step, up=False):
    q = Decimal(str(x))/Decimal(str(step))
    return float(q.to_integral_value(rounding='ROUND_CEILING' if up else ROUND_FLOOR)*Decimal(str(step)))


def run(rows, c, prepared_bars=None, event_source=None, start_time=None):
    bars = prepared_bars if prepared_bars is not None else features(rows, c)
    events = list(event_source if event_source is not None else candidates(bars, c))
    equity, busy, trades, audit = c.equity, -1, [], []
    for e in events:
        e = dict(e)
        i, d = e['index'], e['direction']
        if start_time is not None and bars[i]['t']+900 < start_time: continue
        reason = None
        if i+1 >= len(bars): reason = 'no_next_open'
        elif i+1 <= busy: reason = 'existing_position'
        elif c.require_rsi and not e['rsi_ok']: reason = 'rsi_filter'
        elif c.require_volume and not e['volume_ok']: reason = 'volume_filter'
        elif e['target'] is None: reason = 'no_confirmed_target'
        elif e.get('adx',0) is not None and e.get('adx',0) < c.min_adx: reason = 'adx_filter'
        elif c.require_1h_trend and d*(bars[i]['h1']['ema25']-bars[i]['h1']['ema99']) <= 0: reason = '1h_trend_filter'
        if reason:
            audit.append(dict(e, status=reason)); continue
        entry = bars[i+1]['open']*(1+d*c.slippage)
        stop = round_step(e['stop'], c.tick_size, up=d==-1)
        target = round_step(e['target'], c.tick_size, up=d==-1)
        if c.min_stop_atr:
            stop = min(stop,entry-c.min_stop_atr*e['atr']) if d==1 else max(stop,entry+c.min_stop_atr*e['atr'])
            stop = round_step(stop,c.tick_size,up=d==-1)
        if c.target_rr_cap:
            cap = entry+d*c.target_rr_cap*abs(entry-stop)
            target = min(target,cap) if d==1 else max(target,cap)
            target = round_step(target,c.tick_size,up=d==-1)
        stop_fill, target_fill = stop*(1-d*c.slippage), target*(1-d*c.slippage)
        funding = entry*c.funding_per_8h*math.ceil(c.max_hold_bars/32)
        loss = d*(entry-stop_fill)+c.fee*(entry+stop_fill)+funding
        reward = d*(target_fill-entry)-c.fee*(entry+target_fill)-funding
        rr = reward/loss if loss > 0 else -1
        if d*(entry-stop) <= 0 or d*(target-entry) <= 0: reason = 'invalid_stop_target'
        elif d*(entry-e['structure']) > c.max_entry_atr*e['atr']: reason = 'late_entry'
        elif rr < c.min_rr: reason = 'net_rr'
        contracts = round_step(min(equity*min(c.risk,c.total_risk)/max(loss, 1e-12), max(0,equity)/(entry*(1+c.fee)))/c.contract_value, c.lot_size)
        if equity <= 0 or contracts < c.min_contracts: reason = reason or 'order_size'
        if reason:
            audit.append(dict(e, status=reason, entry=entry, net_rr=rr)); continue
        qty = contracts*c.contract_value
        last = min(len(bars)-1, i+c.max_hold_bars)
        exit_price, why, j = bars[last]['close']*(1-d*c.slippage), 'timeout', last
        for j in range(i+1, last+1):
            b = bars[j]
            stop_hit = b['low'] <= stop if d==1 else b['high'] >= stop
            target_hit = b['high'] >= target if d==1 else b['low'] <= target
            if stop_hit:
                raw = min(stop,b['open']) if d==1 else max(stop,b['open'])
                exit_price, why = raw*(1-d*c.slippage), 'stop'; break
            if target_hit:
                exit_price, why = target_fill, 'target'; break
        funding_paid = qty*entry*c.funding_per_8h*math.ceil((j-i)/32)
        pnl = qty*(d*(exit_price-entry)-c.fee*(entry+exit_price))-funding_paid
        trade = dict(e, entry_time=bars[i+1]['t'], exit_time=bars[j]['t']+900,
                     entry=entry, stop=stop, target=target, exit=exit_price, contracts=contracts,
                     quantity=qty, planned_risk=qty*loss, net_rr=rr, net_pnl=pnl,
                     return_on_equity=pnl/equity, exit_reason=why, funding=funding_paid)
        equity += pnl
        trade['equity'] = equity
        trades.append(trade); audit.append(dict(e, status='filled', entry=entry, net_rr=rr))
        busy = j
    return trades, audit


def stats(trades):
    pnl = [t['net_pnl'] for t in trades]
    wins, losses = sum(max(x,0) for x in pnl), -sum(min(x,0) for x in pnl)
    streak = worst = 0
    for x in pnl:
        streak = streak+1 if x < 0 else 0
        worst = max(worst, streak)
    return dict(trades=len(pnl), win_rate=sum(x>0 for x in pnl)/len(pnl) if pnl else None,
                net_pnl=sum(pnl), mean_net_pnl=sum(pnl)/len(pnl) if pnl else None,
                profit_factor=wins/losses if losses else None, max_consecutive_losses=worst)


def report(trades):
    return {'all':stats(trades), **{side:stats([t for t in trades if t['side']==side]) for side in ('long','short')},
            'scores':{label:stats([t for t in trades if low<=t['score']<=high])
                      for label,low,high in [('50-59',50,59),('60-69',60,69),('70-79',70,79),('80+',80,100)]}}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('csv'); p.add_argument('--config'); p.add_argument('--out', default='results/pullback')
    args = p.parse_args()
    c = Config(**json.loads(Path(args.config).read_text(encoding='utf-8'))) if args.config else Config()
    rows = load(args.csv)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    summary = {}
    for name,rsi,vol in [('baseline',False,False),('rsi',True,False),('volume',False,True),('rsi_volume',True,True)]:
        cfg = replace(c, require_rsi=rsi, require_volume=vol)
        trades, audit = run(rows, cfg)
        summary[name] = report(trades)
        for suffix, records in [('trades',trades),('signals',audit)]:
            (out/f'{name}_{suffix}.json').write_text(json.dumps(records,indent=2,allow_nan=False),encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(summary,indent=2,allow_nan=False),encoding='utf-8')
    (out/'config.json').write_text(json.dumps(asdict(c),indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__': main()
