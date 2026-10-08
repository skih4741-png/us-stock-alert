"""3단계: 신호 성적 · 모의투자 성적 (F-A11 실력 vs 운, S-10).

- '신호 기록' 탭: 매일 아침 후보를 적어 두고, 5일·20일 뒤 수익률과 같은 기간 SPY, 목표·손절 중 먼저 닿은 쪽을 채워요.
- '모의 거래' 탭: 앱에서 '모의투자에 담기'·'팔기'·'회고'를 누르면 로그인 서버가 적어요(가상 1,000달러, 실제 주문 없음).
- 계산 결과는 '앱 데이터'의 perf 묶음으로 저장해서 앱 '성적' 탭이 읽어요.
"""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

import prices

log = logging.getLogger(__name__)
START_CASH = 1000.0
SIG_EXTRA = ["SPY 5일", "SPY 20일", "결과"]  # 결과: 목표 먼저 · 손절 먼저 · 20일 안에 둘 다 안 닿음 · 진행 중


def _f(x):
    try:
        v = float(x)
        return None if math.isnan(v) or math.isinf(v) else v
    except (TypeError, ValueError):
        return None


def _d(x) -> str:
    """시트가 날짜를 '2026. 10. 8' 같은 모양으로 돌려줘도 YYYY-MM-DD로 맞춰요."""
    import re
    m = re.findall(r"\d+", str(x or ""))
    if len(m) >= 3 and len(m[0]) == 4:
        return f"{int(m[0]):04d}-{int(m[1]):02d}-{int(m[2]):02d}"
    return str(x or "")


def _pos(df: pd.DataFrame, day: str) -> int | None:
    """day(YYYY-MM-DD) 종가가 있는 줄 번호. 그날이 없으면 그 이전 마지막 거래일."""
    idx = df.index.strftime("%Y-%m-%d")
    p = int(np.searchsorted(idx, day, side="right")) - 1
    return p if p >= 0 else None


def _ret(df, pos, n):
    if df is None or pos is None or pos + n >= len(df):
        return None
    return float(df["Close"].iloc[pos + n] / df["Close"].iloc[pos] - 1) * 100


def first_touch(df: pd.DataFrame, pos: int, target: float | None, stop: float | None, days: int = 20) -> str:
    """신호(또는 매수) 다음 날부터 목표가와 손절가 중 먼저 닿은 쪽. 같은 날 둘 다면 보수적으로 손절."""
    if df is None or pos is None or not target or not stop:
        return ""
    end = min(len(df), pos + 1 + days)
    for i in range(pos + 1, end):
        lo, hi = float(df["Low"].iloc[i]), float(df["High"].iloc[i])
        if lo <= stop:
            return "손절 먼저"
        if hi >= target:
            return "목표 먼저"
    return "둘 다 안 닿음" if pos + days < len(df) else "진행 중"


def _stats(vals: list[float]) -> dict:
    v = [x for x in vals if x is not None]
    if not v:
        return {"n": 0}
    wins = [x for x in v if x > 0]
    losses = [-x for x in v if x <= 0]
    return {"n": len(v), "avg": round(sum(v) / len(v), 2), "win": round(len(wins) / len(v) * 100),
            "pf": round((sum(wins) / len(wins)) / (sum(losses) / len(losses)), 2) if wins and losses and sum(losses) > 0 else None}


def update(store, period: str = "250d") -> dict:
    """신호 기록을 채우고 성적 묶음(perf)을 만들어 돌려줘요."""
    sig = store.read("신호 기록")
    paper = store.read("모의 거래")
    if len(sig):
        sig["날짜"] = sig["날짜"].map(_d)
    for c in ("담은 날", "판 날"):
        if len(paper) and c in paper:
            paper[c] = paper[c].map(lambda v: _d(v) if v else "")
    tickers = set(paper["종목"]) if len(paper) else set()
    if len(sig):
        recent = sig[sig["날짜"] >= (pd.Timestamp.today() - pd.Timedelta(days=200)).strftime("%Y-%m-%d")]
        tickers |= set(recent["종목"])
    tickers = sorted(t for t in tickers if t)
    hist = prices.download_history([t.replace(".", "-") for t in tickers] + ["SPY"], period=period) if tickers else {}
    spy = hist.get("SPY")
    H = lambda t: hist.get(str(t).replace(".", "-"))

    # ---- 신호 기록 채우기 ----
    if len(sig):
        for c in SIG_EXTRA:
            if c not in sig.columns:
                sig[c] = ""
        for i, row in sig.iterrows():
            if row.get("결과") in ("목표 먼저", "손절 먼저", "둘 다 안 닿음") and row.get("20일 뒤 수익률"):
                continue  # 다 끝난 줄은 다시 계산하지 않아요
            df = H(row["종목"])
            if df is None or spy is None:
                continue
            p, sp = _pos(df, row["날짜"]), _pos(spy, row["날짜"])
            for col, d, n in (("5일 뒤 수익률", df, 5), ("20일 뒤 수익률", df, 20), ("SPY 5일", spy, 5), ("SPY 20일", spy, 20)):
                v = _ret(d, p if d is df else sp, n)
                sig.at[i, col] = "" if v is None else f"{v:.1f}"
            sig.at[i, "결과"] = first_touch(df, p, _f(row.get("1차 목표")), _f(row.get("손절")))
        try:
            store.overwrite("신호 기록", sig)
        except Exception as e:
            log.warning("신호 기록 저장 실패: %s", e)

    perf = {"v": 1, "start_cash": START_CASH, "signals": signal_summary(sig), "paper": paper_summary(paper, H, spy),
            "prices": {}}
    for t in tickers:
        df = H(t)
        if df is not None and len(df):
            perf["prices"][t] = {"close": round(float(df["Close"].iloc[-1]), 2), "date": df.index[-1].strftime("%Y-%m-%d")}
    return perf


def signal_summary(sig: pd.DataFrame) -> dict:
    if not len(sig):
        return {"n": 0}
    s = sig.copy()
    for c in ("5일 뒤 수익률", "20일 뒤 수익률", "SPY 5일", "SPY 20일"):
        s[c] = s[c].map(_f) if c in s else None
    out = {"n": int(len(s)), "since": str(s["날짜"].min())}
    for n in (5, 20):
        mine, bench = s[f"{n}일 뒤 수익률"], s[f"SPY {n}일"]
        ok = mine.notna() & bench.notna()
        st = _stats(mine[ok].tolist())
        if st["n"]:
            r = mine[ok]
            # 후보마다 100달러씩 샀다고 치면 번 돈·잃은 돈 (달러)
            st["usd_gain"] = round(float(r[r > 0].sum()), 2)
            st["usd_loss"] = round(float(r[r <= 0].sum()), 2)
            st["usd_net"] = round(float(r.sum()), 2)
            st["spy"] = round(float(bench[ok].mean()), 2)
            st["excess"] = round(float((mine[ok] - bench[ok]).mean()), 2)
        out[f"d{n}"] = st
    res = s.get("결과", pd.Series(dtype=str))
    done = res[res.isin(["목표 먼저", "손절 먼저", "둘 다 안 닿음"])]
    out["hit"] = {"n": int(len(done)), "target": int((done == "목표 먼저").sum()), "stop": int((done == "손절 먼저").sum()),
                  "none": int((done == "둘 다 안 닿음").sum())}
    groups = {}
    ok5 = s["5일 뒤 수익률"].notna()
    for col in ("가격대", "시장 국면"):
        if col in s:
            g = []
            for k, part in s[ok5].groupby(col):
                st = _stats(part["5일 뒤 수익률"].tolist())
                g.append({"name": str(k), **st})
            groups[col] = sorted(g, key=lambda x: -x["n"])
    out["groups"] = groups
    recent = s.sort_values("날짜", ascending=False).head(15)
    out["recent"] = [{"date": r["날짜"], "t": r["종목"], "band": r.get("가격대", ""), "price": _f(r.get("그날 주가")),
                      "r5": r["5일 뒤 수익률"], "r20": r["20일 뒤 수익률"], "spy5": r["SPY 5일"], "result": r.get("결과", "")}
                     for _, r in recent.iterrows()]
    return out


def paper_summary(paper: pd.DataFrame, H, spy) -> dict:
    trades = []
    cash = START_CASH
    for _, r in (paper.iterrows() if len(paper) else []):
        qty, px = _f(r.get("수량")), _f(r.get("담은 가격"))
        if not qty or not px:
            continue
        t, d0 = r["종목"], r["담은 날"]
        df = H(t)
        sold = bool(r.get("판 날")) and _f(r.get("판 가격")) is not None
        exit_px = _f(r.get("판 가격")) if sold else (float(df["Close"].iloc[-1]) if df is not None and len(df) else None)
        cost = qty * px
        cash -= cost
        if sold:
            cash += qty * exit_px
        ret = (exit_px / px - 1) * 100 if exit_px else None
        spy_ret = None
        if spy is not None:
            a = _pos(spy, d0)
            b = _pos(spy, r["판 날"]) if sold else len(spy) - 1
            if a is not None and b is not None and b >= a:
                spy_ret = float(spy["Close"].iloc[b] / spy["Close"].iloc[a] - 1) * 100
        p0 = _pos(df, d0) if df is not None else None
        pred = first_touch(df, p0, _f(r.get("1차 목표")), _f(r.get("손절")), days=20) if df is not None else ""
        stop = _f(r.get("손절"))
        trades.append({
            "id": str(r.get("번호", "")), "t": t, "date": d0, "qty": qty, "price": px, "stop": stop, "target": _f(r.get("1차 목표")),
            "sold": sold, "sold_date": r.get("판 날", ""), "exit": round(exit_px, 2) if exit_px else None,
            "why_sold": r.get("판 이유", ""), "note": r.get("회고", ""),
            "ret": None if ret is None else round(ret, 2), "spy": None if spy_ret is None else round(spy_ret, 2),
            "excess": None if ret is None or spy_ret is None else round(ret - spy_ret, 2),
            "pnl": None if exit_px is None else round(qty * (exit_px - px), 2), "pred": pred,
            "below_stop": bool(not sold and exit_px and stop and exit_px < stop),
        })
    open_val = sum(x["qty"] * (x["exit"] or x["price"]) for x in trades if not x["sold"])
    equity = cash + open_val
    my_pnl = sum(x["pnl"] or 0 for x in trades)
    bench_pnl = sum(x["qty"] * x["price"] * (x["spy"] or 0) / 100 for x in trades)
    rets = [x["ret"] for x in trades]
    exc = [x["excess"] for x in trades]
    closed = [x["ret"] for x in trades if x["sold"]]
    preds = [x["pred"] for x in trades if x["pred"] in ("목표 먼저", "손절 먼저", "둘 다 안 닿음")]

    def part(xs):
        r = [x["ret"] for x in xs if x["ret"] is not None]
        e = [x["excess"] for x in xs if x["excess"] is not None]
        return {"n": len(xs), "avg": round(sum(r) / len(r), 2) if r else None,
                "excess": round(sum(e) / len(e), 2) if e else None,
                "win": round(sum(1 for v in r if v > 0) / len(r) * 100) if r else None}

    pn = [x for x in trades if x["pnl"] is not None]
    money = {
        "realized": round(sum(x["pnl"] for x in pn if x["sold"]), 2),
        "unrealized": round(sum(x["pnl"] for x in pn if not x["sold"]), 2),
        "gain": round(sum(x["pnl"] for x in pn if x["pnl"] > 0), 2),
        "loss": round(sum(x["pnl"] for x in pn if x["pnl"] <= 0), 2),
        "wins": sum(1 for x in pn if x["pnl"] > 0), "losses": sum(1 for x in pn if x["pnl"] <= 0),
        "best": max(pn, key=lambda x: x["pnl"])["t"] + f" {max(x['pnl'] for x in pn):+.2f}" if pn else "",
        "worst": min(pn, key=lambda x: x["pnl"])["t"] + f" {min(x['pnl'] for x in pn):+.2f}" if pn else "",
    }
    return {
        "money": money,
        "cash": round(cash, 2), "equity": round(equity, 2), "ret": round((equity / START_CASH - 1) * 100, 2),
        "pnl": round(my_pnl, 2), "spy_pnl": round(bench_pnl, 2),
        "excess_pct": round((my_pnl - bench_pnl) / START_CASH * 100, 2),
        "n": len(trades), "open": sum(1 for x in trades if not x["sold"]),
        "all": _stats(rets), "closed": _stats(closed),
        "avg_excess": round(sum(v for v in exc if v is not None) / max(1, sum(1 for v in exc if v is not None)), 2) if trades else None,
        "pred": {"n": len(preds), "hit": sum(1 for p in preds if p == "목표 먼저"),
                 "rate": round(sum(1 for p in preds if p == "목표 먼저") / len(preds) * 100) if preds else None},
        "first20": part(trades[:20]), "last20": part(trades[-20:]),
        "no_note": sum(1 for x in trades if x["sold"] and not x["note"]),
        "trades": trades[::-1][:100],
    }
