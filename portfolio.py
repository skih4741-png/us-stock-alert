"""내 포트폴리오 진단 (경제정리노트 '월가 애널리스트처럼' 05번: 종목 비중·상관관계·수익률/변동성·리스크·비중 검토).

숫자는 모두 파이썬으로 계산 (1년 일봉). GPT는 그 숫자를 쉬운 말로 풀고 '검토 포인트'만 써요(사라·팔라 금지).
결과: {"at","total","items":[{t,weight,sector,ret_1y,vol,beta,div}],"sectors":{업종:비중},"pairs":[가장 같이 움직이는 쌍],
       "port":{"vol","beta","div_yield","ret_1y","mdd"},"flags":[쉬운 경고],"ai":{GPT 풀이}}
"""
from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

TASK = """목표: 초보자에게 내 포트폴리오 상태를 5초에 이해하게 설명해줘.
규칙:
- 숫자는 '자료'의 계산 결과에 있는 것만 써. 새로 계산하지 마.
- 사라·팔라·추천 금지. '검토 포인트'는 '이런 걸 확인해 보세요' 형태로.
- 예시는 생활 비유(바구니에 달걀, 우산 장수와 아이스크림 장수 같은)로.
출력 JSON:
{"한 줄":"","좋은 점":["",""],"주요 리스크":[{"이름":"","설명":"","숫자":"자료 숫자"}],"예시":"","검토 포인트":["","",""]}
- 주요 리스크는 3개 (쏠림·같이 움직임·변동성·금리 민감·배당 의존 등 자료로 보이는 것)."""


def analyze(holds: list[dict], hist: dict, sector_of) -> dict | None:
    """holds: [{t, qty, price, avg}], hist: {티커: 일봉}, sector_of: 티커→업종 이름."""
    rows = []
    for h in holds:
        q, px = h.get("qty"), h.get("price")
        if not q or not px:
            continue
        rows.append({"t": h["t"], "value": float(q) * float(px), "cost": float(q) * float(h.get("avg") or px)})
    total = sum(r["value"] for r in rows)
    if total <= 0 or not rows:
        return None
    rets = {}
    for r in rows:
        df = hist.get(r["t"].replace(".", "-"))
        if df is not None and len(df.dropna(subset=["Close"])) > 60:
            rets[r["t"]] = df["Close"].dropna().pct_change()
    spy = hist.get("SPY")
    spy_r = spy["Close"].dropna().pct_change() if spy is not None else None
    items = []
    for r in rows:
        w = r["value"] / total
        x = rets.get(r["t"])
        it = {"t": r["t"], "weight": round(w * 100, 1), "sector": sector_of(r["t"]) or "ETF·기타", "value": round(r["value"], 2),
              "gain_pct": round((r["value"] / r["cost"] - 1) * 100, 1) if r["cost"] else None}
        if x is not None:
            x = x.dropna()
            it["vol"] = round(float(x.std() * math.sqrt(252) * 100), 1)
            px = hist[r["t"].replace(".", "-")]["Close"].dropna()
            it["ret_1y"] = round(float(px.iloc[-1] / px.iloc[max(0, len(px) - 252)] - 1) * 100, 1)
            if spy_r is not None:
                j = pd.concat([x, spy_r], axis=1, join="inner").dropna()
                if len(j) > 60 and j.iloc[:, 1].var() > 0:
                    it["beta"] = round(float(j.iloc[:, 0].cov(j.iloc[:, 1]) / j.iloc[:, 1].var()), 2)
        items.append(it)
    items.sort(key=lambda x: -x["weight"])
    sectors = {}
    for it in items:
        sectors[it["sector"]] = round(sectors.get(it["sector"], 0) + it["weight"], 1)
    sectors = dict(sorted(sectors.items(), key=lambda x: -x[1]))
    # 같이 움직이는 쌍 (최근 6개월 일간 수익률 상관)
    pairs = []
    R = pd.DataFrame({k: v for k, v in rets.items()}).dropna().tail(126)
    if R.shape[1] >= 2:
        C = R.corr()
        cols = list(C.columns)
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                pairs.append({"a": cols[i], "b": cols[j], "corr": round(float(C.iloc[i, j]), 2)})
        pairs.sort(key=lambda x: -x["corr"])
    # 포트폴리오 전체
    port = {}
    if R.shape[1] >= 1:
        wv = np.array([next(it["weight"] for it in items if it["t"] == c) / 100 for c in R.columns])
        wv = wv / wv.sum()
        pr = R.values @ wv
        port["vol"] = round(float(np.std(pr) * math.sqrt(252) * 100), 1)
        eq = np.cumprod(1 + pr)
        port["mdd_6m"] = round(float((eq / np.maximum.accumulate(eq) - 1).min() * 100), 1)
        if spy_r is not None:
            s = spy_r.reindex(R.index).values
            ok = ~np.isnan(s)
            if ok.sum() > 60:
                port["beta"] = round(float(np.cov(pr[ok], s[ok])[0, 1] / np.var(s[ok], ddof=1)), 2)
                port["spy_vol"] = round(float(np.nanstd(s[ok]) * math.sqrt(252) * 100), 1)
    port["gain_pct"] = round((total / sum(r["cost"] for r in rows) - 1) * 100, 1)
    # 쉬운 경고
    flags = []
    top = items[0]
    if top["weight"] > 25:
        flags.append(f"{top['t']} 한 종목이 {top['weight']:.0f}% — 한 바구니에 달걀이 많이 담겨 있어요 (25% 넘음)")
    s0 = next(((k, v) for k, v in sectors.items() if k != "ETF·기타"), ("", 0))   # ETF는 안에서 이미 나눠져 있어서 제외
    if s0[1] > 40:
        flags.append(f"'{s0[0]}' 업종이 {s0[1]:.0f}% — 한 업종 뉴스에 전체가 흔들릴 수 있어요 (40% 넘음)")
    hi_pairs = [p for p in pairs if p["corr"] >= 0.7]
    if hi_pairs:
        flags.append("거의 같이 움직이는 종목: " + ", ".join(f"{p['a']}·{p['b']}({p['corr']:.2f})" for p in hi_pairs[:3]) + " — 나눠 산 효과가 작아요")
    hv = [it for it in items if (it.get("vol") or 0) >= 45]
    if hv:
        flags.append("출렁임이 큰 종목(연 변동성 45% 이상): " + ", ".join(f"{it['t']} {it['vol']:.0f}%" for it in hv))
    if port.get("beta") is not None and port["beta"] >= 1.2:
        flags.append(f"시장보다 {port['beta']:.1f}배 크게 움직여요 (베타)")
    if not flags:
        flags.append("눈에 띄는 쏠림·같이 움직임 경고는 없어요")
    return {"total": round(total, 2), "items": items, "sectors": sectors, "pairs": pairs[:5], "low_pairs": sorted(pairs, key=lambda x: x["corr"])[:3],
            "port": port, "flags": flags}


def build(holds: list[dict], sector_of) -> dict | None:
    import prices
    tick = [h["t"].replace(".", "-") for h in holds if h.get("qty")] + ["SPY"]
    hist = prices.download_history(tick, period="1y")
    return analyze(holds, hist, sector_of)
