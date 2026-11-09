"""Durable health evidence for each scheduled pipeline run.

This does not infer delivery from a provider accepting a request. A channel
acknowledgment, paper state change and app blob read-back are distinct checks.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone

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
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    run_url = f"https://github.com/{repo}/actions/runs/{run_id}" if repo and run_id.isdigit() else ""
    result = {
        "workflow_url": run_url,
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


SAFE_RETRY_STEPS = {"앱 데이터 읽기 검증"}
MANUAL_ONLY_STEPS = {"메일·슬랙 발송", "자동 모의투자", "모의매매 저장 상태"}


def recovery_plan(checks: list[dict]) -> list[dict]:
    """Classify failed checks. Never replay notifications, trading or paper state."""
    out = []
    for item in checks:
        if item.get("ok") is not False:
            continue
        name = str(item.get("n") or "")
        safe = name in SAFE_RETRY_STEPS
        out.append({
            "step": name,
            "mode": "auto_safe" if safe else "manual",
            "message": ("앱 데이터 원본으로만 재저장·읽기 확인" if safe
                        else "자동 재실행 차단: 중복 알림·중복 체결 방지"),
        })
    return out


def repair_daily_blob(store, expected_date: str, canonical_payload: str) -> dict:
    """One idempotent repair of today's saved app blob, never a strategy re-run.

    Do not overwrite a newer report; do not re-run notification or paper trade.
    A failed readback or a conflicting newer date requires manual intervention.
    """
    try:
        canonical = json.loads(canonical_payload)
        if canonical.get("date") != expected_date or "summary" not in canonical:
            return {"status": "blocked", "reason": "검증되지 않은 앱 데이터 원본"}
        old = store.get_blob("daily")
        if old:
            try:
                previous = json.loads(old)
                date = str(previous.get("date") or "")
                if date > expected_date:
                    return {"status": "blocked", "reason": "더 최신 앱 데이터를 덮어쓸 수 없음"}
            except (ValueError, TypeError, AttributeError):
                return {"status": "blocked", "reason": "기존 앱 데이터가 손상되어 수동 확인 필요"}
        if old == canonical_payload:
            return {"status": "verified", "reason": "기존 저장 내용 동일"}
        store.put_blob("daily", canonical_payload)
        if store.get_blob("daily") == canonical_payload:
            return {"status": "repaired", "reason": "동일 기준일 앱 데이터만 복구"}
        return {"status": "failed", "reason": "재저장 후 읽기 검증 실패"}
    except (OSError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
        return {"status": "failed", "reason": str(exc)[:200]}


def weekly_metrics(runs: list[dict], now: datetime | None = None,
                   *, days: int = 7, kind: str = "daily") -> dict:
    """Rolling 7-day executions, not scheduled-day uptime (missed runs unknown)."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    start = now - timedelta(days=days)
    selected = []
    for r in runs:
        if r.get("kind") != kind:
            continue
        try:
            timestamp = datetime.fromisoformat(str(r.get("at", "")).replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                continue
        except ValueError:
            continue
        if start <= timestamp <= now:
            selected.append(r)
    success = sum(r.get("ok") is True for r in selected)
    partial = sum(r.get("ok") == "warn" for r in selected)
    failed = sum(r.get("ok") is False for r in selected)
    durations = [float(r["took"]) for r in selected
                 if isinstance(r.get("took"), (int, float))
                 and not isinstance(r.get("took"), bool)
                 and 0 <= r["took"] <= 86400]
    total = len(selected)
    return {
        "period_days": days, "total": total, "success": success,
        "partial": partial, "failed": failed,
        "success_rate_pct": round(100*success/total, 1) if total else None,
        "mean_seconds": round(sum(durations)/len(durations), 1) if durations else None,
        "timed_runs": len(durations),
        "note": "기록된 실행 기준. 예약됐지만 시작되지 않은 실행은 이 통계에 포함되지 않음",
    }
