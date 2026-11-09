"""Minimum OHLCV data-integrity checks for research inputs."""
from __future__ import annotations

import numpy as np
import pandas as pd

REQUIRED = ("Open", "High", "Low", "Close", "Volume")


def validate_bars(df: pd.DataFrame, min_bars: int = 260) -> list[str]:
    problems = []
    if df is None or len(df) < min_bars:
        problems.append("insufficient_bars")
        return problems
    if any(k not in df.columns for k in REQUIRED):
        problems.append("missing_ohlcv_columns")
        return problems
    if not df.index.is_monotonic_increasing or df.index.has_duplicates:
        problems.append("unsorted_or_duplicate_dates")
    ohlc = df[list(REQUIRED[:4])].apply(pd.to_numeric, errors="coerce")
    if not np.isfinite(ohlc.to_numpy(dtype=float)).all():
        problems.append("nonfinite_price")
    if (ohlc <= 0).any().any():
        problems.append("nonpositive_price")
    if (ohlc["High"] < ohlc[["Open", "Close", "Low"]].max(axis=1)).any():
        problems.append("invalid_high")
    if (ohlc["Low"] > ohlc[["Open", "Close", "High"]].min(axis=1)).any():
        problems.append("invalid_low")
    vol = pd.to_numeric(df["Volume"], errors="coerce")
    if not np.isfinite(vol.to_numpy(dtype=float)).all() or (vol < 0).any():
        problems.append("invalid_volume")
    return problems


def clean_history(history: dict[str, pd.DataFrame], min_bars: int = 260):
    valid, rejected = {}, {}
    for ticker, bars in history.items():
        problems = validate_bars(bars, min_bars)
        if problems:
            rejected[ticker] = problems
        else:
            valid[ticker] = bars
    return valid, rejected
