"""11장: 자동 모의매매(판단용 규칙)를 한국투자증권 **모의투자 계좌**에 실제 주문으로 따라 내요.
(실전용 앱키가 들어 있으면 EGW02007을 한 번 보고 스스로 꺼져요. 키가 바뀔 때까지 다시 시도·경고하지 않아요.)

장중 감시(매시) 때 돌아요.
 1) 그날 첫 실행: 모의매매가 세운 '오늘 밤 주문 계획'을 지정가 매수로 냄 (지금가가 추격 금지선 위면 안 냄)
 2) 매 실행: 증권사 모의 잔고의 종목을 손절선·1차 목표와 비교 → 닿으면 지정가 매도 (1차 목표는 절반, 남은 것은 손절을 매수가로)
 3) 장 마감 전 마지막 실행: 오늘 주문·체결을 '증권사 모의 체결' 탭과 슬랙·앱에 기록
매수 판단은 아침 규칙이 하고, 여기서는 주문만 내요. 실패해도 리포트·모의매매 계산은 그대로예요.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import appdata
import kis
import notify
import prices
import push
import simtrade
import trade_guard
import broker_state
import trading_sessions

log = logging.getLogger(__name__)
KEY = "kis"
TAB = "증권사 모의 체결"


def _load(store) -> dict:
    try:
        return json.loads(store.get_blob(KEY) or "{}")
    except Exception:
        return {}


LIVE_KEY_ERR = ("EGW02007", "모의투자용 앱키가 아닙니다")


def _kid() -> str:
    import hashlib
    import os
    return hashlib.sha256((os.environ.get("KIS_APP_KEY") or "").encode()).hexdigest()[:12]


def run(store, now_utc: datetime | None = None) -> dict | None:
    ok, why = kis.configured()
    st = _load(store)
    dis = st.get("disabled") or {}
    if dis and dis.get("kid") == _kid():
        log.info("증권사 모의 연결 꺼둠: %s (키가 바뀌면 다시 시도)", dis.get("why"))
        return st          # 같은 키면 다시 시도하지 않고 경고도 안 보내요
    if dis:
        st.pop("disabled", None)
        st["err"] = ""
        log.info("앱키가 바뀌어서 증권사 모의 연결을 다시 시도해요")
    if not ok:
        st.update({"on": False, "why": why})
        store.put_blob(KEY, json.dumps(st, ensure_ascii=False))
        log.info("증권사 모의 연동 꺼짐: %s", why)
        return st
    now_utc = now_utc or datetime.now(timezone.utc)
    et = now_utc.astimezone(ZoneInfo("America/New_York"))
    kst = now_utc.astimezone(timezone(timedelta(hours=9)))
    day = et.strftime("%Y-%m-%d")
    st.setdefault("orders", [])
    st.setdefault("pos", {})       # 종목별 손절·목표·절반 익절 여부 (매수 체결 뒤 채움)
    st.setdefault("excg", {})
    st["on"], st["why"] = True, ""
    try:
        c = kis.Client(store)
        sim = simtrade.load(store) or {}
        cfg = dict(simtrade.DEFAULT, **sim.get("cfg", {}))
        bal = c.balance()
        held = {h["t"]: h for h in bal["holdings"]}
        # 한국 자정 전후 체결을 모두 조회. 미확인 데이터는 매수를 막되 보호 매도는 유지.
        fills_ok = True
        fills = []
        try:
            for date_arg in (kst.strftime("%Y%m%d"), (kst - timedelta(days=1)).strftime("%Y%m%d")):
                fills.extend(c.fills(date_arg))
            broker_state.reconcile(st, fills, day)
            st["fills"] = fills
        except Exception:
            fills_ok = False
            st["reconcile"] = {"date": day, "ok": False, "note": "증권사 주문·체결 조회 실패"}
        st["balance"] = bal

        def persist():
            st["at"] = kst.isoformat(timespec="minutes")
            store.put_blob(KEY, json.dumps(st, ensure_ascii=False, default=str))

        def send(rec, side, excg):
            # 응답 유실/프로세스 중단 뒤에도 같은 의도를 재전송하지 않도록 선기록.
            rec.update(status="전송 중", broker_date=kst.strftime("%Y%m%d"), filled=0)
            st["orders"].append(rec)
            persist()
            try:
                rec["odno"] = c.order(side, rec["t"], rec["qty"], rec["price"], excg)
                rec["status"] = "주문 접수" if rec["odno"] else "확인 필요"
            except Exception:
                rec["status"] = "확인 필요"
            persist()

        # 1) 보호 매도를 먼저 확인. 접수만으로 절반 익절/본전 손절로 바꾸지 않아요.
        live = prices.last_price_intraday([t.replace(".", "-") for t in held]) if held else {}
        for t, h in held.items():
            p = st["pos"].get(t) or {}
            if not p:
                continue
            if h.get("avg") and not p.get("half"):
                p["entry"] = h["avg"]
            px = (live.get(t.replace(".", "-")) or {}).get("price") or h["now"]
            if not px:
                continue
            kind = "stop" if px <= p["stop"] else "target" if not p.get("half") and px >= p["target"] else ""
            if not kind:
                continue
            reserved = sum(broker_state.outstanding(o) for o in st["orders"] if o["t"] == t and o["side"] == "매도")
            qty = max(0, h["qty"] - reserved)
            if kind == "target" and qty >= 2:
                qty //= 2
            key = broker_state.intent_key("sell", t, day, kind)
            if qty < 1 or any(o.get("intent") == key for o in st["orders"]):
                continue
            rec = {"date": day, "t": t, "side": "매도", "qty": qty,
                   "price": round(px * (.995 if kind == "target" else .99), 2),
                   "why": "1차 목표" if kind == "target" else "손절선", "exit_kind": kind,
                   "entry": p.get("entry"), "intent": key, "odno": ""}
            send(rec, "sell", h.get("excg") or kis.exchange(t, st["excg"]))

        # 2) 매수 직전: 증권사 잔고·주문가능 현금·확인 체결 기준 공통 검사.
        sent = {(o["t"], o.get("signal")) for o in st["orders"] if o["side"] == "매수"}
        pend = [o for o in sim.get("pending", []) if o["signal_date"] < day and (o["t"], o["signal_date"]) not in sent]
        quotes = prices.last_price_intraday([o["t"].replace(".", "-") for o in pend]) if pend else {}
        for o in pend:
            rec = {"date": day, "t": o["t"], "side": "매수", "qty": o["qty"], "price": o["limit"],
                   "why": o["why"], "odno": "", "signal": o["signal_date"],
                   "intent": broker_state.intent_key("buy", o["t"], o["signal_date"])}
            valid_session = trading_sessions.order_session(o)
            if valid_session != day:
                rec["status"] = "안 냄: " + ("주문 유효기간 만료" if valid_session and day > valid_session else "주문 유효 거래일 확인 대기")
                st["orders"].append(rec)
                persist()
                continue
            reason = ""
            px = (quotes.get(o["t"].replace(".", "-")) or {}).get("price")
            try:
                excg = kis.exchange(o["t"], st["excg"])
                cash = c.buying_power(o["t"], o["limit"], excg)
                account = broker_state.account(st, bal, cash, day, cfg)
                # 시장/월 중지는 내부 장부의 선별 결과를 함께 사용해요.
                pause = (sim.get("selection") or {}).get("pause")
                check = trade_guard.validate_buy(o, account, cfg)
                if not fills_ok:
                    reason = "주문·체결 조회 실패"
                elif px is None:
                    reason = "현재가 확인 대기"
                elif px > o["skip_above"]:
                    reason = "추격 금지"
                elif px <= o["stop"]:
                    reason = "손절선 아래 현재가"
                elif pause:
                    reason = pause
                elif not check["ok"]:
                    reason = check["reasons"][0]
                rec["checks"] = check
            except Exception:
                reason = "주문가능 현금·계좌 확인 실패"
            if reason:
                rec["status"] = "안 냄: " + reason
                st["orders"].append(rec)
                persist()
                continue
            # 주문이 불확실하더라도 손절 계획은 보관. 실제 보유는 증권사 잔고로만 판단.
            st["pos"][o["t"]] = {"stop": o["stop"], "target": o["target"], "entry": o["limit"], "half": False}
            send(rec, "buy", excg)
        st["order_summary"] = {"접수·미체결": sum(o.get("status") in ("주문 접수", "미체결") for o in st["orders"] if o["date"] == day),
                               "부분체결": sum(o.get("status") == "부분체결" for o in st["orders"] if o["date"] == day),
                               "체결 완료": sum(o.get("status") == "체결 완료" for o in st["orders"] if o["date"] == day),
                               "확인 필요": sum(o.get("status") in ("전송 중", "확인 필요") for o in st["orders"]),
                               "차단": sum(str(o.get("status", "")).startswith("안 냄") for o in st["orders"] if o["date"] == day)}
        persist()
        # 3) 장 마감 1시간 안쪽 실행: 체결 기록
        mins = et.hour * 60 + et.minute
        if mins >= 15 * 60 and st.get("log_day") != day:
            st["log_day"] = day
            fills = c.fills(kst.strftime("%Y%m%d"))
            done = [f for f in fills if f.get("filled")]
            if done:
                store.append(TAB, [{"날짜": day, "시각": f["time"], "종목": f["t"], "구분": f["side"], "주문 수량": f["qty"],
                                    "체결 수량": f["filled"], "체결가": f["price"], "상태": f["status"]} for f in done])
            text = "\n".join(f"• {f['side']} {f['t']} {f['filled'] or 0:.0f}/{f['qty'] or 0:.0f}주 @{f['price'] or f['ord_price'] or 0:.2f} · {f['status']}" for f in fills) or "• 오늘 주문 없음"
            title = f"증권사 모의투자 · {day} 체결"
            notify.send_slack(title, [{"type": "header", "text": {"type": "plain_text", "text": title}},
                                      {"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}])
            appdata.add_alert(store, "kis", title, text.replace("\n", " / ")[:200], kst.isoformat(timespec="minutes"), "info")
            if done:
                push.send(store, title, text.replace("• ", "").replace("\n", " / ")[:170], "#/score", "daily", tag="kis")
            st["fills"] = fills
        st["err"] = ""
    except kis.KisError as e:
        st["err"] = str(e)
        if any(k in str(e) for k in LIVE_KEY_ERR):
            st["disabled"] = {"why": "넣어 둔 앱키가 실전용이라 모의 서버가 거절해요", "kid": _kid(), "at": kst.isoformat(timespec="minutes")}
            st["err"] = ""
            notify.send_slack(":information_source: 증권사 모의 연결을 자동으로 껐어요 — 넣어 둔 한국투자증권 앱키가 실전용이에요. "
                              "자동 모의투자(가상 장부·장중 체결·리허설 주문표)는 그대로 정상 진행돼요. 모의투자용 키로 바꾸면 자동으로 다시 켜져요.")
            st["at"] = kst.isoformat(timespec="minutes")
            store.put_blob(KEY, json.dumps(st, ensure_ascii=False, default=str))
            return st
        if st.get("err_day") != day:
            st["err_day"] = day
            notify.send_slack(f":warning: 증권사 모의투자 연결 실패 — {e}")
        log.warning("증권사 모의 연동 실패: %s", e)
    st["orders"] = [o for o in st["orders"][:-200] if broker_state.outstanding(o)] + st["orders"][-200:]
    st["at"] = kst.isoformat(timespec="minutes")
    store.put_blob(KEY, json.dumps(st, ensure_ascii=False, default=str))
    return st

