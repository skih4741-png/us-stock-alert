"""증권사 확인 체결만 반영하는 모의 주문 상태. 접수/타임아웃은 체결이 아니에요."""
from __future__ import annotations

import trade_guard


def reconcile(st, fills, day):
    # 이전 버전 접수 기록은 날짜·종목·방향까지 유일하게 맞는 조회에서만 복구.
    for o in st.get("orders", []):
        if o.get("odno") and not o.get("broker_date"):
            matches = [f for f in fills if str(f.get("odno")) == str(o["odno"]) and f.get("t") == o["t"] and f.get("side") == o["side"]]
            if len(matches) == 1:
                o["broker_date"] = matches[0].get("order_date")
            else:
                o["status"] = "확인 필요"
        elif not o.get("odno") and str(o.get("status", "")).startswith("주문 실패"):
            o["status"] = "확인 필요"
    by_id = {(f.get("order_date"), str(f.get("odno"))): f for f in fills if f.get("odno")}
    unknown_sales = []
    known_ids = {(o.get("broker_date"), str(o.get("odno"))) for o in st.get("orders", []) if o.get("odno")}
    for f in fills:
        if f.get("side") == "매도" and f.get("filled", 0) > 0 and (f.get("order_date"), str(f.get("odno"))) not in known_ids:
            unknown_sales.append(f.get("t"))
    for o in st.get("orders", []):
        f = by_id.get((o.get("broker_date"), str(o.get("odno"))))
        if not f:
            if o.get("date", day) < day and outstanding(o):
                o["status"] = "확인 필요"
            continue
        filled = trade_guard.number(f.get("filled"))
        px = trade_guard.number(f.get("price"))
        if filled is None or filled < 0 or filled > o["qty"]:
            o["status"] = "확인 필요"; continue
        o["filled"] = filled
        o["fill_price"] = px
        cancelled = any(x in str(f.get("status", "")) for x in ("취소", "거부", "거절"))
        o["status"] = ("체결 완료" if filled == o["qty"] else "취소·거절" if cancelled
                       else "부분체결" if filled else "미체결")
        if o["side"] == "매도" and filled > 0:
            if not o.get("entry") or not px:
                unknown_sales.append(o["t"])
            else:
                o["realized"] = round(filled * (px * (1 - .0035) - o["entry"] * (1 + .0035)), 4)
            if o.get("exit_kind") == "target":
                p = st.get("pos", {}).get(o["t"], {})
                p["half"] = True
                p["stop"] = p.get("entry", o.get("entry"))
    st["reconcile"] = {"date": day, "ok": not unknown_sales,
                       "unknown_sales": sorted(set(unknown_sales)), "basis": "증권사 확인 체결 · 비용 추정 0.35%씩"}


def outstanding(o):
    if o.get("status") in ("체결 완료", "취소·거절") or str(o.get("status", "")).startswith("안 냄"):
        return 0
    return max(0, o.get("qty", 0) - o.get("filled", 0))


def account(st, bal, cash, day, cfg):
    holdings = bal.get("holdings", [])
    rows = [o for o in st.get("orders", []) if o.get("date") == day]
    buys = [o for o in rows if o["side"] == "매수" and not str(o.get("status", "")).startswith("안 냄")
            and (o.get("status") != "취소·거절" or o.get("filled", 0) > 0)]
    pending = {o["t"] for o in st.get("orders", []) if o["side"] == "매수" and outstanding(o)}
    held = {h["t"] for h in holdings} | pending
    reserve = sum(outstanding(o) * o["price"] for o in st.get("orders", []) if o["side"] == "매수")
    equity = cash + reserve + sum(h["qty"] * h["now"] for h in holdings)
    snapshots = st.setdefault("equity", {})
    previous = sorted(d for d in snapshots if d < day)
    bases = st.setdefault("day_base", {})
    bases.setdefault(day, snapshots[previous[-1]] if previous else equity)
    base = bases[day]
    snapshots[day] = equity
    for key in list(snapshots):
        if key not in sorted(snapshots)[-35:]:
            snapshots.pop(key)
    pnl = sum(o.get("realized", 0) for o in rows if o["side"] == "매도")
    stopped = st.setdefault("day_stops", {})
    if pnl <= -base * cfg.get("day_loss", .03):
        stopped[day] = True
    verified = bal.get("complete", True) and st.get("reconcile", {}).get("ok", False) and not any(o.get("status") in ("전송 중", "확인 필요") for o in st.get("orders", []))
    result = {"verified": verified, "unverified_reason": "미확인 주문·외부 매도 원가 확인 필요", "cash": cash,
              "equity": equity, "buys": len(buys), "held": sorted(held), "positions": len(held),
              "blocked": bool(stopped.get(day)), "reason": "하루 확정손실 한도", "pnl": round(pnl, 2),
              "loss_limit": round(base * cfg.get("day_loss", .03), 2), "date": day,
              "base_note": "전일 저장 평가 추정액" if previous else "최초 연결 평가 추정액 (전일 스냅샷 없음)",
              "max_trades": cfg.get("day_trades", 3), "policy": trade_guard.POLICY}
    st["guard"] = result
    return result


def intent_key(side, ticker, signal, kind=""):
    return ":".join((side, ticker, signal, kind))
