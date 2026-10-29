"""Allocation-matched controls: prevent small extra slots reallocating more to originals."""
from NFIShortOpportunities import NFIShortOPControl,NFIShortOPPullback,NFIShortOPBreakout,NFIShortOPNative,NFIShortOPRetest,NFIShortOPCombined
class FixedSlotBudget:
    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        ordinary=self.wallets.get_total_stake_amount()/self.config['max_open_trades']
        return super().custom_stake_amount(pair,current_time,current_rate,min(proposed_stake,ordinary),min_stake,max_stake,leverage,entry_tag,side,**kwargs)
class NFIShortOPFixedControl(FixedSlotBudget,NFIShortOPControl):pass
class NFIShortOPFixedPullback(FixedSlotBudget,NFIShortOPPullback):pass
class NFIShortOPFixedBreakout(FixedSlotBudget,NFIShortOPBreakout):pass
class NFIShortOPFixedNative(FixedSlotBudget,NFIShortOPNative):pass
class NFIShortOPFixedRetest(FixedSlotBudget,NFIShortOPRetest):pass
class NFIShortOPFixedCombined(FixedSlotBudget,NFIShortOPCombined):pass
