"""F-19 매수 구간 · 손절 · 목표 · 매도 규칙."""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


def add_trading_days(d: date, n: int) -> date:
    return np.busday_offset(np.datetime64(d), n, roll="forward").astype(object)


def buy_plan(t: dict, rr: float, cfg: dict, signal_day: date) -> dict:
    close = t["close"]
    upper = close * 1.01
    lower = max(t["ma20"], close * 0.97)
    if lower > close:
        lower = close * 0.97
    stop = max(t["ma50"], t["low20"])
    max_loss = float(cfg["최대 손실(%)"]) / 100
    min_risk = float(cfg["최소 위험폭(%)"]) / 100
    if stop < close * (1 - max_loss):
        stop = close * (1 - max_loss)
    if stop > close * (1 - min_risk):
        stop = close * (1 - max(min_risk, 0.03))
    risk = close - stop
    target = close + risk * rr
    return {
        "zone_low": round(lower, 2), "zone_high": round(upper, 2), "stop": round(stop, 2),
        "target": round(target, 2), "rr": round(rr, 1), "risk_pct": round(risk / close * 100, 1),
        "valid_until": add_trading_days(signal_day, int(cfg["신호 유효 거래일"])).isoformat(),
        "skip_if_open_above": round(upper * (1 + float(cfg["추격 금지 기준(%)"]) / 100), 2),
    }


def shares_for_budgets(price: float, budgets: list[int]) -> dict[int, tuple[int, float]]:
    return {b: (int(b // price), round(b - int(b // price) * price, 2)) for b in budgets} if price > 0 else {}


def levels(h: dict, df: pd.DataFrame, t: dict | None, cfg: dict) -> dict:
    """보유 종목의 현재가·평단·손절선·1차 목표·수익률 (매도 규칙과 앱 화면이 같은 값을 써요)."""
    close = float(df["Close"].iloc[-1])
    avg = float(h["avg"])
    max_loss = float(cfg["최대 손실(%)"]) / 100
    stop = h.get("stop")
    if not stop:
        computed = max(t["ma50"], t["low20"]) if t else avg * (1 - max_loss)
        stop = max(computed, avg * (1 - max_loss)) if computed < avg else avg * (1 - max_loss)
    stop = float(stop)
    risk = max(avg - stop, avg * 0.01)
    return {"close": close, "avg": avg, "stop": stop, "target": avg + 2 * risk, "gain": close / avg - 1}


def sell_check(h: dict, df: pd.DataFrame, t: dict | None, total: float | None, regime_changed_to_bear: bool,
               earnings_in: int | None, cfg: dict) -> list[dict]:
    """보유 종목 하나에 매도 규칙을 적용해요. 반환: 걸린 규칙 목록(가장 급한 것 먼저)."""
    hits = []
    c = df["Close"]
    lv = levels(h, df, t, cfg)
    close, avg, stop, target, gain = lv["close"], lv["avg"], lv["stop"], lv["target"], lv["gain"]
    since = c
    if h.get("buy_date"):
        try:
            since = c[c.index >= pd.Timestamp(h["buy_date"]).tz_localize(c.index.tz)]
        except Exception:
            since = c[c.index >= pd.Timestamp(h["buy_date"])]
    peak = float(since.max()) if len(since) else close
    held_days = len(since)

    if close < stop:
        hits.append({"rule": "stop", "why": f"종가 {close:.2f}가 손절선 {stop:.2f} 아래"})
    if close >= target and gain > 0:
        hits.append({"rule": "target", "why": f"1차 목표 {target:.2f} 도달 → 남은 물량 손절을 {avg:.2f}로"})
    trail = float(cfg["추적 매도 하락률(%)"]) / 100
    if gain > 0 and peak > avg and (close <= peak * (1 - trail) or (t and close < t["ma20"] and peak >= target)):
        hits.append({"rule": "trail", "why": f"최고 종가 {peak:.2f} 대비 {(close / peak - 1) * 100:.1f}% 또는 20일선 이탈"})
    if h.get("buy_date") and held_days >= int(cfg["제자리 판단 거래일"]) and stop <= close < target and total is not None and total < 70:
        hits.append({"rule": "stale", "why": f"{held_days}거래일째 제자리, 점수 {total:.0f}점"})
    if total is not None and t is not None:
        broken = t["ma20"] < t["ma50"] and t["macd_cross_dn_10d"]
        if total < float(cfg["점수 급락 기준"]) or broken:
            hits.append({"rule": "score", "why": "점수 급락" if total < float(cfg["점수 급락 기준"]) else "정배열 깨짐 · 하락 교차"})
    if regime_changed_to_bear:
        hits.append({"rule": "regime", "why": "시장이 하락장으로 바뀜 → 수익 중이면 손절을 매수가로" if gain > 0 else "시장이 하락장으로 바뀜"})
    if earnings_in is not None and 0 <= earnings_in <= 1 and gain > 0:
        hits.append({"rule": "earnings", "why": "내일 실적 발표, 수익 중"})
    for x in hits:
        x.update({"close": round(close, 2), "avg": round(avg, 2), "gain_pct": round(gain * 100, 1),
                  "stop": round(stop, 2), "to_stop_pct": round((close / stop - 1) * 100, 1)})
    return hits
