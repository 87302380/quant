"""Trace every baseline YTD campaign before inferring avoidable losses."""
import json
from pathlib import Path
import nfi_loss_diagnosis as diagnosis
from nfi_analyze import load_result

ROOT=Path(__file__).resolve().parent


def main():
    diagnosis.DATA=ROOT/'data/nfi_ytd2026/freqtrade/futures'
    source=next((ROOT/'results/nfi/ytd_research/baseline').glob('*.zip'))
    details=sorted((diagnosis.diagnose(t) for t in load_result(source)['trades']),key=lambda t:t['profit_usdt'])
    losses=[t for t in details if t['profit_usdt']<0]
    summary={'campaigns':len(details),'losses':len(losses),'gross_loss_usdt':sum(t['profit_usdt'] for t in losses),
             'largest4_loss_share_pct':100*sum(t['profit_usdt'] for t in losses[:4])/sum(t['profit_usdt'] for t in losses),
             'losers_ever_net_green_5m':sum(t['max_sampled_pnl']['pnl_usdt']>0 for t in losses),
             'losers_never_net_green_5m':sum(t['max_sampled_pnl']['pnl_usdt']<=0 for t in losses)}
    for h in [6,12,18]:
        summary[f'negative_at_{h}h_then_won']=sum(t['profit_usdt']>0 and t['at'+str(h)+'h'] and t['at'+str(h)+'h']['hours']==h and t['at'+str(h)+'h']['pnl_usdt']<0 for t in details)
    out={'source':str(source.relative_to(ROOT)),'summary':summary,'campaigns':details,
         'scope':'Original order paths, closed 5m marks incl fees and estimated cost to close; not a replay of alternative exits. Future adds/exits would change under a new rule. Entry features only last closed 4h. Excursion extrema are price-only.'}
    (ROOT/'results/nfi/ytd_research/trade_diagnosis.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':main()
