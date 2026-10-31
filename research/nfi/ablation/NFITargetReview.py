"""Primary experiment: one target attribute on the untouched frozen compression core."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'opportunities'))
from NFIShortOPMore import NFIShortOPCompression


class NFIShortTargetR15(NFIShortOPCompression):
    reward_multiple = 1.5


class NFIShortTargetR10(NFIShortOPCompression):
    reward_multiple = 1.0
