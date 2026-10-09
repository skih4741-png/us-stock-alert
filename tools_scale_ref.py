"""한 번만: 참고용 자동 모의를 1,000달러로 키워요 (2026-10-09 사용자 요청). 지금까지 기록을 같은 비율로 늘려요.
최대 보유 종목 수(2)는 그대로라서 '1,000달러 · 2종목 집중형'이 돼요. 이미 1,000달러면 아무것도 안 해요."""
from datetime import datetime, timedelta, timezone

import simtrade
from sheets import Store

store = Store()
st = simtrade.load(store, simtrade.REF_KEY)
if not st:
    raise SystemExit("참고용 기록 없음")
b = st["cfg"]["budget"]
if b >= 1000:
    raise SystemExit(f"이미 ${b:.0f}")
k = 1000.0 / b
st["cfg"]["budget"] = 1000.0
st["cash"] = round(st["cash"] * k, 2)
for p in st["positions"] + st["pending"]:
    p["qty"] = int(round(p["qty"] * k))
for c in st["closed"]:
    c["qty"] = int(round(c["qty"] * k)); c["pnl"] = round(c["pnl"] * k, 2)
st["equity"] = [[e[0], round(e[1] * k, 2)] + list(e[2:]) for e in st["equity"]]
st["reports"] = []
now = datetime.now(timezone(timedelta(hours=9)))
st["log"].append(f"{now:%Y-%m-%d} 참고용을 가상 $1,000로 변경 (기존 기록 x{k:.0f}, 최대 {st['cfg']['max_pos']}종목 유지)")
simtrade.save(store, st)
import main as M
M.save_perf(store, now, notify_stops=False)
s = simtrade.summary(st)
print("REF", s["budget"], s["max_pos"], s["equity"], s["cash"], [(p["t"], p["qty"]) for p in s["positions"]], [(o["t"], o["qty"]) for o in s["pending"]])
