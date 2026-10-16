"""앱(홈 화면 앱·웹사이트)이 읽는 데이터를 만들어 구글 시트 '앱 데이터' 탭에 저장해요.

앱은 로그인 서버(Apps Script)를 거쳐서만 이 데이터를 받아요. 공개된 곳에는 저장하지 않아요.
"""
from __future__ import annotations

import json
import math

from terms import DISCLAIMER, REGIME

# 보유 종목 한 줄 결론 (F-A5). 여러 규칙에 걸리면 앞의 것이 이겨요.
CONCLUSION = [
    ("stop", "손절선 아래", "bad"),
    ("trail", "이익 지키기", "warn"),
    ("target", "분할익절", "warn"),
    ("score", "점수 하락", "warn"),
    ("stale", "제자리", "warn"),
    ("earnings", "실적 주의", "warn"),
    ("regime", "국면 주의", "warn"),
]


def conclusion(hits: list[dict]) -> tuple[str, str]:
    rules = {h["rule"] for h in hits}
    for rule, label, tone in CONCLUSION:
        if rule in rules:
            return label, tone
    return "원칙대로", "good"


def _num(x, nd=2):
    if x is None:
        return None
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) or math.isinf(x) else round(x, nd)


TREND5 = [
    ("주가가 200일선 위", lambda t: t["close"] > t["ma200"]),
    ("이평선 정배열 (20 > 50 > 200일)", lambda t: t["ma20"] > t["ma50"] > t["ma200"]),
    ("MACD가 신호선 위", lambda t: bool(t.get("macd_above"))),
    ("RSI 40~70 (과열 아님)", lambda t: t.get("rsi") is not None and 40 <= t["rsi"] <= 70),
    ("거래량이 20일 평균 이상", lambda t: (t.get("vol_ratio") or 0) >= 1.0),
]


def trend5(t: dict | None) -> list:
    """F-A8 추세 합류 5조건 (참고용, 점수에는 섞지 않아요). [[조건, 충족], ...]"""
    if not t:
        return []
    out = []
    for label, fn in TREND5:
        try:
            out.append([label, bool(fn(t))])
        except Exception:
            out.append([label, False])
    return out


def pick_view(p: dict) -> dict:
    pl = p.get("plan") or {}
    return {
        "trend5": trend5(p.get("tech")),
        "t": p["ticker"], "name": p.get("name", ""), "price": _num(p["price"]), "total": _num(p["total"], 0),
        "cats": {k: _num(v, 0) for k, v in (p.get("cats") or {}).items()},
        "reasons": p.get("reasons", []), "tags": p.get("tags", []), "etf": bool(p.get("etf")),
        "rank": p.get("rank"), "streak": p.get("streak", 1), "band": p.get("band", ""),
        "plan": {k: (_num(v) if k != "valid_until" else v) for k, v in pl.items()},
        "desc": p.get("desc", ""), "caution": p.get("caution", ""), "warn": p.get("warn", ""),
    }


def build_daily(report: dict, holdings_view: list[dict], bar_date: str, run_at: str, fin: dict | None = None) -> dict:
    mk = report["market"]
    bands = []
    for b in report["bands"]:
        bands.append({"name": b["name"], "count": b["count"], "etf_count": b.get("etf_count", 0),
                      "picks": [pick_view(p) for p in b["picks"]],
                      "etf_picks": [pick_view(p) for p in b.get("etf_picks", [])],
                      "dropped": b.get("dropped", [])})
    sells = sum(1 for h in holdings_view if h["hits"])
    return {
        "v": 1, "date": bar_date, "run_at": run_at, "date_label": report["date_label"],
        "market": {"regime": mk["regime"], "label": REGIME[mk["regime"]], "threshold": _num(mk.get("threshold"), 0),
                   "rest_day": bool(mk.get("rest_day")), "rr": _num(mk.get("rr"), 1)},
        "summary": {"sell": sells, "buy": report["buy_total"], "stock": report.get("stock_total", 0),
                    "new": report["new_count"]},
        "holdings": holdings_view, "bands": bands, "warnings": report.get("warnings", []),
        "fin": _clean(fin or {}),
        "disclaimer": DISCLAIMER,
    }


def _clean(o):
    """JSON에 못 들어가는 NaN·무한대를 없애요."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, float):
        return None if math.isnan(o) or math.isinf(o) else round(o, 4)
    return o


def holding_view(h: dict, lv: dict | None, hits: list[dict], r: dict | None, action: str = "") -> dict:
    label, tone = conclusion(hits)
    out = {"t": h["ticker"], "name": (r or {}).get("name", ""), "qty": _num(h.get("qty")), "avg": _num(h.get("avg")),
           "conclusion": label, "tone": tone, "action": action, "hits": [x["why"] for x in hits],
           "rules": sorted({x["rule"] for x in hits}),
           "total": _num((r or {}).get("total"), 0), "cats": {k: _num(v, 0) for k, v in ((r or {}).get("cats") or {}).items()},
           "reasons": (r or {}).get("reasons", [])}
    if lv:
        out.update({"price": _num(lv["close"]), "stop": _num(lv["stop"]), "target": _num(lv["target"]),
                    "gain_pct": _num(lv["gain"] * 100, 1), "to_stop_pct": _num((lv["close"] / lv["stop"] - 1) * 100, 1)})
    return out


def dumps(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


RUN_LABEL = {"daily": "아침 리포트", "premarket": "장 시작 전 점검", "intraday": "장중 감시", "weekly": "주간 요약"}


def add_run(store, kind: str, at: str, ok, took: int, changed: list, checks: list, err: str = "", keep: int = 60):
    """실행 기록(앱 '알림 → 실행 기록')에 한 줄 추가 — symphony-kanban의 'proof of work' 방식.

    프로그램이 '잘 됐다'고 말하는 대신, 실행마다 (1) 무엇이 바뀌었는지 (2) 자동 점검을 통과했는지를 남겨요.
    점검: [{"n": 이름, "ok": True/False/None(점검 안 함), "d": 자세히}]. ok: True 성공 · False 실패 · "skip" 건너뜀.
    perf 덩어리 안에 같이 저장해요 (로그인 서버가 이미 앱으로 보내 주는 자료라 서버를 고칠 필요가 없어요).
    """
    try:
        raw = store.get_blob("perf")
        perf = json.loads(raw) if raw else {}
    except Exception:
        perf = {}
    runs = perf.get("runs") or []
    bad = [c for c in checks if c.get("ok") is False]
    if ok is True and bad:
        ok = "warn"   # 끝까지 돌았지만 점검 하나 이상 실패
    runs.insert(0, {"kind": kind, "label": RUN_LABEL.get(kind, kind), "at": at, "ok": ok, "took": took,
                    "changed": [str(x)[:160] for x in changed][:8], "checks": checks[:12], "err": str(err)[-600:]})
    perf["runs"] = runs[:keep]
    try:
        store.put_blob("perf", dumps(_clean(perf)))
    except Exception:
        pass


def add_alert(store, kind: str, title: str, body: str, at: str, tone: str = "info", max_items: int = 200):
    """알림 기록(앱 '알림' 화면)에 한 줄 추가. 실패해도 리포트는 그대로 가요."""
    try:
        raw = store.get_blob("alerts")
        items = json.loads(raw) if raw else []
    except Exception:
        items = []
    items.insert(0, {"kind": kind, "title": title, "body": body, "at": at, "tone": tone})
    store.put_blob("alerts", dumps(items[:max_items]))
