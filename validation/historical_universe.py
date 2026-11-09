"""Explicit point-in-time universe membership contract.

This does NOT supply market data. The upstream provider must separately
prove historical listing completeness, delisted-security coverage and
availability of OHLCV on all eligible dates.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from pathlib import Path


@dataclass(frozen=True)
class Interval:
    start: date
    end: date | None


class HistoricalMembership:
    def __init__(self, intervals: dict[str, list[Interval]]):
        self.intervals = intervals

    def includes(self, ticker: str, asof: str | date) -> bool:
        day = date.fromisoformat(asof) if isinstance(asof, str) else asof
        return any(it.start <= day and (it.end is None or day <= it.end)
                   for it in self.intervals.get(ticker, []))

    @property
    def tickers(self) -> list[str]:
        return sorted(self.intervals)


def read_membership_csv(path: str | Path) -> HistoricalMembership:
    """Required CSV columns: ticker,start_date,end_date (blank end = active)."""
    path = Path(path)
    output: dict[str, list[Interval]] = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not {"ticker", "start_date", "end_date"} <= set(reader.fieldnames or []):
            raise ValueError("membership requires ticker,start_date,end_date")
        for line, row in enumerate(reader, 2):
            ticker = (row.get("ticker") or "").strip().upper()
            if not ticker:
                raise ValueError(f"empty ticker on line {line}")
            start = date.fromisoformat(row["start_date"])
            end = date.fromisoformat(row["end_date"]) if row.get("end_date") else None
            if end is not None and end < start:
                raise ValueError(f"end before start on line {line}")
            output.setdefault(ticker, []).append(Interval(start, end))
    if not output:
        raise ValueError("empty membership file")
    return HistoricalMembership(output)
