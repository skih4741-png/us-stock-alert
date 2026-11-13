"""종목 하나의 기술지표 + 리스크 수치 — 블루프린트 STEP 02(기술/리스크) 구현.

가격 이력(OHLCV, 1년)으로 계산해요. 투자 권유 아님, 관찰·참고용.
 기술: 이동평균(20/60) · RSI(14) · MACD · 볼린저밴드 · 스토캐스틱 → 메인 신호(매수/중립/매도)
 리스크: 변동성(연율, 30일) · VaR(95%, 1일) · 최대낙폭(MDD, 1년) · 베타(vs SPY)
RSI·MACD는 scoring.py의 것을 재사용(한 곳에서만 계산).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

import scoring  # rsi(), macd() 재사용


def _f(x):
    try:
        v = float(x)
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 4)
    except (TypeError, ValueError):
        return None


def _last(s: pd.Series):
    s = s.dropna()
    return _f(s.iloc[-1]) if len(s) else None


def bollinger(c: pd.Series, n: int = 20, k: float = 2.0) -> dict:
    mid = c.rolling(n).mean()
    sd = c.rolling(n).std()
    up, low = mid + k * sd, mid - k * sd
    last_c, last_up, last_low = _last(c), _last(up), _last(low)
    pctb = None
    if None not in (last_c, last_up, last_low) and last_up != last_low:
        pctb = round((last_c - last_low) / (last_up - last_low), 2)   # 0=하단,1=상단
    return {"mid": _last(mid), "up": last_up, "low": last_low, "pctb": pctb}


def stochastic(df: pd.DataFrame, n: int = 14, d: int = 3) -> dict:
    low_n = df["Low"].rolling(n).min()
    high_n = df["High"].rolling(n).max()
    rng = (high_n - low_n).replace(0, np.nan)
    k = 100 * (df["Close"] - low_n) / rng
    return {"k": _last(k), "d": _last(k.rolling(d).mean())}


def risk_metrics(c: pd.Series, spy: pd.Series | None) -> dict:
    """변동성(연율)·VaR(95%,1일)·MDD·베타. 1년 일간 수익률 기준."""
    ret = c.pct_change().dropna()
    out = {"vol30": None, "var95": None, "mdd": None, "beta": None}
    if len(ret) >= 20:
        out["vol30"] = _f(ret.tail(30).std() * math.sqrt(252) * 100)      # 연율 %
        out["var95"] = _f(np.percentile(ret.tail(252), 5) * 100)          # 1일 5% 분위 %
    if len(c) >= 20:
        roll_max = c.cummax()
        out["mdd"] = _f(((c / roll_max) - 1.0).min() * 100)               # 최대낙폭 %
    if spy is not None:
        j = pd.concat([ret, spy.pct_change()], axis=1, join="inner").dropna()
        if len(j) >= 30:
            cov = j.iloc[:, 0].cov(j.iloc[:, 1])
            var = j.iloc[:, 1].var()
            out["beta"] = _f(cov / var) if var else None
    return out


def _main_signal(c, ma20, ma60, r, macd_line, macd_sig) -> str:
    """이동평균·RSI·MACD를 모아 한 단어로. 과하게 단정하지 않아요(관찰용)."""
    score = 0
    if None not in (ma20, ma60):
        score += 1 if ma20 > ma60 else -1
    if c is not None and ma20 is not None:
        score += 1 if c > ma20 else -1
    if None not in (macd_line, macd_sig):
        score += 1 if macd_line > macd_sig else -1
    if r is not None:
        if r >= 70:
            score -= 1   # 과매수
        elif r <= 30:
            score += 1   # 과매도
    return "매수" if score >= 2 else "매도" if score <= -2 else "중립"


def analyze(df: pd.DataFrame | None, spy: pd.Series | None = None) -> dict | None:
    """한 종목 OHLCV(1년)로 기술지표+리스크. 자료가 너무 짧으면 None."""
    if df is None or "Close" not in getattr(df, "columns", []):
        return None
    c = df["Close"].dropna()
    if len(c) < 30:
        return None
    ma20, ma60 = _last(c.rolling(20).mean()), _last(c.rolling(60).mean())
    r = _last(scoring.rsi(c))
    line, sig = scoring.macd(c)
    ml, ms = _last(line), _last(sig)
    boll = bollinger(c)
    stoch = stochastic(df) if {"High", "Low"} <= set(df.columns) else {"k": None, "d": None}
    price = _last(c)
    return {
        "price": price, "ma20": ma20, "ma60": ma60, "rsi14": r,
        "macd": ml, "macd_signal": ms,
        "macd_hist": (round(ml - ms, 4) if None not in (ml, ms) else None),
        "boll": boll, "stoch": stoch,
        "main_signal": _main_signal(price, ma20, ma60, r, ml, ms),
        "risk": risk_metrics(c, spy),
    }
