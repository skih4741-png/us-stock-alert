"""후보 발굴용 '자리(셋업)' 탐지 + 과거 승률(엣지) 검증.

- 셋업 3가지(일봉 기준): 돌파 · 눌림목 · 과매도 반등.
- 엣지: 같은 셋업이 그 종목 과거에 나왔을 때, backtest.simulate(다음 날 시가 매수 → 손절·목표 규칙)로
  이긴 비율(목표 먼저)과 평균 수익을 구해요. 동전 던지기(승률 낮음·기대값 0 이하)면 거릅니다.
- 전부 '추가 정보'일 뿐, 기존 점수·판정은 바꾸지 않아요(안전). GPT 아님.
"""
from __future__ import annotations

import backtest

# 셋업 기준 (일봉)
BREAKOUT_DD = -0.03      # 52주 신고가 3% 이내
BREAKOUT_VOLR = 1.5      # 거래량 20일 평균의 1.5배 이상
BOUNCE_RSI = 35.0        # 과매도
MIN_SAMPLES = 8          # 이보다 적으면 '자료 부족'
EDGE_WIN = 55.0          # 이김 비율(%) 기준
MAX_SAMPLES = 80         # 과거 표본 상한(최근 것부터)
GAP = 5                  # 표본 사이 최소 간격(겹침 방지)

# '엄선 후보' 기준 (엄격) — 과거 승률 최상위 순수종목만. 보장이 아니라 확률이 가장 좋은 것.
ELITE_WIN = 65.0
ELITE_N = 12
ELITE_RR = 1.5


def is_elite(edge: dict | None, rr: float | None) -> bool:
    """엄선(고확신) 여부: 엣지 통과 + 이김 ≥ 65% + 표본 ≥ 12 + 평균 > 0 + 손익비 ≥ 1.5."""
    if not edge or not edge.get("ok"):
        return False
    return bool((edge.get("win") or 0) >= ELITE_WIN and (edge.get("n") or 0) >= ELITE_N
                and (edge.get("avg") or 0) > 0 and (rr or 0) >= ELITE_RR)


def detect(t: dict) -> str | None:
    """최신 봉의 자리(셋업) 이름. 우선순위: 돌파 → 눌림목 → 과매도 반등."""
    if not t:
        return None
    dd, volr, rsi = t.get("drawdown"), t.get("vol_ratio"), t.get("rsi")
    ma20, ma50, ma200, close = t.get("ma20"), t.get("ma50"), t.get("ma200"), t.get("close")
    ret5 = t.get("ret5")
    if dd is not None and volr is not None and dd >= BREAKOUT_DD and volr >= BREAKOUT_VOLR:
        return "돌파"
    if (ma20 and ma50 and ma200 and close and ma20 > ma50 > ma200
            and close >= ma50 and close <= ma20 and (ret5 is None or ret5 <= 0.02)):
        return "눌림목"
    if rsi is not None and ma200 and close and close > ma200 and rsi < BOUNCE_RSI:
        return "과매도 반등"
    return None


def _mask(o, setup: str):
    if setup == "돌파":
        return (o.dd >= BREAKOUT_DD) & (o.volr >= BREAKOUT_VOLR)
    if setup == "눌림목":
        return (o.ma20 > o.ma50) & (o.ma50 > o.ma200) & (o.close >= o.ma50) & (o.close <= o.ma20) & (o.ret5 <= 0.02)
    if setup == "과매도 반등":
        return (o.close > o.ma200) & (o.rsi < BOUNCE_RSI)
    return None


def edge(df, rr: float, cfg: dict, setup: str | None) -> dict | None:
    """같은 셋업의 과거 표본으로 '목표 먼저 vs 손절 먼저' 비율과 평균 수익을 구해요."""
    if not setup or df is None or len(df) < 260:
        return None
    try:
        o = backtest.indicator_frame(df)
    except Exception:
        return None
    m = _mask(o, setup)
    if m is None:
        return None
    m = m.fillna(False).to_numpy()
    n = len(o)
    idxs = [i for i in range(200, n - 2) if m[i]]
    # 겹침 방지 + 최근 표본 우선
    picked, last = [], -10 ** 9
    for i in idxs:
        if i - last >= GAP:
            picked.append(i); last = i
    picked = picked[-MAX_SAMPLES:]
    rets = []
    for i in picked:
        try:
            res = backtest.simulate(o, i, rr, cfg)
        except Exception:
            res = None
        if res and not res.get("skipped") and "ret" in res:
            rets.append(res["ret"])
    k = len(rets)
    if k == 0:
        return {"setup": setup, "n": 0, "win": None, "avg": None, "ok": False, "label": "자료 부족"}
    wins = sum(1 for r in rets if r > 0)
    win_pct = int(round(wins / k * 100))
    avg = round(float(sum(rets)) / k * 100, 1)
    enough = k >= MIN_SAMPLES
    ok = bool(enough and win_pct >= EDGE_WIN and avg > 0)
    label = ("엣지 있음" if ok else ("자료 부족" if not enough else "동전 던지기"))
    return {"setup": setup, "n": int(k), "win": win_pct, "loss": 100 - win_pct, "avg": avg, "ok": ok, "label": label}
