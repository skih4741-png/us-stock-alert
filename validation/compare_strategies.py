"""Compare three daily setups with one shared execution model.

Research-only, NOT production execution. Historical universe is currently assembled
from today's listings: survivorship and selection bias remain. No historical
point-in-time fundamentals are reconstructed. Do not treat as live track record.

Usage: python -m validation.compare_strategies --tickers 100 --years 3
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

import backtest
import config
import market
import prices
import universe

STRATEGIES = ("breakout", "pullback", "oversold")
OUTPUT = Path("data/strategy_comparison.json")
COST_EACH_SIDE = 0.0035
MAX_HOLD = 20
MIN_HISTORY = 260


def signals(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """Form signals using only information known at each signal-date close."""
    o = frame
    previous_high = o["close"].shift(1).rolling(252, min_periods=200).max()
    trend = (o.ma20 > o.ma50) & (o.ma50 > o.ma200)
    breakout = trend & (o.close > previous_high) & (o.volr >= 1.5)
    pullback = (
        trend & (o.close >= o.ma50) &
        (o.close.shift(1) <= o.ma20.shift(1)) &
        (o.close > o.ma20) & (o.close > o.close.shift(1))
    )
    oversold = (
        (o.close > o.ma200) &
        (o.rsi.shift(1) < 35) & (o.rsi >= 35) &
        (o.close > o.close.shift(1))
    )
    return {
        "breakout": breakout.fillna(False),
        "pullback": pullback.fillna(False),
        "oversold": oversold.fillna(False),
    }


def net_return(gross_return: float, fee_each_side: float = COST_EACH_SIDE) -> float:
    """Round-trip costs, applied consistently to each simulated trade."""
    return (1.0 + gross_return) * (1.0 - fee_each_side) / (1.0 + fee_each_side) - 1.0


def metrics(returns: list[float], starting_cash: float = 10000.0) -> dict:
    """Trade-level diagnostics only; NOT portfolio CAGR or equity-curve MDD."""
    if not returns:
        return {"trades": 0, "win_rate": None, "mean_net_pct": None,
                "profit_factor": None, "sum_net_pct": None}
    arr = np.asarray(returns, dtype=float)
    gross_profit = float(arr[arr > 0].sum())
    gross_loss = float(-arr[arr < 0].sum())
    return {
        "trades": len(arr),
        "win_rate": round(float(np.mean(arr > 0) * 100), 2),
        "mean_net_pct": round(float(arr.mean() * 100), 3),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
        "sum_net_pct": round(float(arr.sum() * 100), 3),
        "note": "Sum of percent trades is not portfolio return. Positions are not capital-constrained.",
    }


def compare(history: dict[str, pd.DataFrame], spy: pd.DataFrame,
            cfg: dict, years: int = 3, fee_each_side: float = COST_EACH_SIDE,
            max_hold: int = MAX_HOLD) -> dict:
    """Evaluate three entry rules over identical price, regime and exit assumptions."""
    cut = spy.index[-1] - pd.DateOffset(years=years)
    regime = market.regime_series(spy)
    raw = {name: [] for name in STRATEGIES}
    events = {name: [] for name in STRATEGIES}
    for ticker, df in history.items():
        if len(df) < MIN_HISTORY:
            continue
        o = backtest.indicator_frame(df)
        masks = signals(o)
        aligned_regime = regime.reindex(o.index, method="ffill")
        for name, mask in masks.items():
            last_entry = -max_hold - 1
            for i in np.flatnonzero(mask.to_numpy()):
                if i < 252 or i + max_hold >= len(o) or o.index[i] < cut:
                    continue
                # Avoid repeatedly counting signals with overlapping holding windows
                # on the same ticker and strategy.
                if i - last_entry <= max_hold:
                    continue
                r = aligned_regime.iloc[i]
                if pd.isna(r) or r == "bear":
                    continue
                if not math.isfinite(float(o["close"].iloc[i])):
                    continue
                rr = float(cfg["상승장 손익비"] if r == "bull" else cfg["횡보장 손익비"])
                result = backtest.simulate(o, int(i), rr, cfg, max_hold=max_hold)
                if not result or result.get("skipped") or not result.get("complete"):
                    continue
                net = net_return(float(result["ret"]), fee_each_side)
                raw[name].append(net)
                events[name].append({
                    "ticker": ticker,
                    "signal_date": o.index[i].strftime("%Y-%m-%d"),
                    "regime": str(r),
                    "gross_pct": round(float(result["ret"])*100, 3),
                    "net_pct": round(net*100, 3),
                    "exit": str(result.get("exit", "")),
                    "days": int(result.get("days", 0)),
                })
                last_entry = int(i)
    return {
        "method": "exploratory same-exit trade comparison, not portfolio backtest",
        "limitations": [
            "Current-day universe: survivorship and selection bias",
            "Daily OHLC cannot establish intrabar order, conservative stop-first",
            "No point-in-time delisted stocks or fundamentals",
            "Fees are an assumption and fills are simplified",
            "Overlapping positions across tickers are not cash-constrained",
            "No independent walk-forward or out-of-sample guarantee",
        ],
        "settings": {"years": years, "max_hold": max_hold,
                     "fee_each_side": fee_each_side, "ticker_count": len(history)},
        "results": {name: metrics(raw[name]) for name in STRATEGIES},
        "trades": events,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=int, default=100)
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--output", type=Path, default=OUTPUT)
    args = ap.parse_args()
    if args.tickers < 1 or args.years < 1:
        ap.error("--tickers and --years must be positive")
    cfg, _ = config.merge_settings({})
    listing, _ = universe.load_universe(cfg, include_etf=False)
    listing = listing.assign(
        dv=listing["price"].fillna(0)*listing["volume"].fillna(0)
    ).sort_values("dv", ascending=False).head(args.tickers)
    tickers = list(listing["yf_ticker"])
    hist = prices.download_history(["SPY"] + tickers, period=f"{args.years + 2}y")
    spy = hist.pop("SPY", None)
    if spy is None or len(spy) < MIN_HISTORY:
        raise SystemExit("Missing adequate SPY history; not generating results")
    result = compare(hist, spy, cfg, years=args.years)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["results"], ensure_ascii=False, indent=2))
    print(f"Saved research-only report: {args.output}")


if __name__ == "__main__":
    main()
