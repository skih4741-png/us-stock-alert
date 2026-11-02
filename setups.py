"""후보 발굴용 '자리(셋업)' 탐지 + 과거 승률(엣지) 검증.

- 셋업 3가지(일봉 기준): 돌파 · 눌림목 · 과매도 반등.
- 엣지: 같은 셋업이 그 종목 과거에 나왔을 때, backtest.simulate(다음 날 시가 매수 → 손절·목표 규칙)로
  이긴 비율(목표 먼저)과 평균 수익을 구해요. 동전 던지기(승률 낮음·기대값 0 이하)면 거릅니다.
- 전부 '추가 정보'일 뿐, 기존 점수·판정은 바꾸지 않아요(안전). GPT 아님.
"""
from __future__ import annotations

import math

import backtest

# 셋업 기준 (일봉)
BREAKOUT_DD = -0.03      # 52주 신고가 3% 이내
BREAKOUT_VOLR = 1.5      # 거래량 20일 평균의 1.5배 이상
BOUNCE_RSI = 35.0        # 과매도
MIN_SAMPLES = 8          # 이보다 적으면 '자료 부족'
EDGE_WIN = 55.0          # 이김 비율(%) 기준
MAX_SAMPLES = 80         # 과거 표본 상한(최근 것부터)
GAP = 5                  # 표본 사이 최소 간격(겹침 방지)

# 모의 검증용 균형 기준. 표본이 적으므로 실제 수익 보장이나 실전 승인이 아니에요.
ELITE_WIN = 55.0
ELITE_N = 8
ELITE_RR = 1.5

# 과적합(운으로 좋아 보이는 것) 방어 — lazyowen 자기개선 루프 방법론 차용.
HOLDOUT_FRAC = 0.30     # 최근 30% 표본은 '봉인 구간'(한 번만 검증용)
STRESS_COST = 0.007     # 왕복 비용 2배 스트레스: 추가로 0.7%p 더 불리하게
WILSON_Z = 1.64         # 윌슨 하한(한쪽 95%) — 표본 적으면 승률을 보수적으로 깎음
WIN_LB_MIN = 50.0       # 승률 하한이 이보다 낮으면 '동전 던지기와 통계적으로 구분 안 됨'
HOLDOUT_MIN = 4         # 봉인 구간 표본이 이보다 적으면 판단 보류
HOLDOUT_WIN = 50.0      # 봉인 구간 목표 도달률이 이보다 낮으면 '무너짐'


def _wilson_lb(wins: int, n: int, z: float = WILSON_Z) -> float:
    """승률의 윌슨 점수 하한(%). 표본이 적을수록 더 많이 깎여요 — 디플레이티드 샤프와 같은 취지."""
    if n <= 0:
        return 0.0
    p = wins / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return round(max(0.0, (center - margin) / denom) * 100, 1)


def is_elite(edge: dict | None, rr: float | None) -> bool:
    """비용 차감 기대값 + 과적합 방어(봉인 구간·비용 스트레스·표본 보정)를 통과한 모의 후보 여부."""
    if not edge or not edge.get("ok"):
        return False
    return bool((edge.get("win") or 0) >= ELITE_WIN and (edge.get("n") or 0) >= ELITE_N
                and (edge.get("avg") or 0) > 0 and (edge.get("avg_r") or 0) > 0
                and (rr or 0) >= ELITE_RR and edge.get("robust"))


def exclusion(p: dict) -> str:
    """후보별 첫 탈락 이유. 앱과 모의 주문이 같은 기준을 사용해요."""
    e, pl = p.get("edge") or {}, p.get("plan") or {}
    if p.get("etf"):
        return "ETF·펀드 제외"
    if not p.get("setup"):
        return "셋업 없음"
    if (e.get("n") or 0) < ELITE_N:
        return "완료 표본 부족"
    if (e.get("win") or 0) < ELITE_WIN:
        return "목표 도달률 미달"
    if (e.get("avg") or 0) <= 0 or (e.get("avg_r") or 0) <= 0:
        return "비용 차감 기대값 미달"
    if (pl.get("rr") or 0) < ELITE_RR:
        return "손익비 미달"
    if not e.get("robust"):
        return "과적합 방어 미통과(표본·비용·봉인)"
    return "" if is_elite(e, pl.get("rr")) else "엣지 검증 미통과"


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
    rets, targets, stops, rs = [], [], [], []
    for i in picked:
        try:
            res = backtest.simulate(o, i, rr, cfg)
        except Exception:
            res = None
        if res and not res.get("skipped") and res.get("complete") and "ret" in res:
            # 자동 모의투자와 같은 왕복 비용 추정(한쪽 0.35%).
            net = (1 + res["ret"]) * (1 - 0.0035) / (1 + 0.0035) - 1
            rets.append(net)
            targets.append(bool(res.get("target_hit")))
            stops.append(res.get("exit") == "손절")
            rs.append(net / res["risk"])
    k = len(rets)
    if k == 0:
        return {"setup": setup, "n": 0, "win": None, "avg": None, "ok": False, "label": "자료 부족"}
    wins = sum(targets)
    win_pct = int(round(wins / k * 100))
    avg = round(float(sum(rets)) / k * 100, 1)
    enough = k >= MIN_SAMPLES
    ok = bool(enough and win_pct >= EDGE_WIN and avg > 0)
    label = ("엣지 있음" if ok else ("자료 부족" if not enough else "동전 던지기"))

    # ---- 과적합 방어 3종 (표본은 과거→현재 순서) ----
    # ① 표본 보정: 승률의 윌슨 하한(표본 적으면 깎임)
    win_lb = _wilson_lb(wins, k)
    # ② 비용 스트레스: 왕복 비용을 2배로 더 물려도 평균이 +인가
    avg_stress = round((float(sum(rets)) / k - STRESS_COST) * 100, 1)
    # ③ 봉인 구간: 최근 30% 표본은 따로 떼어, 거기서도 안 무너지는가
    cut = int(k * (1 - HOLDOUT_FRAC))
    hold_targets = targets[cut:]
    hold_n = len(hold_targets)
    hold_win = int(round(sum(hold_targets) / hold_n * 100)) if hold_n else None
    holdout_ok = (hold_n < HOLDOUT_MIN) or (hold_win is not None and hold_win >= HOLDOUT_WIN)
    robust = bool(ok and win_lb >= WIN_LB_MIN and avg_stress > 0 and holdout_ok)

    return {"setup": setup, "n": int(k), "win": win_pct, "loss": 100 - win_pct, "avg": avg, "ok": ok, "label": label,
            "stop": int(round(sum(stops) / k * 100)), "profit_win": int(round(sum(r > 0 for r in rets) / k * 100)),
            "avg_r": round(sum(rs) / k, 2), "cost_included": True,
            "win_lb": win_lb, "avg_stress": avg_stress, "hold_win": hold_win, "hold_n": int(hold_n), "robust": robust}
