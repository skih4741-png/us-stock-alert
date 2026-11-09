"""Fail-closed strategy selection based on disjoint evaluation windows.

Research-only recommendations. No automatic deployment, order placement or
modification of production signal thresholds. Feed independently verified
walk-forward records, not in-sample results or current biased portfolio reports.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class Gate:
    min_trades: int = 100
    min_profit_factor: float = 1.3
    max_drawdown_pct: float = -15.0
    min_excess_pct: float = 0.0


def assess_strategy(report: Mapping, *, independent_oos: bool,
                    verified_universe: bool, gate: Gate = Gate()) -> dict:
    """Fail closed whenever evidence is missing, ambiguous or overfitted."""
    reasons = []
    if not independent_oos:
        reasons.append("독립 OOS 검증 미확인")
    if not verified_universe:
        reasons.append("과거 상장폐지 포함 유니버스 미확인")
    def number(key):
        try:
            val = float(report[key])
            return val if val == val and abs(val) != float("inf") else None
        except (KeyError, TypeError, ValueError, OverflowError):
            return None
    trades = number("closed_trades")
    pf = number("profit_factor")
    mdd = number("mdd_pct")
    excess = number("excess_return_pct")
    if trades is None or trades < gate.min_trades:
        reasons.append("거래 표본 부족")
    if pf is None or pf < gate.min_profit_factor:
        reasons.append("Profit Factor 기준 미달")
    if mdd is None or mdd < gate.max_drawdown_pct:
        reasons.append("MDD 한도 위반 또는 데이터 없음")
    if excess is None or excess <= gate.min_excess_pct:
        reasons.append("SPY 대비 초과수익 미확인")
    return {"eligible": not reasons, "reasons": reasons,
            "action": "review_for_paper_only" if not reasons else "observe_only"}


def rank_candidates(reports: Mapping[str, Mapping], *,
                    independent_oos: bool = False,
                    verified_universe: bool = False) -> dict:
    """Never auto-promote into live signals. Expose diagnostics for future review."""
    return {name: assess_strategy(report, independent_oos=independent_oos,
                                  verified_universe=verified_universe)
            for name, report in reports.items()}
