"""Replay one high-timeframe location candidate; never sends orders."""
import argparse
import json
from dataclasses import asdict
from btc_locations import DATA,OUT,Rules,Config,load,prepare,simulate,ts


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--style',choices=['balanced','high_win'],default='balanced')
    p.add_argument('--start');p.add_argument('--end')
    args=p.parse_args()
    r=Rules('4h_long_level' if args.style=='balanced' else '4h_long_cap',short=False,
        exit='level' if args.style=='balanced' else 'cap',only4h=True,stop_floor4h=.75,
        cooldown_hours=12,max_cost_fraction=.15,min_net_rr=.75)
    bars=prepare(load(DATA,step_seconds=300))
    m,t,_=simulate(bars,r,Config(),start=ts(args.start) if args.start else None,end=ts(args.end) if args.end else None)
    folder=OUT/'candidates'/r.name;folder.mkdir(parents=True,exist_ok=True)
    for name,value in [('rules',dict(rules=asdict(r),risk=asdict(Config()),live_trading_enabled=False,
                         status='research only; cost stress failed')),
                       ('metrics',m),('trades',t)]:
        (folder/f'{name}.json').write_text(json.dumps(value,indent=2),encoding='utf-8')
    print(json.dumps(m,indent=2))


if __name__=='__main__':main()
