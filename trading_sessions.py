"""NYSE sessions for one-session paper orders. Unknown calendars block new buys."""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


@lru_cache(maxsize=8)
def _calendar(year: int):
    import exchange_calendars
    return exchange_calendars.get_calendar("XNYS", start=f"{year-1}-01-01", end=f"{year+2}-12-31")


@lru_cache(maxsize=2048)
def next_session(signal_date: str) -> str | None:
    try:
        signal = date.fromisoformat(signal_date)
        day = signal + timedelta(days=1)
        return _calendar(signal.year).date_to_session(day.isoformat(), direction="next").strftime("%Y-%m-%d")
    except Exception:
        return None


def order_session(order: dict) -> str | None:
    expected = next_session(str(order.get("signal_date") or ""))
    explicit = order.get("valid_session")
    return expected if expected and (not explicit or explicit == expected) else None


@lru_cache(maxsize=2048)
def close_time(day: str):
    try:
        session = date.fromisoformat(day)
        return _calendar(session.year).session_close(day).to_pydatetime()
    except Exception:
        return None


def completed_session(seen_to: str, day: str) -> bool:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    closing = close_time(day)
    try:
        seen = datetime.strptime(seen_to, "%Y-%m-%d %H:%M").replace(tzinfo=ZoneInfo("America/New_York"))
        return closing is not None and seen + timedelta(minutes=5) >= closing
    except (ValueError, TypeError):
        return False
