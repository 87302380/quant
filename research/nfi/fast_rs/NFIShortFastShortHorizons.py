"""Complete short-only horizon controls after observing long-filter confounding."""
from NFIShortFastRS import NFIShortFastShort60


class NFIShortFastShort15(NFIShortFastShort60):
    horizon=15

class NFIShortFastShort240(NFIShortFastShort60):
    horizon=240
