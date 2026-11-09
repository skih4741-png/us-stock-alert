"""Run three research portfolios on historical Yahoo daily data.

Output is research evidence only; today-selected ticker universe is biased.
"""
import argparse
import json
from pathlib import Path

import config
import prices
import universe
from validation.portfolio import simulate_portfolio
from validation.compare_strategies import STRATEGIES


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", type=int, default=30)
    p.add_argument("--years", type=int, default=2)
    p.add_argument("--output", type=Path, default=Path("data/portfolio_comparison.json"))
    args = p.parse_args()
    cfg, _ = config.merge_settings({})
    u, _ = universe.load_universe(cfg, include_etf=False)
    u = u.assign(dv=u["price"].fillna(0) * u["volume"].fillna(0))
    names = list(u.sort_values("dv", ascending=False).head(args.tickers)["yf_ticker"])
    history = prices.download_history(["SPY"] + names, period=f"{args.years+2}y")
    spy = history.pop("SPY", None)
    if spy is None or len(spy) < 260:
        raise SystemExit("SPY history unavailable. No statistics produced.")
    results = {name: simulate_portfolio(history, spy, name, cfg, years=args.years)
               for name in STRATEGIES}
    report = {
        "source": "Yahoo Finance via yfinance (as served at execution time)",
        "universe": "current top dollar-volume listed shares: SURVIVORSHIP BIAS",
        "verified_oos": False,
        "settings": {"tickers_requested": len(names), "tickers_received": len(history),
                     "years": args.years, "cost_each_side": 0.0035,
                     "starting_cash": 10000, "max_positions": 5},
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k:v["metrics"] for k,v in results.items()}, indent=2))
    print("Wrote:", args.output)


if __name__ == "__main__":
    main()
