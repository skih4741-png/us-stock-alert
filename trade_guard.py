"""내부 모의와 증권사 모의 주문 직전에 사용하는 동일한 매수 검사."""
from __future__ import annotations

import math

POLICY = "balanced-2.19.0"


def number(x):
    try:
        n = float(x)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def validate_buy(order: dict, account: dict, cfg: dict, price=None) -> dict:
    """account는 해당 계좌에서 얻은 잔고·체결·확정손익. 모르는 값을 0으로 대체하지 않아요."""
    reasons = []
    px, stop, target, qty = [number(x) for x in
                             (price if price is not None else order.get("limit"), order.get("stop"), order.get("target"), order.get("qty"))]
    if qty is None or qty < 1 or qty != int(qty):
        reasons.append("정수 수량 오류")
    if px is None or stop is None or target is None or not 0 < stop < px < target:
        reasons.append("주문 가격·손절·목표 오류")
    ceiling = number(order.get("skip_above"))
    if px is not None and ceiling is not None and px > ceiling:
        reasons.append("추격 금지")
    if not account.get("verified", False):
        reasons.append(account.get("unverified_reason") or "계좌 확인 대기")
    if account.get("blocked"):
        reasons.append(account.get("reason") or "일일 손실 한도")
    if account.get("buys", 0) >= cfg.get("day_trades", 3):
        reasons.append("하루 매수 횟수 한도")
    if order.get("t") in account.get("held", []):
        reasons.append("이미 보유·주문 중")
    if account.get("positions", 0) >= cfg.get("max_pos", 2):
        reasons.append("보유 종목 수 한도")
    cash, equity = number(account.get("cash")), number(account.get("equity"))
    fee = cfg.get("fee", .0035)
    cost = qty * px * (1 + fee) if qty is not None and px is not None else None
    risk = qty * ((px - stop) + (px + stop) * fee) if qty is not None and px is not None and stop is not None else None
    if cash is None or equity is None or equity <= 0:
        reasons.append("잔고·평가금액 확인 대기")
    elif cost is not None:
        if cost > cash + 1e-6:
            reasons.append("현금 부족 (비용 포함)")
        if qty * px > equity * cfg.get("cap", .6) + 1e-6:
            reasons.append("한 종목 비중 한도")
        if risk is not None and risk > equity * cfg.get("risk", .03) + 1e-6:
            reasons.append("손절 위험금액 한도 (비용 포함)")
    return {"ok": not reasons, "reasons": list(dict.fromkeys(reasons)), "cost": cost, "risk": risk, "policy": POLICY}


def sim_account(st: dict, day_guard: dict) -> dict:
    cfg = st["cfg"]
    # 없는 시세를 새로 만들지 않고 마지막 평가 스냅샷을 사용.
    equity = st["equity"][-1][1] if st.get("equity") else cfg["budget"]
    return {"verified": True, "cash": st["cash"], "equity": equity, "buys": day_guard["fills"],
            "blocked": day_guard["blocked"], "reason": day_guard["reason"],
            "positions": len(st["positions"]), "held": [p["t"] for p in st["positions"]]}
