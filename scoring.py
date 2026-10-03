"""F-04 추세 점수 · F-05 재무 점수 · F-06 판정 · F-23 급등 거름망.

점수 4개(추세·가치·성장·안전)는 각 25점, 합계 100점.
자료가 없는 항목은 0점이 아니라 빼고 100점으로 환산해요.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd


# ---------- 지표 ----------

def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def macd(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    line = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    sig = line.ewm(span=9, adjust=False).mean()
    return line, sig


def technicals(df: pd.DataFrame, spy_ret63: float | None) -> dict | None:
    """한 종목의 추세·안전 관련 숫자. 자료가 짧으면 None."""
    c, v = df["Close"], df["Volume"]
    if len(c) < 210:
        return None
    ma20, ma50, ma200 = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    line, sig = macd(c)
    cross_up = (line > sig) & (line.shift(1) <= sig.shift(1))
    cross_dn = (line < sig) & (line.shift(1) >= sig.shift(1))
    r = rsi(c)
    vol20 = v.rolling(20).mean()
    rets = c.pct_change()
    close = float(c.iloc[-1])
    high252 = float(c.iloc[-252:].max())
    t = {
        "close": close,
        "ma20": float(ma20.iloc[-1]), "ma50": float(ma50.iloc[-1]), "ma200": float(ma200.iloc[-1]),
        "low20": float(df["Low"].iloc[-20:].min()),
        "rsi": float(r.iloc[-1]) if not math.isnan(r.iloc[-1]) else None,
        "macd_cross_up_10d": bool(cross_up.iloc[-10:].any()),
        "macd_cross_dn_10d": bool(cross_dn.iloc[-10:].any()),
        "macd_above": bool(line.iloc[-1] > sig.iloc[-1]),
        "vol_ratio": float(v.iloc[-1] / vol20.iloc[-1]) if vol20.iloc[-1] else None,
        "dollar_vol20": float((c * v).iloc[-20:].mean()),
        "ret63": float(c.iloc[-1] / c.iloc[-64] - 1) if len(c) > 64 else None,
        "ret5": float(c.iloc[-1] / c.iloc[-6] - 1) if len(c) > 6 else None,
        "vol60": float(rets.iloc[-60:].std() * math.sqrt(252)),
        "drawdown": close / high252 - 1,
        "days": len(c),
    }
    t["beats_spy"] = (t["ret63"] is not None and spy_ret63 is not None and t["ret63"] > spy_ret63)
    return t


# ---------- 점수 ----------

def _pct_rank(values: pd.Series, x, higher_better: bool) -> float | None:
    """같은 업종 안에서 상위 몇 %인지 (0=가장 좋음, 1=가장 나쁨)."""
    s = values.dropna()
    if x is None or (isinstance(x, float) and math.isnan(x)) or len(s) < 5:
        return None
    better = (s > x).mean() if higher_better else (s < x).mean()
    return float(better)


def _band(rank: float | None, full: float, cut_full: float, cut_half: float, half: float) -> float | None:
    if rank is None:
        return None
    if rank <= cut_full:
        return full
    if rank <= cut_half:
        return half
    return 0.0


def score_trend(t: dict, rs_pct: float | None) -> tuple[dict, dict]:
    pts, maxes = {}, {}
    full_align = t["ma20"] > t["ma50"] > t["ma200"]
    some_align = (t["ma20"] > t["ma50"]) or (t["ma50"] > t["ma200"])
    pts["align"], maxes["align"] = (7 if full_align else 3 if some_align else 0), 7
    pts["above200"], maxes["above200"] = (3 if t["close"] > t["ma200"] else 0), 3
    pts["macd"], maxes["macd"] = (5 if t["macd_cross_up_10d"] else 2 if t["macd_above"] else 0), 5
    if t["ret63"] is not None:
        top30 = rs_pct is not None and rs_pct <= 0.30
        pts["rs"] = 4 if (t["beats_spy"] and top30) else 2 if t["beats_spy"] else 0
        maxes["rs"] = 4
    if t["rsi"] is not None:
        pts["rsi"] = 3 if 40 <= t["rsi"] <= 70 else 1 if 70 < t["rsi"] <= 75 else 0
        maxes["rsi"] = 3
    if t["vol_ratio"] is not None:
        pts["volume"] = 3 if t["vol_ratio"] >= 1.5 else 1 if t["vol_ratio"] >= 1.2 else 0
        maxes["volume"] = 3
    return pts, maxes


def score_value_growth(f: dict, peers: pd.DataFrame) -> tuple[dict, dict, dict, dict, list[str]]:
    vp, vm, gp, gm, flags = {}, {}, {}, {}, []
    per = f.get("per")
    if per is not None and per <= 0:
        vp["per"], vm["per"] = 0, 10
        flags.append("적자")
    else:
        r = _pct_rank(peers["per"][peers["per"] > 0], per, higher_better=False) if "per" in peers else None
        b = _band(r, 10, 0.2, 0.4, 5)
        if b is not None:
            vp["per"], vm["per"] = b, 10
    pbr = f.get("pbr")
    if pbr is not None and pbr > 0:
        b = _band(_pct_rank(peers["pbr"][peers["pbr"] > 0], pbr, False), 5, 0.2, 0.4, 2)
        if b is not None:
            vp["pbr"], vm["pbr"] = b, 5
    fy = f.get("fcf_yield")
    if fy is not None:
        b = _band(_pct_rank(peers["fcf_yield"], fy, True), 10, 0.2, 0.4, 5)
        if b is not None:
            vp["fcf"], vm["fcf"] = (b if fy > 0 else 0), 10
    rg = f.get("rev_growth")
    if rg is not None:
        gp["rev"], gm["rev"] = (8 if rg >= 0.15 else 4 if rg >= 0.05 else 0), 8
    eg = f.get("earn_growth")
    if eg is not None:
        gp["earn"], gm["earn"] = (8 if eg >= 0.15 else 4 if eg >= 0.05 else 0), 8
    roe = f.get("roe")
    if roe is not None:
        gp["roe"], gm["roe"] = (9 if roe >= 0.15 else 4 if roe >= 0.08 else 0), 9
    return vp, vm, gp, gm, flags


def score_safety(t: dict, f: dict | None, peers: pd.DataFrame | None, market_vol: float) -> tuple[dict, dict]:
    pts, maxes = {}, {}
    if f and f.get("debt_to_equity") is not None and peers is not None and "debt_to_equity" in peers:
        b = _band(_pct_rank(peers["debt_to_equity"], f["debt_to_equity"], False), 8, 0.3, 0.6, 4)
        if b is not None:
            pts["debt"], maxes["debt"] = b, 8
    pts["vol"] = 8 if t["vol60"] <= market_vol else 4 if t["vol60"] <= market_vol * 1.5 else 0
    maxes["vol"] = 8
    dd = t["drawdown"]
    pts["dd"] = 9 if dd >= -0.15 else 4 if dd >= -0.25 else 0
    maxes["dd"] = 9
    return pts, maxes


def _scale(p: dict, m: dict) -> float | None:
    tot = sum(m.values())
    return None if tot == 0 else sum(p.values()) / tot * 25


def combine(t: dict, f: dict | None, peers: pd.DataFrame | None, rs_pct: float | None, market_vol: float, is_etf: bool) -> dict:
    tp, tm = score_trend(t, rs_pct)
    vp = vm = gp = gm = {}
    flags: list[str] = []
    if f and not is_etf and peers is not None:
        vp, vm, gp, gm, flags = score_value_growth(f, peers)
    sp, sm = score_safety(t, None if is_etf else f, peers, market_vol)
    cats = {"추세": _scale(tp, tm), "가치": _scale(vp, vm), "성장": _scale(gp, gm), "안전": _scale(sp, sm)}
    all_p = {**tp, **vp, **gp, **sp}
    all_m = {**tm, **vm, **gm, **sm}
    total = sum(all_p.values()) / sum(all_m.values()) * 100 if all_m else 0
    # 이유 3가지 = 만점 비율이 가장 높은 항목
    ratios = sorted(((all_p[k] / all_m[k], all_m[k], k) for k in all_p if all_m[k] and all_p[k] > 0), reverse=True)
    reasons = [k for _, _, k in ratios[:3]]
    return {"total": round(total, 1), "cats": {k: (None if v is None else round(v, 1)) for k, v in cats.items()},
            "reasons": reasons, "flags": flags}


# ---------- 판정 ----------

def trend_conditions(t: dict) -> int:
    return sum([t["ma20"] > t["ma50"] > t["ma200"], t["macd_cross_up_10d"], (t["vol_ratio"] or 0) >= 1.5])


def down_conditions(t: dict) -> int:
    return sum([t["ma20"] < t["ma50"] < t["ma200"], t["macd_cross_dn_10d"], t["close"] < t["ma200"]])


def verdict(t: dict, sc: dict, mk: dict, cfg: dict, is_etf: bool) -> tuple[str, str]:
    """반환: (판정, 탈락 이유 또는 빈 문자열)."""
    surge = (t["ret5"] or 0) * 100 > float(cfg["급등 기준(5일 상승률 %)"])
    total = sc["total"]
    cats = sc["cats"]
    pass_min = float(cfg["점수별 최소 통과 점수"])
    if total <= float(cfg["피해야 할 종목 최대 점수"]) and down_conditions(t) >= 2:
        return "avoid", ""
    if surge:
        return "surge", "급등 · 추격 주의"
    if total < mk["threshold"]:
        return "hold", ""
    if trend_conditions(t) < 2:
        return "hold", "추세 조건 부족"
    safety_ok = (cats["안전"] or 0) >= pass_min
    if is_etf:
        ok = safety_ok and (cats["추세"] or 0) >= pass_min
    else:
        passed = sum(1 for v in cats.values() if v is not None and v >= pass_min)
        ok = safety_ok and passed >= 3
    if not ok:
        return "hold", "한 가지 장점뿐"
    return "buy", ""
