"""에이전트 심층분석 — 재무·적정가 에이전트 (Fundamental + Valuation).

종목 하나의 재무 자료(financials.fetch() 결과)와 현재가를 받아
① 버핏 체크리스트(해자·수익성·안정성·현금흐름)
② 적정가 3방식 — 그레이엄 넘버 · 적정 PER 밴드 · 간이 2단계 DCF
③ 종합 적정가 범위 + 현재가 대비 안전마진(%)
④ 한 줄 판정(저평가/적정/고평가)
을 계산해요. 모두 '자료에 있는 숫자만' 쓰고, 없으면 「확인 못 함」. 투자 권유가 아니라 관찰·참고용이에요.

입력(fin): financials.fetch() 모양 = {"years":[...], "rows":{키:[연도별 값]}}.
  rows 키(financials.py와 동일): net, equity, shares_avg, shares_out, fcf, ocf, capex,
  revenue, op, lt_debt, cur_assets, cur_liab, assets, liab, cash, interest 등.
"""
from __future__ import annotations

import math

# 적정가 가정(보수적). 시트 '설정'의 같은 이름으로 덮어쓸 수 있어요.
DEFAULTS = {
    "DCF 할인율": 0.10,        # r: 요구수익률 10%
    "DCF 성장률 상한": 0.12,   # 1단계 성장률 상한(과거 성장 그대로 안 믿어요)
    "DCF 영구성장률": 0.025,   # g_term: 2.5%
    "DCF 1단계 연수": 5,       # 고성장 유지 5년
    "DCF 감쇠 연수": 5,        # 이후 5년에 걸쳐 영구성장률로 감쇠
    "적정 PER 상한": 20.0,     # 그레이엄식 — 성장주라도 함부로 높이지 않음
    "안전마진 기준": 0.25,     # 현재가가 적정가보다 25% 이상 낮으면 '저평가'
}


def _f(v):
    try:
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else f
    except (TypeError, ValueError):
        return None


def _series(rows: dict, key: str) -> list:
    """연도별 값 리스트(None 포함). 오래된→최신 순으로 본다고 가정."""
    xs = rows.get(key) if isinstance(rows, dict) else None
    return [_f(x) for x in xs] if isinstance(xs, list) else []


def _last(xs, k=1):
    vals = [x for x in xs if x is not None]
    return vals[-k] if len(vals) >= k else None


def _cagr(xs, years: int) -> float | None:
    """처음→끝 연평균 성장률. 음수/0 시작은 불가 → None."""
    vals = [x for x in xs if x is not None]
    if len(vals) < 2:
        return None
    first, last = vals[0], vals[-1]
    if first is None or first <= 0 or last is None or last <= 0:
        return None
    n = years if years and years > 0 else (len(vals) - 1)
    try:
        return (last / first) ** (1.0 / n) - 1.0
    except (ValueError, ZeroDivisionError):
        return None


def _eps_series(rows: dict) -> list:
    net = _series(rows, "net")
    sh = _series(rows, "shares_avg") or _series(rows, "shares_out")
    out = []
    for i, n in enumerate(net):
        s = sh[i] if i < len(sh) else None
        out.append(n / s if (n is not None and s not in (None, 0)) else None)
    return out


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ---------------------------------------------------------------- 버핏 체크리스트
def buffett_checklist(rows: dict) -> dict:
    """해자·수익성·안정성·현금흐름을 5개 항목으로. 각 항목 ok(True/False/None)."""
    net = _series(rows, "net")
    eq = _series(rows, "equity")
    rev = _series(rows, "revenue")
    op = _series(rows, "op")
    fcf = _series(rows, "fcf")
    ocf = _series(rows, "ocf")
    capex = _series(rows, "capex")
    cur_a = _last(_series(rows, "cur_assets"))
    cur_l = _last(_series(rows, "cur_liab"))
    debt = _last(_series(rows, "lt_debt"))
    eq_last = _last(eq)

    roe = (_last(net) / eq_last) if (eq_last not in (None, 0)) else None
    op_margin = (_last(op) / _last(rev)) if (_last(rev) not in (None, 0)) else None
    cur_ratio = (cur_a / cur_l) if (cur_l not in (None, 0)) else None
    debt_eq = (debt / eq_last) if (eq_last not in (None, 0) and debt is not None) else None
    # FCF: financials에 fcf 없으면 ocf - |capex| 로
    fcf_last = _last(fcf)
    if fcf_last is None and _last(ocf) is not None and _last(capex) is not None:
        fcf_last = _last(ocf) - abs(_last(capex))
    net_pos = [x for x in net if x is not None]
    profit_streak = bool(net_pos) and all(x > 0 for x in net_pos[-4:])

    items = [
        {"n": "꾸준한 흑자", "ok": profit_streak if net_pos else None,
         "d": f"최근 {min(4, len(net_pos))}년 순이익 모두 흑자" if profit_streak else "적자 해 있음"},
        {"n": "높은 ROE(≥12%)", "ok": (roe is not None and roe >= 0.12) if roe is not None else None,
         "d": (f"ROE {roe * 100:.1f}%" if roe is not None else "확인 못 함")},
        {"n": "탄탄한 영업마진(≥10%)", "ok": (op_margin is not None and op_margin >= 0.10) if op_margin is not None else None,
         "d": (f"영업마진 {op_margin * 100:.1f}%" if op_margin is not None else "확인 못 함")},
        {"n": "건전한 부채(부채/자본 ≤1)", "ok": (debt_eq is not None and debt_eq <= 1.0) if debt_eq is not None else None,
         "d": (f"장기부채/자본 {debt_eq:.2f}" if debt_eq is not None else "확인 못 함")},
        {"n": "플러스 잉여현금(FCF>0)", "ok": (fcf_last is not None and fcf_last > 0) if fcf_last is not None else None,
         "d": ("FCF 플러스" if (fcf_last is not None and fcf_last > 0) else ("FCF 마이너스" if fcf_last is not None else "확인 못 함"))},
    ]
    passed = sum(1 for i in items if i["ok"] is True)
    checked = sum(1 for i in items if i["ok"] is not None)
    return {"items": items, "passed": passed, "checked": checked,
            "roe": roe, "op_margin": op_margin, "cur_ratio": cur_ratio,
            "debt_eq": debt_eq, "fcf": fcf_last}


# ---------------------------------------------------------------- 적정가 3방식
def graham_number(eps: float | None, bps: float | None) -> float | None:
    """√(22.5 × EPS × BPS). 그레이엄의 방어적 상한선. EPS·BPS 둘 다 양수일 때만."""
    if eps is None or bps is None or eps <= 0 or bps <= 0:
        return None
    return math.sqrt(22.5 * eps * bps)


def per_band_value(eps: float | None, growth: float | None, cfg: dict) -> dict:
    """적정 PER × EPS. 적정 PER = min(상한, 8 + 성장률%×1.5) — PEG 느낌, 보수적."""
    cap = float(cfg.get("적정 PER 상한", DEFAULTS["적정 PER 상한"]))
    if eps is None or eps <= 0:
        return {"value": None, "per": None}
    g_pct = (growth * 100) if growth is not None else 0.0
    fair_per = _clamp(8.0 + g_pct * 1.5, 8.0, cap)
    return {"value": fair_per * eps, "per": round(fair_per, 1)}


def dcf_value(fcf_ps: float | None, growth: float | None, cfg: dict) -> dict:
    """보수적 2단계 DCF(주당 FCF): 1단계 고성장 N년 → 2단계 영구성장률로 선형 감쇠 N년 → 영구가치.
    성장률이 할인율을 넘어도 폭주하지 않게 감쇠 구간을 둬요."""
    if fcf_ps is None or fcf_ps <= 0:
        return {"value": None}
    r = float(cfg.get("DCF 할인율", DEFAULTS["DCF 할인율"]))
    g1_cap = float(cfg.get("DCF 성장률 상한", DEFAULTS["DCF 성장률 상한"]))
    g_term = float(cfg.get("DCF 영구성장률", DEFAULTS["DCF 영구성장률"]))
    n1 = int(cfg.get("DCF 1단계 연수", DEFAULTS["DCF 1단계 연수"]))
    n2 = int(cfg.get("DCF 감쇠 연수", DEFAULTS["DCF 감쇠 연수"]))
    if r <= g_term:
        return {"value": None}
    g1 = _clamp(growth if growth is not None else 0.04, 0.0, g1_cap)
    pv, cash, t = 0.0, fcf_ps, 0
    for _ in range(n1):                       # 1단계: 고성장 유지
        t += 1
        cash *= (1.0 + g1)
        pv += cash / ((1.0 + r) ** t)
    for j in range(1, n2 + 1):                # 2단계: g1 → g_term 선형 감쇠
        t += 1
        g = g1 + (g_term - g1) * (j / n2)
        cash *= (1.0 + g)
        pv += cash / ((1.0 + r) ** t)
    terminal = cash * (1.0 + g_term) / (r - g_term)
    pv += terminal / ((1.0 + r) ** t)
    return {"value": pv, "g1": round(g1 * 100, 1)}


def _median(xs: list) -> float | None:
    vals = sorted(v for v in xs if v is not None)
    if not vals:
        return None
    m = len(vals) // 2
    return vals[m] if len(vals) % 2 else (vals[m - 1] + vals[m]) / 2.0


# ---------------------------------------------------------------- 종합
def analyze(fin: dict | None, price: float | None, shares: float | None = None,
            cfg: dict | None = None) -> dict | None:
    """재무·적정가 에이전트 종합. 반환: 앱에 그대로 올릴 수 있는 dict(또는 None)."""
    cfg = cfg or {}
    if not isinstance(fin, dict):
        return None
    rows = fin.get("rows") or {}
    years = fin.get("years") or []
    price = _f(price)

    eps_s = _eps_series(rows)
    eps = _last(eps_s)
    eq = _series(rows, "equity")
    sh = shares or _last(_series(rows, "shares_out")) or _last(_series(rows, "shares_avg"))
    bps = (_last(eq) / sh) if (sh not in (None, 0)) else None
    fcf_s = _series(rows, "fcf")
    fcf_last = _last(fcf_s)
    if fcf_last is None:
        ocf, capex = _last(_series(rows, "ocf")), _last(_series(rows, "capex"))
        if ocf is not None and capex is not None:
            fcf_last = ocf - abs(capex)
    fcf_ps = (fcf_last / sh) if (sh not in (None, 0) and fcf_last is not None) else None

    # 성장률: EPS CAGR 우선, 없으면 매출 CAGR
    nyr = max(1, len([y for y in years if y]) - 1)
    growth = _cagr(eps_s, nyr)
    if growth is None:
        growth = _cagr(_series(rows, "revenue"), nyr)

    methods = {
        "그레이엄 넘버": graham_number(eps, bps),
        "적정 PER": per_band_value(eps, growth, cfg).get("value"),
        "간이 DCF": dcf_value(fcf_ps, growth, cfg).get("value"),
    }
    vals = [v for v in methods.values() if v is not None and v > 0]
    fair_low = min(vals) if vals else None
    fair_high = max(vals) if vals else None
    fair_mid = _median(vals)   # 중앙값 — 한 방식이 튀어도 덜 휘둘려요

    margin = None
    if fair_mid is not None and price not in (None, 0):
        margin = (fair_mid - price) / fair_mid   # +면 저평가

    thr = float(cfg.get("안전마진 기준", DEFAULTS["안전마진 기준"]))
    if margin is None:
        verdict, why = "확인 못 함", "적정가를 계산할 자료가 부족해요"
    elif margin >= thr:
        verdict, why = "저평가", f"현재가가 적정가 중앙값보다 {margin * 100:.0f}% 낮아요(안전마진 확보)"
    elif margin <= -0.10:
        verdict, why = "고평가", f"현재가가 적정가 중앙값보다 {-margin * 100:.0f}% 높아요"
    else:
        verdict, why = "적정", "현재가가 적정가 범위 근처예요"

    chk = buffett_checklist(rows)
    return {
        "eps": round(eps, 2) if eps is not None else None,
        "bps": round(bps, 2) if bps is not None else None,
        "fcf_ps": round(fcf_ps, 2) if fcf_ps is not None else None,
        "growth_pct": round(growth * 100, 1) if growth is not None else None,
        "methods": {k: (round(v, 2) if v is not None else None) for k, v in methods.items()},
        "fair_low": round(fair_low, 2) if fair_low is not None else None,
        "fair_mid": round(fair_mid, 2) if fair_mid is not None else None,
        "fair_high": round(fair_high, 2) if fair_high is not None else None,
        "price": price,
        "margin_pct": round(margin * 100, 1) if margin is not None else None,
        "verdict": verdict, "why": why,
        "buffett": {"passed": chk["passed"], "checked": chk["checked"], "items": chk["items"]},
        "note": "관찰·참고용 — 매수/매도 권유 아님. 가정이 바뀌면 적정가도 바뀌어요.",
    }


# ---------------------------------------------------------------- 매수·매도 적용
# 위원회(committee)와 같은 철학: '더 조심하는 쪽으로만' 작용해요.
#  - 매수: 심하게 고평가 + 재무 부실이면 '매수 반대(거부)'. 규칙이 산 걸 새로 사지는 않아요.
#  - 매도: 보유 종목이 적정가보다 크게 고평가면 '정리 고려 신호'. 손절을 막지는 않아요.
VETO_MARGIN = -0.25     # 현재가가 적정가 중앙값보다 25% 이상 높으면 '강한 고평가'
SOFT_MARGIN = -0.15     # 15% 이상 높으면 '주의'
WEAK_BUFFETT = 0.4      # 버핏 체크 통과율이 이 아래면 재무 부실


def verdict(analysis: dict | None) -> dict:
    """analyze() 결과에서 매수 거부·매도 신호를 뽑아요(둘 다 '안전' 방향).
    반환: {veto_buy, sell_signal, caution, score(margin), why}."""
    a = analysis or {}
    mp = a.get("margin_pct")
    margin = (mp / 100.0) if mp is not None else None
    b = a.get("buffett") or {}
    passed, checked = b.get("passed") or 0, b.get("checked") or 0
    weak_fin = (checked >= 3 and passed / checked < WEAK_BUFFETT)

    if margin is None:
        return {"veto_buy": False, "sell_signal": False, "caution": False,
                "score": None, "why": ""}

    strong_over = margin <= VETO_MARGIN
    soft_over = margin <= SOFT_MARGIN
    # 매수 거부: 강한 고평가거나, (주의 수준 고평가 + 재무 부실)
    veto_buy = bool(strong_over or (soft_over and weak_fin))
    # 매도 신호(보유용): 강한 고평가면 '정리 고려'
    sell_signal = bool(strong_over)
    why = ""
    if veto_buy or sell_signal:
        why = f"적정가 대비 {-mp:.0f}% 고평가" + ("·재무 부실" if weak_fin else "")
    elif soft_over:
        why = f"적정가 근처~소폭 고평가({-mp:.0f}%)"
    return {"veto_buy": veto_buy, "sell_signal": sell_signal,
            "caution": bool(soft_over), "score": margin, "why": why}


if __name__ == "__main__":   # 간단 자가 시험 (합성 자료)
    import json
    demo = {
        "years": [2021, 2022, 2023, 2024],
        "rows": {
            "net": [8e9, 9e9, 10e9, 12e9],
            "equity": [40e9, 42e9, 45e9, 50e9],
            "shares_out": [1e9, 1e9, 1e9, 1e9],
            "revenue": [50e9, 55e9, 60e9, 66e9],
            "op": [12e9, 13e9, 14e9, 16e9],
            "fcf": [7e9, 8e9, 9e9, 11e9],
            "lt_debt": [20e9, 20e9, 22e9, 24e9],
            "cur_assets": [30e9, 32e9, 34e9, 36e9],
            "cur_liab": [18e9, 19e9, 20e9, 21e9],
        },
    }
    for px in (90.0, 320.0):
        a = analyze(demo, price=px)
        v = verdict(a)
        print(f"\n현재가 ${px}: {a['verdict']} (적정가 중앙 ${a['fair_mid']}, 안전마진 {a['margin_pct']}%)")
        print(f"  매수거부={v['veto_buy']} 매도신호={v['sell_signal']} 주의={v['caution']} — {v['why']}")
