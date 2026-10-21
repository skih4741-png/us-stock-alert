"""Claude 펀드매니저 4단계 (every-ai-guides 'claude-fund-manager-repos-4' 가이드를 이 앱에 맞춰 옮김).

  ① 예측  Kronos      (github.com/shiyu-coder/Kronos)          — 다음 5거래일 종가 예측 → fund_forecast.json
  ② 배분  skfolio     (github.com/skfolio/skfolio)              — 예측·위험 → 비중표 (MeanRisk · HRP · 균등)
  ③ 실행  NautilusTrader (github.com/nautechsystems/nautilus_trader) — 비중대로 매주 리밸런싱 백테스트 (수수료 0.1%)
  ④ 감독  Vibe-Trading (github.com/HKUDS/Vibe-Trading)          — 한 장 보고서 (무엇이 통했나·위험·다음 주 바꿀 것)

이 파일은 ②③과 보고서를 맡고, ①은 비밀 키가 없는 따로 된 단계(fund_kronos.py)가 만든 fund_forecast.json 을 읽기만 해요.
④ Vibe-Trading 에이전트는 자동 실행에 넣지 않았어요(사람 없이 도는 에이전트라서). 대신 앱 GPT가 같은 형식으로 보고서를 쓰고,
PC에서 직접 Vibe-Trading을 돌려 만든 보고서를 data/fund_vibe.md 로 두면 `python fund.py --attach-vibe` 로 붙여요.

공통 원칙: 실제 주문·증권사 연결 없음 · 투자 권유 아님 · 과거 검증은 매주 그때까지의 자료로만 비중을 다시 계산(walk-forward).
결과는 시트 '앱 데이터'의 ai 덩어리 안 fund 로 저장 → 앱 '모의투자 → 펀드매니저'.
"""
from __future__ import annotations

import json
import logging
import math
from pathlib import Path

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent
FORECAST_FILE = ROOT / "data" / "fund_forecast.json"
VIBE_FILE = ROOT / "data" / "fund_vibe.md"
MAX_N = 15
BENCH = "SPY"


# ---------------------------------------------------------------- 대상 종목
def universe(store) -> list[str]:
    """보유 + 자동 모의 보유·주문 + 오늘 후보 상위(개별 종목) — 최대 15개."""
    import simtrade
    out = []
    try:
        d = json.loads(store.get_blob("daily") or "{}")
    except Exception:
        d = {}
    out += [h["t"] for h in d.get("holdings", []) if h.get("t")]
    st = simtrade.load(store) or {}
    out += [p["t"] for p in st.get("positions", [])] + [o["t"] for o in st.get("pending", [])]
    picks = sorted([p for b in d.get("bands", []) for p in b.get("picks", [])], key=lambda p: -(p.get("total") or 0))
    out += [p["t"] for p in picks]
    seen, res = set(), []
    for t in out:
        t = str(t).upper().replace(".", "-")
        if t and t not in seen and t != BENCH:
            seen.add(t)
            res.append(t)
    return res[:MAX_N]


# ---------------------------------------------------------------- ① 예측 (파일 읽기)
def load_forecast(tickers: list[str]) -> dict:
    """fund_forecast.json: {"at","model","horizon","items":{티커:{"last","pred":[...],"exp_ret"}}} — Kronos 단계가 만들어요."""
    try:
        f = json.loads(FORECAST_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}
    items = {t: v for t, v in (f.get("items") or {}).items() if t in tickers and isinstance(v, dict) and v.get("exp_ret") is not None}
    return dict(f, items=items) if items else {}


def score_forecasts(old_hist: list[dict], hist: dict[str, pd.DataFrame]) -> dict:
    """지난 예측 채점: 예측한 5거래일이 지났으면 실제 종가와 비교 (방향 적중률·평균 오차)."""
    done, hit, err = [], 0, []
    for rec in old_hist:
        for t, v in (rec.get("items") or {}).items():
            df = hist.get(t)
            if df is None or not v.get("last") or not v.get("pred"):
                continue
            after = df.loc[df.index > pd.Timestamp(rec["date"])]["Close"]
            h = len(v["pred"])
            if len(after) < h:
                continue
            real = float(after.iloc[h - 1])
            pr = float(v["pred"][-1])
            rr, pp = real / v["last"] - 1, pr / v["last"] - 1
            done.append({"date": rec["date"], "t": t, "pred": round(pp * 100, 2), "real": round(rr * 100, 2)})
            hit += (rr > 0) == (pp > 0)
            err.append(abs(rr - pp) * 100)
    if not done:
        return {"n": 0}
    return {"n": len(done), "hit": round(hit / len(done) * 100), "mae": round(float(np.mean(err)), 2), "recent": done[-12:]}


# ---------------------------------------------------------------- ② 배분 (skfolio)
def _returns(hist: dict[str, pd.DataFrame], tickers: list[str], upto=None, days: int = 252) -> pd.DataFrame:
    px = pd.DataFrame({t: hist[t]["Close"] for t in tickers if t in hist})
    if upto is not None:
        px = px.loc[px.index <= upto]
    px = px.tail(days + 1).dropna(axis=1, thresh=int(days * 0.8)).ffill().dropna()
    return px.pct_change().dropna()


def _max_w(n: int) -> float:
    return min(1.0, max(0.25, 1.0 / n + 0.05))


def allocate(X: pd.DataFrame, views: dict[str, float] | None = None) -> dict:
    """X: 일간 수익률. views: {티커: 예상 일간 수익률} (Kronos). 반환 {"meanrisk":{}, "hrp":{}, "equal":{}, "prior":...}"""
    from skfolio.optimization import EqualWeighted, HierarchicalRiskParity, MeanRisk, ObjectiveFunction
    from skfolio.prior import BlackLitterman, EmpiricalPrior

    cols = list(X.columns)
    n = len(cols)
    out = {"assets": cols}
    v = {t: x for t, x in (views or {}).items() if t in cols and x is not None and math.isfinite(x)}
    prior = BlackLitterman(views=[f"{t} == {x:.6f}" for t, x in v.items()], tau=0.05) if v else EmpiricalPrior()
    out["prior"] = f"Black-Litterman (Kronos 예측 {len(v)}종목을 '견해'로)" if v else "과거 1년 평균(예측 없음)"

    def fit(model):
        model.fit(X)
        return {c: round(float(w), 4) for c, w in zip(cols, model.weights_) if w > 0.0005}
    try:
        out["meanrisk"] = fit(MeanRisk(objective_function=ObjectiveFunction.MAXIMIZE_RATIO, prior_estimator=prior, max_weights=_max_w(n)))
    except Exception as e:
        log.info("MeanRisk(BL) 실패 → 과거 평균으로: %s", e)
        out["meanrisk"] = fit(MeanRisk(objective_function=ObjectiveFunction.MAXIMIZE_RATIO, max_weights=_max_w(n)))
        out["prior"] += " → 실패해서 과거 1년 평균"
    out["hrp"] = fit(HierarchicalRiskParity())
    out["equal"] = fit(EqualWeighted())
    return out


def weight_fn(kind: str):
    """백테스트용: 그 주까지의 1년 수익률로만 비중 계산 (미래 정보 없음). 예측(Kronos)은 과거 주마다 없으니 쓰지 않아요."""
    from skfolio.optimization import EqualWeighted, HierarchicalRiskParity, MeanRisk, ObjectiveFunction

    def f(day, past):
        X = _returns(past, [t for t in past if t != BENCH], days=252)
        if X.shape[0] < 120 or X.shape[1] < 2:
            return {t: 1 / len(X.columns) for t in X.columns} if X.shape[1] else {}
        m = {"meanrisk": lambda: MeanRisk(objective_function=ObjectiveFunction.MAXIMIZE_RATIO, max_weights=_max_w(X.shape[1])),
             "hrp": HierarchicalRiskParity, "equal": EqualWeighted}[kind]()
        m.fit(X)
        return dict(zip(X.columns, m.weights_))
    return f


# ---------------------------------------------------------------- ③ 실행 (Nautilus 백테스트)
def backtest(hist: dict[str, pd.DataFrame], tickers: list[str]) -> dict:
    import fund_backtest as fb
    h = {t: hist[t] for t in tickers if t in hist and len(hist[t]) >= 380}
    out = {}
    if len(h) < 2:
        return {"skip": "2년 치 일봉이 있는 종목이 2개 미만이라 백테스트를 건너뛰었어요"}
    start = None
    for kind in ("meanrisk", "hrp", "equal"):
        try:
            r = fb.run(h, weight_fn(kind), start=start)
        except Exception as e:
            log.warning("백테스트 실패 %s: %s", kind, e)
            out[kind] = {"err": str(e)[:200]}
            continue
        if r:
            start = start or r["curve"][0][0]
            out[kind] = dict(fb.stats(r["curve"]), trades=r["trades"], fees=r["fees"], last_w=(r["rebalances"] or [{}])[-1].get("w"),
                             curve=_thin(r["curve"]))
    b = hist.get(BENCH)
    if b is not None and start:
        s = b["Close"].loc[b.index >= pd.Timestamp(start)]
        curve = [[str(i.date()), round(float(v) / float(s.iloc[0]) * fb.START_CASH, 2)] for i, v in s.items()]
        out["spy"] = dict(fb.stats(curve), curve=_thin(curve))
    out["start"], out["fee"], out["engine"] = start, "0.1%", "NautilusTrader BacktestEngine (가상 $100,000 · 정수 주식 · 매주 첫 거래일 리밸런싱)"
    return out


def _thin(curve: list, n: int = 60) -> list:
    step = max(1, len(curve) // n)
    c = curve[::step]
    return c if c[-1] == curve[-1] else c + [curve[-1]]


# ---------------------------------------------------------------- 전체
TASK = """목표: 초보자가 30초 안에 읽는 '이번 주 펀드매니저 한 장 보고서'를 써줘.
자료: ①예측(Kronos, 5거래일) ②비중(skfolio) ③과거 검증(NautilusTrader, 매주 리밸런싱·수수료 0.1%) ④지난 예측 채점.
규칙:
- 숫자는 자료에 있는 것만. 새로 계산하지 마. 예측·과거 검증은 '참고'이고 수익을 보장하지 않는다고 한 번만.
- 사라·팔라 금지. '다음 주에 확인해 볼 것' 형태로.
- 예측 적중률이 50% 근처거나 표본이 적으면 그 사실을 먼저 말해.
출력 JSON:
{"한 줄":"","무엇이 통했나":["",""],"위험":["",""],"다음 주에 바꿔 볼 것":["",""],"예시":"생활 비유 한 줄"}"""


def build(store, cfg: dict) -> dict:
    import ai
    import config
    import prices
    now = config.now_kst()
    tickers = universe(store)
    hist = prices.download_history(tickers + [BENCH], period="2y", batch=50, pause=1)
    tickers = [t for t in tickers if t in hist and len(hist[t]) > 130]
    try:
        old = json.loads(store.get_blob("ai") or "{}").get("fund") or {}
    except Exception:
        old = {}
    res = {"at": now.isoformat(timespec="minutes"), "tickers": tickers, "steps": {}}
    if len(tickers) < 2:
        res["why"] = "분석할 종목이 2개 미만이에요 (보유·모의·후보 합계)"
        return res
    # ① 예측
    fc = load_forecast(tickers)
    res["forecast"] = fc
    res["steps"]["예측 (Kronos)"] = {"ok": bool(fc), "d": f"{len(fc.get('items', {}))}종목 · {fc.get('model', '')} · {fc.get('at', '')}" if fc
                                     else "이번 주 예측 파일이 없어요 (Kronos 단계가 꺼져 있거나 실패) — 과거 평균으로 배분"}
    hist_fc = [h for h in (old.get("forecast_hist") or []) if h.get("date") != (fc.get("date") or "")]
    if fc:
        hist_fc = [{"date": fc.get("date"), "items": {t: {"last": v["last"], "pred": v["pred"]} for t, v in fc["items"].items()}}] + hist_fc
    res["forecast_hist"] = hist_fc[:12]
    res["forecast_score"] = score_forecasts(hist_fc, hist)
    # ② 배분
    X = _returns(hist, tickers)
    views = {t: v["exp_ret"] / max(1, len(v.get("pred") or [1])) for t, v in (fc.get("items") or {}).items()}
    try:
        res["weights"] = allocate(X, views)
        res["steps"]["배분 (skfolio)"] = {"ok": True, "d": f"{X.shape[1]}종목 · {res['weights']['prior']}"}
    except Exception as e:
        log.warning("배분 실패: %s", e)
        res["steps"]["배분 (skfolio)"] = {"ok": False, "d": str(e)[:160]}
    # ③ 실행
    try:
        bt = backtest(hist, tickers)
        res["backtest"] = bt
        ok = any(isinstance(bt.get(k), dict) and "ret" in bt[k] for k in ("meanrisk", "hrp", "equal"))
        res["steps"]["실행 (NautilusTrader)"] = {"ok": ok if "skip" not in bt else None, "d": bt.get("skip") or f"{bt.get('start')}부터 · 수수료 0.1%"}
    except Exception as e:
        log.warning("백테스트 실패: %s", e)
        res["steps"]["실행 (NautilusTrader)"] = {"ok": False, "d": str(e)[:160]}
    # ④ 감독 (Vibe-Trading 파일이 있으면 그것, 없으면 앱의 GPT가 같은 형식으로)
    vibe = ""
    try:
        vibe = VIBE_FILE.read_text(encoding="utf-8").strip()[:6000]
    except Exception:
        pass
    if vibe:
        res["vibe"] = vibe
        res["steps"]["감독 (Vibe-Trading)"] = {"ok": True, "d": "Vibe-Trading 에이전트 보고서"}
    else:
        res["steps"]["감독 (Vibe-Trading)"] = {"ok": None, "d": "자동 실행은 안 해요 — 앱 GPT가 같은 형식(통한 것·위험·다음 주)으로 정리. Vibe-Trading은 PC에서 직접 돌려 data/fund_vibe.md로 붙일 수 있어요"}
    ai.init(store, cfg)
    brief = {"예측": {t: {"지금": v["last"], "5일 뒤 예측": v["pred"][-1], "예상 %": round(v["exp_ret"] * 100, 2)} for t, v in (fc.get("items") or {}).items()},
             "비중": {k: res.get("weights", {}).get(k) for k in ("meanrisk", "hrp", "equal")},
             "과거 검증": {k: {x: y for x, y in (res.get("backtest", {}).get(k) or {}).items() if x in ("ret", "cagr", "vol", "mdd", "sharpe", "trades")}
                       for k in ("meanrisk", "hrp", "equal", "spy")},
             "지난 예측 채점": {k: v for k, v in res["forecast_score"].items() if k != "recent"}}
    res["brief"] = brief
    rep = ai.checked("펀드매니저 보고서", TASK, brief, "big", 6000, 150, keep_unchecked=True)
    if rep:
        res["report"] = rep
    ai.flush()
    return res


def save(store, res: dict):
    ab = json.loads(store.get_blob("ai") or "{}")
    ab["fund"] = res
    store.put_blob("ai", json.dumps(ab, ensure_ascii=False, default=str))


if __name__ == "__main__":  # python fund.py — 주간 실행 (fund.yml) 또는 수동
    import config
    from sheets import Store
    logging.basicConfig(level=logging.INFO)
    st = Store()
    cfg, _ = config.merge_settings(st.settings())
    argv = __import__("sys").argv
    if "--universe" in argv:   # Kronos 단계에 넘길 종목 목록만 출력
        print(" ".join(universe(st) + [BENCH]))
        raise SystemExit
    if "--attach-vibe" in argv:  # ④ Vibe-Trading 보고서를 붙이기만
        ab = json.loads(st.get_blob("ai") or "{}")
        f = ab.get("fund") or {}
        try:
            v = VIBE_FILE.read_text(encoding="utf-8").strip()[:6000]
        except Exception:
            v = ""
        f.setdefault("steps", {})["감독 (Vibe-Trading)"] = ({"ok": True, "d": "Vibe-Trading 에이전트 보고서"} if v else
                                                           {"ok": False, "d": "Vibe-Trading이 보고서를 만들지 못했어요 — 앱 GPT 보고서를 보세요"})
        if v:
            f["vibe"] = v
        ab["fund"] = f
        st.put_blob("ai", json.dumps(ab, ensure_ascii=False, default=str))
        print("Vibe-Trading 보고서", "붙임" if v else "없음")
        raise SystemExit
    out = build(st, cfg)
    save(st, out)
    for k, v in out.get("steps", {}).items():
        print(("✓" if v["ok"] else "✕" if v["ok"] is False else "–"), k, "·", v["d"])
    for k in ("meanrisk", "hrp", "equal", "spy"):
        b = (out.get("backtest") or {}).get(k) or {}
        print(f"  {k:9s} 수익 {b.get('ret')}% · 샤프 {b.get('sharpe')} · 최대낙폭 {b.get('mdd')}% · 거래 {b.get('trades')}")
