"""A necessary control for aggregate portfolio restrictions: halve both directions."""
from NFIShortPortfolioRisk import NFIShortPMBase


class NFIShortPMHalfAll(NFIShortPMBase):
    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        stake=super().custom_stake_amount(pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs)*.5
        return stake if min_stake is None or stake>=min_stake else 0.
