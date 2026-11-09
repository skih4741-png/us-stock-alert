"""Pure, conservative execution primitives shared by research and paper paths.

No broker API access. These primitives evaluate one completed OHLC bar, and
cannot establish intrabar order. Stops always take precedence over targets.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Fill:
    price: float
    reason: str


def entry_fill(open_price: float, low: float, limit: float, skip_above: float,
               stop: float, touch: float = 0.001) -> Fill | None:
    if min(open_price, low, limit, skip_above, stop) <= 0:
        return None
    if open_price > skip_above or open_price <= stop:
        return None
    if low > limit * (1.0 - touch):
        return None
    price = min(open_price, limit)
    if price <= stop:
        return None
    return Fill(price, "limit")


def exit_fill(open_price: float, high: float, low: float, stop: float,
              target: float, half: bool = False, fresh: bool = False,
              slip: float = 0.0015, touch: float = 0.001) -> Fill | None:
    if min(open_price, high, low, stop, target) <= 0:
        return None
    # An unsequenced bar may have hit both prices. Stop-first is conservative.
    if low <= stop:
        # Fresh position: entry timing within the same bar is unknown.
        # Assumes stop occurred after entry; a pessimistic convention.
        return Fill(min(open_price, stop) * (1.0 - slip), "stop")
    if not fresh and not half and high >= target * (1.0 + touch):
        return Fill(max(open_price, target), "target")
    return None
