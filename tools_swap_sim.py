"""한 번만: 판단용 자동 모의를 1,000달러로 바꿔요 (2026-10-09 사용자 요청).
10/8부터 같은 규칙으로 돌던 참고용 1,000달러 기록을 판단용으로 올리고, 기존 100달러 기록은 참고용으로 내려요.
python tools_swap_sim.py  (두 번 돌려도 안전: 이미 바꿨으면 아무것도 안 해요)"""
import json
from datetime import datetime, timedelta, timezone

import simtrade
from sheets import Store

store = Store()
main, ref = simtrade.load(store), simtrade.load(store, simtrade.REF_KEY)
if not main or not ref:
    raise SystemExit("모의 기록이 없어요")
if main["cfg"]["budget"] >= 1000:
    raise SystemExit(f"이미 판단용이 ${main['cfg']['budget']:.0f}예요. 바꿀 것 없음")
ref["key"], main["key"] = simtrade.KEY, simtrade.REF_KEY
now = datetime.now(timezone(timedelta(hours=9)))
ref.setdefault("log", []).append(f"{now:%Y-%m-%d} 판단용으로 전환 (가상 $1,000, 사용자 요청)")
simtrade.save(store, ref)
simtrade.save(store, main)
import main as M
perf = M.save_perf(store, now, notify_stops=False) or {}
sig = (perf or {}).get("signals")
title, text, _ = simtrade.daily_text(ref, sig)
simtrade.keep_report(store, ref, "자동 모의 $1,000 · " + now.strftime("%m/%d") + " (전환)", text, now.isoformat(timespec="minutes"))
M.save_perf(store, now, notify_stops=False)
s = simtrade.summary(ref, sig)
print("판단용:", f"${s['budget']:.0f}", f"평가 ${s['equity']:.2f}", f"현금 ${s['cash']:.2f}", "보유", [p['t'] for p in s['positions']], "주문 계획", [o['t'] for o in s['pending']])
print("참고용: $", main["cfg"]["budget"])
