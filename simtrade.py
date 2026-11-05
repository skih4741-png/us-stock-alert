"""자동 모의매매 (11장 규칙 그대로, 실제 주문 없음) — 3개월 시험 후 실전 전환 판단.

매일 아침 리포트 때 한 번 돌아요.
 1) 어제 낸 '주문 계획'을 지난 거래일 시세로 체결해 봐요 (시작가가 추격 금지선 위면 취소, 저가가 지정가 이하면 체결)
 2) 가진 종목에 매도 규칙을 날마다 적용해요 (손절 → 1차 목표 절반 + 손절을 매수가로 → 추적 손절 → 제자리)
 3) 오늘 후보로 다음 거래일 주문 계획을 세워요 (돈에 맞춰 스스로 고르기)
 4) 90일이 지나면 8가지 기준(리허설 주문표 체결률 포함)으로 실전 가능 여부를 판단해 푸시·슬랙·메일로 알려요 (실전 전환은 본인이 요청해야 해요)
수수료·환전 비용은 추정치(한쪽 0.25% + 0.10%)를 빼요.

증권사처럼 체결 (2026-10-10~):
 - 미국 장중 매시간(장중 감시 때) 5분봉으로 주문을 확인해요: 지정가를 0.1% 넘어서야 매수 체결, 손절선·목표가에 닿은 시각에 매도.
   '바로 팔기'(손절·추적 손절·제자리)는 0.15% 불리한 값(미끄러짐)으로 계산해요. 체결 시각을 같이 남겨요.
 - 아침 리포트 때는 지난 거래일 일봉으로 한 번 더 확인해요(장중에 못 본 시간대 보완). 그날 안 닿은 주문은 '미체결'.
 - 리허설 주문표: 매일 주문 계획을 증권사 앱에 그대로 넣을 모양으로 남기고, 결과(체결·미체결·안 냄)를 채점해 체결률을 실전 기준에 넣어요.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

from zoneinfo import ZoneInfo

import numpy as np

import ledger
import prices
import setups
import trade_guard

log = logging.getLogger(__name__)
KEY = "sim"          # 판단용 (가상 1,000달러, 2026-10-09 사용자 요청으로 100→1,000)
REF_KEY = "sim_ref"  # 참고용 1,000달러 · 최대 2종목 집중형 (판단용 5종목 분산과 비교, 판단에 안 씀)
FEE = 0.0025 + 0.0010      # 한쪽 거래 비용 추정 (수수료 + 환전)
SLIP = 0.0015              # 미끄러짐: 손절·추적 손절·제자리처럼 '바로 팔기'는 0.15% 불리하게 체결
TOUCH = 0.001              # 지정가에 '딱 닿기만' 하면 못 산 것으로: 0.1% 넘어서야 체결
TICKET_RATE = 0.6          # 실전 기준: 리허설 주문표 체결률
TICKET_MIN = 10
DAYS = 90                  # 시험 기간 (달력 기준)
DEFAULT = {"budget": 100.0, "max_pos": 2, "risk": 0.03, "cap": 0.6, "month_loss": 0.10, "stale_days": 15, "day_loss": 0.03, "day_trades": 3}
AVOID = ("신규 매수 보류", "재무 주의", "급등", "출렁임", "참고용")


def load(store, key: str = KEY) -> dict | None:
    try:
        raw = store.get_blob(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


def save(store, st: dict):
    store.put_blob(st.get("key", KEY), json.dumps(st, ensure_ascii=False, separators=(",", ":")))


def start(store, start_day: str, budget: float = 100.0, key: str = KEY, max_pos: int = 2) -> dict:
    st = {"v": 1, "key": key, "start": start_day, "end": (date.fromisoformat(start_day) + timedelta(days=DAYS)).isoformat(),
          "cfg": dict(DEFAULT, budget=budget, max_pos=max_pos), "cash": budget, "positions": [], "pending": [], "closed": [], "log": [],
          "equity": [], "checked": "", "violations": 0, "month_stops": [], "evaluated": None}
    save(store, st)
    return st


def _bar_after(df, day: str):
    """day 다음 첫 거래일의 (날짜, 행)."""
    idx = df.index.strftime("%Y-%m-%d")
    i = int(np.searchsorted(idx, day, side="right"))
    return (idx[i], df.iloc[i]) if i < len(df) else (None, None)


def _bars_between(df, after: str, upto: str):
    idx = df.index.strftime("%Y-%m-%d")
    for i, d in enumerate(idx):
        if after < d <= upto:
            yield d, df.iloc[i], i


def _ticket(st, t: str, signal: str, **kw):
    """리허설 주문표의 매수 한 줄을 찾아(없으면 만들어) 결과를 적어요."""
    tk = st.setdefault("tickets", [])
    for x in reversed(tk):
        if x["t"] == t and x["signal"] == signal and x["side"] == "매수":
            x.update(kw)
            return x
    x = {"t": t, "signal": signal, "side": "매수", "result": "대기"}
    x.update(kw)
    tk.append(x)
    del tk[:-200]
    return x


def ticket_stats(st: dict) -> dict:
    tk = st.get("tickets") or []
    done = [x for x in tk if x.get("result") in ("체결", "미체결")]
    filled = [x for x in done if x["result"] == "체결"]
    diffs = [(x["fill_px"] / x["limit"] - 1) * 100 for x in filled if x.get("fill_px") and x.get("limit")]
    return {"n": len(done), "filled": len(filled), "rate": (len(filled) / len(done)) if done else None,
            "skipped": sum(1 for x in tk if str(x.get("result", "")).startswith("안 냄")),
            "avg_vs_limit": round(sum(diffs) / len(diffs), 2) if diffs else None,
            "intraday": sum(1 for x in filled if x.get("at") and "장중" not in str(x.get("at")))}


def day_risk(st: dict, day: str) -> dict:
    """미국 거래일별 확정 순손실/매수 체결 횟수. 기존 장부도 tickets에서 복구."""
    cfg = dict(DEFAULT, **st["cfg"])
    base = next((e[1] for e in reversed(st["equity"]) if e[0] < day), cfg["budget"])
    pnl = sum(c["pnl"] for c in st["closed"] if c["exit_date"] == day)
    fills = sum(t.get("result") == "체결" and t.get("day") == day for t in st.get("tickets", []))
    loss_limit = base * cfg["day_loss"]
    stopped = st.setdefault("day_stops", {})
    if pnl <= -loss_limit:
        stopped[day] = True
    reason = "하루 확정손실 한도" if stopped.get(day) else "하루 매수 횟수 한도" if fills >= cfg["day_trades"] else ""
    return {"date": day, "pnl": round(pnl, 2), "loss_limit": round(loss_limit, 2),
            "fills": fills, "max_trades": cfg["day_trades"], "blocked": bool(reason), "reason": reason}


def entry_meta(o: dict, px: float) -> dict:
    return {"trade_id": o.get("trade_id") or o["signal_date"] + ":" + o["t"],
            "initial_stop": o["stop"], "risk_per_share": max(0., px - o["stop"])}


def review(st: dict) -> dict:
    """분할 매도를 한 거래로 묶고, 매수 시점 1R로 비용 차감 손익을 평가."""
    groups = {}
    open_ids = {p.get("trade_id") for p in st["positions"] if p.get("trade_id")}
    for c in st["closed"]:
        key = c.get("trade_id") or "legacy:" + c["date"] + ":" + c["t"]
        g = groups.setdefault(key, {"id": key, "t": c["t"], "pnl": 0., "risk": 0., "known": True,
                                    "setup": c.get("setup"), "edge": c.get("signal_edge"), "date": c["exit_date"],
                                    "entry_context": c.get("entry_context"), "fees": 0., "exit_reasons": []})
        g["pnl"] += c["pnl"]
        g["fees"] += c.get("qty", 0) * (c.get("entry", 0) + c.get("exit", 0)) * FEE
        if c.get("why") not in g["exit_reasons"]:
            g["exit_reasons"].append(c.get("why"))
        g["known"] = g["known"] and bool(c.get("risk_per_share", 0) > 0)
        g["risk"] += c["qty"] * (c.get("risk_per_share") or 0)
        g["date"] = max(g["date"], c["exit_date"])
    trades = [g for k, g in groups.items() if k not in open_ids and
              not any(not p.get("trade_id") and k == "legacy:" + p["date"] + ":" + p["t"] for p in st["positions"])]
    for g in trades:
        g["r"] = round(g["pnl"] / g["risk"], 2) if g["known"] and g["risk"] > 0 else None
        g["pnl"] = round(g["pnl"], 2)
    measured = [g for g in trades if g["r"] is not None]
    avg_r = round(sum(g["r"] for g in measured) / len(measured), 2) if measured else None
    by_setup = []
    for name in sorted({g.get("setup") or "셋업 기록 없음" for g in trades}):
        bucket = [g for g in trades if (g.get("setup") or "셋업 기록 없음") == name]
        known = [g for g in bucket if g["r"] is not None]
        by_setup.append({"setup": name, "n": len(bucket), "r_n": len(known),
                         "avg_r": round(sum(g["r"] for g in known) / len(known), 2) if known else None})
    tips = []
    if len(measured) < 12:
        tips.append("1R 기록이 있는 완료 거래가 12건 미만이에요. 성과를 단정하지 말고 모의를 이어가요.")
    if avg_r is not None and avg_r <= 0:
        tips.append("비용을 뺀 평균 R이 0 이하예요. 매수 횟수나 금액을 늘리기 전에 셋업별 손실을 점검해요.")
    if any(g.get("edge") and not g["edge"].get("ok") for g in trades):
        tips.append("엣지를 통과하지 않은 거래 기록이 있어요. 매수 당시 기준을 확인해요.")
    if not tips:
        tips.append("평균 R은 과거 결과예요. 금액을 늘리기 전 새로운 기간에도 유지되는지 확인해요.")
    def has_current_team(g):
        ctx = g.get("entry_context") or {}
        team = ctx.get("team") or {}
        return bool(team.get("views") and team.get("date") == ctx.get("date"))
    team_trades = [g for g in trades if has_current_team(g)]
    avoided = [g for g in team_trades if g["entry_context"].get("shadow_avoid")]
    comparison = {"n": len(team_trades), "avoided": len(avoided), "actual_pnl": round(sum(g["pnl"] for g in team_trades), 2),
                  "kept_pnl": round(sum(g["pnl"] for g in team_trades if not g["entry_context"].get("shadow_avoid")), 2),
                  "missed_gains": round(sum(max(0, g["pnl"]) for g in avoided), 2),
                  "avoided_losses": round(-sum(min(0, g["pnl"]) for g in avoided), 2),
                  "note": "같은 날 AI 주의 의견이 있었다면 그 거래만 건너뛴 단순 비교. 현금 재투자·대체 거래·계좌 수익률은 계산하지 않음"}
    led_failures = ledger.failures(ledger.from_closed(st["closed"]))
    if led_failures:
        tips.append(f"장부: 반복 실패한 자리 {len(led_failures)}개를 다음 후보에서 자동 제외하고 있어요 (같은 실수 방지).")
    return {"n": len(trades), "r_n": len(measured), "avg_r": avg_r, "team_comparison": comparison,
            "win": round(sum(g["pnl"] > 0 for g in trades) / len(trades) * 100, 1) if trades else None,
            "violations": st.get("violations", 0), "tips": tips, "by_setup": by_setup,
            "ledger_failures": led_failures[:12],
            "trades": sorted(trades, key=lambda g: g["date"], reverse=True)[:30]}


def _close(st, p, day, px, why):
    qty = p["qty"]
    proceeds = qty * px * (1 - FEE)
    st["cash"] += proceeds
    cost = qty * p["entry"] * (1 + FEE)
    st["closed"].append({"t": p["t"], "qty": qty, "entry": p["entry"], "date": p["date"], "exit": round(px, 4), "exit_date": day,
                         "why": why, "trade_id": p.get("trade_id"), "risk_per_share": p.get("risk_per_share"), "signal_edge": p.get("signal_edge"), "setup": p.get("setup"), "entry_context": p.get("entry_context"), "pnl": round(proceeds - cost, 2), "ret": round((proceeds / cost - 1) * 100, 2)})
    day_risk(st, day)
    st["log"].append(f"{day} 매도 {p['t']} {qty}주 @{px:.2f} · {why}")


def step(store, picks: list[dict], bar_date: str, market: dict, now_iso: str, key: str = KEY) -> dict | None:
    """picks: 앱 형식 후보(pick_view). market: {'regime','rest_day'}. 반환: 상태(없으면 None)."""
    st = load(store, key)
    if not st:
        return None
    cfg = st["cfg"]
    n_log = len(st["log"])
    need = sorted({o["t"] for o in st["pending"]} | {p["t"] for p in st["positions"]} | {"SPY"})
    hist = prices.download_history([t.replace(".", "-") for t in need], period="90d")
    H = lambda t: hist.get(t.replace(".", "-"))

    # 2) 매도 규칙 (날마다)
    keep = []
    for p in st["positions"]:
        df = H(p["t"])
        if df is None:
            keep.append(p); continue
        closed = False
        ma20 = df["Close"].rolling(20).mean()
        for d, row, i in _bars_between(df, max(p["date"], st.get("checked") or ""), bar_date):
            if d <= p["date"]:
                continue
            op, hi, lo, cl = (float(row[k]) for k in ("Open", "High", "Low", "Close"))
            seen = p.get("seen_to", "")[:10] >= d   # 장중에 5분봉으로 이미 확인한 날은 손절·목표를 다시 보지 않아요 (순서를 모르니까)
            if not seen and lo <= p["stop"]:
                _close(st, p, d, min(op, p["stop"]) * (1 - SLIP), "손절선" if not p["half"] else "본전 손절"); closed = True; break
            if not seen and not p["half"] and hi >= p["target"] * (1 + TOUCH):
                px = max(op, p["target"])
                if p["qty"] >= 2:
                    half = dict(p, qty=p["qty"] // 2)
                    _close(st, half, d, px, "1차 목표 (절반)")
                    p["qty"] -= half["qty"]
                    p["half"], p["stop"] = True, p["entry"]
                else:
                    _close(st, p, d, px, "1차 목표"); closed = True; break
            p["peak"] = max(p["peak"], cl)
            if p["half"] and (cl < p["peak"] * 0.92 or (not np.isnan(ma20.iloc[i]) and cl < ma20.iloc[i])):
                _close(st, p, d, cl * (1 - SLIP), "이익 지키기 (추적 손절)"); closed = True; break
            held = int(np.busday_count(date.fromisoformat(p["date"]), date.fromisoformat(d)))
            if held >= cfg["stale_days"] and cl < p["entry"] * 1.02:
                _close(st, p, d, cl * (1 - SLIP), f"{held}거래일 제자리"); closed = True; break
        # 일봉 백스톱 — 장중(5분봉)이 그날을 다 못 봤어도(실행 누락·수집 실패·마지막 봉 이후 급락),
        # 최신 일봉으로 손절·목표를 반드시 재확인해 매도 누락을 막아요. 이미 닫혔으면 건너뜀(이중 매도 없음).
        if not closed and len(df):
            ld = df.index[-1].strftime("%Y-%m-%d")
            if ld > p["date"]:
                last = df.iloc[-1]
                op_, hi_, lo_ = float(last["Open"]), float(last["High"]), float(last["Low"])
                if lo_ <= p["stop"]:
                    _close(st, p, ld, min(op_, p["stop"]) * (1 - SLIP), ("손절선" if not p["half"] else "본전 손절") + " · 일봉 백스톱"); closed = True
                elif not p["half"] and hi_ >= p["target"] * (1 + TOUCH):
                    px_ = max(op_, p["target"])
                    if p["qty"] >= 2:
                        half = dict(p, qty=p["qty"] // 2)
                        _close(st, half, ld, px_, "1차 목표 (절반) · 일봉 백스톱")
                        p["qty"] -= half["qty"]; p["half"], p["stop"] = True, p["entry"]
                    else:
                        _close(st, p, ld, px_, "1차 목표 · 일봉 백스톱"); closed = True
        if not closed:
            if market.get("regime") == "bear" and p["stop"] < p["entry"] and float(df["Close"].iloc[-1]) > p["entry"]:
                p["stop"] = p["entry"]  # 하락장 전환: 수익 중이면 손절을 매수가로
            keep.append(p)
    st["positions"] = keep
    st["checked"] = bar_date

    # 1) 주문 체결
    still = []
    for o in st["pending"]:
        df = H(o["t"])
        if df is None:
            still.append(o); continue
        d, row = _bar_after(df, o["signal_date"])
        if d is None or d > bar_date:
            still.append(o); continue
        guard = day_risk(st, d)
        if guard["blocked"]:
            _ticket(st, o["t"], o["signal_date"], result="안 냄 (" + guard["reason"] + ")", day=d)
            st["log"].append(f"{d} 취소 {o['t']} · {guard['reason']}")
            continue
        op, lo = float(row["Open"]), float(row["Low"])
        if op > o["skip_above"]:
            st["log"].append(f"{d} 취소 {o['t']} · 시작가 {op:.2f}가 추격 금지선 {o['skip_above']:.2f} 위")
            _ticket(st, o["t"], o["signal_date"], result="안 냄 (추격 금지)", day=d, limit=o["limit"], qty=o["qty"])
        elif lo <= o["limit"] * (1 - TOUCH):
            px = min(op, o["limit"])
            check = trade_guard.validate_buy(o, trade_guard.sim_account(st, guard), cfg, px)
            if not check["ok"]:
                _ticket(st, o["t"], o["signal_date"], result="안 냄 (" + check["reasons"][0] + ")", day=d)
                continue
            cost = o["qty"] * px * (1 + FEE)
            if px <= o["stop"]:
                _ticket(st, o["t"], o["signal_date"], result="안 냄 (손절선 아래 시가)", day=d)
                continue
            if cost > st["cash"] + 1e-9:  # 돈이 모자라면 사지 않음
                st["log"].append(f"{d} 취소 {o['t']} · 현금 부족")
                _ticket(st, o["t"], o["signal_date"], result="안 냄 (현금 부족)", day=d, limit=o["limit"], qty=o["qty"])
            else:
                st["cash"] -= cost
                st["positions"].append({**entry_meta(o, px), "t": o["t"], "qty": o["qty"], "entry": round(px, 4), "date": d, "stop": o["stop"],
                                        "target": o["target"], "peak": px, "half": False, "signal_edge": o.get("signal_edge"), "setup": o.get("setup"), "entry_context": o.get("entry_context"), "why": o["why"], "fill_time": "장중(일봉 확인)"})
                st["log"].append(f"{d} 매수 {o['t']} {o['qty']}주 @{px:.2f} · {o['why']}")
                _ticket(st, o["t"], o["signal_date"], result="체결", day=d, limit=o["limit"], qty=o["qty"], fill_px=round(px, 4), at="장중(일봉 확인)")
                if lo <= o["stop"]:
                    new = st["positions"].pop()
                    _close(st, new, d, o["stop"] * (1 - SLIP), "손절선 (매수일 일봉 보수적 확인)")
        else:
            st["log"].append(f"{d} 미체결 {o['t']} · 지정가 {o['limit']:.2f}보다 0.1% 넘게 안 내려옴")
            _ticket(st, o["t"], o["signal_date"], result="미체결", day=d, limit=o["limit"], qty=o["qty"], low=round(lo, 2))
    st["pending"] = still

    # 평가금액·SPY
    spy = H("SPY")
    val = st["cash"] + sum(p["qty"] * float(H(p["t"])["Close"].iloc[-1]) for p in st["positions"] if H(p["t"]) is not None)
    spy_px = float(spy["Close"].iloc[-1]) if spy is not None else None
    if st["equity"] and st["equity"][-1][0] == bar_date:
        st["equity"][-1] = [bar_date, round(val, 2), spy_px]   # 같은 날 다시 돌면 최신 값으로
    else:
        st["equity"].append([bar_date, round(val, 2), spy_px])

    # 월 손실 한도
    month = bar_date[:7]
    m0 = next((e[1] for e in st["equity"] if e[0][:7] == month), val)
    stopped = month in st["month_stops"]
    if not stopped and val < m0 * (1 - cfg["month_loss"]):
        st["month_stops"].append(month); stopped = True
        st["log"].append(f"{bar_date} 이번 달 손실 한도 도달 → 새 매수 멈춤")

    # 3) 다음 거래일 주문 계획
    st["pending"] = []
    in_window = bar_date < st["end"]
    selection = {"date": bar_date, "total": len(picks), "planned": 0, "excluded": {}}
    def reject(reason):
        selection["excluded"][reason] = selection["excluded"].get(reason, 0) + 1
    selection["pause"] = ("모의 기간 종료" if not in_window else "시장 매수 쉬는 날" if market.get("rest_day")
                          else "하락장" if market.get("regime") == "bear" else "월 손실 한도" if stopped else "")
    if in_window and not market.get("rest_day") and market.get("regime") != "bear" and not stopped:
        held = {p["t"] for p in st["positions"]}
        slots = cfg["max_pos"] - len(st["positions"])
        cash = st["cash"]
        equity = val
        led = ledger.from_closed(st.get("closed"))   # 실패 장부 — 반복 실패한 자리 배제
        cands = []
        for p in picks:
            # 모의는 '측정된 양의 기대값'(paper_gate)으로 진입해 계속 돌며 track record를 쌓아요.
            # 엄선(exclusion/is_elite)은 ⭐실전급 신호로 따로 표시 — 둘을 분리.
            reason = setups.paper_gate(p)
            if reason:
                reject(reason); continue
            led_blocked, led_why = ledger.blocked(led, p["t"], p.get("setup"))
            if led_blocked:
                reject(led_why); continue
            pl = p.get("plan") or {}
            px, stop = p.get("price"), pl.get("stop")
            if not px or not stop or px < 3 or p["t"] in held or px * (1 + FEE) > cash:
                reject("이미 보유" if p["t"] in held else "현금·가격 조건")
                continue
            if any(a in " ".join(p.get("tags") or []) for a in AVOID) or any(t.startswith("실적 D-") and int(t[5:] or 9) <= 3 for t in (p.get("tags") or [])):
                reject("위험 태그·실적 임박")
                continue
            t5 = sum(1 for x in (p.get("trend5") or []) if x[1])
            cands.append((-(p.get("total") or 0), -t5, -(pl.get("rr") or 0), (px - stop) / px, p))
        cands.sort(key=lambda x: x[:4])
        for *_, p in cands:
            if slots <= 0:
                reject("보유 종목 수 한도"); continue
            pl = p["plan"]
            limit = float(pl.get("zone_high") or p["price"])
            if not 0 < pl["stop"] < limit < pl["target"]:
                reject("주문 가격 조건")
                continue
            risk = max(limit - pl["stop"] + (limit + pl["stop"]) * FEE, limit * 0.01)
            qty = int(min(equity * cfg["risk"] / risk, equity * cfg["cap"] / limit, cash / (limit * (1 + FEE))))
            if qty < 1:
                reject("정수 1주 위험·예산 한도")
                continue
            t5 = sum(1 for x in (p.get("trend5") or []) if x[1])
            st["pending"].append({"t": p["t"], "qty": qty, "limit": round(limit, 2), "skip_above": float(pl.get("skip_if_open_above") or limit * 1.03),
                                  "stop": float(pl["stop"]), "target": float(pl["target"]), "signal_date": bar_date, "signal_edge": dict(p.get("edge") or {}), "setup": p.get("setup"),
                                  "why": f"총점 {p.get('total'):.0f} · 추세 합류 {t5}/5 · 손익비 {pl.get('rr')}"})
            o = st["pending"][-1]
            _ticket(st, o["t"], bar_date, result="대기", limit=o["limit"], qty=qty, skip_above=o["skip_above"], stop=o["stop"], target=o["target"])
            cash -= qty * limit * (1 + FEE)
            slots -= 1
    selection["planned"] = len(st["pending"])
    st["selection"] = selection
    st["today"] = list(dict.fromkeys([x for x in st["log"] if x[:10] == bar_date] + st["log"][n_log:]))  # 장중 체결 + 아침 확인
    st["log"] = st["log"][-200:]
    st["updated"] = now_iso
    save(store, st)
    return st


# ---------------- 장중 체결 (매시간) ----------------

def _bars5(tickers: list[str]) -> dict:
    import pandas as pd
    import yfinance as yf
    out = {}
    if not tickers:
        return out
    raw = yf.download(tickers, period="1d", interval="5m", group_by="ticker", progress=False, auto_adjust=True, prepost=False)
    for t in tickers:
        try:
            m = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
            m = m.dropna(subset=["Close"])
            if len(m):
                if m.index.tz is not None:
                    m.index = m.index.tz_convert("America/New_York")
                out[t] = m
        except Exception:
            pass
    return out


def intraday(store, now_utc: datetime, key: str = KEY, bars: dict | None = None) -> list[str]:
    """미국 장중 매시간: 오늘 5분봉으로 주문 계획·손절·목표를 증권사처럼 체결해요. 반환: 새로 생긴 일(문장)."""
    st = load(store, key)
    if not st:
        return []
    day = now_utc.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d")
    pend = [o for o in st["pending"] if day > o["signal_date"]]
    tick = sorted({o["t"] for o in pend} | {p["t"] for p in st["positions"]})
    if not tick:
        return []
    bars = bars if bars is not None else _bars5([t.replace(".", "-") for t in tick])
    today = {}
    for t in tick:
        m = bars.get(t.replace(".", "-"))
        if m is not None:
            m = m[m.index.strftime("%Y-%m-%d") == day]
            if len(m):
                today[t] = m
    events, n_log = [], len(st["log"])
    # 시간 순서대로 기존 보유 매도 → 신규 매수. 손실 한도 도달 뒤의 매수를 막아요.
    times = sorted({i for m in today.values() for i in m.index if i + timedelta(minutes=5) <= now_utc})
    def exits(p, row, day, stamp, fresh=False):
        op, hi, lo = (float(row[k]) for k in ("Open", "High", "Low"))
        if lo <= p["stop"]:
            px = (p["stop"] if fresh else min(op, p["stop"])) * (1 - SLIP)
            why = ("손절선" if not p["half"] else "본전 손절") + f" ({stamp} ET)"
            _close(st, p, day, px, why)
            events.append(f"매도 {p['t']} {p['qty']}주 · {why}")
            return True
        # 매수 봉의 고가는 매수 전에 나왔을 수 있어 목표 체결로 가정하지 않아요.
        if not fresh and not p["half"] and hi >= p["target"] * (1 + TOUCH):
            px = max(op, p["target"])
            if p["qty"] >= 2:
                half = dict(p, qty=p["qty"] // 2)
                _close(st, half, day, px, f"1차 목표 (절반, {stamp} ET)")
                p["qty"] -= half["qty"]
                p["half"], p["stop"] = True, p["entry"]
                events.append(f"매도 {p['t']} {half['qty']}주 · 1차 목표 절반")
            else:
                _close(st, p, day, px, f"1차 목표 ({stamp} ET)")
                events.append(f"매도 {p['t']} {p['qty']}주 · 1차 목표")
                return True
        return False

    for i in times:
        ts, stamp = i.strftime("%Y-%m-%d %H:%M"), i.strftime("%H:%M")
        alive = []
        for p in st["positions"]:
            m = today.get(p["t"])
            if m is None or i not in m.index or ts <= p.get("seen_to", ""):
                alive.append(p); continue
            p["seen_to"] = ts
            if not exits(p, m.loc[i], day, stamp):
                alive.append(p)
        st["positions"] = alive
        keep = []
        for o in st["pending"]:
            m = today.get(o["t"])
            if day <= o["signal_date"] or m is None or i not in m.index or ts <= o.get("seen_to", ""):
                keep.append(o); continue
            row = m.loc[i]
            o["seen_to"] = ts
            guard = day_risk(st, day)
            reason = guard["reason"]
            if not o.get("open_px"):
                o["open_px"] = float(row["Open"])
            if o["open_px"] > o["skip_above"]:
                reason = "추격 금지"
            if float(row["Open"]) <= o["stop"]:
                reason = "손절선 아래 시가"
            if reason:
                _ticket(st, o["t"], o["signal_date"], result="안 냄 (" + reason + ")", day=day)
                st["log"].append(f"{day} 취소 {o['t']} · {reason}")
                events.append(f"{o['t']} 주문 안 냄 · {reason}")
                continue
            if float(row["Low"]) > o["limit"] * (1 - TOUCH):
                keep.append(o); continue
            px = min(float(row["Open"]), o["limit"])
            cost = o["qty"] * px * (1 + FEE)
            check = trade_guard.validate_buy(o, trade_guard.sim_account(st, guard), st["cfg"], px)
            if not check["ok"]:
                reason = check["reasons"][0]
                _ticket(st, o["t"], o["signal_date"], result="안 냄 (" + reason + ")", day=day)
                events.append(f"{o['t']} 주문 안 냄 · {reason}")
                continue
            st["cash"] -= cost
            p = {**entry_meta(o, px), "t": o["t"], "qty": o["qty"], "entry": round(px, 4), "date": day,
                 "stop": o["stop"], "target": o["target"], "peak": px, "half": False,
                 "signal_edge": o.get("signal_edge"), "setup": o.get("setup"), "entry_context": o.get("entry_context"), "why": o["why"],
                 "fill_time": f"{stamp} ET", "seen_to": ts}
            _ticket(st, o["t"], o["signal_date"], result="체결", day=day, limit=o["limit"], qty=o["qty"], fill_px=round(px, 4), at=f"{stamp} ET")
            st["log"].append(f"{day} 매수 {o['t']} {o['qty']}주 @{px:.2f} · {stamp} ET 체결 · {o['why']}")
            events.append(f"매수 체결 {o['t']} {o['qty']}주 @${px:.2f}")
            if not exits(p, row, day, stamp, fresh=True):
                st["positions"].append(p)
        st["pending"] = keep
    day_risk(st, day)
    st["intra_at"] = now_utc.astimezone(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    if events:
        st["today"] = (st.get("today") or []) + st["log"][n_log:]
    st["log"] = st["log"][-200:]
    save(store, st)
    return events


# ---------------- 판단 ----------------

def _mdd(vals):
    peak, mdd = -1e18, 0.0
    for v in vals:
        peak = max(peak, v)
        if peak > 0:
            mdd = min(mdd, v / peak - 1)
    return mdd * 100


def summary(st: dict, sig: dict | None = None) -> dict:
    cfg, eq = st["cfg"], st["equity"]
    budget = cfg["budget"]
    last = eq[-1][1] if eq else budget
    closed = st["closed"]
    wins = [c for c in closed if c["pnl"] > 0]
    losses = [c for c in closed if c["pnl"] <= 0]
    spy0 = next((e[2] for e in eq if e[2]), None)
    spy_ret = (eq[-1][2] / spy0 - 1) * 100 if eq and spy0 and eq[-1][2] else None
    spy_vals = [e[2] for e in eq if e[2]]
    half = max(1, len(closed) // 2)
    first, lastn = closed[:half], closed[-half:]
    avg = lambda xs: sum(c["ret"] for c in xs) / len(xs) if xs else None
    aw = sum(c["pnl"] for c in wins) / len(wins) if wins else None
    al = -sum(c["pnl"] for c in losses) / len(losses) if losses else None
    ret = (last / budget - 1) * 100
    mdd = _mdd([e[1] for e in eq])
    spy_mdd = _mdd(spy_vals) if spy_vals else None
    d0 = date.fromisoformat(st["start"])
    import config
    today = config.now_kst().date()
    d5 = (sig or {}).get("d5") or {}
    ts = ticket_stats(st)
    checks = [
        ["모의 거래 12번 이상", len(closed) >= 12, f"{len(closed)}번"],
        ["아침 후보 기록 100개 이상, 5일 뒤 평균이 SPY보다 나음",
         d5.get("n", 0) >= 100 and d5.get("excess") is not None and d5["excess"] > 0,
         f"{d5.get('n', 0)}개 · SPY 대비 {d5['excess']:+.2f}%p" if d5.get("excess") is not None else f"{d5.get('n', 0)}개"],
        ["SPY보다 수익률이 높거나 비슷하고 최대 낙폭은 더 작음",
         spy_ret is not None and ret >= spy_ret - 1 and (spy_mdd is None or mdd >= spy_mdd),
         f"내 {ret:+.1f}% (낙폭 {mdd:.1f}%) · SPY {spy_ret:+.1f}% (낙폭 {spy_mdd:.1f}%)" if spy_ret is not None and spy_mdd is not None else "자료 부족"],
        ["최대 낙폭 15% 이내, 손실 한도로 멈춘 달 없음", mdd >= -15 and not st["month_stops"], f"낙폭 {mdd:.1f}% · 멈춘 달 {len(st['month_stops'])}"],
        ["평균 이익 ÷ 평균 손실 1.5 이상", bool(aw and al and aw / al >= 1.5) or bool(aw and not losses and len(closed) >= 5),
         f"{aw / al:.2f}" if aw and al else "—"],
        ["처음 절반보다 최근 절반이 나빠지지 않음, 규칙 위반 0번",
         len(closed) >= 12 and avg(lastn) is not None and avg(lastn) >= avg(first) - 0.5 and st["violations"] == 0,
         f"처음 {avg(first):+.1f}% · 최근 {avg(lastn):+.1f}%" if closed else "—"],
        ["수수료·환전 비용을 빼고도 플러스", last > budget, f"${last - budget:+.2f}"],
        [f"리허설 주문표 {TICKET_MIN}건 이상 · 체결률 {TICKET_RATE:.0%} 이상", ts["n"] >= TICKET_MIN and (ts["rate"] or 0) >= TICKET_RATE,
         f"{ts['n']}건 · 체결률 {ts['rate']:.0%}" if ts["rate"] is not None else f"{ts['n']}건"],
    ]
    return {
        "start": st["start"], "end": st["end"], "day": max(1, (today - d0).days + 1), "days": DAYS, "budget": budget, "max_pos": cfg["max_pos"],
        "equity": round(last, 2), "cash": round(st["cash"], 2), "ret": round(ret, 2), "spy_ret": None if spy_ret is None else round(spy_ret, 2),
        "mdd": round(mdd, 2), "gain": round(sum(c["pnl"] for c in wins), 2), "loss": round(sum(c["pnl"] for c in losses), 2),
        "wins": len(wins), "losses": len(losses), "fees": round(sum(c["qty"] * (c["entry"] + c["exit"]) * FEE for c in closed) + sum(p["qty"] * p["entry"] * FEE for p in st["positions"]), 2), "positions": st["positions"], "pending": st["pending"],
        "closed": closed[::-1][:50], "log": st["log"][::-1][:30], "checks": checks, "passed": all(c[1] for c in checks),
        "evaluated": st.get("evaluated"), "today": st.get("today") or [], "updated": st.get("updated"), "reports": (st.get("reports") or [])[:30], "curve": [[e[0], e[1]] for e in eq][-120:],
        "risk_day": day_risk(st, max(eq[-1][0] if eq else st["start"], (st.get("intra_at") or st["start"])[:10])), "review": review(st),
        "selection": st.get("selection"),
        "tickets": (st.get("tickets") or [])[::-1][:30], "ticket_stats": ts, "intra_at": st.get("intra_at"),
    }


def maybe_evaluate(store, st: dict, notify_fn, sig: dict | None = None) -> dict | None:
    """시험 기간이 끝나면 한 번만 판단해서 알림을 보내요."""
    if not st or st.get("evaluated") or not st["equity"] or st["equity"][-1][0] < st["end"]:
        return None
    s = summary(st, sig)
    ok = s["passed"]
    lines = [f"■ 3개월 자동 모의매매 결과 ({s['start']} ~ {st['equity'][-1][0]}, 가상 ${s['budget']:.0f})",
             f"평가 ${s['equity']:.2f} ({s['ret']:+.1f}%) · 같은 기간 SPY {s['spy_ret']:+.1f}%" if s["spy_ret"] is not None else f"평가 ${s['equity']:.2f}",
             f"번 돈 +${s['gain']:.2f} ({s['wins']}건) · 잃은 돈 -${abs(s['loss']):.2f} ({s['losses']}건)", ""]
    lines += [("✅ " if c[1] else "❌ ") + c[0] + " — " + c[2] for c in s["checks"]]
    lines.append("")
    if ok:
        lines.append(f"{len(s['checks'])}가지 기준을 모두 넘었어요. 실전으로 바꾸려면 Claude에게 '실전 전환해줘'라고 요청해 주세요. "
                     "실전 계좌에 돈을 넣고 KIS_MODE를 real로 바꾸는 것까지 함께 진행해요. (자동으로 바뀌지는 않아요)")
        title = "실전 전환 검토 요청 — 3개월 모의 통과"
    else:
        lines.append("아직 실전 기준에 못 미쳤어요. 실전으로 바꾸지 않고 모의를 1개월 더 이어가요. 못 넘은 항목을 보고 규칙을 손볼지 정해 주세요.")
        title = "3개월 모의 결과 — 아직 실전 전 단계"
        st["end"] = (date.fromisoformat(st["end"]) + timedelta(days=30)).isoformat()
    st.setdefault("evals", []).append({"at": st["equity"][-1][0], "passed": ok})
    if ok:
        st["evaluated"] = {"at": st["equity"][-1][0], "passed": True}
    save(store, st)
    notify_fn(title, "\n".join(lines))
    return {"title": title, "passed": ok, "text": "\n".join(lines)}


def daily_text(st: dict, sig: dict | None = None) -> tuple[str, str, bool]:
    """아침 일일 리포트용: (제목, 본문, 오늘 사고판 게 있나)."""
    m = summary(st, sig)
    today = st.get("today") or []
    traded = any((" 매수 " in x or " 매도 " in x) for x in today)
    lines = [f"평가 ${m['equity']:.2f} ({m['ret']:+.1f}%) · 같은 기간 SPY " + (f"{m['spy_ret']:+.1f}%" if m["spy_ret"] is not None else "—"),
             f"번 돈 +${m['gain']:.2f} ({m['wins']}건) · 잃은 돈 " + (f"-${abs(m['loss']):.2f}" if m['loss'] < 0 else "$0.00") + f" ({m['losses']}건) · 현금 ${m['cash']:.2f}",
             f"수수료·환전 비용(추정) ${m['fees']:.2f} 포함", ""]
    lines.append("■ 지난 거래일에 한 일")
    lines += [f"• {x}" for x in today] or ["• 체결·매도 없음"]
    lines.append("■ 가진 종목")
    lines += [f"• {p['t']} {p['qty']}주 @{p['entry']:.2f} · 손절 {p['stop']:.2f} · 목표 {p['target']:.2f}" for p in m["positions"]] or ["• 없음"]
    ts = m["ticket_stats"]
    prev = [x for x in (st.get("tickets") or []) if x.get("day") and x.get("result") != "대기"][-5:]
    lines.append("■ 지난 주문표 채점")
    lines += [f"• {x['t']} {x.get('qty', '')}주 지정가 {x.get('limit', 0):.2f} → {x['result']}" + (f" @{x['fill_px']:.2f} ({x.get('at', '')})" if x.get("fill_px") else "") for x in prev] or ["• 아직 없음"]
    if ts["rate"] is not None:
        lines.append(f"  누적 {ts['n']}건 · 체결률 {ts['rate']:.0%}" + (f" · 지정가 대비 평균 {ts['avg_vs_limit']:+.2f}%" if ts["avg_vs_limit"] is not None else ""))
    lines.append("■ 오늘의 리허설 주문표 (증권사 앱에 넣는다면)")
    lines += [f"• 매수 {o['t']} {o['qty']}주 · 지정가 ${o['limit']:.2f} · 당일 유효 · 시작가가 ${o['skip_above']:.2f} 위면 주문 취소 · {o['why']}" for o in m["pending"]]
    lines += [f"• 매도 {p['t']} {p['qty']}주 · 손절 ${p['stop']:.2f} 이하 · " + ("목표 달성 후 본전 손절" if p.get("half") else f"목표 ${p['target']:.2f}에 절반 지정가 매도") for p in m["positions"]]
    if not m["pending"] and not m["positions"]:
        lines.append("• 없음")
    lines.append(f"실전 기준 {sum(1 for c in m['checks'] if c[1])}/{len(m['checks'])} 통과 중")
    title = f"자동 모의 {m['day']}/{m['days']}일째 · ${m['equity']:.2f} ({m['ret']:+.1f}%)"
    return title, "\n".join(lines), traded


def keep_report(store, st: dict, title: str, text: str, at: str):
    """앱 '자동 모의'에서 볼 수 있게 일일 리포트를 30일치 보관."""
    reps = [r for r in (st.get("reports") or []) if r.get("date") != at[:10]]
    st["reports"] = ([{"date": at[:10], "at": at, "title": title, "text": text}] + reps)[:30]
    save(store, st)
