"""실적·배당 캘린더 — 보유·관심 종목의 다가오는 실적 발표일·배당락일을 모아요.

(파일명을 calendar.py로 하면 파이썬 표준 모듈과 충돌해서 evcal.py로 둬요.)
"""
from __future__ import annotations

from datetime import date, datetime, timezone


def _days(dstr: str | None) -> int | None:
    try:
        return (datetime.strptime(dstr, "%Y-%m-%d").date() - date.today()).days
    except Exception:
        return None


def build(earnings: dict, dividends: dict) -> dict:
    """earnings: {종목: 'YYYY-MM-DD'}, dividends: {종목: {exdate, amount, yield}}.

    오늘 이후(D-0 포함) 일정만, 가까운 순으로 정렬해 돌려줘요.
    """
    ev = []
    for t, d in (earnings or {}).items():
        dd = _days(d)
        if dd is not None and dd >= 0:
            ev.append({"t": t, "date": d, "days": dd})
    ev.sort(key=lambda x: x["days"])

    dv = []
    for t, info in (dividends or {}).items():
        d = (info or {}).get("exdate")
        dd = _days(d) if d else None
        if dd is not None and dd >= 0:
            dv.append({"t": t, "exdate": d, "days": dd,
                       "amount": (info or {}).get("amount"), "yield": (info or {}).get("yield")})
    dv.sort(key=lambda x: x["days"])

    return {"at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
            "earnings": ev[:40], "dividends": dv[:40]}
