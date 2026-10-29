"""Original-path diagnostics, not counterfactual strategy returns."""
import json,hashlib
from pathlib import Path
import nfi_loss_diagnosis as d
from nfi_analyze import load_result
ROOT=Path(__file__).resolve().parent

def main():
    d.DATA=ROOT/'data/nfi_ytd2026/freqtrade/futures'
    archive=next((ROOT/'results/nfi/portfolio_risk/control').glob('*.zip'))
    trades=[t for t in load_result(archive)['trades'] if not t['is_short']]
    rows=[d.diagnose(t) for t in trades]
    def summary(items):
        return {'trades':len(items),'pnl_usdt':sum(t['profit_usdt'] for t in items),'median_min_margin_pnl_pct':__import__('statistics').median(t['min_sampled_pnl']['pnl_initial_margin_pct'] for t in items) if items else None,
                'positive_sampled_pnl_before_exit':sum(t['max_sampled_pnl']['pnl_usdt']>0 for t in items),
                'underwater_at6h':sum(t['at6h']['hours']>=6 and t['at6h']['pnl_usdt']<0 for t in items),
                'underwater_at12h':sum(t['at12h']['hours']>=12 and t['at12h']['pnl_usdt']<0 for t in items)}
    result={'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'warning':'Original paths only; horizon snapshots only counted if position still open at horizon. Five-minute cash-flow marks include actual partial fills and fees; no counterfactual returns. Excursions include intrabar ranges, equity sampled at closed5m.',
            'winners':summary([t for t in rows if t['profit_usdt']>0]),'losers':summary([t for t in rows if t['profit_usdt']<0]),'campaigns':rows}
    out=ROOT/'results/nfi/long_entry/diagnosis.json';out.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='campaigns'},indent=2))
if __name__=='__main__':main()
