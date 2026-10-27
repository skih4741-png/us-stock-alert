"""차트 분석 카드 (경제정리노트 '월가 애널리스트처럼' 02번: 추세·지지/저항·이동평균 20·60·120·거래량·RSI·MACD).

GPT 없이 1년 일봉으로 직접 계산해요 → 숫자를 지어낼 일이 없어요.
결과: {종목: {"at","price","ma":{20,60,120},"rsi","macd":{...},"vol_ratio","hi52","lo52","support":[..],"resist":[..],
               "trend","lines":[쉬운 말],"up":상승 시나리오,"down":하락 시나리오}}
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def _rsi(close: pd.Series, n: int = 14) -> float | None:
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    v = (100 - 100 / (1 + rs)).iloc[-1]
    return None if pd.isna(v) else round(float(v), 1)


def _levels(df: pd.DataFrame, price: float) -> tuple[list[float], list[float]]:
    """최근 6개월 '꺾인 점'(앞뒤 5일 중 가장 낮은/높은 날)을 모아 가까운 지지·저항 2개씩."""
    d = df.tail(126)
    lo, hi = d["Low"], d["High"]
    lows = [float(lo.iloc[i]) for i in range(5, len(d) - 5) if lo.iloc[i] == lo.iloc[i - 5:i + 6].min()]
    highs = [float(hi.iloc[i]) for i in range(5, len(d) - 5) if hi.iloc[i] == hi.iloc[i - 5:i + 6].max()]

    def merge(xs):  # 1.5% 안쪽으로 붙은 값은 하나로
        out = []
        for x in sorted(xs):
            if out and abs(x / out[-1] - 1) < 0.015:
                out[-1] = (out[-1] + x) / 2
            else:
                out.append(x)
        return out
    sup = sorted([x for x in merge(lows) if x < price * 0.995], reverse=True)[:2]
    res = sorted([x for x in merge(highs) if x > price * 1.005])[:2]
    if not res:
        res = [float(d["High"].max())] if float(d["High"].max()) > price * 1.005 else []
    if not sup:
        sup = [float(d["Low"].min())] if float(d["Low"].min()) < price * 0.995 else []
    return [round(x, 2) for x in sup], [round(x, 2) for x in res]


def analyze(df: pd.DataFrame) -> dict | None:
    df = df.dropna(subset=["Close"])
    if len(df) < 130:
        return None
    c, v = df["Close"], df.get("Volume")
    price = float(c.iloc[-1])
    ma = {n: round(float(c.rolling(n).mean().iloc[-1]), 2) for n in (20, 60, 120)}
    ema12, ema26 = c.ewm(span=12, adjust=False).mean(), c.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    sig = macd.ewm(span=9, adjust=False).mean()
    hist = macd - sig
    cross = None
    for k in range(1, 6):  # 최근 5일 안의 교차
        if hist.iloc[-k] > 0 >= hist.iloc[-k - 1]:
            cross = f"{k}일 전 골든크로스(MACD가 신호선 위로)"; break
        if hist.iloc[-k] < 0 <= hist.iloc[-k - 1]:
            cross = f"{k}일 전 데드크로스(MACD가 신호선 아래로)"; break
    rsi = _rsi(c)
    vol_ratio = None
    if v is not None and v.tail(60).mean() > 0:
        vol_ratio = round(float(v.tail(5).mean() / v.tail(60).mean()), 2)
    y = df.tail(252)
    hi52, lo52 = round(float(y["High"].max()), 2), round(float(y["Low"].min()), 2)
    sup, res = _levels(df, price)

    above = sum(price > ma[n] for n in ma)
    aligned_up = ma[20] > ma[60] > ma[120]
    aligned_dn = ma[20] < ma[60] < ma[120]
    trend = "상승 추세" if above == 3 and aligned_up else "하락 추세" if above == 0 and aligned_dn else "횡보·전환 구간"

    lines = []
    lines.append(f"주가 ${price:.2f}는 이동평균 20·60·120일선 중 {above}개 위에 있어요 → {trend}"
                 + (" (정배열: 짧은 선이 긴 선 위)" if aligned_up else " (역배열: 짧은 선이 긴 선 아래)" if aligned_dn else ""))
    if rsi is not None:
        lines.append(f"RSI {rsi:.0f}: " + ("70 넘음 → 단기 과열(많이 오름)" if rsi >= 70 else "30 아래 → 단기 과매도(많이 내림)" if rsi <= 30
                                          else "50 위 → 사려는 힘이 조금 더 셈" if rsi >= 50 else "50 아래 → 팔려는 힘이 조금 더 셈"))
    lines.append("MACD: " + (cross or ("신호선 위 → 오르는 힘 유지" if hist.iloc[-1] > 0 else "신호선 아래 → 내리는 힘 유지")))
    if vol_ratio is not None:
        lines.append(f"거래량: 최근 5일이 평소(60일)의 {vol_ratio:.1f}배" + (" → 관심 커짐" if vol_ratio >= 1.5 else " → 조용함" if vol_ratio <= 0.7 else ""))
    lines.append(f"52주 범위 ${lo52:.2f} ~ ${hi52:.2f} · 지금은 최고가보다 {((price / hi52) - 1) * 100:+.1f}%")
    up = (f"저항 ${res[0]:.2f}를 거래량과 함께 넘으면 다음 목표 ${res[1]:.2f}" if len(res) > 1 else
          f"저항 ${res[0]:.2f}를 넘으면 52주 최고 ${hi52:.2f} 시험" if res else "52주 최고가 근처라 위쪽 저항이 뚜렷하지 않아요")
    down = (f"지지 ${sup[0]:.2f}가 깨지면 다음 지지 ${sup[1]:.2f}" if len(sup) > 1 else
            f"지지 ${sup[0]:.2f}가 깨지면 52주 최저 ${lo52:.2f} 쪽" if sup else "52주 최저가 근처라 아래 지지가 뚜렷하지 않아요")
    # 그려진 차트용 종가 시계열 + 전일 대비 (크기 줄이려 반올림·다운샘플)
    closes = [round(float(x), 2) for x in c.tolist()]
    prev = round(float(c.iloc[-2]), 2) if len(c) >= 2 else None
    chg = round((price / prev - 1) * 100, 2) if prev else None

    def _ds(seq: list, step: int) -> list:
        s = seq[::step]
        if s and seq and s[-1] != seq[-1]:
            s = s + [seq[-1]]
        return s
    series = {"1M": closes[-22:], "3M": closes[-66:], "1Y": _ds(closes, 5)}

    return {"at": str(df.index[-1])[:10], "price": round(price, 2), "prev": prev, "chg": chg, "ma": ma, "rsi": rsi,
            "macd": {"macd": round(float(macd.iloc[-1]), 3), "signal": round(float(sig.iloc[-1]), 3), "hist": round(float(hist.iloc[-1]), 3), "cross": cross},
            "vol_ratio": vol_ratio, "hi52": hi52, "lo52": lo52, "support": sup, "resist": res, "trend": trend,
            "series": series, "lines": lines, "up": up, "down": down}


def build(tickers: list[str]) -> dict:
    import prices
    out = {}
    if not tickers:
        return out
    hist = prices.download_history([t.replace(".", "-") for t in tickers], period="1y")
    fund = {}
    try:  # 재무 캐시(시총·PER·배당 등) — 이미 받아 둔 저장본이라 추가 호출이 거의 없어요
        fund = prices.fundamentals([t.replace(".", "-") for t in tickers])
    except Exception as e:
        log.info("차트 재무 캐시 실패: %s", e)
    for t in tickers:
        df = hist.get(t.replace(".", "-"))
        if df is None:
            continue
        try:
            r = analyze(df)
            if r:
                fd = fund.get(t.replace(".", "-")) or {}
                r["info"] = {"name": fd.get("long_name") or fd.get("short_name") or "",
                             "sector": fd.get("sector"), "per": fd.get("per"), "pbr": fd.get("pbr"),
                             "mktcap": fd.get("market_cap"), "div": fd.get("div_yield")}
                out[t] = r
        except Exception as e:
            log.info("차트 분석 실패 %s: %s", t, e)
    return out
