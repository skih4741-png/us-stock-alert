"""F-20 시장 국면 판정: 상승장 · 횡보장 · 하락장 + 매수 쉬는 날."""
from __future__ import annotations

import pandas as pd


def raw_regime(spy: pd.DataFrame, upto: int | None = None) -> str:
    c = spy["Close"] if upto is None else spy["Close"].iloc[: upto + 1]
    if len(c) < 200:
        return "sideways"
    ma50 = c.rolling(50).mean().iloc[-1]
    ma200 = c.rolling(200).mean().iloc[-1]
    above = c.iloc[-1] > ma200
    golden = ma50 > ma200
    if above and golden:
        return "bull"
    if (not above) and (not golden):
        return "bear"
    return "sideways"


def regime_series(spy: pd.DataFrame) -> pd.Series:
    """날짜별 국면 (이틀 연속 같아야 바뀜). 과거 검증에도 써요."""
    c = spy["Close"]
    ma50, ma200 = c.rolling(50).mean(), c.rolling(200).mean()
    raw = pd.Series("sideways", index=c.index)
    raw[(c > ma200) & (ma50 > ma200)] = "bull"
    raw[(c < ma200) & (ma50 < ma200)] = "bear"
    raw[ma200.isna()] = "sideways"
    out, cur = [], raw.iloc[0]
    for i in range(len(raw)):
        if i > 0 and raw.iloc[i] == raw.iloc[i - 1]:
            cur = raw.iloc[i]
        out.append(cur)
    return pd.Series(out, index=c.index)


def judge(spy: pd.DataFrame, vix: pd.DataFrame | None, cfg: dict) -> dict:
    regime = regime_series(spy).iloc[-1]
    c = spy["Close"]
    day_change = (c.iloc[-1] / c.iloc[-2] - 1) * 100 if len(c) > 1 else 0.0
    vix_last = float(vix["Close"].iloc[-1]) if vix is not None and len(vix) else None
    shaky = day_change <= float(cfg["흔들린 날 하락률(%)"]) or (vix_last is not None and vix_last >= float(cfg["공포 지수 기준"]))
    rest = regime == "bear" or shaky
    if regime == "bull":
        threshold, rr = cfg["상승장 매수 기준"], cfg["상승장 손익비"]
    elif regime == "sideways":
        threshold, rr = cfg["횡보장 매수 기준"], cfg["횡보장 손익비"]
    else:
        threshold, rr = cfg["하락장 참고 기준"], cfg["횡보장 손익비"]
    reason = ""
    if regime == "bear":
        reason = "시장이 하락장이라"
    elif shaky:
        parts = []
        if day_change <= float(cfg["흔들린 날 하락률(%)"]):
            parts.append(f"대표 지수가 하루 {day_change:.1f}% 내렸고")
        if vix_last is not None and vix_last >= float(cfg["공포 지수 기준"]):
            parts.append(f"시장 공포 지수가 {vix_last:.0f}이라")
        reason = " ".join(parts)
    return {
        "regime": regime, "rest_day": bool(rest), "shaky": bool(shaky), "threshold": float(threshold),
        "rr": float(rr), "spy_change": round(day_change, 2), "vix": vix_last, "reason": reason,
        "first_buy_fraction": "1/3" if regime == "sideways" else "1/2",
    }
