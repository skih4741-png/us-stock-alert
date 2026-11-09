"""Research portfolio: chronological daily equity accounting with common fills.

CAUTION: Current-active-ticker universe is survivorship-biased. Signals use
daily-close information and enter no earlier than the next session. Intrabar
stops take priority over targets, in both research and paper simulation.
"""
from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np
import pandas as pd

import backtest
import execution_rules
import market
from validation.compare_strategies import signals, STRATEGIES, COST_EACH_SIDE


@dataclass
class Position:
    ticker: str
    qty: int
    entry: float
    stop: float
    target: float
    entry_idx: int
    peak: float
    half: bool = False
    realized: float = 0.0


def _risk_metrics(equity: list[dict], spy: pd.DataFrame, initial_cash: float,
                  closed: list[dict]) -> dict:
    if not equity:
        return {"trades": 0}
    v = np.array([x["equity"] for x in equity], dtype=float)
    daily = pd.Series(v).pct_change().dropna()
    years = max((pd.Timestamp(equity[-1]["date"]) - pd.Timestamp(equity[0]["date"])).days / 365.25, 1 / 365.25)
    peak = np.maximum.accumulate(np.r_[initial_cash, v])
    drawdown = v / peak[1:] - 1.0
    spy_ix = pd.DatetimeIndex([x["date"] for x in equity])
    spy_close = spy["Close"].copy()
    spy_close.index = pd.to_datetime(spy_close.index).tz_localize(None)
    matched = spy_close.reindex(spy_ix).ffill().dropna()
    spy_return = float(matched.iloc[-1] / matched.iloc[0] - 1) if len(matched) >= 2 else None
    rets = [x["pnl"] for x in closed]
    wins = sum(x for x in rets if x > 0)
    losses = -sum(x for x in rets if x < 0)
    return {
        "starting_cash": initial_cash,
        "ending_equity": round(float(v[-1]), 2),
        "total_return_pct": round(float((v[-1] / initial_cash - 1) * 100), 2),
        "cagr_pct": round(float(((v[-1] / initial_cash) ** (1 / years) - 1) * 100), 2),
        "mdd_pct": round(float(np.min(drawdown) * 100), 2),
        "sharpe": round(float(daily.mean() / daily.std(ddof=1) * np.sqrt(252)), 2) if len(daily) > 2 and daily.std(ddof=1) > 0 else None,
        "spy_return_pct": round(spy_return * 100, 2) if spy_return is not None else None,
        "excess_return_pct": round(float((v[-1] / initial_cash - 1 - spy_return) * 100), 2) if spy_return is not None else None,
        "closed_trades": len(closed),
        "win_rate_pct": round(sum(x > 0 for x in rets) / len(rets) * 100, 2) if rets else None,
        "profit_factor": round(wins / losses, 3) if losses > 0 else None,
    }


def simulate_portfolio(history: dict[str, pd.DataFrame], spy: pd.DataFrame,
                       strategy: str, cfg: dict, *, years: int = 3,
                       initial_cash: float = 10000.0, max_positions: int = 5,
                       risk_fraction: float = 0.01, max_weight: float = 0.25,
                       max_hold: int = 20, fee: float = COST_EACH_SIDE,
                       start_date: str | None = None, end_date: str | None = None) -> dict:
    """Full daily mark-to-market with finite cash and integer shares."""
    if strategy not in STRATEGIES:
        raise ValueError("unknown strategy")
    if initial_cash <= 0 or not 0 < risk_fraction <= 1 or not 0 < max_weight <= 1:
        raise ValueError("invalid risk parameters")
    spy = spy.copy()
    spy.index = pd.to_datetime(spy.index).tz_localize(None)
    window_start = pd.Timestamp(start_date) if start_date else spy.index[-1] - pd.DateOffset(years=years)
    window_end = pd.Timestamp(end_date) if end_date else spy.index[-1]
    dates = spy.index[(spy.index >= window_start) & (spy.index <= window_end)]
    if len(dates) == 0:
        raise ValueError("empty portfolio window")
    regimes = market.regime_series(spy)
    prepared = {}
    for ticker, df in history.items():
        if len(df) < 260:
            continue
        df = df.copy()
        df.index = pd.to_datetime(df.index).tz_localize(None)
        o = backtest.indicator_frame(df)
        prepared[ticker] = (o, signals(o)[strategy].shift(1).fillna(False))
    cash = float(initial_cash)
    positions: dict[str, Position] = {}
    equity, closed = [], []
    last_prices: dict[str, float] = {}
    for day in dates:
        # Freeze prior-session capital and position slots for this day's opens.
        # Intraday exits must not retroactively finance an opening fill.
        order_nav = float(equity[-1]["equity"]) if equity else initial_cash
        entry_cash_budget = cash
        remaining_new_slots = max_positions - len(positions)
        exited_today: set[str] = set()
        # On each day execute exits from available day's OHLC.
        for ticker, p in list(positions.items()):
            o, _ = prepared[ticker]
            if day not in o.index:
                continue
            row = o.loc[day]
            op, hi, lo, cl = (float(row[k]) for k in ("open", "high", "low", "close"))
            last_prices[ticker] = cl
            d = execution_rules.exit_fill(op, hi, lo, p.stop, p.target,
                                          half=p.half, slip=0.0015)
            if d is not None:
                if d.reason == "stop":
                    cash += p.qty * d.price * (1 - fee)
                    closed.append({"ticker": ticker, "date": day.strftime("%Y-%m-%d"),
                                   "pnl": p.realized + p.qty * (d.price * (1-fee) - p.entry * (1+fee))})
                    del positions[ticker]
                    exited_today.add(ticker)
                    continue
                if p.qty >= 2:
                    sold = p.qty // 2
                    cash += sold * d.price * (1-fee)
                    p.realized += sold * (d.price * (1-fee) - p.entry * (1+fee))
                    p.qty -= sold
                    p.half, p.stop = True, p.entry
                else:
                    cash += p.qty * d.price * (1-fee)
                    closed.append({"ticker": ticker, "date": day.strftime("%Y-%m-%d"),
                                   "pnl": p.realized + p.qty * (d.price * (1-fee) - p.entry * (1+fee))})
                    del positions[ticker]
                    continue
            p.peak = max(p.peak, cl)
            age = int(o.index.get_loc(day)) - p.entry_idx
            trailing = p.half and (cl < p.peak * 0.92 or cl < float(row["ma20"]))
            if trailing or age >= max_hold:
                px = cl * (1 - 0.0015)
                cash += p.qty * px * (1-fee)
                closed.append({"ticker": ticker, "date": day.strftime("%Y-%m-%d"),
                               "pnl": p.realized + p.qty * (px * (1-fee) - p.entry * (1+fee))})
                del positions[ticker]
                exited_today.add(ticker)
        # New positions use yesterday's confirmed signal, never same day's close.
        if regimes.loc[day] != "bear":
            for ticker in sorted(prepared):
                if ticker in positions or ticker in exited_today or remaining_new_slots <= 0:
                    continue
                o, pending = prepared[ticker]
                if day not in o.index or not bool(pending.loc[day]):
                    continue
                pos_idx = int(o.index.get_loc(day))
                if pos_idx < 1:
                    continue
                prev, row = o.iloc[pos_idx-1], o.iloc[pos_idx]
                if not (np.isfinite(prev.ma50) and np.isfinite(prev.low20)):
                    continue
                close = float(prev.close)
                stop = max(float(prev.ma50), float(prev.low20), close * (1 - float(cfg["최대 손실(%)"]) / 100))
                if stop > close * (1-float(cfg["최소 위험폭(%)"])/100):
                    stop = close * 0.97
                limit = close * 1.01
                skip = limit * (1 + float(cfg["추격 금지 기준(%)"]) / 100)
                fill = execution_rules.entry_fill(float(row.open), float(row.low), limit, skip, stop)
                if fill is None:
                    continue
                entry = fill.price
                rr = float(cfg["상승장 손익비"] if regimes.loc[day] == "bull" else cfg["횡보장 손익비"])
                target = close + (close-stop) * rr
                if target <= entry:
                    continue
                nav = order_nav
                unit_risk = (entry-stop) + (entry+stop)*fee
                qty = math.floor(min(nav*risk_fraction/max(unit_risk, .01),
                                     nav*max_weight/entry, entry_cash_budget/(entry*(1+fee))))
                if qty < 1:
                    continue
                cash -= qty*entry*(1+fee)
                entry_cash_budget -= qty*entry*(1+fee)
                remaining_new_slots -= 1
                p = Position(ticker, qty, entry, stop, target, pos_idx, entry)
                # Conservative same-bar stop, consistent with live paper policy.
                same_bar = execution_rules.exit_fill(float(row.open), float(row.high), float(row.low),
                                                     stop, target, fresh=True)
                if same_bar is not None and same_bar.reason == "stop":
                    cash += qty*same_bar.price*(1-fee)
                    closed.append({"ticker":ticker,"date":day.strftime("%Y-%m-%d"),
                                   "pnl":qty*(same_bar.price*(1-fee)-entry*(1+fee))})
                else:
                    positions[ticker] = p
                    last_prices[ticker] = float(row.close)
        nav = cash + sum(p.qty*last_prices.get(t,p.entry) for t,p in positions.items())
        equity.append({"date":day.strftime("%Y-%m-%d"),"equity":round(nav,4),
                       "cash":round(cash,4),"positions":len(positions)})
    return {"strategy":strategy,
            "metrics":_risk_metrics(equity,spy,initial_cash,closed),
            "equity":equity,"closed":closed,
            "limitations":["Current listed-universe survivorship bias",
                           "OHLC intrabar order ambiguity; pessimistic convention",
                           "Daily close trailing exits, not same-day stop orders",
                           "Daily SPY benchmark without distributions/cost parity",
                           "No point-in-time corporate fundamentals or delisted equities"]}
