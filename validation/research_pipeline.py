"""One-shot reproducible research run using a shared, validated price snapshot.

Yahoo historical data is exploratory and the current listing universe has
survivorship bias; a successful download DOES NOT certify strategy profits.
A short or missing response fails the entire run, rather than silently
comparing different ticker universes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import config
import prices
import universe
from validation.data_quality import clean_history
from validation.diagnostics import trade_attribution, cost_sensitivity
from validation.compare_strategies import STRATEGIES, COST_EACH_SIDE
from validation.portfolio import simulate_portfolio
from validation.walk_forward import rolling_evaluation
from validation.historical_universe import read_membership_csv


def acquire(cfg: dict, tickers: int, years: int, universe_csv: Path | None):
    membership = read_membership_csv(universe_csv) if universe_csv else None
    if membership is not None:
        names = membership.tickers
    else:
        u, _ = universe.load_universe(cfg, include_etf=False)
        u = u.assign(dv=u["price"].fillna(0) * u["volume"].fillna(0))
        names = list(u.sort_values("dv", ascending=False).head(tickers)["yf_ticker"])
    if not names:
        raise ValueError("Empty research ticker selection")
    period = "5y" if years <= 3 else "10y" if years <= 8 else "max"
    history = prices.download_history(["SPY"] + names, period=period, fallback=True)
    history, rejected = clean_history(history, min_bars=260)
    spy = history.pop("SPY", None)
    missing = sorted(set(names) - set(history))
    if spy is None or missing or rejected:
        raise ValueError(f"Data coverage incomplete: missing={missing}, rejected={rejected}, SPY={spy is not None}")
    digest = hashlib.sha256()
    for ticker in sorted(history):
        digest.update(ticker.encode())
        digest.update(history[ticker].to_csv().encode())
    digest.update(spy.to_csv().encode())
    return history, spy, membership, {
        "source": "Yahoo Finance via yfinance",
        "selected_tickers": names,
        "downloaded_tickers": len(history),
        "price_snapshot_sha256": digest.hexdigest(),
        "historical_universe_verified": False,
        "coverage_complete_for_requested_tickers": True,
        "membership_csv_used": membership is not None,
        "limitations": [
            "Current listed ticker selection has survivorship bias when no as-of membership is supplied",
            "A supplied membership CSV does not establish delisted-price coverage or source reliability",
            "Adjusted close bars and daily OHLC fills are not independent execution records",
        ],
    }


def build_reports(history, spy, cfg, membership, meta, *, years, folds, fold_months):
    portfolios = {name: simulate_portfolio(history, spy, name, cfg,
                                           years=years, membership=membership)
                  for name in STRATEGIES}
    stress = {str(x): {name: simulate_portfolio(history, spy, name, cfg, years=years,
                                                fee=COST_EACH_SIDE*x,
                                                membership=membership)["metrics"]
                        for name in STRATEGIES}
              for x in (1.5, 2.0)}
    portfolio_report = {
        "meta": meta,
        "verified_oos": False,
        "starting_cash": 10000,
        "cost_each_side": COST_EACH_SIDE,
        "strategies": portfolios,
        "trade_attribution": {name: trade_attribution(p["closed"])
                              for name, p in portfolios.items()},
        "cost_stress": cost_sensitivity(portfolios, stress),
    }
    rolling = rolling_evaluation(history, spy, cfg, folds=folds,
                                 fold_months=fold_months, membership=membership)
    rolling["meta"] = meta
    return portfolio_report, rolling


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", type=int, default=20)
    p.add_argument("--years", type=int, default=2)
    p.add_argument("--folds", type=int, default=3)
    p.add_argument("--months", type=int, default=12)
    p.add_argument("--universe-csv", type=Path, default=None)
    p.add_argument("--output-dir", type=Path, default=Path("data"))
    args = p.parse_args()
    if min(args.tickers, args.years, args.folds, args.months) < 1:
        p.error("all integer arguments must be positive")
    cfg, _ = config.merge_settings({})
    history, spy, membership, meta = acquire(cfg, args.tickers, max(args.years,
                                                   args.folds*args.months//12), args.universe_csv)
    portfolio, rolling = build_reports(history, spy, cfg, membership, meta,
                                       years=args.years, folds=args.folds,
                                       fold_months=args.months)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir/"portfolio_comparison.json").write_text(
        json.dumps(portfolio, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.output_dir/"rolling_comparison.json").write_text(
        json.dumps(rolling, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k:v["metrics"] for k,v in portfolio["strategies"].items()},
                     ensure_ascii=False, indent=2))
    print("Rolling summary:", json.dumps(rolling["summary"], ensure_ascii=False))
    print("Approval:", json.dumps(rolling["promotion_gate"], ensure_ascii=False))
    print("Snapshot SHA256:", meta["price_snapshot_sha256"])


if __name__ == "__main__":
    main()
