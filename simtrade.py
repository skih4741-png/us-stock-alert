"""자동 모의매매 (11장 규칙 그대로, 실제 주문 없음) — 3개월 시험 후 실전 전환 판단.

매일 아침 리포트 때 한 번 돌아요.
 1) 어제 낸 '주문 계획'을 지난 거래일 시세로 체결해 봐요 (시작가가 추격 금지선 위면 취소, 저가가 지정가 이하면 체결)
 2) 가진 종목에 매도 규칙을 날마다 적용해요 (손절 → 1차 목표 절반 + 손절을 매수가로 → 추적 손절 → 제자리)
 3) 오늘 후보로 다음 거래일 주문 계획을 세워요 (돈에 맞춰 스스로 고르기)
 4) 90일이 지나면 6가지 기준으로 실전 가능 여부를 판단해 푸시·슬랙·메일로 알려요 (실전 전환은 본인이 요청해야 해요)
수수료·환전 비용은 추정치(한쪽 0.25% + 0.10%)를 빼요.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta

import numpy as np

import prices

log = logging.getLogger(__name__)
KEY = "sim"          # 판단용 (가상 1,000달러, 2026-10-09 사용자 요청으로 100→1,000)
REF_KEY = "sim_ref"  # 참고용 100달러 (실전 첫 금액 비교용, 판단에 안 씀)
FEE = 0.0025 + 0.0010      # 한쪽 거래 비용 추정 (수수료 + 환전)
DAYS = 90                  # 시험 기간 (달력 기준)
DEFAULT = {"budget": 100.0, "max_pos": 2, "risk": 0.03, "cap": 0.6, "month_loss": 0.10, "stale_days": 15}
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


def _close(st, p, day, px, why):
    qty = p["qty"]
    proceeds = qty * px * (1 - FEE)
    st["cash"] += proceeds
    cost = qty * p["entry"] * (1 + FEE)
    st["closed"].append({"t": p["t"], "qty": qty, "entry": p["entry"], "date": p["date"], "exit": round(px, 4), "exit_date": day,
                         "why": why, "pnl": round(proceeds - cost, 2), "ret": round((proceeds / cost - 1) * 100, 2)})
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

    # 1) 주문 체결
    still = []
    for o in st["pending"]:
        df = H(o["t"])
        if df is None:
            still.append(o); continue
        d, row = _bar_after(df, o["signal_date"])
        if d is None or d > bar_date:
            still.append(o); continue
        op, lo = float(row["Open"]), float(row["Low"])
        if op > o["skip_above"]:
            st["log"].append(f"{d} 취소 {o['t']} · 시작가 {op:.2f}가 추격 금지선 {o['skip_above']:.2f} 위")
        elif lo <= o["limit"]:
            px = min(op, o["limit"])
            cost = o["qty"] * px * (1 + FEE)
            if cost > st["cash"] + 1e-9:  # 돈이 모자라면 사지 않음
                st["log"].append(f"{d} 취소 {o['t']} · 현금 부족")
            else:
                st["cash"] -= cost
                st["positions"].append({"t": o["t"], "qty": o["qty"], "entry": round(px, 4), "date": d, "stop": o["stop"],
                                        "target": o["target"], "peak": px, "half": False, "why": o["why"]})
                st["log"].append(f"{d} 매수 {o['t']} {o['qty']}주 @{px:.2f} · {o['why']}")
        else:
            st["log"].append(f"{d} 미체결 {o['t']} · 지정가 {o['limit']:.2f}까지 안 내려옴")
    st["pending"] = still

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
            if lo <= p["stop"]:
                _close(st, p, d, min(op, p["stop"]), "손절선" if not p["half"] else "본전 손절"); closed = True; break
            if not p["half"] and hi >= p["target"]:
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
                _close(st, p, d, cl, "이익 지키기 (추적 손절)"); closed = True; break
            held = int(np.busday_count(date.fromisoformat(p["date"]), date.fromisoformat(d)))
            if held >= cfg["stale_days"] and cl < p["entry"] * 1.02:
                _close(st, p, d, cl, f"{held}거래일 제자리"); closed = True; break
        if not closed:
            if market.get("regime") == "bear" and p["stop"] < p["entry"] and float(df["Close"].iloc[-1]) > p["entry"]:
                p["stop"] = p["entry"]  # 하락장 전환: 수익 중이면 손절을 매수가로
            keep.append(p)
    st["positions"] = keep
    st["checked"] = bar_date

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
    if in_window and not market.get("rest_day") and market.get("regime") != "bear" and not stopped:
        held = {p["t"] for p in st["positions"]}
        slots = cfg["max_pos"] - len(st["positions"])
        cash = st["cash"]
        equity = val
        cands = []
        for p in picks:
            pl = p.get("plan") or {}
            px, stop = p.get("price"), pl.get("stop")
            if not px or not stop or px < 3 or p["t"] in held or px * (1 + FEE) > cash:
                continue
            if any(a in " ".join(p.get("tags") or []) for a in AVOID) or any(t.startswith("실적 D-") and int(t[5:] or 9) <= 3 for t in (p.get("tags") or [])):
                continue
            t5 = sum(1 for x in (p.get("trend5") or []) if x[1])
            cands.append((-(p.get("total") or 0), -t5, -(pl.get("rr") or 0), (px - stop) / px, p))
        cands.sort(key=lambda x: x[:4])
        for *_, p in cands:
            if slots <= 0:
                break
            pl = p["plan"]
            limit = float(pl.get("zone_high") or p["price"])
            risk = max(limit - pl["stop"], limit * 0.01)
            qty = int(min(equity * cfg["risk"] / risk, equity * cfg["cap"] / limit, cash / (limit * (1 + FEE))))
            if qty < 1:
                continue
            t5 = sum(1 for x in (p.get("trend5") or []) if x[1])
            st["pending"].append({"t": p["t"], "qty": qty, "limit": round(limit, 2), "skip_above": float(pl.get("skip_if_open_above") or limit * 1.03),
                                  "stop": float(pl["stop"]), "target": float(pl["target"]), "signal_date": bar_date,
                                  "why": f"총점 {p.get('total'):.0f} · 추세 합류 {t5}/5 · 손익비 {pl.get('rr')}"})
            cash -= qty * limit * (1 + FEE)
            slots -= 1
    st["today"] = st["log"][n_log:] or [x for x in st["log"] if x[:10] == bar_date]
    st["log"] = st["log"][-200:]
    st["updated"] = now_iso
    save(store, st)
    return st


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
    ]
    return {
        "start": st["start"], "end": st["end"], "day": max(1, (today - d0).days + 1), "days": DAYS, "budget": budget,
        "equity": round(last, 2), "cash": round(st["cash"], 2), "ret": round(ret, 2), "spy_ret": None if spy_ret is None else round(spy_ret, 2),
        "mdd": round(mdd, 2), "gain": round(sum(c["pnl"] for c in wins), 2), "loss": round(sum(c["pnl"] for c in losses), 2),
        "wins": len(wins), "losses": len(losses), "fees": round(sum(c["qty"] * (c["entry"] + c["exit"]) * FEE for c in closed) + sum(p["qty"] * p["entry"] * FEE for p in st["positions"]), 2), "positions": st["positions"], "pending": st["pending"],
        "closed": closed[::-1][:50], "log": st["log"][::-1][:30], "checks": checks, "passed": all(c[1] for c in checks),
        "evaluated": st.get("evaluated"), "today": st.get("today") or [], "updated": st.get("updated"), "reports": (st.get("reports") or [])[:30], "curve": [[e[0], e[1]] for e in eq][-120:],
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
    lines.append("■ 오늘 밤 주문 계획")
    lines += [f"• {o['t']} {o['qty']}주 · 지정가 {o['limit']:.2f} 이하 · {o['why']}" for o in m["pending"]] or ["• 없음"]
    lines.append(f"실전 기준 {sum(1 for c in m['checks'] if c[1])}/{len(m['checks'])} 통과 중")
    title = f"자동 모의 {m['day']}/{m['days']}일째 · ${m['equity']:.2f} ({m['ret']:+.1f}%)"
    return title, "\n".join(lines), traded


def keep_report(store, st: dict, title: str, text: str, at: str):
    """앱 '자동 모의'에서 볼 수 있게 일일 리포트를 30일치 보관."""
    reps = [r for r in (st.get("reports") or []) if r.get("date") != at[:10]]
    st["reports"] = ([{"date": at[:10], "at": at, "title": title, "text": text}] + reps)[:30]
    save(store, st)
