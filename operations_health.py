"""Durable health evidence for each scheduled pipeline run.

This does not infer delivery from a provider accepting a request. A channel
acknowledgment, paper state change and app blob read-back are distinct checks.
"""
from __future__ import annotations

import json

CRITICAL = ("메일·슬랙 발송", "앱 데이터 저장", "자동 모의투자")


def build_health(*, kind: str, at: str, checks: list[dict], success: bool,
                 error: str = "", stage: str = "", previous: dict | None = None) -> dict:
    entries = {str(c.get("n")): {"ok": c.get("ok"), "detail": str(c.get("d", ""))[:300]}
               for c in checks if c.get("n")}
    failing = [name for name, value in entries.items() if value["ok"] is False]
    missing = [name for name in CRITICAL if name not in entries] if kind == "daily" else []
    optional = [name for name in CRITICAL if entries.get(name, {}).get("ok") is None]
    state = "failed" if not success or failing else "incomplete" if missing or optional else "ok"
    if kind != "daily" and state == "ok":
        state = "ok"
    result = {
        "kind": kind, "at": at, "state": state, "stage": stage,
        "failed": failing, "missing": missing, "not_checked": optional,
        "checks": entries, "error": str(error)[-1000:],
        "previous_run": {"at": previous.get("at"), "state": previous.get("state")}
                        if isinstance(previous, dict) else None,
    }
    return result


def save_health(store, report: dict) -> dict:
    """Write and verify exact read-back, including all mandatory evidence."""
    raw = json.dumps(report, ensure_ascii=False, separators=(",", ":"))
    store.put_blob("health", raw)
    echoed = store.get_blob("health")
    if echoed != raw:
        raise RuntimeError("health report read-back mismatch")
    return report


def read_health(store) -> dict:
    raw = store.get_blob("health")
    if not raw:
        return {}
    try:
        out = json.loads(raw)
        return out if isinstance(out, dict) else {}
    except (ValueError, TypeError):
        return {}


def verify_daily_artifacts(store, expected_date: str, *, require_paper: bool = True) -> list[dict]:
    """Audit saved daily report/paper state without triggering any trades."""
    result = []
    try:
        daily = json.loads(store.get_blob("daily") or "{}")
        actual_date = str(daily.get("date") or "")
        # The daily report's date is the market-data bar date, NOT execution day.
        result.append({"n": "앱 데이터 읽기 검증",
                       "ok": bool(actual_date and actual_date == expected_date and daily.get("summary") is not None),
                       "d": f"기준일={actual_date or '없음'}"})
    except (ValueError, TypeError, OSError) as e:
        result.append({"n": "앱 데이터 읽기 검증", "ok": False, "d": str(e)[:200]})
    try:
        raw = store.get_blob("sim")
        st = json.loads(raw) if raw else None
        result.append({"n": "모의매매 저장 상태",
                       "ok": True if isinstance(st, dict) and "positions" in st and "cash" in st else None,
                       "d": "모의 계좌 저장 확인" if isinstance(st, dict) else "모의 계좌가 초기화되지 않음"})
    except (ValueError, TypeError, OSError) as e:
        result.append({"n": "모의매매 저장 상태", "ok": False, "d": str(e)[:200]})
    return result
