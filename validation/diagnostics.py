"""Explain portfolio outcomes by setup context and realized exit mechanism.

Realized closed P&L is a dollar amount; no inference about the
profitability of still-open positions. Research-only summary.
"""
from __future__ import annotations

from collections import defaultdict


def trade_attribution(closed: list[dict]) -> dict:
    groups = defaultdict(lambda: {"trades": 0, "wins": 0, "gross_profit": 0.0,
                                 "gross_loss": 0.0, "pnl_usd": 0.0})
    for trade in closed:
        pnl = float(trade.get("pnl") or 0)
        for dimension in ("reason", "regime", "ticker"):
            key = (dimension, str(trade.get(dimension) or "unclassified"))
            g = groups[key]
            g["trades"] += 1
            g["wins"] += int(pnl > 0)
            g["gross_profit"] += max(0.0, pnl)
            g["gross_loss"] += max(0.0, -pnl)
            g["pnl_usd"] += pnl
    out = {}
    for (dimension, key), value in sorted(groups.items()):
        n = value["trades"]
        loss = value["gross_loss"]
        out.setdefault(dimension, {})[key] = {
            "trades": n,
            "win_rate_pct": round(100 * value["wins"] / n, 2),
            "avg_pnl_usd": round(value["pnl_usd"] / n, 2),
            "realized_pnl_usd": round(value["pnl_usd"], 2),
            "profit_factor": round(value["gross_profit"] / loss, 3) if loss > 0 else None,
        }
    return out


def cost_sensitivity(results: dict, stress: dict) -> dict:
    """Stress keys are cost multipliers; flag only improvements that remain positive."""
    answer = {}
    for name, payload in results.items():
        base = payload.get("metrics", {})
        rows = {"1.0": base}
        for factor, by_strategy in stress.items():
            rows[factor] = by_strategy.get(name, {})
        net = [v.get("total_return_pct") for v in rows.values()]
        answer[name] = {
            "scenarios": rows,
            "profitable_at_all_costs": bool(net and all(x is not None and x > 0 for x in net)),
            "note": "Sensitivity is not a confidence interval or future forecast.",
        }
    return answer
