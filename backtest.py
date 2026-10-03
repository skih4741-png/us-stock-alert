"""F-18 과거 검증.

무료 자료로는 과거 시점의 재무제표를 구할 수 없어서, 과거 검증은 '추세 + 안전(출렁임·고점 대비)' 점수만으로 해요.
실제 리스트는 재무 점수까지 더하니, 이 결과는 "규칙의 뼈대가 돈이 되는가"를 보는 용도예요.

  python backtest.py --tickers 400 --years 3      거래대금 상위 400개, 최근 3년
결과는 data/backtest_report.md 에 저장되고, 메일 설정이 있으면 메일로도 보내요.
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
import pandas as pd

import config
import market
import prices
import universe

OUT = Path(__file__).parent / "data" / "backtest_report.md"


def indicator_frame(df: pd.DataFrame) -> pd.DataFrame:
    c, v = df["Close"], df["Volume"]
    o = pd.DataFrame(index=df.index)
    o["open"], o["high"], o["low"], o["close"] = df["Open"], df["High"], df["Low"], c
    o["ma20"], o["ma50"], o["ma200"] = c.rolling(20).mean(), c.rolling(50).mean(), c.rolling(200).mean()
    line = c.ewm(span=12, adjust=False).mean() - c.ewm(span=26, adjust=False).mean()
    sig = line.ewm(span=9, adjust=False).mean()
    up = (line > sig) & (line.shift(1) <= sig.shift(1))
    o["macd_up10"] = up.rolling(10).max().fillna(0).astype(bool)
    o["macd_above"] = line > sig
    d = c.diff()
    rs = d.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean() / (-d.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    o["rsi"] = 100 - 100 / (1 + rs)
    o["volr"] = v / v.rolling(20).mean()
    o["ret63"] = c / c.shift(63) - 1
    o["ret5"] = c / c.shift(5) - 1
    o["vol60"] = c.pct_change().rolling(60).std() * math.sqrt(252)
    o["dd"] = c / c.rolling(252, min_periods=120).max() - 1
    o["low20"] = df["Low"].rolling(20).min()
    o["dv20"] = (c * v).rolling(20).mean()
    return o


def score_frame(o: pd.DataFrame, rs_pct: pd.Series, spy_ret63: pd.Series, mvol: pd.Series) -> pd.DataFrame:
    full = (o.ma20 > o.ma50) & (o.ma50 > o.ma200)
    some = (o.ma20 > o.ma50) | (o.ma50 > o.ma200)
    beats = o.ret63 > spy_ret63.reindex(o.index)
    rsp = rs_pct.reindex(o.index)
    t = (np.where(full, 7, np.where(some, 3, 0)) + np.where(o.close > o.ma200, 3, 0)
         + np.where(o.macd_up10, 5, np.where(o.macd_above, 2, 0))
         + np.where(beats & (rsp <= 0.3), 4, np.where(beats, 2, 0))
         + np.where(o.rsi.between(40, 70), 3, np.where(o.rsi.between(70, 75), 1, 0))
         + np.where(o.volr >= 1.5, 3, np.where(o.volr >= 1.2, 1, 0)))
    mv = mvol.reindex(o.index)
    s = (np.where(o.vol60 <= mv, 8, np.where(o.vol60 <= mv * 1.5, 4, 0))
         + np.where(o.dd >= -0.15, 9, np.where(o.dd >= -0.25, 4, 0)))
    out = pd.DataFrame(index=o.index)
    out["trend"] = t / 25 * 25
    out["safety"] = s / 17 * 25
    out["total"] = (t + s) / 42 * 100
    out["conds"] = full.astype(int) + o.macd_up10.astype(int) + (o.volr >= 1.5).astype(int)
    return out


def simulate(o: pd.DataFrame, i: int, rr: float, cfg: dict, max_hold: int = 60) -> dict | None:
    """신호일 i의 다음 날 시가에 사서 규칙대로 팔아요."""
    if i + 1 >= len(o):
        return None
    r = o.iloc[i]
    close = r.close
    upper = close * 1.01
    skip = upper * (1 + float(cfg["추격 금지 기준(%)"]) / 100)
    stop = max(r.ma50, r.low20)
    stop = max(stop, close * (1 - float(cfg["최대 손실(%)"]) / 100))
    if stop > close * (1 - float(cfg["최소 위험폭(%)"]) / 100):
        stop = close * 0.97
    nxt = o.iloc[i + 1]
    if nxt.open > skip:
        return {"skipped": True}
    entry = float(nxt.open)
    if entry <= stop:
        return {"skipped": True}
    risk = entry - stop
    target = entry + risk * rr
    half_done, peak, realized = False, entry, 0.0
    first3_low = float(o["close"].iloc[i + 1:i + 4].min()) if i + 4 <= len(o) else float(o["close"].iloc[i + 1:].min())
    for j in range(i + 1, min(len(o), i + 1 + max_hold)):
        bar = o.iloc[j]
        if bar.low <= stop:
            px = min(bar.open, stop) if j > i + 1 else stop
            rest = (px / entry - 1)
            ret = realized + (0.5 if half_done else 1.0) * rest
            return {"ret": ret, "days": j - i, "exit": "손절" if not half_done else "본전 손절", "first3": first3_low / entry - 1}
        if not half_done and bar.high >= target:
            realized += 0.5 * (target / entry - 1)
            half_done, stop = True, entry
        peak = max(peak, bar.close)
        if half_done and (bar.close <= peak * (1 - float(cfg["추적 매도 하락률(%)"]) / 100) or bar.close < bar.ma20):
            return {"ret": realized + 0.5 * (bar.close / entry - 1), "days": j - i, "exit": "추적 매도", "first3": first3_low / entry - 1}
    last = o.iloc[min(len(o) - 1, i + max_hold)]
    ret = realized + (0.5 if half_done else 1.0) * (last.close / entry - 1)
    return {"ret": ret, "days": max_hold, "exit": "기간 만료", "first3": first3_low / entry - 1}


def run(n_tickers: int, years: int, send: bool):
    cfg, _ = config.merge_settings({})
    uni, _ = universe.load_universe(cfg, include_etf=False)
    uni = uni.assign(dv=uni["price"].fillna(0) * uni["volume"].fillna(0)).sort_values("dv", ascending=False).head(n_tickers)
    period = f"{years + 1}y"
    hist = prices.download_history(["SPY"] + list(uni["yf_ticker"]), period=period)
    spy = hist.pop("SPY")
    reg = market.regime_series(spy)
    spy_ret63 = spy["Close"] / spy["Close"].shift(63) - 1
    frames = {t: indicator_frame(df) for t, df in hist.items() if len(df) > 260}
    ret63 = pd.DataFrame({t: f["ret63"] for t, f in frames.items()})
    rs_pct = ret63.rank(axis=1, ascending=False, pct=True)
    mvol = pd.DataFrame({t: f["vol60"] for t, f in frames.items()}).median(axis=1)
    start = spy.index[-1] - pd.DateOffset(years=years)
    rows = []
    for t, o in frames.items():
        sc = score_frame(o, rs_pct[t], spy_ret63, mvol)
        o = o.join(sc)
        o["regime"] = reg.reindex(o.index)
        o["spy_chg"] = spy["Close"].pct_change().reindex(o.index) * 100
        ok = ((o.index >= start) & (o.dv20 >= float(cfg["최소 거래대금(달러)"])) & (o.close >= 1)
              & (o.conds >= 2) & (o.trend >= 10) & (o.safety >= 10)
              & (o.ret5 * 100 <= float(cfg["급등 기준(5일 상승률 %)"])))
        thr = o.regime.map({"bull": cfg["상승장 매수 기준"], "sideways": cfg["횡보장 매수 기준"], "bear": cfg["하락장 참고 기준"]}).astype(float)
        ok &= o.total >= thr
        for d in o.index[ok]:
            rows.append({"date": d, "ticker": t, "total": o.at[d, "total"], "price": o.at[d, "close"],
                         "regime": o.at[d, "regime"], "shaky": o.at[d, "spy_chg"] <= float(cfg["흔들린 날 하락률(%)"])})
    sig = pd.DataFrame(rows)
    if sig.empty:
        print("신호가 없어요")
        return
    step = float(cfg["가격대 단위(달러)"])
    sig["band"] = np.minimum((sig["price"] // step).astype(int), int(cfg["가격대 개수"]) - 1)
    sig["rank"] = sig.groupby(["date", "band"])["total"].rank(ascending=False, method="first")
    sig = sig[sig["rank"] <= 15]
    # 같은 종목이 3거래일 안에 다시 신호가 나면 첫 신호만 (신호 유효 기간)
    sig = sig.sort_values(["ticker", "date"])
    keep, last = [], {}
    for _, r in sig.iterrows():
        p = last.get(r.ticker)
        if p is not None and np.busday_count(p.date(), r.date.date()) <= int(cfg["신호 유효 거래일"]):
            keep.append(False)
        else:
            keep.append(True)
            last[r.ticker] = r.date
    sig = sig[keep]
    res = []
    for _, r in sig.iterrows():
        o = frames[r.ticker]
        i = o.index.get_loc(r.date)
        rr = float(cfg["상승장 손익비"] if r.regime == "bull" else cfg["횡보장 손익비"])
        s = simulate(o, i, rr, cfg)
        if s and not s.get("skipped"):
            res.append({**r.to_dict(), **s})
    tr = pd.DataFrame(res)
    report(tr, n_tickers, years, len(frames), send)


def _stats(df: pd.DataFrame) -> str:
    if df.empty:
        return "거래 없음"
    win = (df.ret > 0).mean() * 100
    return (f"{len(df)}건 · 맞은 비율 {win:.0f}% · 평균 {df.ret.mean() * 100:+.2f}% · 평균 수익 {df[df.ret > 0].ret.mean() * 100:+.1f}% · "
            f"평균 손실 {df[df.ret <= 0].ret.mean() * 100:+.1f}% · 사자마자 -3% {((df.first3 <= -0.03).mean() * 100):.0f}%")


def report(tr: pd.DataFrame, n: int, years: int, used: int, send: bool):
    regname = {"bull": "상승장", "sideways": "횡보장", "bear": "하락장"}
    L = [f"# 과거 검증 결과", "", f"- 대상: 거래대금 상위 {n}개 중 자료가 충분한 {used}개, 최근 {years}년",
         "- 점수: 추세 + 안전(출렁임·고점 대비)만 사용 (과거 재무 자료 없음)", "- 매매: 다음 날 시가 매수, 손절·1차 목표 절반·추적 매도, 최대 60거래일", "",
         "## 전체", _stats(tr), ""]
    # 최악의 연속 손실
    seq = (tr.sort_values("date").ret <= 0).astype(int).tolist()
    worst, cur = 0, 0
    for x in seq:
        cur = cur + 1 if x else 0
        worst = max(worst, cur)
    L += [f"최악의 연속 손실: {worst}건", ""]
    L += ["## 순위 구간별 (상위 3개만 보내는 게 맞는지)"]
    for name, m in (("1~3위", tr["rank"] <= 3), ("4~10위", (tr["rank"] > 3) & (tr["rank"] <= 10)), ("11~15위", tr["rank"] > 10)):
        L.append(f"- {name}: {_stats(tr[m])}")
    L += ["", "## 시장 국면별"]
    for k, g in tr.groupby("regime"):
        L.append(f"- {regname.get(k, k)}{' (실제로는 매수 쉼, 85점 이상 참고)' if k == 'bear' else ''}: {_stats(g)}")
    L += ["", "## 흔들린 날(대표 지수 -3% 이상) 신호", f"- 흔들린 날: {_stats(tr[tr.shaky])}", f"- 그 외: {_stats(tr[~tr.shaky])}", ""]
    L += ["## 가격대별"]
    for k, g in tr.groupby("band"):
        lab = f"{int(k) * 10}달러 이상" if k == 10 else f"{int(k) * 10}~{int(k) * 10 + 10}달러"
        L.append(f"- {lab}: {_stats(g)}")
    L += ["", "## 판단", ("기대 수익이 0보다 커요. 다음 단계(모의투자 2주)로 넘어가도 돼요." if tr.ret.mean() > 0
                         else "기대 수익이 0 이하예요. 규칙부터 고친 뒤 다시 검증하세요."),
          "", "과거 성적이 미래 수익을 보장하지는 않아요. 수수료·환전 비용은 빼지 않은 숫자예요."]
    text = "\n".join(L)
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(text)
    if send:
        import notify
        notify.send_mail("[미국주식] 과거 검증 결과", text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=int, default=400)
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--send", action="store_true")
    a = ap.parse_args()
    run(a.tickers, a.years, a.send)
