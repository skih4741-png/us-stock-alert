"""Rolling chronological evaluation windows for the three fixed-rule strategies.

No hyperparameter training is performed here. Evaluations are not independent
evidence of profitability until universe survivorship, data licensing and
out-of-sample procedure have been independently verified.
"""
from __future__ import annotations

import pandas as pd

from validation.compare_strategies import STRATEGIES
from validation.portfolio import simulate_portfolio
from validation.promotion import rank_candidates


def rolling_evaluation(history, spy, cfg, *,
                       fold_months: int = 12, folds: int = 3,
                       initial_cash: float = 10000.0, membership=None) -> dict:
    if folds < 1 or fold_months < 1:
        raise ValueError("folds and fold_months must be positive")
    end = pd.Timestamp(spy.index[-1]).tz_localize(None)
    results = {name: [] for name in STRATEGIES}
    for k in reversed(range(folds)):
        finish = end - pd.DateOffset(months=k * fold_months)
        start = finish - pd.DateOffset(months=fold_months) + pd.Timedelta(days=1)
        window = spy.loc[(spy.index >= start) & (spy.index <= finish)]
        if len(window) < 120:
            continue
        for name in STRATEGIES:
            p = simulate_portfolio(
                history, spy, name, cfg,
                initial_cash=initial_cash,
                membership=membership,
                start_date=start.strftime("%Y-%m-%d"),
                end_date=finish.strftime("%Y-%m-%d"),
            )
            results[name].append({
                "start": start.strftime("%Y-%m-%d"),
                "end": finish.strftime("%Y-%m-%d"),
                "metrics": p["metrics"],
            })
    summary = {}
    for name, windows in results.items():
        if not windows:
            summary[name] = {"eligible": False, "reasons": ["평가 기간 부족"],
                             "action": "observe_only"}
            continue
        # No synthetic pooled Sharpe or PF: folding these is not statistically valid.
        summary[name] = {
            "folds": len(windows),
            "positive_folds": sum(w["metrics"]["total_return_pct"] > 0 for w in windows),
            "beat_spy_folds": sum(
                (w["metrics"]["excess_return_pct"] or -999) > 0 for w in windows
            ),
            "all_folds_beat_spy": all(
                w["metrics"]["excess_return_pct"] is not None and
                w["metrics"]["excess_return_pct"] > 0 for w in windows
            ),
        }
    # Survivorship universe unresolved: fail-closed regardless of favorable stats.
    no_promotion = rank_candidates(
        {name: (windows[-1]["metrics"] if windows else {}) for name, windows in results.items()},
        independent_oos=False, verified_universe=False,
    )
    return {
        "status": "research_only_unverified",
        "rolling_windows": results,
        "summary": summary,
        "promotion_gate": no_promotion,
        "note": "Fixed rules; chronological windows, no training. Historical universe still biased.",
    }
