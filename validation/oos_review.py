"""Offline out-of-sample gate with all data available before any promotion.

The validation fold is not an independently *certified* OOS unless training
and strategy selection occurred before the held-out period was observed.
This module never changes live orders, and never fabricates verification.
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd

from validation.compare_strategies import STRATEGIES
from validation.portfolio import simulate_portfolio
from validation.promotion import Gate, assess_strategy


def holdout_review(history, spy, cfg, membership, *, years: int = 1,
                   gate: Gate = Gate(), independent_oos: bool = False,
                   verified_universe: bool = False) -> dict:
    """Use only the most recent full year for held-out diagnostics.

    All three strategy definitions are frozen in code; they are not fitted
    to the validation window here. Flag attestation separately from metrics.
    """
    if years < 1:
        raise ValueError("years must be positive")
    last = pd.Timestamp(spy.index[-1])
    first = last - pd.DateOffset(years=years)
    if len(spy.loc[(spy.index >= first) & (spy.index <= last)]) < 120:
        raise ValueError("insufficient holdout data")
    metrics, decisions = {}, {}
    for name in STRATEGIES:
        result = simulate_portfolio(
            history, spy, name, cfg,
            start_date=first.strftime("%Y-%m-%d"),
            end_date=last.strftime("%Y-%m-%d"),
            membership=membership,
        )
        metrics[name] = result["metrics"]
        decisions[name] = assess_strategy(
            result["metrics"],
            independent_oos=independent_oos,
            verified_universe=verified_universe,
            gate=gate,
        )
    return {
        "holdout_start": first.strftime("%Y-%m-%d"),
        "holdout_end": last.strftime("%Y-%m-%d"),
        "independent_oos_attested": independent_oos,
        "historical_universe_attested": verified_universe,
        "metrics": metrics,
        "decisions": decisions,
        "eligible_for_paper_review": [
            n for n, decision in decisions.items()
            if decision["eligible"]
        ],
        "note": "A favorable retrospective result is not self-certification of independent OOS.",
    }
