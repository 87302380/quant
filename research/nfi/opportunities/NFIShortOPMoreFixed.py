"""Identical fixed-slot controls for the adaptive opportunities."""
from NFIShortOPFixed import FixedSlotBudget
from NFIShortOPMore import NFIShortOPCompression,NFIShortOPContext
class NFIShortOPFixedCompression(FixedSlotBudget,NFIShortOPCompression):pass
class NFIShortOPFixedContext(FixedSlotBudget,NFIShortOPContext):pass
