"""Frozen stop and allocation; vary only the inherited short target multiple."""
from NFIAblation import NFIAblation_CP


class NFIShortStop_2_0_R2_0(NFIAblation_CP):
    reward_multiple = 2.0


class NFIShortStop_2_0_R1_5(NFIAblation_CP):
    reward_multiple = 1.5


class NFIShortStop_2_0_R1_0(NFIAblation_CP):
    reward_multiple = 1.0
