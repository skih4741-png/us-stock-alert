"""Run three research portfolios on historical Yahoo daily data.

Output is research evidence only; today-selected ticker universe is biased.
"""
import argparse
import json
from pathlib import Path

import config
import prices
import universe
from validation.data_quality import clean_history
from validation.historical_universe import read_membership_csv
from validation.diagnostics import trade_attribution, cost_sensitivity
from validation.portfolio import simulate_portfolio
from validation.compare_strategies import STRATEGIES


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tickers", type=int, default=30)
    p.add_argument("--years", type=int, default=2)
    p.add_argument("--universe-csv", type=Path, default=None,
                   help="Historical membership ticker,start_date,end_date; requires separately verified price coverage")
    p.add_argument("--output", type=Path, default=Path("data/portfolio_comparison.json"))
    args = p.parse_args()
    cfg, _ = config.merge_settings({})
    u, _ = universe.load_universe(cfg, include_etf=False)
    u = u.assign(dv=u["price"].fillna(0) * u["volume"].fillna(0))
    names = list(u.sort_values("dv", ascending=False).head(args.tickers)["yf_ticker"])
    membership = read_membership_csv(args.universe_csv) if args.universe_csv else None
    if membership is not None:
        names = membership.tickers
    history = prices.download_history(["SPY"] + names, period=("5y" if args.years <= 3 else "10y" if args.years <= 8 else "max"))
    history, rejected = clean_history(history, min_bars=260)
    spy = history.pop("SPY", None)
    if spy is None or len(spy) < 260:
        raise SystemExit("SPY history unavailable. No statistics produced.")
    results = {name: simulate_portfolio(history, spy, name, cfg, years=args.years, membership=membership)
               for name in STRATEGIES}
    # Trading costs can dominate apparent edge. Run stress scenarios independently.
    cost_stress = {
        str(mult): {
            name: simulate_portfolio(history, spy, name, cfg, years=args.years,
                                     fee=0.0035 * mult, membership=membership)["metrics"]
            for name in STRATEGIES
        }
        for mult in (1.5, 2.0)
    }
    report = {
        "source": "Yahoo Finance via yfinance (as served at execution time)",
        "universe": "current top dollar-volume listed shares: SURVIVORSHIP BIAS",
        "verified_oos": False,
        "membership_csv_used": membership is not None,
        "missing_price_history": sorted(set(names) - set(history)),
        "historical_universe_verified": False,
        "settings": {"tickers_requested": len(names), "tickers_received": len(history), "data_rejected": rejected,
                     "years": args.years, "cost_each_side": 0.0035,
                     "starting_cash": 10000, "max_positions": 5},
        "results": results,
        "cost_stress": cost_stress,
        "cost_sensitivity": cost_sensitivity(results, cost_stress),
        "trade_attribution": {name: trade_attribution(p["closed"]) for name, p in results.items()},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k:v["metrics"] for k,v in results.items()}, indent=2))
    print("Wrote:", args.output)


if __name__ == "__main__":
    main()
