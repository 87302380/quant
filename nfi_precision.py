"""Machine-roundoff tolerance only; never expand a candle by a market tick."""
import math


def candle_contains(rate,low,high):
    return (low<=rate<=high or abs(rate-low)<=4*max(math.ulp(rate),math.ulp(low)) or
            abs(rate-high)<=4*max(math.ulp(rate),math.ulp(high)))
