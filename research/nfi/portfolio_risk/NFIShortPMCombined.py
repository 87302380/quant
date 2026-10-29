"""Adaptive combination of pre-existing risk rules, without new fitted thresholds."""
from NFIShortPortfolioRisk import NFIShortPMShock,NFIShortPMLongATR


class NFIShortPMShockCorrelation(NFIShortPMShock):
    correlation_cap=True

class NFIShortPMATRCorrelation(NFIShortPMLongATR):
    correlation_cap=True
