import unittest
from btc_v2 import Config,Strategy,run


class ProfitTests(unittest.TestCase):
    def test_profitable_add_respects_risk_cap_and_ledger(self):
        rows=[dict(t=i*300,open=100,high=101,low=99,close=100,volume=1) for i in range(105)]
        for b in rows[95:]:b.update(open=108,high=109,low=107,close=108)
        rows[97]['low']=90
        h=[dict(t=0,ema25=101,ema99=99,close=100,atr=2,daily={},previous_high=99),
           dict(t=14400,ema25=105,ema99=99,close=108,atr=2,daily={},previous_high=103)]
        m,t,_=run(rows,h,Strategy('adds','trend',max_adds=2),Config(),bar_seconds=300)
        self.assertTrue(t)
        trade=t[0]
        self.assertGreaterEqual(trade['adds'],1)
        for u in trade['units'][1:]:
            self.assertLessEqual(u['planned_campaign_loss'],u['risk_budget']+1e-8)
            self.assertLessEqual(u['gross_notional'],u['marked_equity_before_fee']+1e-8)
        self.assertAlmostEqual(m['end_equity'],10000+sum(x['net_pnl'] for x in t))
        self.assertAlmostEqual(m['fees'],sum(sum(u['fee'] for u in x['units'])+x['quantity']*x['exit']*.0005 for x in t))


if __name__=='__main__':unittest.main()
