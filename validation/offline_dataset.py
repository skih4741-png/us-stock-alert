"""Offline point-in-time OHLCV loader for independently licensed historical bars.

Input layout:
  historical_data/
    membership.csv  (ticker,start_date,end_date)
    prices/
      AAPL.csv       (Date,Open,High,Low,Close,Volume)
      DELISTED.csv   (same schema, including records before delisting)

This does not certify an external vendor's accuracy, delisting completeness,
or corporate action methodology. Reject any absent series; never replace with
present-day survivor-only Yahoo prices.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from validation.historical_universe import read_membership_csv
from validation.data_quality import validate_bars


def read_historical_dataset(root: str | Path, min_bars: int = 260):
    root = Path(root)
    member = read_membership_csv(root / "membership.csv")
    bars = {}
    missing = []
    rejected = {}
    for ticker in ["SPY"] + [t for t in member.tickers if t != "SPY"]:
        # Disallow slash/path traversal in symbolic tickers.
        if not ticker or any(c not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-^_" for c in ticker):
            raise ValueError(f"unsupported ticker file name: {ticker!r}")
        file = root / "prices" / f"{ticker}.csv"
        if not file.is_file():
            missing.append(ticker)
            continue
        try:
            df = pd.read_csv(file, parse_dates=["Date"])
            if df["Date"].isna().any():
                raise ValueError("invalid date")
            df = df.set_index("Date")
            problems = validate_bars(df, min_bars=min_bars)
            if problems:
                rejected[ticker] = problems
                continue
            bars[ticker] = df[["Open", "High", "Low", "Close", "Volume"]]
        except (ValueError, KeyError, TypeError, OSError) as exc:
            rejected[ticker] = [str(exc)]
    if missing or rejected or len(bars) < 2:
        raise ValueError(f"incomplete historical dataset missing={missing} invalid={rejected}")
    spy = bars.pop("SPY")
    return bars, spy, member, {
        "source": f"offline_csv:{root.name}",
        "historical_universe_verified": False,
        "membership_csv_used": True,
        "missing_price_history": [],
        "note": "Input integrity checked, but provider survivorship/corporate-action evidence not authenticated",
    }
