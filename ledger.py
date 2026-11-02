"""실패 장부 — 같은 (종목·자리)가 모의에서 반복 실패했으면 다음 후보에서 빼요.

lazyowen 자기개선 루프의 'ledger'(실패를 쌓아 같은 실수를 반복하지 않기) 차용.
모의투자 기록(끝난 거래)만 씁니다. 실제 매매와 무관하고, 수익 보장이 아니에요.
"""
from __future__ import annotations

MIN_ATTEMPTS = 3      # 이만큼은 시도해 봐야 '반복 실패'로 판단
FAIL_RATE = 0.34      # 끝난 거래 중 수익 비율이 이보다 낮으면 반복 실패


def _key(t, setup) -> str:
    return f"{str(t or '').upper()}:{setup or '-'}"


def from_closed(closed: list | None) -> dict:
    """끝난 모의 거래를 (종목·자리)별로 묶어 성적을 내요."""
    led: dict = {}
    for c in closed or []:
        s = led.setdefault(_key(c.get("t"), c.get("setup")),
                           {"t": str(c.get("t") or "").upper(), "setup": c.get("setup"), "n": 0, "win": 0})
        s["n"] += 1
        if (c.get("ret") or 0) > 0:
            s["win"] += 1
    for s in led.values():
        s["win_rate"] = round(s["win"] / s["n"] * 100) if s["n"] else None
        s["fail"] = bool(s["n"] >= MIN_ATTEMPTS and s["win"] / s["n"] < FAIL_RATE)
    return led


def blocked(led: dict | None, t, setup) -> tuple[bool, str]:
    """이 (종목·자리)가 장부상 반복 실패면 (True, 이유)."""
    s = (led or {}).get(_key(t, setup))
    if s and s.get("fail"):
        return True, f"과거 모의 {s['n']}번 중 {s['win']}번만 수익 — 이 자리 제외(장부)"
    return False, ""


def failures(led: dict | None) -> list[dict]:
    """앱 표시용: 반복 실패로 걸러진 (종목·자리) 목록 (실패율 높은 순)."""
    out = [{"t": s["t"], "setup": s["setup"], "n": s["n"], "win": s["win"], "win_rate": s["win_rate"]}
           for s in (led or {}).values() if s.get("fail")]
    return sorted(out, key=lambda x: (x["win_rate"] if x["win_rate"] is not None else 0, -x["n"]))
